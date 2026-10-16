"""自吸收共享工具与独立离线论文模型。

模块内的组件分工：
1. validate_optical_depth/slab_attenuation_factor/attenuate_spectrum：
   校验显式光学厚度并计算均匀发射层的衰减因子；可独立用于整谱后处理。
2. _number/load_paper_data/PaperSpectrumResult 及资源上限常量：
   同时供当前 nist_self_absorption.py 和本模块离线模型使用。
3. simulate_paper_spectrum：从本地或用户提供的跃迁、能级数据出发，
   使用 I/II/III Saha/Boltzmann、逐线光学厚度和经验宽度关系合成离线光谱。

当前 SimulatedLIBS 的 static+self_absorption 主流程位于
nist_self_absorption.py；本模块的离线入口仍可直接调用以复现实例和调试公式。
论文依据：John & Anoop (2023), DOI 10.1039/D3RA06226K。
显式衰减工具依据：https://www.astro.uvic.ca/~tatum/stellatm/atm5.pdf 第 5.7 节。

公共单位：Te/能量为 eV，Ne/数密度为 cm^-3，波长与线宽为 nm，光程为 m。
q 的计算会换算到 SI，tau 无量纲。调试时先区分“显式给定 tau”与
“逐线根据布居推导 tau”两个入口，再观察 SA、thin_fwhm_nm 和 absorbed_area。
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from scipy.constants import c, e, h, m_e
from scipy.special import logsumexp, voigt_profile


PAPER_DOI = "10.1039/D3RA06226K"
MODEL_VERSION = "john-anoop-2023-lines-1"
# 论文式(8)的经验指数 alpha；吸收后 FWHM=原 FWHM*SA^alpha。
WIDTH_EXPONENT = -0.54
# 离线网格点数上限，以及两个逐线引擎共用的内存/计算规模保护。
MAX_OUTPUT_POINTS = 200000
MAX_SPECTRUM_CELLS = 5000000
MAX_LINE_POINT_WORK = 50000000

#数值检验（optical_depth）
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


@dataclass(frozen=True)
class PaperSelfAbsorptionConfig:
    """独立离线入口的配置，供 simulate_paper_spectrum 使用。

    line_data/atomic_data 可替换内置跃迁和 I/II/III 能级快照；当前 NIST
    主入口使用另一个 NISTSelfAbsorptionConfig，两者的数据来源分别维护。
    """

    #自吸收配置参数
    # 光程 m；0 对应薄谱极限。密度 cm^-3；None 时用电荷守恒反推。
    path_length_m: float = 0.01
    total_number_density_cm3: object = None
    # 输出步长 nm；仪器开关默认 False，方便直接观察内禀 Lorentz 峰高与宽度。
    wavelength_step_nm: float = 0.005
    instrument_broadening: bool = False
    # energy 将光子线权重乘以 hc/lambda；photon 保留光子计数权重。
    intensity_scale: str = "energy"
    # 本地/用户逐线表与原子能级表；缺少任一表时，从 data_path 的 JSON 补读。
    line_data: object = None
    atomic_data: object = None
    data_path: object = None

    def __post_init__(self):
        """在配置创建时检查范围、强度尺度和开关类型。"""
        object.__setattr__(self, "path_length_m", _number(self.path_length_m, "path_length_m"))
        object.__setattr__(self, "wavelength_step_nm", _number(self.wavelength_step_nm, "wavelength_step_nm", positive=True))
        if self.total_number_density_cm3 is not None:
            object.__setattr__(self, "total_number_density_cm3", _number(self.total_number_density_cm3, "total_number_density_cm3"))
        if type(self.instrument_broadening) is not bool:
            raise ValueError("instrument_broadening must be a boolean")
        if self.intensity_scale not in ("energy", "photon"):
            raise ValueError("intensity_scale must be energy or photon")

#配置参数验证
def _config(config):
    """将 None、字典或现成配置对象统一为 PaperSelfAbsorptionConfig。"""
    if config is None:
        return PaperSelfAbsorptionConfig()
    if isinstance(config, PaperSelfAbsorptionConfig):
        return config
    if isinstance(config, dict):
        try:
            return PaperSelfAbsorptionConfig(**config)
        except TypeError as error:
            raise ValueError("invalid paper model configuration: {}".format(error)) from None
    raise ValueError("config must be PaperSelfAbsorptionConfig or a dictionary")

#读取论文数据
def load_paper_data(path=None):
    """读取本地论文谱线/能级快照，并附加文件路径与 SHA256 追溯信息。

    离线引擎使用 lines 和 elements；当前 NIST 引擎只从 lines 查 Stark 系数。
    此函数不发网络请求，也不自动增加元素或谱线覆盖。
    """
    path = Path(path) if path is not None else Path(__file__).with_name("data") / "paper_atomic_data.json"
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("cannot read paper atomic data {}: {}".format(path, error)) from None
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list) or not isinstance(data.get("elements"), dict):
        raise ValueError("paper data must contain lines and elements")
    data["_source_sha256"] = hashlib.sha256(raw).hexdigest()
    data["_source_path"] = str(path.resolve())
    return data

# 粒子布居：输出 I/II/III 的数目比例、配分函数和实际纳入的束缚能级数量。
def saha_populations(atomic_data, *, Te, Ne):
    """使用提供的真实束缚能级计算三阶段 LTE 布居；Te[eV]，Ne[cm^-3]。

    输入 levels 的键为字符串 '0'/'1'/'2'；输出三个数组均按 charge=0/1/2
    排列。缺少任何阶段的真实束缚能级时明确报错。
    """
    te = _number(Te, "Te", positive=True)
    ne = _number(Ne, "Ne", positive=True)
    if not isinstance(atomic_data, dict):
        raise ValueError("atomic data must be a dictionary")
    levels = atomic_data.get("levels", {})
    energies = atomic_data.get("ionization_energies_eV", [])
    if len(energies) < 2:
        raise ValueError("I/II/III Saha requires the first two ionization energies")
    ionization = [_number(v, "ionization energy", positive=True) for v in energies[:2]]
    log_u, counts = [], []
    # logsumexp 累加 g*exp(-E/Te)，减小大配分和极小布居的数值误差。
    for stage in ("0", "1", "2"):
        weights = []
        if not isinstance(levels.get(stage), list):
            raise ValueError("missing real levels for ionization stage {}".format(stage))
        for state in levels[stage]:
            bound = state.get("is_bound", True)
            if type(bound) is not bool:
                raise ValueError("is_bound must be boolean")
            if not bound:
                continue
            energy = _number(state["energy_eV"], "level energy")
            weight = _number(state["g"], "level statistical weight", positive=True)
            if not weight.is_integer():
                raise ValueError("level statistical weight must be an integer")
            weights.append(math.log(weight) - energy/te)
        if not weights:
            raise ValueError("missing bound levels for ionization stage {}".format(stage))
        log_u.append(float(logsumexp(weights))); counts.append(len(weights))
    # 常数使用 SI：Te 的 eV 乘 e 转成 J，Ne 的 cm^-3 乘 1e6 转成 m^-3。
    prefactor = math.log(2) + 1.5*(math.log(2*math.pi*m_e*e/h**2) + math.log(te)) - math.log(ne) - math.log(1e6)
    logs = [0.0]
    for stage in (0, 1):
        logs.append(logs[-1] + prefactor + log_u[stage+1] - log_u[stage] - ionization[stage]/te)
    fractions = np.exp(np.array(logs) - logsumexp(logs))
    partitions = np.exp(log_u)
    if not np.isfinite(partitions).all() or not np.isfinite(fractions).all():
        raise ValueError("partition/population calculation exceeded the numeric range")
    return {"fractions": fractions, "partition_functions": partitions, "bound_level_counts": counts}


def _line(line):
    """校验并复制离线跃迁记录：元素、charge=0/1/2、能级、Aki、g 和 Stark W。

    能量为 eV，波长及 W 为 nm；W 的约定为 FWHM=2*W*Ne/Ne_ref。
    """
    if not isinstance(line, dict):
        raise ValueError("each transition must be a dictionary")
    out = dict(line)
    try:
        for name in ("wavelength_nm", "Aki_s", "g_lower", "g_upper", "stark_width_nm"):
            out[name] = _number(line[name], name, positive=True)
        for name in ("lower_eV", "upper_eV", "charge"):
            out[name] = _number(line[name], name)
        out["stark_reference_ne_cm3"] = _number(line.get("stark_reference_ne_cm3", 1e16), "stark_reference_ne_cm3", positive=True)
        if out["charge"] not in (0, 1, 2) or not out["g_lower"].is_integer() or not out["g_upper"].is_integer():
            raise ValueError("charges must be 0/1/2 and statistical weights positive integers")
        out["charge"] = int(out["charge"])
        if not isinstance(out.get("element"), str) or not out["element"]:
            raise ValueError("transition element is required")
        if out["upper_eV"] <= out["lower_eV"]:
            raise ValueError("upper_eV must exceed lower_eV")
    except (KeyError, TypeError) as error:
        raise ValueError("missing/invalid transition data: {}".format(error)) from None
    return out


def paper_line_parameters(line, *, Te, Ne, species_density_cm3, partition_function, config=None):
    """计算一条离线跃迁的薄谱面积、Stark FWHM、光学厚度和吸收后参数。

    species_density_cm3 是该元素该电荷态的 Ns；partition_function 是该阶段 U。
    返回包含 q_m、tau_center、SA、前后峰高/面积/FWHM 的字典，适合单线断点调试。
    """
    cfg = _config(config); row = _line(line)
    te = _number(Te, "Te", positive=True); ne = _number(Ne, "Ne", positive=True)
    ns = _number(species_density_cm3, "species_density_cm3")
    partition = _number(partition_function, "partition_function", positive=True)
    wavelength_m = row["wavelength_nm"] * 1e-9
    width = 2*row["stark_width_nm"]*(ne/row["stark_reference_ne_cm3"])
    _number(width, "derived Stark FWHM", positive=True)
    try:
        # 论文式(7)：下能级 Boltzmann 布居决定吸收，q_m 与内禀宽度换算成 m 后求 tau。
        q_m = (math.exp(math.log(ns) + math.log(1e6) + math.log(row["g_upper"]) + 4*math.log(wavelength_m)
                        + math.log(row["Aki_s"]) + math.log(cfg.path_length_m)
                        - math.log(4*math.pi**2*c) - math.log(partition) - row["lower_eV"]/te)
               if ns > 0 and cfg.path_length_m > 0 else 0.0)
        tau = q_m/(width*1e-9)
        sa = float(slab_attenuation_factor(tau))
        absorbed_width = width*sa**WIDTH_EXPONENT
        # 离线入口从上能级布居与 Aki 计算相对线面积；当前 NIST 入口直接保留 NIST 面积。
        area = (math.exp(math.log(ns) + math.log(1e6) + math.log(row["g_upper"])
                         + math.log(row["Aki_s"]) - math.log(4*math.pi) - math.log(partition)
                         - row["upper_eV"]/te) if ns > 0 else 0.0)
        if cfg.intensity_scale == "energy":
            area *= h*c/wavelength_m
        # Lorentz 峰高正比于面积/FWHM；面积指数 1+alpha=0.46 保证峰高比为 SA。
        absorbed_area = area*sa**(1+WIDTH_EXPONENT)
        peak = area/(math.pi*width/2)
        absorbed_peak = absorbed_area/(math.pi*absorbed_width/2)
    except (OverflowError, ZeroDivisionError):
        raise ValueError("line parameters exceeded the finite numeric range") from None
    row.update(species_density_cm3=ns, partition_function=partition, q_m=q_m, q_nm=q_m*1e9,
               tau_center=tau, SA=sa, thin_fwhm_nm=width, absorbed_fwhm_nm=absorbed_width,
               thin_area=area, absorbed_area=absorbed_area, thin_peak=peak, absorbed_peak=absorbed_peak)
    for name in ("q_nm", "tau_center", "absorbed_fwhm_nm", "thin_area", "absorbed_area", "thin_peak", "absorbed_peak"):
        _number(row[name], "derived " + name)
    return row


@dataclass
class PaperSpectrumResult:
    """两个逐线引擎共用的结果容器。

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


def simulate_paper_spectrum(*, Te, Ne, elements, percentages, low_w, upper_w,
                            resolution=1000, max_ion_charge=2, config=None, cancelled=None, progress=None):
    """从本地/用户跃迁和 I/II/III 能级表生成独立离线论文模型光谱。

    执行顺序：校验组成 -> 读取逐线数据 -> Saha 布居与密度 -> 单线参数 ->
    可选仪器响应 -> 各离子/总谱 -> 诊断和来源。每条线保留 Lorentz 翼部，
    records 不按输出窗口预先裁剪；超出窗口的线也可能贡献翼部。

    仪器高斯与内禀 Lorentz 通过 Voigt 解析合成；本离线入口约定
    lambda/R 为仪器高斯 FWHM。当前 NIST 入口的 1/e 半宽约定见对应模块。
    cancelled 为无参回调，progress 接收 (当前进度, 100, 消息)。
    """
    cfg = _config(config)
    def check():
        """在准备和逐线循环中响应取消请求，终止时抛出 InterruptedError。"""
        if cancelled is not None and cancelled():
            raise InterruptedError("paper self-absorption calculation cancelled")
    def emit(current, message):
        """先检查取消，再向调用方报告 0-100 范围内的进度。"""
        check()
        if progress is not None:
            progress(current, 100, message)
    check()
    te = _number(Te, "Te", positive=True); ne = _number(Ne, "Ne", positive=True)
    low = _number(low_w, "low_w", positive=True); high = _number(upper_w, "upper_w", positive=True)
    r = _number(resolution, "resolution", positive=True)
    charge = _number(max_ion_charge, "max_ion_charge")
    if high <= low or not r.is_integer() or not charge.is_integer():
        raise ValueError("wavelength range must increase; resolution and charge must be integers")
    if elements is None or percentages is None or len(elements) != len(percentages) or not len(elements):
        raise ValueError("elements and percentages must have equal nonzero lengths")
    if len(set(elements)) != len(elements):
        raise ValueError("duplicate composition elements")
    pcts = [_number(p, "percentage") for p in percentages]
    if not math.isclose(math.fsum(pcts), 100, rel_tol=0, abs_tol=1e-6):
        raise ValueError("paper model atomic percentages must sum to 100")
    active = {el: pct/100 for el, pct in zip(elements, pcts) if pct > 0}
    quotient = (high-low)/cfg.wavelength_step_nm
    if not math.isfinite(quotient) or quotient > MAX_OUTPUT_POINTS-1:
        raise ValueError("paper output exceeds 200000 points; narrow the window or increase wavelength_step_nm")
    count = int(math.ceil(quotient)) + 1
    data = (load_paper_data(cfg.data_path) if cfg.line_data is None or cfg.atomic_data is None else
            {"lines": [], "elements": {}, "paper": {"doi": PAPER_DOI}})
    line_data = cfg.line_data if cfg.line_data is not None else data["lines"]
    if isinstance(line_data, pd.DataFrame):
        line_data = line_data.to_dict("records")
    if not isinstance(line_data, (list, tuple)):
        raise ValueError("line_data must be a transition list or DataFrame")
    validated_lines = [_line(v) for v in line_data]
    records = [v for v in validated_lines if v["element"] in active]
    records = [v for v in records if v["charge"] <= charge]
    if not records or any(not any(v["element"] == el for v in records) for el in active):
        raise ValueError("missing paper/Stark transitions for requested elements; built-in coverage is Mg, Ca, Zn; provide custom line_data")
    if count*len(records) > MAX_LINE_POINT_WORK:
        raise ValueError("paper line-point work exceeds 50000000 cells")
    atoms = cfg.atomic_data if cfg.atomic_data is not None else data["elements"]
    if not isinstance(atoms, dict):
        raise ValueError("atomic_data must map elements to levels and ionization energies")
    populations = {}
    for el in active:
        check()
        if el not in atoms:
            raise ValueError("missing atomic I/II/III data for " + str(el))
        populations[el] = saha_populations(atoms[el], Te=te, Ne=ne)
    # 组成按原子数比例；每个阶段的电荷权重为 0、1、2。
    mean_charge = math.fsum(active[el]*float(np.dot([0, 1, 2], populations[el]["fractions"])) for el in active)
    if cfg.total_number_density_cm3 is None:
        if mean_charge <= 0:
            raise ValueError("cannot close charge balance with zero mean charge; supply a total density")
        total_density = _number(ne/mean_charge, "charge-balance total density", positive=True)
        density_mode = "charge_balance"
    else:
        total_density = cfg.total_number_density_cm3; density_mode = "specified_total"
    charge_density = _number(total_density*mean_charge, "derived charge-balance density")
    charge_error = (charge_density-ne)/ne
    if not math.isfinite(charge_error):
        raise ValueError("derived charge-balance relative error exceeds the finite numeric range")
    axis = np.linspace(low, high, count)
    if not np.isfinite(axis).all() or np.any(axis[1:] <= axis[:-1]):
        raise ValueError("wavelength grid is not representably finite and strictly increasing; enlarge the range or step")
    labels = sorted({v["element"] + " " + ("I", "II", "III")[v["charge"]] for v in records})
    if count*(len(labels)+2)*2 > MAX_SPECTRUM_CELLS:
        raise ValueError("paper spectrum channels exceed 5000000 cells")
    thin = {key: np.zeros(count) for key in labels}; absorbed = {key: np.zeros(count) for key in labels}
    diagnostics = []
    emit(5, "Saha populations and bound-level partition functions ready")
    for index, line in enumerate(records):
        check(); el = line["element"]; stage = line["charge"]
        ns = total_density*active[el]*float(populations[el]["fractions"][stage])
        row = paper_line_parameters(line, Te=te, Ne=ne, species_density_cm3=ns,
                                   partition_function=float(populations[el]["partition_functions"][stage]), config=cfg)
        # 高斯 sigma=FWHM/(2*sqrt(2*ln2))；Voigt 的 Lorentz 参数则为 FWHM/2。
        sigma = (line["wavelength_nm"]/r/(2*math.sqrt(2*math.log(2))) if cfg.instrument_broadening else 0.0)
        key = el + " " + ("I", "II", "III")[stage]
        delta = axis-line["wavelength_nm"]
        thin[key] += row["thin_area"]*voigt_profile(delta, sigma, row["thin_fwhm_nm"]/2)
        absorbed[key] += row["absorbed_area"]*voigt_profile(delta, sigma, row["absorbed_fwhm_nm"]/2)
        row["instrument_gaussian_fwhm_nm"] = line["wavelength_nm"]/r if cfg.instrument_broadening else 0.0
        diagnostics.append(row)
        emit(5+90*(index+1)/len(records), "Paper transition {}/{}".format(index+1, len(records)))
    def frame(channels):
        """把离子数组组织为宽表，并生成与主类兼容的总光谱表。"""
        ion = pd.DataFrame({"Wavelength (nm)": axis, **channels})
        ion["Sum(calc)"] = ion[labels].sum(axis=1)
        if not np.isfinite(ion.to_numpy(dtype=float)).all():
            raise ValueError("paper spectrum contains nonfinite values")
        return ion, pd.DataFrame({"wavelength": axis, "intensity": ion["Sum(calc)"].to_numpy()})
    ion, spectrum = frame(absorbed); thin_ion, thin_spectrum = frame(thin)
    def json_number(value):
        """将 NumPy 标量转换为 JSON 数字，用于稳定计算输入数据的来源指纹。"""
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError("atomic data must be JSON serializable")
    try:
        signature = hashlib.sha256(json.dumps({"lines": records, "elements": {el: atoms[el] for el in active}},
                                              sort_keys=True, allow_nan=False, default=json_number).encode()).hexdigest()
    except (TypeError, ValueError) as error:
        raise ValueError("invalid atomic data provenance: {}".format(error)) from None
    metadata = dict(model_version=MODEL_VERSION, paper_doi=PAPER_DOI, data_sha256=signature,
                    source_dataset_sha256=data.get("_source_sha256"), source_dataset=data.get("_source_path"),
                    density_mode=density_mode, total_number_density_cm3=total_density,
                    charge_balance_ne_cm3=charge_density,
                    charge_balance_relative_error=charge_error,
                    ion_populations={el: populations[el]["fractions"].tolist() for el in active},
                    partition_functions={el: populations[el]["partition_functions"].tolist() for el in active},
                    bound_level_counts={el: populations[el]["bound_level_counts"] for el in active},
                    intensity_scale=cfg.intensity_scale, intensity_units="relative {} spectral weight / nm; uncalibrated".format(cfg.intensity_scale),
                    instrument_broadening=cfg.instrument_broadening, resolution_applied=cfg.instrument_broadening,
                    optical_depth_width="unabsorbed Stark FWHM", width_exponent=WIDTH_EXPONENT,
                    population_stages=[0, 1, 2], emission_stages=sorted({v["charge"] for v in records}),
                    line_count=len(records), line_centers_in_window=sum(low <= v["wavelength_nm"] <= high for v in records),
                    output_points=count, output_step_nm=float(axis[1]-axis[0]),
                    parameters=dict(Te_eV=te, Ne_cm3=ne, elements=list(elements), percentages=pcts,
                                    low_w=low, upper_w=high, resolution=int(r), max_ion_charge=int(charge),
                                    path_length_m=cfg.path_length_m),
                    assumptions=["uniform LTE; finite bound-level I/II/III Saha; no higher stages or continuum lowering",
                                 "Table 1 fixed Stark W; no invented temperature dependence",
                                 "Eq.6 uses pre-absorption Stark FWHM; Eq.8 applied once",
                                 "Eq.2 is a relative integrated line weight; peak ratio enforced by SA^(1+alpha) area scaling",
                                 "independent line reconstruction/summation, not coupled overlapping-line radiative transfer",
                                 "optional analytic Gaussian instrument response after intrinsic self-absorption",
                                 "finite line coverage; Lorentz wings retained; finite output window and sampling",
                                 "not a digit-for-digit reproduction of the authors' unpublished source code"])
    emit(100, "Paper spectrum complete")
    return PaperSpectrumResult(spectrum, thin_spectrum, ion, thin_ion, pd.DataFrame(diagnostics), metadata)
