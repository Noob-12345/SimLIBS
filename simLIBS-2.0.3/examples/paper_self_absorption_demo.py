"""Run the actual paper model and export figures/data used by the MD report."""

import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simLIBS import SimulatedLIBS
from simLIBS.self_absorption import load_paper_data, paper_line_parameters, PaperSelfAbsorptionConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"docs"/"self_absorption_results")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    data = load_paper_data()
    line = next(v for v in data["lines"] if v["element"] == "Mg" and v["wavelength_nm"] == 285.212)
    common = dict(Te=1.0, Ne=1e17, elements=["Mg"], percentages=[100],
                  low_w=283.212, upper_w=287.212, resolution=3000,
                  max_ion_charge=2, self_absorption=True)
    config = dict(path_length_m=1e-4, wavelength_step_nm=0.0005,
                  instrument_broadening=False, intensity_scale="energy")
    isolated = SimulatedLIBS(**common, self_absorption_config={**config, "line_data": [line]})
    row = isolated.self_absorption_diagnostics.iloc[0]
    isolated_csv = pd.DataFrame({"wavelength_nm": isolated.raw_spectrum.wavelength,
        "thin": isolated.unabsorbed_raw_spectrum.intensity, "self_absorbed": isolated.raw_spectrum.intensity})
    isolated_csv.to_csv(output/"mg285_single_line.csv", index=False)
    isolated.self_absorption_diagnostics.to_csv(output/"mg285_line_diagnostics.csv", index=False)

    mixture = SimulatedLIBS(Te=1.0, Ne=1e17, elements=["Mg", "Ca"], percentages=[50, 50],
        low_w=200, upper_w=650, resolution=3000, max_ion_charge=2, self_absorption=True,
        self_absorption_config={**config, "wavelength_step_nm": 0.01})
    mixture.save_to_csv(str(output/"mg_ca_absorbed.csv"))
    mixture.unabsorbed_raw_spectrum.to_csv(output/"mg_ca_thin.csv", index=False)
    mixture.self_absorption_diagnostics.to_csv(output/"mg_ca_line_diagnostics.csv", index=False)

    paths = [0.0, 1e-5, 1e-4, 1e-3, 1e-2]
    scans = []
    for length in paths:
        entry = paper_line_parameters(line, Te=1.0, Ne=1e17,
            species_density_cm3=float(row.species_density_cm3), partition_function=float(row.partition_function),
            config=PaperSelfAbsorptionConfig(path_length_m=length))
        scans.append({key: entry[key] for key in ("tau_center", "SA", "thin_fwhm_nm", "absorbed_fwhm_nm")}
                      | {"path_length_m": length})
    pd.DataFrame(scans).to_csv(output/"mg285_path_scan.csv", index=False)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), dpi=170)
    scale = float(isolated.unabsorbed_raw_spectrum.intensity.max())
    axes[0].plot(isolated_csv.wavelength_nm, isolated_csv.thin/scale, label="Thin reference", color="#475569")
    axes[0].plot(isolated_csv.wavelength_nm, isolated_csv.self_absorbed/scale, label="Paper model", color="#dc2626")
    axes[0].set(title="Isolated Mg I 285.212 nm", xlabel="Wavelength (nm)", ylabel="Intensity / thin peak")
    axes[0].text(.04, .95, f"SA = {row.SA:.5f}\nFWHM: {row.thin_fwhm_nm:.4f} -> {row.absorbed_fwhm_nm:.4f} nm",
                 transform=axes[0].transAxes, va="top", fontsize=9)
    full_scale = float(mixture.unabsorbed_raw_spectrum.intensity.max())
    axes[1].plot(mixture.raw_spectrum.wavelength, mixture.unabsorbed_raw_spectrum.intensity/full_scale,
                 color="#475569", lw=1, label="Thin reference")
    axes[1].plot(mixture.raw_spectrum.wavelength, mixture.raw_spectrum.intensity/full_scale,
                 color="#dc2626", lw=1, label="Paper model")
    axes[1].set(title="Mg/Ca = 50/50 at%, Table 1 transitions", xlabel="Wavelength (nm)", ylabel="Intensity / common thin maximum")
    for ax in axes:
        ax.grid(alpha=.18); ax.legend(fontsize=9); ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Actual implementation output: Te = 1 eV, Ne = 1e17 cm^-3, L = 0.1 mm", fontsize=12)
    fig.tight_layout(); fig.savefig(output/"paper_model_spectra.png", dpi=170); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8), dpi=170)
    x = np.array(paths[1:])*1000
    axes[0].semilogx(x, [v["SA"] for v in scans[1:]], "o-", color="#2563eb")
    axes[0].set(xlabel="Absorption path (mm)", ylabel="Line-center SA", title="Mg I 285.212 nm: opacity response")
    axes[1].semilogx(x, [v["absorbed_fwhm_nm"] for v in scans[1:]], "o-", color="#dc2626")
    axes[1].axhline(row.thin_fwhm_nm, color="#475569", ls="--", label="Thin Stark width")
    axes[1].set(xlabel="Absorption path (mm)", ylabel="FWHM (nm)", title="Empirical Eq. (8) width change")
    for ax in axes:
        ax.grid(alpha=.2); ax.spines[["top", "right"]].set_visible(False)
    axes[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(output/"paper_model_path_scan.png", dpi=170); plt.close(fig)

    summary = {"description": "Actual implementation output; not digitized paper data or an exact Figure 2 reproduction",
        "single_line": {key: float(row[key]) for key in ("species_density_cm3", "partition_function", "q_m", "tau_center", "SA",
            "thin_fwhm_nm", "absorbed_fwhm_nm", "thin_peak", "absorbed_peak", "thin_area", "absorbed_area")},
        "parameters": isolated.self_absorption_metadata["parameters"], "path_scan": scans,
        "metadata": isolated.self_absorption_metadata, "mixture_metadata": mixture.self_absorption_metadata}
    (output/"example_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "single_line": summary["single_line"], "path_scan": scans}, ensure_ascii=False))


if __name__ == "__main__":
    main()
