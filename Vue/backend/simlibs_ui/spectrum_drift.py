"""Drift correction migrated from ElementsDetectionApplication/drift_correction.py
(source SHA256 fcf7fced63e4bbd6a82322f8a2796fa53973d82999ea876fa794663a5ad6f9d2).

The polynomial recalibration model and fit semantics are line-faithful to the
source: non-finite pair filtering, >=2 matched lines, >=2 unique experimental
wavelengths, degree capped at min(n_line-1, max_degree, unique-1), unweighted
np.polyfit. Two deviations, both documented:
  1. The source collects matched pairs from element-family objects
     (collect_element_family_matches); here matched pairs arrive as plain
     arrays produced by the greedy matcher below, so that collector is not
     ported.
  2. match_peaks_to_reference (greedy nearest-neighbour one-to-one pairing
     inside a tolerance) is NEW code: the source project produced pairs via
     element_integration weighted matching, which SimLIBS does not migrate.
"""
from dataclasses import dataclass

import numpy as np

SOURCE_SHA256 = 'fcf7fced63e4bbd6a82322f8a2796fa53973d82999ea876fa794663a5ad6f9d2'
MAX_MATCH_PAIRS = 2_000_000


@dataclass
class DriftCorrectionModel:
    degree: int  # 多项式次数
    coefficients: np.ndarray  # 多项式系数（最高次在前，np.polyfit 约定）
    exp_wl: np.ndarray  # 实验波长（匹配到的峰位）
    theo_wl: np.ndarray  # 理论波长（参考谱线位置）

    @property
    def n_line(self):
        return int(self.exp_wl.size)

    def correct(self, wavelength):
        wavelength = np.asarray(wavelength, dtype=float)
        return np.polyval(self.coefficients, wavelength)

    def drift(self, wavelength):
        wavelength = np.asarray(wavelength, dtype=float)
        return self.correct(wavelength) - wavelength


def clean_matches(exp_wl, theo_wl):
    """Filter non-finite pairs, require equal 1-D lengths, sort by exp."""
    exp_wl = np.asarray(exp_wl, dtype=float)
    theo_wl = np.asarray(theo_wl, dtype=float)
    if exp_wl.ndim != 1 or theo_wl.ndim != 1:
        raise ValueError('匹配波长须为一维数组')
    if exp_wl.size != theo_wl.size:
        raise ValueError('实验峰位与理论位置数量不一致')
    valid = np.isfinite(exp_wl) & np.isfinite(theo_wl)
    exp_wl = exp_wl[valid]
    theo_wl = theo_wl[valid]
    order = np.argsort(exp_wl)
    return exp_wl[order], theo_wl[order]


def match_peaks_to_reference(exp_wl, reference_wl, tolerance):
    """Greedy nearest-neighbour one-to-one matching (NEW code, not from the
    source project): all (peak, reference) pairs within tolerance are sorted by
    distance and accepted while both sides remain unused, so each theoretical
    position matches at most one peak. Returns (exp_matched, theo_matched)."""
    exp_wl = np.asarray(exp_wl, dtype=float)
    reference_wl = np.asarray(reference_wl, dtype=float)
    if not np.isfinite(exp_wl).all() or not np.isfinite(reference_wl).all():
        raise ValueError('峰位或参考位置存在非有限数值')
    if exp_wl.size == 0 or reference_wl.size == 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    if exp_wl.size * reference_wl.size > MAX_MATCH_PAIRS:
        raise ValueError('峰位与参考位置组合数超限；减少曲线节点或参考组')
    if not (np.isfinite(tolerance) and tolerance > 0):
        raise ValueError('匹配容差须为正的有限数值')
    candidates = []
    for i, peak in enumerate(exp_wl):
        for j, ref in enumerate(reference_wl):
            distance = abs(float(peak) - float(ref))
            if distance <= tolerance:
                candidates.append((distance, i, j))
    candidates.sort()
    used_exp, used_ref, exp_out, theo_out = set(), set(), [], []
    for _, i, j in candidates:
        if i in used_exp or j in used_ref:
            continue
        used_exp.add(i)
        used_ref.add(j)
        exp_out.append(exp_wl[i])
        theo_out.append(reference_wl[j])
    exp_out = np.asarray(exp_out, dtype=float)
    theo_out = np.asarray(theo_out, dtype=float)
    order = np.argsort(exp_out)
    return exp_out[order], theo_out[order]


def fit_drift_correction(exp_wl, theo_wl, max_degree=3):
    """Faithful port of fit_element_family_drift_correction on plain arrays."""
    exp_wl, theo_wl = clean_matches(exp_wl, theo_wl)
    n_line = exp_wl.size
    if n_line < 2:
        raise ValueError('匹配谱线少于2条，无法拟合漂移校正')
    max_degree = int(max_degree)
    if max_degree < 1:
        raise ValueError('拟合阶数上限须至少为1')
    unique_exp_count = np.unique(exp_wl).size
    if unique_exp_count < 2:
        raise ValueError('唯一实验峰位少于2个，无法拟合漂移校正')
    degree = min(n_line - 1, max_degree, unique_exp_count - 1)
    coefficients = np.polyfit(exp_wl, theo_wl, degree)
    return DriftCorrectionModel(degree=degree, coefficients=coefficients, exp_wl=exp_wl, theo_wl=theo_wl)
