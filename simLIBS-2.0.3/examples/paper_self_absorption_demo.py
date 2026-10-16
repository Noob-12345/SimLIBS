"""独立离线论文模型示例：单条 Mg 线、Mg/Ca 混合谱和光程扫描。

调用 self_absorption.simulate_paper_spectrum，从本地 JSON 读取数据，无联网步骤。
输出 CSV/JSON 和两张图，供 SELF_ABSORPTION_REPORT.md 解释公式与线形变化。
当前 SimulatedLIBS 的 NIST 自吸收流程可用 nist_self_absorption_demo.py 调试。
"""

import argparse
import json
from pathlib import Path
import sys

import matplotlib
# 只保存图像文件，使用无窗口后端，方便在脚本和自动验证环境中运行。
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# 优先使用项目源码；调试时断点会落在当前目录下的 self_absorption.py。
sys.path.insert(0, str(ROOT))
from simLIBS.self_absorption import (
    load_paper_data, paper_line_parameters, PaperSelfAbsorptionConfig, simulate_paper_spectrum,
)


def main():
    """生成三个离线算例，导出原始结果，再绘制使用共同参考尺度的对比图。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"docs"/"self_absorption_results")
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    data = load_paper_data()
    # 固定一条内置 Mg I 记录，以便单独核对 tau、SA 和前后 FWHM/峰高关系。
    line = next(v for v in data["lines"] if v["element"] == "Mg" and v["wavelength_nm"] == 285.212)
    common = dict(Te=1.0, Ne=1e17, elements=["Mg"], percentages=[100],
                  low_w=283.212, upper_w=287.212, resolution=3000,
                  max_ion_charge=2)
    config = dict(path_length_m=1e-4, wavelength_step_nm=0.0005,
                  instrument_broadening=False, intensity_scale="energy")
    # 关闭仪器响应，便于直接检查内禀 Lorentz 峰高比是否等于 SA。
    isolated = simulate_paper_spectrum(**common, config={**config, "line_data": [line]})
    row = isolated.line_diagnostics.iloc[0]
    isolated_csv = pd.DataFrame({"wavelength_nm": isolated.spectrum.wavelength,
        "thin": isolated.thin_spectrum.intensity, "self_absorbed": isolated.spectrum.intensity})
    isolated_csv.to_csv(output/"mg285_single_line.csv", index=False)
    isolated.line_diagnostics.to_csv(output/"mg285_line_diagnostics.csv", index=False)

    # 混合算例使用同一套物理配置，但增加波段和采样步长，检查各离子/谱线叠加。
    mixture = simulate_paper_spectrum(Te=1.0, Ne=1e17, elements=["Mg", "Ca"], percentages=[50, 50],
        low_w=200, upper_w=650, resolution=3000, max_ion_charge=2,
        config={**config, "wavelength_step_nm": 0.01})
    mixture.spectrum.to_csv(output/"mg_ca_absorbed.csv", index=False)
    mixture.thin_spectrum.to_csv(output/"mg_ca_thin.csv", index=False)
    mixture.line_diagnostics.to_csv(output/"mg_ca_line_diagnostics.csv", index=False)

    paths = [0.0, 1e-5, 1e-4, 1e-3, 1e-2]
    scans = []
    # 仅改变光程 L；固定单线算例的 Ns/U/Te/Ne，隔离光程对吸收和展宽的影响。
    for length in paths:
        entry = paper_line_parameters(line, Te=1.0, Ne=1e17,
            species_density_cm3=float(row.species_density_cm3), partition_function=float(row.partition_function),
            config=PaperSelfAbsorptionConfig(path_length_m=length))
        scans.append({key: entry[key] for key in ("tau_center", "SA", "thin_fwhm_nm", "absorbed_fwhm_nm")}
                      | {"path_length_m": length})
    pd.DataFrame(scans).to_csv(output/"mg285_path_scan.csv", index=False)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), dpi=170)
    # 两条曲线共用薄谱最大值作显示尺度，避免分别归一化掩盖峰高衰减；CSV 保留原值。
    scale = float(isolated.thin_spectrum.intensity.max())
    axes[0].plot(isolated_csv.wavelength_nm, isolated_csv.thin/scale, label="Thin reference", color="#475569")
    axes[0].plot(isolated_csv.wavelength_nm, isolated_csv.self_absorbed/scale, label="Paper model", color="#dc2626")
    axes[0].set(title="Isolated Mg I 285.212 nm", xlabel="Wavelength (nm)", ylabel="Intensity / thin peak")
    axes[0].text(.04, .95, f"SA = {row.SA:.5f}\nFWHM: {row.thin_fwhm_nm:.4f} -> {row.absorbed_fwhm_nm:.4f} nm",
                 transform=axes[0].transAxes, va="top", fontsize=9)
    full_scale = float(mixture.thin_spectrum.intensity.max())
    axes[1].plot(mixture.spectrum.wavelength, mixture.thin_spectrum.intensity/full_scale,
                 color="#475569", lw=1, label="Thin reference")
    axes[1].plot(mixture.spectrum.wavelength, mixture.spectrum.intensity/full_scale,
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

    # 汇总实际计算结果与来源元数据；这些图是本实现输出，未对论文曲线作数字化取点。
    summary = {"description": "Actual implementation output; not digitized paper data or an exact Figure 2 reproduction",
        "single_line": {key: float(row[key]) for key in ("species_density_cm3", "partition_function", "q_m", "tau_center", "SA",
            "thin_fwhm_nm", "absorbed_fwhm_nm", "thin_peak", "absorbed_peak", "thin_area", "absorbed_area")},
        "parameters": isolated.metadata["parameters"], "path_scan": scans,
        "metadata": isolated.metadata, "mixture_metadata": mixture.metadata}
    (output/"example_results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "single_line": summary["single_line"], "path_scan": scans}, ensure_ascii=False))


if __name__ == "__main__":
    main()
