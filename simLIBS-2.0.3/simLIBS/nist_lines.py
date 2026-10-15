"""Parse NIST calculated sticks and synthesize area-normalized Gaussians.

Matches Dataset/nist_reconstruction.py's kernel: lambda/R is the Gaussian
1/e half-width, NOT FWHM. No per-band normalization or Doppler grid is used.
"""
import math
import re

import numpy as np
import pandas as pd


def parse_sticks(html):
    match = re.search(r"\bdataSticksArray\s*=\s*(\[\[.*?\]\])\s*;", html, re.S)
    if match is None:
        raise ValueError("NIST response has no dataSticksArray")
    rows = re.findall(r"\[([^\[\]]*)\]", match.group(1))
    labels = re.findall(r"label\s*:\s*['\"]([^'\"]*)['\"]", rows[0])
    if not labels:
        raise ValueError("dataSticksArray has no column labels")
    labels[0] = "wavelength"
    if len(set(labels)) != len(labels):
        raise ValueError("dataSticksArray has duplicate column labels")
    records = []
    for row in rows[1:]:
        parts = row.split(",")
        if len(parts) != len(labels):
            raise ValueError("Unexpected column count in dataSticksArray")
        records.append([0.0 if part.strip() == "null" else float(part) for part in parts])
    table = pd.DataFrame(records, columns=labels, dtype=float)
    line_strengths(table)
    return table


def line_strengths(table):
    ions = [col for col in table if re.match(r"^[A-Z][a-z]? [IVXLCDM]+(?:\s|$)", col)]
    if "wavelength" not in table or not ions:
        raise ValueError("Expected wavelengths and calculated ion intensity columns")
    centers = table["wavelength"].to_numpy(dtype=float)
    values = table[ions].to_numpy(dtype=float)
    if not np.isfinite(centers).all() or not np.isfinite(values).all():
        raise ValueError("Line positions and calculated strengths must be finite")
    if (centers <= 0).any() or (values < 0).any():
        raise ValueError("Line positions must be positive and strengths nonnegative")
    strengths = values.sum(axis=1)
    if not np.isfinite(strengths).all():
        raise ValueError("Summed line strengths must be finite")
    return centers, strengths


def bands_for(low, high, width=500.0, overlap=2.0):
    if not np.isfinite([low, high]).all() or not 0 < low < high:
        raise ValueError("Wavelength range must be finite, positive and increasing")
    for index in range(math.ceil((high-low)/width)):
        start = low + index*width
        stop = min(start+width, high)
        yield start, stop, max(low, start-overlap), min(high, stop+overlap)


def wavelength_grid(low, high, step):
    if not np.isfinite([low, high, step]).all() or not 0 < low < high or step <= 0:
        raise ValueError("Wavelength bounds and sampling step must be finite and positive")
    quotient = (high-low)/step
    if not np.isfinite(quotient) or quotient > 1999999:
        raise ValueError("Static output exceeds 2000000 points; increase sampling step")
    count = max(2, int(round(quotient)) + 1)
    if count > 2000000:
        raise ValueError("Static output exceeds 2000000 points; increase sampling step")
    grid = np.linspace(low, high, count)
    if np.any(np.diff(grid) <= 0):
        raise ValueError("Wavelength grid must be strictly increasing")
    return grid


def render_sticks(table, grid, resolution):
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("Spectrometer resolution must be finite and positive")
    centers, strengths = line_strengths(table)
    intensity = np.zeros_like(grid)
    for center, strength in zip(centers, strengths):
        if strength == 0:
            continue
        width = center / resolution
        low = np.searchsorted(grid, center-6*width, side="left")
        high = np.searchsorted(grid, center+6*width, side="right")
        delta = (grid[low:high]-center)/width
        intensity[low:high] += strength/(width*np.sqrt(np.pi))*np.exp(-delta*delta)
    if not np.isfinite(intensity).all():
        raise ValueError("Rendered spectrum contains nonfinite values")
    return pd.DataFrame({"wavelength": grid, "intensity": intensity})
