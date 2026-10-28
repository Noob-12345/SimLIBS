"""逐线自吸收共享数值工具与结果容器。

Stark 系数统一来自 STARK-B 数据库及其已验证响应缓存。
自吸收经验宽度关系依据 John & Anoop (2023), DOI 10.1039/D3RA06226K。
"""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


WIDTH_EXPONENT = -0.54
MAX_LINE_POINT_WORK = 50_000_000


def validate_optical_depth(optical_depth):
    """返回有限非负的无量纲 tau 副本，允许标量或非空一维数组。

    布尔、复数、NaN、无穷值及负值均拒绝，避免强制类型转换掩盖输入问题。
    """
    try:
        original = np.asarray(optical_depth, dtype=object)
        if original.ndim > 1 or original.size == 0:
            raise ValueError("optical_depth must be a scalar or nonempty 1D array")
        if any(isinstance(value, (bool, np.bool_, complex, np.complexfloating))
               for value in original.flat):
            raise ValueError("optical_depth cannot contain booleans or complex numbers")
        tau = np.array(optical_depth, dtype=float, copy=True)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("invalid optical_depth: {}".format(error)) from None
    if not np.isfinite(tau).all() or np.any(tau < 0):
        raise ValueError("optical_depth must be finite and nonnegative")
    return tau


#自吸收系数
def slab_attenuation_factor(optical_depth):
    """计算 SA=(1-exp(-tau))/tau；tau=0 时连续取极限 SA=1。

    expm1 保证极薄情形的数值精度；该因子也作为逐线内禀峰高衰减系数。
    """
    tau = validate_optical_depth(optical_depth)
    factor = np.ones_like(tau)
    np.divide(-np.expm1(-tau), tau, out=factor, where=tau != 0)
    return factor


def attenuate_spectrum(spectrum, optical_depth, wavelength_column="wavelength")-> pd.DataFrame:
    """对已存在的谱表逐点乘显式衰减因子，返回副本并保留输入。

    标量 tau 应用于所有波长，一维 tau 必须与波长行数一致；各强度列共用因子。
    本工具只缩放强度，不计算布居、Stark 宽度或逐线重建。
    """

    if not isinstance(spectrum, pd.DataFrame):
        raise ValueError("spectrum must be a pandas DataFrame")
    if wavelength_column not in spectrum or not spectrum.columns.is_unique:
        raise ValueError("spectrum needs a wavelength column and unique channel names")
    channels = [name for name in spectrum.columns if name != wavelength_column]
    if spectrum.empty or not channels:
        raise ValueError("spectrum must contain wavelength nodes and intensity channels")
    values = spectrum.to_numpy()
    if np.iscomplexobj(values) or (values.dtype == object and any(
            isinstance(value, (complex, np.complexfloating)) for value in values.flat)):
        raise ValueError("spectrum wavelengths and intensities must be real numbers")
    try:
        wavelengths = spectrum[wavelength_column].to_numpy(dtype=float)
        intensities = spectrum[channels].to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("spectrum wavelengths and intensities must be numeric") from None
    if not np.isfinite(wavelengths).all() or np.any(wavelengths <= 0) or np.any(np.diff(wavelengths) <= 0):
        raise ValueError("spectrum wavelengths must be finite, positive and strictly increasing")
    if not np.isfinite(intensities).all() or np.any(intensities < 0):
        raise ValueError("spectrum intensities must be finite and nonnegative")
    #计算自吸收因子
    factor = slab_attenuation_factor(optical_depth)
    if factor.ndim == 1 and factor.size != len(spectrum):
        raise ValueError("optical_depth array length must match the spectrum wavelength nodes")
    result = spectrum.copy(deep=True)
    result[wavelength_column] = wavelengths
    result[channels] = intensities * np.broadcast_to(factor, (len(spectrum),))[:, None]
    return result

#数值检验
def _number(value, name, minimum=0.0, positive=False):
    """共享数值校验：拒绝布尔/复数，按需要求非负或严格为正的有限实数。"""
    if isinstance(value, (bool, np.bool_, complex, np.complexfloating)):
        raise ValueError("{} must be a real number".format(name))
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("{} must be a finite real number".format(name)) from None
    if not math.isfinite(result) or result < minimum or (positive and result <= 0):
        raise ValueError("{} is outside its finite nonnegative/positive range".format(name))
    return result


@dataclass
class SpectrumResult:
    """NIST Stark/逐线自吸收引擎的结果容器。

    spectrum/thin_spectrum 为 wavelength/intensity 总谱；ion_spectrum 和
    thin_ion_spectrum 为离子宽表；line_diagnostics 保存逐线中间量，metadata
    保存模型、参数和数据来源。thin 表示同一线形模型下移除自吸收的参考谱。
    """
    spectrum: pd.DataFrame
    thin_spectrum: pd.DataFrame
    ion_spectrum: pd.DataFrame
    thin_ion_spectrum: pd.DataFrame
    line_diagnostics: pd.DataFrame
    metadata: dict
