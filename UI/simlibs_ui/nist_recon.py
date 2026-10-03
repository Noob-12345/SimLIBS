"""Rebuild an ASD LIBS spectrum from calculated, unbroadened line strengths.

Copied from D:/LIBS/Deeplearning/Cross_attention/Dataset/nist_reconstruction.py
(verified against NIST saha_lte.js, corr >= 0.9999999; see
NIST_ASD_DIAGNOSIS.md in that project) with two UI-side additions, clearly
marked: `Band` (core-band holder for merge_core_sticks) and
`render_ion_sticks` (per-ion curves for the ion view).

The kernel deliberately follows NIST's saha_lte.js, including its width
convention: width = wavelength / resolution is a Gaussian 1/e half-width.
This differs from interpreting that value as a Gaussian FWHM.
Source: https://physics.nist.gov/PhysRefData/ASD/LIBS/js/saha_lte.js
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Band:
    """Core wavelength band used by merge_core_sticks (UI addition)."""

    core_low: float
    core_high: float


def parse_nist_matrix(html: str, variable: str) -> pd.DataFrame:
    """Read a numeric ASD JavaScript array without executing the response."""
    match = re.search(rf"\b{re.escape(variable)}\s*=\s*(\[\[.*?\]\])\s*;", html, re.S)
    if match is None:
        raise ValueError(f"NIST response has no {variable}")
    rows = re.findall(r"\[([^\[\]]*)\]", match.group(1))
    labels = re.findall(r"label\s*:\s*['\"]([^'\"]*)['\"]", rows[0])
    if not labels:
        raise ValueError(f"{variable} has no column labels")
    labels[0] = "wavelength"
    labels = ["intensity" if label in ("Sum", "Sum(calc)") else label for label in labels]
    records = []
    for row in rows[1:]:
        parts = row.split(",")
        if len(parts) != len(labels):
            raise ValueError(f"Unexpected column count in {variable}")
        records.append([0.0 if part.strip() == "null" else float(part) for part in parts])
    return pd.DataFrame(records, columns=labels)


def actual_resolution(html: str) -> float:
    """Return the resolving power actually used in the server's initial plot."""
    match = re.search(r"\bvar\s+resolution\s*=\s*([\d.eE+-]+)\s*;", html)
    if match is None:
        raise ValueError("NIST response does not expose its actual resolution")
    return float(match.group(1))


def line_strengths(sticks: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Sum calculated ion columns; these are line areas, not broadened heights."""
    if "wavelength" not in sticks or "intensity" in sticks:
        raise ValueError("Expected a dataSticksArray table, not a Doppler table")
    # Require ion columns to prevent accidental use of ASD's observed Rel. Int.
    ions = [column for column in sticks if re.match(r"^[A-Z][a-z]? [IVX]+(?:\s|$)", column)]
    if not ions:
        raise ValueError("No calculated ion intensity columns found")
    centers = sticks["wavelength"].to_numpy(dtype=float)
    strengths = sticks[ions].fillna(0.0).sum(axis=1).to_numpy(dtype=float)
    if not np.isfinite(centers).all() or not np.isfinite(strengths).all():
        raise ValueError("Line positions and strengths must be finite")
    if (centers <= 0).any() or (strengths < 0).any():
        raise ValueError("Line positions must be positive and strengths nonnegative")
    return centers, strengths


def render_nist_sticks(
    sticks: pd.DataFrame,
    wavelengths: np.ndarray,
    resolution: float = 3000.0,
    *,
    center_decimals: int | None = None,
) -> pd.DataFrame:
    """Evaluate normalized Gaussians directly on one common wavelength axis.

    Each line's integrated strength is preserved. No per-band normalization,
    spline interpolation or server Doppler grid is used. center_decimals is
    only for reproducing the rounding in NIST's browser reference calculation;
    retaining original Ritz wavelengths is preferable for a new dataset.
    """
    grid = np.asarray(wavelengths, dtype=float)
    if grid.ndim != 1 or grid.size < 2 or not np.isfinite(grid).all():
        raise ValueError("Expected a finite, one-dimensional wavelength grid")
    if (grid <= 0).any() or (np.diff(grid) <= 0).any():
        raise ValueError("Wavelength grid must be positive and strictly increasing")
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("resolution must be finite and positive")
    centers, strengths = line_strengths(sticks)
    intensity = np.zeros_like(grid)
    for original_center, strength in zip(centers, strengths):
        if strength == 0:
            continue
        width = original_center / resolution
        center = original_center if center_decimals is None else round(original_center, center_decimals)
        # NIST also truncates at approximately six widths. The omitted area
        # here is < 3e-17; work grows with profile width rather than all pixels.
        low = np.searchsorted(grid, center - 6.0 * width, side="left")
        high = np.searchsorted(grid, center + 6.0 * width, side="right")
        delta = (grid[low:high] - center) / width
        intensity[low:high] += strength / (width * np.sqrt(np.pi)) * np.exp(-delta * delta)
    return pd.DataFrame({"wavelength": grid, "intensity": intensity})


def merge_core_sticks(band_tables, bands) -> pd.DataFrame:
    """Assign each line to exactly one core band, retaining all ion columns.

    Inputs must use the same composition, Te, Ne, wavelength convention,
    intensity scale and min_rel_int=0. Nonzero thresholds select different
    lines in different wavelength windows and cannot guarantee equivalence.
    Merge line lists before broadening so profiles cross band boundaries.
    """
    if len(band_tables) != len(bands) or not bands:
        raise ValueError("Expected one line table for each wavelength band")
    cores = []
    for index, (table, band) in enumerate(zip(band_tables, bands)):
        line_strengths(table)
        wave = table["wavelength"]
        upper = wave <= band.core_high if index == len(bands) - 1 else wave < band.core_high
        cores.append(table.loc[(wave >= band.core_low) & upper])
    # A row may contain unresolved transitions already summed by NIST. Do not
    # round wavelengths or deduplicate by a coarse wavelength key.
    return pd.concat(cores, ignore_index=True).fillna(0.0).sort_values("wavelength").reset_index(drop=True)


def ion_columns(sticks: pd.DataFrame) -> list[str]:
    """UI addition: calculated ion contribution columns of a line table."""
    return [column for column in sticks if re.match(r"^[A-Z][a-z]? [IVX]+(?:\s|$)", column)]


def render_ion_sticks(
    sticks: pd.DataFrame,
    wavelengths: np.ndarray,
    resolution: float = 3000.0,
    *,
    center_decimals: int | None = None,
) -> pd.DataFrame:
    """UI addition: broaden each ion column separately on one common grid.

    Returns a frame with 'Wavelength (nm)', one column per ion and 'Sum(calc)'
    (the sum of the per-ion curves). Linearity of the Gaussian kernel makes the
    sum identical (up to floating point) to render_nist_sticks on the table.
    """
    ions = ion_columns(sticks)
    if not ions:
        raise ValueError("No calculated ion intensity columns found")
    grid = np.asarray(wavelengths, dtype=float)
    data = {"Wavelength (nm)": grid}
    for column in ions:
        sub = sticks[["wavelength", column]].copy()
        data[column] = render_nist_sticks(
            sub, grid, resolution, center_decimals=center_decimals)["intensity"].to_numpy()
    frame = pd.DataFrame(data)
    frame["Sum(calc)"] = frame[ions].sum(axis=1)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="NIST response HTML or calculated sticks CSV")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resolution", type=float, default=3000.0)
    parser.add_argument("--low", type=float, default=200.0)
    parser.add_argument("--high", type=float, default=700.0)
    parser.add_argument("--points", type=int, default=50001)
    args = parser.parse_args()
    if args.high <= args.low or args.points < 2:
        parser.error("high must exceed low and points must be at least 2")
    if args.source.suffix.lower() in (".html", ".htm"):
        sticks = parse_nist_matrix(args.source.read_text(encoding="utf-8"), "dataSticksArray")
    else:
        sticks = pd.read_csv(args.source)
    spectrum = render_nist_sticks(sticks, np.linspace(args.low, args.high, args.points), args.resolution)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    spectrum.to_csv(args.output, index=False)
    print(f"Saved {len(spectrum)} points at R={args.resolution:g} to {args.output}")


if __name__ == "__main__":
    main()
