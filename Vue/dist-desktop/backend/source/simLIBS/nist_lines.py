"""普通静态光谱组件：解析 NIST 计算谱线，可选仪器高斯或无展宽投影。

调用链：simulation.retrieve_data_static -> parse_sticks -> render_sticks。
本模块负责波段划分、采样网格和普通静态线形；逐线 Stark/自吸收在
nist_self_absorption.py 中计算。谱线面积直接使用 NIST 计算线强，
各波段合并后统一展宽，不单独归一化。

单位约定：波长和采样步长为 nm，resolution 为无量纲仪器分辨率 R。
lambda/R 表示高斯 1/e 半宽，FWHM = 2*sqrt(log(2))*lambda/R。
调试入口：解析失败看 parse_sticks，谱线面积或线宽异常看 render_sticks。
"""
import math
import re

import numpy as np
import pandas as pd


def parse_sticks(html):
    """从 HTML 的 dataSticksArray 提取波长和各离子线强，返回 DataFrame。

    仅解析网页中的数据文本；null 离子贡献记为 0。返回前检查列结构、
    波长和线强，便于将 NIST 页面格式变化与后续展宽问题分开定位。
    """
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
    """校验谱线表，返回中心波长和每行各离子贡献之和两个数组。

    只汇总 Fe I、Fe II 等离子列；线强非负且有限，作为高斯积分面积。
    """
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
    """依次生成 (核心下界, 核心上界, 请求下界, 请求上界)，单位 nm。

    相邻请求默认重叠 2 nm；调用方按核心区间归属保留谱线，避免重复计入。
    此处只划分请求区间，谱线合并及展宽由 simulation.py 完成。
    """
    if not np.isfinite([low, high]).all() or not 0 < low < high:
        raise ValueError("Wavelength range must be finite, positive and increasing")
    for index in range(math.ceil((high-low)/width)):
        start = low + index*width
        stop = min(start+width, high)
        yield start, stop, max(low, start-overlap), min(high, stop+overlap)


def wavelength_grid(low, high, step):
    """生成包含两端点的递增网格，并在分配数组前限制最大点数。

    step 是期望采样间隔；linspace 按范围与点数调整实际间隔。
    极窄波段无法表示递增浮点坐标时也会明确报错。
    """
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


def _project_sticks(centers, strengths, grid):
    """将未展宽线面积投到相邻网格点，保持梯形积分面积及一阶矩。

    这是离散 delta 的数值表示，不引入物理线宽；端点使用半个网格单元的
    积分权重，窗口外的线不挪到边界，同波长贡献通过 add.at 累加。
    """
    grid = np.asarray(grid, dtype=float)
    if grid.ndim != 1 or len(grid) < 2 or not np.isfinite(grid).all() or np.any(np.diff(grid) <= 0):
        raise ValueError("Unbroadened output grid must be finite and strictly increasing with at least two points")
    weights = np.empty_like(grid)
    weights[0] = (grid[1]-grid[0])/2
    weights[-1] = (grid[-1]-grid[-2])/2
    weights[1:-1] = (grid[2:]-grid[:-2])/2
    inside = (centers >= grid[0]) & (centers <= grid[-1])
    centers, strengths = centers[inside], strengths[inside]
    right = np.clip(np.searchsorted(grid, centers), 1, len(grid)-1)
    left = right-1
    fraction = (centers-grid[left])/(grid[right]-grid[left])
    intensity = np.zeros_like(grid)
    np.add.at(intensity, left, strengths*(1-fraction)/weights[left])
    np.add.at(intensity, right, strengths*fraction/weights[right])
    return intensity


def render_sticks(table, grid, resolution, *, instrument_broadening=True):
    """将谱线面积转换为高斯强度密度，并叠加为 wavelength/intensity 表。

    grid 须使用递增的 nm 坐标；resolution 是仪器 R。同波长的不同跃迁
    逐条相加；仅计算中心左右各 6 个 1/e 半宽内的高斯贡献。
    仪器展宽+高斯展宽
    instrument_broadening=False 时改为离散线投影，仅保持线面积与重心。
    """
    if type(instrument_broadening) is not bool:
        raise ValueError("instrument_broadening must be a boolean")
    if not np.isfinite(resolution) or resolution <= 0:
        raise ValueError("Spectrometer resolution must be finite and positive")
    centers, strengths = line_strengths(table)
    if not instrument_broadening:
        intensity = _project_sticks(centers, strengths, grid)
        if not np.isfinite(intensity).all():
            raise ValueError("Rendered spectrum contains nonfinite values")
        return pd.DataFrame({"wavelength": grid, "intensity": intensity})
    intensity = np.zeros_like(grid)
    for center, strength in zip(centers, strengths):
        if strength == 0:
            continue
        # 面积归一化高斯：积分为 strength；峰高随 width 增大而降低。
        width = center / resolution
        low = np.searchsorted(grid, center-6*width, side="left")
        high = np.searchsorted(grid, center+6*width, side="right")
        delta = (grid[low:high]-center)/width
        intensity[low:high] += strength/(width*np.sqrt(np.pi))*np.exp(-delta*delta)
    if not np.isfinite(intensity).all():
        raise ValueError("Rendered spectrum contains nonfinite values")
    return pd.DataFrame({"wavelength": grid, "intensity": intensity})
