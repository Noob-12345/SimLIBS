"""当前静态 Stark/逐线自吸收组件：保留 NIST 线强，按开关重建谱线。

调试调用链：parse_atomic_payload -> prepare_nist_absorption
（拆分未分辨跃迁、按需计算布居、匹配 Stark）-> render_nist_absorption
（计算 tau/SA、更新面积与宽度、叠加 Voigt 线形）。

数据来源：NIST HTML 提供谱线和能级；Stark 系数优先使用用户 stark_data、
本地 JSON，不足时由 nist_stark -> stark_b 查询真实数据库并保存来源快照。
NIST lines 的六列为 [真空波长 nm, g_upper*Aki, 上能级 cm^-1,
原子序数 Z, 电离阶段 charge+1, 下能级 cm^-1]，网页 JavaScript 仅作为数据解析。

内部能量使用 eV，Te 使用 eV，Ne/粒子数密度使用 cm^-3，光程使用 m。
光学厚度计算局部换算到 SI；输出波长和线宽使用 nm。适合依次观察的变量：
nist_strength -> species_density_cm3 -> stark_width_nm -> tau_center -> SA。
"""
from collections import defaultdict
from dataclasses import dataclass
import json
import math
import re

import numpy as np
import pandas as pd
from scipy.constants import c
from scipy.special import logsumexp, voigt_profile

from .nist_lines import wavelength_grid, render_sticks
from .self_absorption import (
    PaperSpectrumResult, _number, load_paper_data, slab_attenuation_factor,
    WIDTH_EXPONENT, MAX_LINE_POINT_WORK,
)

# 多元素 NIST 输出允许最多 2000 万个双精度渲染单元（约 160 MB）；
# 独立论文模型的原有内存上限不变。未展宽线不计作全网格 Voigt 计算。
MAX_SPECTRUM_CELLS = 20_000_000


@dataclass(frozen=True)
class NISTSelfAbsorptionConfig:
    """当前 NIST Stark/自吸收入口的不可变配置；主类保存深拷贝快照。

    stark_data 接受逐线字典列表或 DataFrame；其 stark_width_nm 为 W，
    使用约定 FWHM = 2*W*Ne/Ne_ref。missing_stark 控制缺失时的处理。
    """
    # 有效吸收光程，m；设为 0 时 tau=0、SA=1，得到同线形模型的薄谱。
    path_length_m: float = 0.01
    # 总粒子数密度，cm^-3；None 时通过 Ne 与平均电荷反推。
    total_number_density_cm3: object = None
    # 光谱采样间隔，nm；与仪器分辨率 resolution 分别控制网格和线宽。
    wavelength_step_nm: float = 0.005
    # 是否在内禀 Stark/自吸收处理后叠加仪器高斯响应。
    instrument_broadening: bool = True
    # 用户逐线系数优先于内置记录；可带 source 字段保留出处。
    stark_data: object = None
    # 替换内置 JSON 的本地路径；这里只读取其中的逐线 Stark 系数。
    data_path: object = None
    # auto：本地缺失时查 STARK-B；local：只用用户/JSON，复现旧取数行为。
    stark_source: str = 'auto'
    # 数据库原始表及 NIST 身份补充表的缓存目录；None 使用用户缓存目录。
    stark_cache_dir: object = None
    # False 只重用已有 Stark/身份快照；主模拟的 NIST 计算谱请求仍需联网。
    stark_allow_network: bool = True
    # 有出处的计算方法优先序；同方法的多个等优先来源不自动选取。
    stark_methods: object = ('SCP', 'MSE')
    # error：缺失时报错；unbroadened：保留线面积，仅使用可选的仪器展宽。
    missing_stark: str = 'error'

    def __post_init__(self):
        """创建配置时校验光程、采样间隔、可选密度和仪器开关。"""
        for key in ('path_length_m', 'wavelength_step_nm'):
            object.__setattr__(self, key, _number(getattr(self, key), key,
                                               positive=key == 'wavelength_step_nm'))
        if self.total_number_density_cm3 is not None:
            object.__setattr__(self, 'total_number_density_cm3',
                               _number(self.total_number_density_cm3, 'total_number_density_cm3'))
        if type(self.instrument_broadening) is not bool:
            raise ValueError('instrument_broadening must be boolean')
        if self.stark_source not in ('auto', 'local'):
            raise ValueError('stark_source must be auto or local')
        if self.missing_stark not in ('error', 'unbroadened'):
            raise ValueError('missing_stark must be error or unbroadened')
        if type(self.stark_allow_network) is not bool:
            raise ValueError('stark_allow_network must be boolean')
        if (not isinstance(self.stark_methods, (list, tuple)) or not self.stark_methods or
                any(m not in ('SCP', 'MSE') for m in self.stark_methods) or
                len(set(self.stark_methods)) != len(self.stark_methods)):
            raise ValueError('stark_methods must be a nonempty ordered selection of SCP and MSE')
        object.__setattr__(self, 'stark_methods', tuple(self.stark_methods))


class MissingStarkDataError(ValueError):
    """逐线系数不全；missing_lines 保存可直接导出 CSV 的完整缺失清单。"""
    def __init__(self, rows, matched=()):
        """异常消息只预览前 8 条，调试完整覆盖情况应查看 missing_lines。"""
        self.missing_lines = pd.DataFrame(rows)
        # 即使未生成总谱，仍能检查哪些跃迁有真实系数、来源是什么。
        self.matched_lines = pd.DataFrame(matched)
        examples = ', '.join(f"{r['element']} charge={r['charge']} {r['wavelength_nm']:.8g} nm" for r in rows[:8])
        super().__init__(f'Missing Stark coefficients for {len(rows)} NIST transitions: {examples}. '
                         'Supply self_absorption_config.stark_data; no lines were silently skipped. '
                         'The complete list is in exception.missing_lines.')


def _array(text):
    """将网页中的 JSON 数值数组转成有限浮点数组，拒绝非数据表达式。"""
    try:
        value = np.asarray(json.loads(text), dtype=float)
    except (ValueError, TypeError):
        raise ValueError('Invalid numeric array in NIST response') from None
    if not np.isfinite(value).all():
        raise ValueError('Nonfinite NIST atomic data')
    return value


def _scalar(html, name):
    """读取 NIST 页面具名正标量，如 cm^-1/eV 换算常数 cmeV。"""
    match = re.search(r'\bvar\s+' + name + r'\s*=\s*([\d.eE+-]+)\s*;', html)
    if match is None:
        raise ValueError('NIST response missing ' + name)
    return _number(match.group(1), name, positive=True)


def parse_atomic_payload(html, *, include_levels=True):
    """解析同一次 NIST 响应的能级、统计权重、电离能和跃迁元数据。

    返回 atoms、transitions、cmeV、koeff。atoms 中阶段从 1 开始，
    transitions 中 charge 从 0 开始；上下能级转换成 eV 后参与后续匹配。
    include_levels=False 供仅 Stark 模式使用：只解析跃迁身份和能级能量，
    跳过布居所需的完整能级表与 Saha 常数。默认 True 保留原调用行为。
    """
    # 能级的获取：直接读取同一 NIST 响应中的 levels、gValues、ips，禁止执行网页 JavaScript。
    matrices = {}
    for name in (('levels', 'gValues', 'ips') if include_levels else ()):
        values = {}
        for z, stage, text in re.findall(
                rf'\b{name}\[(\d+)\]\[(\d+)\]\s*=\s*(\[[^\[\]]*\])\s*;', html):
            key = (int(z), int(stage))
            if key in values:
                raise ValueError('Duplicate NIST atomic stage')
            values[key] = _array(text).tolist()
        matrices[name] = values
    symbols = {}
    for z, stage, name in re.findall(
            r"spectra\[(\d+)\]\[(\d+)\]\['name'\]\s*=\s*'([^']*)'\s*;", html):
        if name:
            element = name.split()[0]
            if not re.fullmatch('[A-Z][a-z]?', element):
                raise ValueError('Invalid NIST element label')
            if int(z) in symbols and symbols[int(z)] != element:
                raise ValueError('Conflicting NIST element labels')
            symbols[int(z)] = element
    atoms = {}
    for z, element in (symbols.items() if include_levels else ()):
        # 要求页面提供从中性到类氢阶段的全套数据；裸核阶段由布居函数补入。
        stages = sorted(stage for number, stage in matrices['levels'] if number == z)
        if stages != list(range(1, z+1)):
            raise ValueError(f'Incomplete NIST ionization stages for {element}')
        atom = dict(z=z, levels={}, weights={}, ionization_cm1={})
        for stage in stages:
            key = (z, stage)
            energies = matrices['levels'][key]
            weights = matrices['gValues'].get(key, [])
            ips = matrices['ips'].get(key, [])
            if not energies or len(energies) != len(weights) or len(ips) != 1:
                raise ValueError(f'Incomplete NIST levels/weights/IP for {element} stage {stage}')
            if min(energies) < 0 or min(weights) <= 0 or ips[0] <= 0:
                raise ValueError('Invalid NIST level data')
            atom['levels'][stage] = energies
            atom['weights'][stage] = weights
            atom['ionization_cm1'][stage] = ips[0]
        atoms[element] = atom

    # 跃迁几率的获取：NIST lines 的第二列已经是 g_upper*Aki，不可误认为单独的 Aki。
    # 光学厚度公式直接使用此乘积，无须猜测简并能级对应的 g_upper。
    match = re.search(r'\bvar\s+lines\s*=\s*(\[.*?\])\s*;', html, re.S)
    if match is None:
        raise ValueError('NIST response missing transition lines')
    rows = _array(match.group(1))
    transitions = []
    if rows.size and (rows.ndim != 2 or rows.shape[1] != 6):
        raise ValueError('Unexpected NIST transition columns')
    cmev = _scalar(html, 'cmeV')
    for wave, ga, upper, z, stage, lower in rows:
        if z not in symbols or not stage.is_integer() or not 1 <= stage <= z:
            raise ValueError('Invalid NIST transition species')
        if wave <= 0 or ga <= 0 or lower < 0 or upper <= lower:
            raise ValueError('Invalid NIST transition parameters')
        transitions.append(dict(element=symbols[z], charge=int(stage)-1,
                                wavelength_nm=wave, gA_s=ga,
                                lower_eV=lower/cmev, upper_eV=upper/cmev))
    return dict(atoms=atoms, transitions=transitions, cmeV=cmev,
                koeff=_scalar(html, 'koeff') if include_levels else None)


def attach_nist_strengths(table, payload, te):
    """把计算线强关联到具体跃迁，保持每个 NIST stick 的总面积。

    相同元素/电荷/波长的未分辨跃迁按 gA*exp(-E_upper/Te) 分配面积。
    返回逐线字典列表；nist_strength 是分配后的 NIST 面积，ion 是离子列名。
    """
    grouped = defaultdict(list)
    for row in payload['transitions']:
        grouped[(row['element'], row['charge'], row['wavelength_nm'])].append(row)
    result = []
    for col in table:
        match = re.match(r'^([A-Z][a-z]?) ([IVXLCDM]+)(?:\s|$)', col)
        if not match:
            continue
        element, roman = match.groups()
        # 将罗马数字阶段转为整数；NIST 返回的电离阶段可能高于 III。
        values = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        stage = sum(-values[ch] if i+1 < len(roman) and values[ch] < values[roman[i+1]]
                    else values[ch] for i, ch in enumerate(roman))
        for wave, strength in zip(table.wavelength, table[col]):
            if strength == 0:
                continue
            candidates = grouped.get((element, stage-1, wave), [])
            if not candidates:
                raise ValueError(f'NIST stick lacks transition metadata: {element} {roman} {wave} nm')
            # 谱线强度的获取：总面积来自 dataSticksArray；同波长未分辨跃迁按 gA*Boltzmann 权重拆分。
            # 对数域归一化避免极弱跃迁直接 exp 下溢后失去相对权重。
            logs = np.array([math.log(row['gA_s'])-row['upper_eV']/te for row in candidates])
            fractions = np.exp(logs-logsumexp(logs))
            for row, fraction in zip(candidates, fractions):
                result.append(dict(row, nist_strength=float(strength*fraction), ion=f'{element} {roman}'))
    return result


def nist_populations(atom, te, ne, cmev, koeff):
    """用页面能级计算全部电离阶段的 LTE 配分函数和 Saha 粒子比例。

    fractions[charge] 对应该电荷态比例；log_partition 同样按 charge 索引。
    te 为 eV、ne 为 cm^-3；末尾裸核态配分函数为 1，即 log(U)=0。
    """
    # 粒子布居的计算：采用 NIST 页面全部电离阶段及其配分函数，并加入裸核阶段。
    # 与 NIST saha_lte.js 一致，使用页面提供的能级集合，不限定为旧 JSON 的 I/II/III。
    log_u = [float(logsumexp(np.log(atom['weights'][s])-
                            np.asarray(atom['levels'][s])/(cmev*te)))
             for s in range(1, atom['z']+1)] + [0.0]
    logs = [0.0]
    # koeff 与 NIST 页面保持一致；在对数域累加各相邻电离阶段的 Saha 比值。
    log_rw = math.log(koeff)+1.5*math.log(te)-math.log(ne)
    for stage in range(1, atom['z']+1):
        logs.append(logs[-1]+log_rw+log_u[stage]-log_u[stage-1]-
                    atom['ionization_cm1'][stage]/(cmev*te))
    fractions = np.exp(np.asarray(logs)-logsumexp(logs))
    return dict(fractions=fractions, log_partition=np.asarray(log_u))


def resolve_stark(records, config, *, te=None, ne=None, cmev=None):
    """为每条非零贡献跃迁匹配 W、参考电子密度和系数出处。

    优先级：用户 stark_data -> 本地 JSON -> STARK-B。自动查询需要 Te/Ne
    与同次 NIST 响应的 cmeV；保留旧直接调用（未传这些参数）为仅本地匹配。
    默认收集缺失项后抛异常；unbroadened 模式返回保留缺失标记的全部谱线。
    """
    # stark展宽系数的获取：JSON 仅提供已有的逐线系数；用户 stark_data 可补充任意 NIST 跃迁。
    # 不把仪器分辨率当作 Stark 系数，不给未知谱线赋默认值，不静默跳过。
    builtins = load_paper_data(config.data_path)['lines']
    supplied = config.stark_data
    if isinstance(supplied, pd.DataFrame):
        supplied = supplied.to_dict('records')
    if supplied is None:
        supplied = []
    if not isinstance(supplied, (list, tuple)):
        raise ValueError('stark_data must be a transition list or DataFrame')
    for row in [*builtins, *supplied]:
        if not isinstance(row, dict) or not isinstance(row.get('element'), str):
            raise ValueError('Each Stark record needs element, charge and line identification')
        charge = _number(row.get('charge'), 'Stark charge')
        if not charge.is_integer():
            raise ValueError('Stark charge must be an integer')
        _number(row.get('stark_width_nm'), 'stark_width_nm', positive=True)
        _number(row.get('stark_reference_ne_cm3', 1e16), 'stark_reference_ne_cm3', positive=True)
        if 'wavelength_nm' not in row and not {'lower_eV', 'upper_eV'} <= row.keys():
            raise ValueError('Stark record needs vacuum wavelength_nm or both level energies')
        for key in ('wavelength_nm', 'lower_eV', 'upper_eV'):
            if key in row:
                _number(row[key], key, positive=key == 'wavelength_nm')

    def matches(candidate, line, builtin):
        """内置记录用能级和 gA 识别；用户记录按其提供的所有标识共同匹配。"""
        if candidate['element'] != line['element'] or candidate['charge'] != line['charge']:
            return False
        # 内置论文波长可能采用空气波长：通过上下能级和 gA 联合匹配，避免空气/真空混用。
        if builtin:
            return (abs(candidate['lower_eV']-line['lower_eV']) <= .002 and
                    abs(candidate['upper_eV']-line['upper_eV']) <= .002 and
                    math.isclose(candidate['Aki_s']*candidate['g_upper'], line['gA_s'], rel_tol=.03))
        # 用户波长按真空 nm、绝对容差 1e-6 匹配；能量绝对容差为 1e-6 eV。
        return (('wavelength_nm' not in candidate or
                 math.isclose(candidate['wavelength_nm'], line['wavelength_nm'], rel_tol=0, abs_tol=1e-6)) and
                all(key not in candidate or abs(candidate[key]-line[key]) <= 1e-6
                    for key in ('lower_eV', 'upper_eV')))

    missing, resolved = {}, []
    for index, line in enumerate(records):
        candidates = [r for r in supplied if matches(r, line, False)]
        source = 'user stark_data'
        if not candidates:
            candidates = [r for r in builtins if matches(r, line, True)]
            source = 'paper coefficient table'
        if len(candidates) > 1:
            raise ValueError(f'Ambiguous Stark coefficients for {line["element"]} {line["wavelength_nm"]} nm')
        if not candidates:
            missing[index] = dict(line, stark_width_nm=None, stark_reference_ne_cm3=1e16,
                                  stark_missing_reason='no local coefficient')
            resolved.append(None)
            continue
        row = candidates[0]
        resolved.append(dict(line, stark_width_nm=float(row['stark_width_nm']),
                             stark_reference_ne_cm3=float(row.get('stark_reference_ne_cm3', 1e16)),
                             stark_source=str(row.get('source', source))))
    if missing and config.stark_source == 'auto' and all(x is not None for x in (te, ne, cmev)):
        from .nist_stark import resolve_online
        indices = list(missing)
        found, absent = resolve_online([records[i] for i in indices], te=te, ne=ne, cmev=cmev,
                                      cache_dir=config.stark_cache_dir, allow_network=config.stark_allow_network,
                                      methods=config.stark_methods)
        for offset, row in found.items():
            resolved[indices[offset]] = row
            del missing[indices[offset]]
        for offset, row in absent.items():
            missing[indices[offset]] = row
    if missing and config.missing_stark == 'error':
        raise MissingStarkDataError([missing[i] for i in sorted(missing)], [r for r in resolved if r is not None])
    for index, row in missing.items():
        # None 表示系数未知；不能用 0 或任意默认系数冒充数据库数据。
        resolved[index] = dict(row, stark_width_nm=None, stark_reference_ne_cm3=None,
                               stark_source='unavailable', stark_missing=True)
    for row in resolved:
        row.setdefault('stark_missing', False)
    return resolved


def prepare_nist_absorption(bands, *, te, ne, elements, percentages, config, self_absorption=True):
    """准备与采样网格无关的逐线缓存，供初次合成和 interpolate 复用。

    bands 是 (核心谱线表, 原子元数据) 列表。这里依次合并数据、分配线强、
    按需计算电离布居和数密度、匹配 Stark；返回 (逐线 records, metadata)。
    自吸收开启时比例总和须为 100；关闭时仅准备 Stark，不求 Saha/总密度。
    """
    if type(self_absorption) is not bool:
        raise ValueError('self_absorption must be a boolean')
    te = _number(te, 'Te', positive=True)
    ne = _number(ne, 'Ne', positive=True)
    pcts = [_number(p, 'percentage') for p in percentages]
    if self_absorption and (len(set(elements)) != len(elements) or
                            not math.isclose(sum(pcts), 100, abs_tol=1e-6, rel_tol=0)):
        raise ValueError('Self absorption requires unique elements with atomic percentages summing to 100')
    records, atoms = [], {}
    constants = None
    for table, payload in bands:
        current = (payload['cmeV'], payload['koeff'])
        if constants is not None and constants != current:
            raise ValueError('Inconsistent NIST constants across bands')
        constants = current
        for element, atom in (payload['atoms'].items() if self_absorption else ()):
            if element in atoms and atoms[element] != atom:
                raise ValueError('Inconsistent NIST atomic data across bands')
            atoms[element] = atom
        records.extend(attach_nist_strengths(table, payload, te))
    if constants is None:
        raise ValueError('No NIST response available')
    if not self_absorption:
        # 仅 Stark 模式保留 NIST 计算线面积；光程和总密度均不进入线宽计算。
        records = resolve_stark(records, config, te=te, ne=ne, cmev=constants[0])
        for index, row in enumerate(records):
            row['line_id'] = index
        return records, dict(
            model_version='nist-lines-stark-1', line_count=len(records),
            strength_source='NIST dataSticksArray (int_scale=2, photon weights)',
            wavelength_convention='vacuum (NIST show_av=3)',
            self_absorption=False, stark_broadening=True,
            assumptions=['NIST line areas preserved; no self-absorption population/opacity calculation',
                         'Local coefficients retain their reference convention; STARK-B HTML uses published temperature data/fits; VAMDC uses in-range linear table interpolation'])
    active = {el: p/100 for el, p in zip(elements, pcts) if p > 0}
    populations = {}
    for el in active:
        if el not in atoms:
            raise ValueError(f'NIST response missing level data for {el}')
        populations[el] = nist_populations(atoms[el], te, ne, *constants)
    # 平均电荷 <Z> 由组成与电离比例加权；默认使用 Ne=N_total*<Z> 闭合密度。
    mean_charge = sum(active[el]*float(np.dot(np.arange(len(pop['fractions'])), pop['fractions']))
                      for el, pop in populations.items())
    if config.total_number_density_cm3 is None:
        if mean_charge <= 0:
            raise ValueError('Cannot infer total density from zero mean charge')
        density = _number(ne/mean_charge, 'total density', positive=True)
    else:
        density = config.total_number_density_cm3
    records = resolve_stark(records, config, te=te, ne=ne, cmev=constants[0])
    for index, row in enumerate(records):
        pop = populations[row['element']]
        row['line_id'] = index
        # Ns 是该元素该电离阶段的数密度，尚需乘下能级 Boltzmann 因子才进入吸收公式。
        row['species_density_cm3'] = density*active[row['element']]*pop['fractions'][row['charge']]
        row['log_partition'] = pop['log_partition'][row['charge']]
    charge_error = _number(density*mean_charge, 'charge density')/ne-1
    if not math.isfinite(charge_error):
        raise ValueError('Charge balance exceeded numeric range')
    metadata = dict(model_version='nist-lines-self-absorption-1', line_count=len(records),
                    self_absorption=True, stark_broadening=True,
                    strength_source='NIST dataSticksArray (int_scale=2, photon weights)',
                    wavelength_convention='vacuum (NIST show_av=3)',
                    total_number_density_cm3=density,
                    density_mode='charge_balance' if config.total_number_density_cm3 is None else 'specified_total',
                    charge_balance_relative_error=charge_error,
                    ion_populations={el: p['fractions'].tolist() for el, p in populations.items()},
                    partition_functions={el: np.exp(p['log_partition']).tolist() for el, p in populations.items()},
                    assumptions=['NIST LTE level set and Saha stages including bare nuclei',
                                 'Independent lines; no coupled overlapping-line transfer',
                                 'Paper center attenuation and empirical width exponent -0.54',
                                 'Local coefficients retain their reference convention; STARK-B HTML uses published temperature data/fits; VAMDC uses in-range linear table interpolation'])
    return records, metadata


def render_nist_absorption(records, metadata, *, te, ne, low, high, resolution, config, self_absorption=True):
    """用缓存逐线数据合成吸收谱、薄谱、离子分量与诊断，无网络请求。

    调试顺序：width（未吸收 Stark FWHM）-> q -> tau -> sa ->
    absorbed_width/absorbed_area -> Voigt。返回共享容器 PaperSpectrumResult；
    self_absorption=False 时直接生成 Stark/Voigt 薄谱，tau=0、SA=1，
    不读取粒子布居或修改光程。函数名和结果容器名保留以兼容已有调用。
    """
    if type(self_absorption) is not bool:
        raise ValueError('self_absorption must be a boolean')
    grid = wavelength_grid(low, high, config.wavelength_step_nm)
    r = _number(resolution, 'resolution', positive=True)
    labels = sorted({row['ion'] for row in records})
    broadened_count = sum(not row.get('stark_missing', False) for row in records)
    channel_sets = 2 if self_absorption else 1
    if (len(grid)*broadened_count > MAX_LINE_POINT_WORK or
            len(grid)*(len(labels)+2)*channel_sets > MAX_SPECTRUM_CELLS):
        raise ValueError('Self absorption output exceeds work/memory limits; increase wavelength_step_nm')
    thin = {label: np.zeros(len(grid)) for label in labels}
    absorbed = {label: np.zeros(len(grid)) for label in labels} if self_absorption else thin
    diagnostics = []
    missing_channels = defaultdict(list)
    for row in records:
        center = row['wavelength_nm']
        sigma = center/r/math.sqrt(2) if config.instrument_broadening else 0.0
        if row.get('stark_missing', False):
            missing_channels[row['ion']].append(row)
            # 未知内禀宽度无法用于 tau/自吸收公式；保留 NIST 面积并明确标记。
            # SA=1 表示本次不施加衰减，NaN 表示相应物理量未计算。
            peak = row['nist_strength']/(sigma*math.sqrt(2*math.pi)) if sigma else np.nan
            diagnostics.append(dict(
                row, q_m=np.nan if self_absorption else 0.0,
                tau_center=np.nan if self_absorption else 0.0, SA=1.0,
                thin_area=row['nist_strength'], absorbed_area=row['nist_strength'],
                thin_fwhm_nm=np.nan, absorbed_fwhm_nm=np.nan,
                thin_peak=peak, absorbed_peak=peak, instrument_sigma_nm=sigma,
                stark_broadening_applied=False, self_absorption_applied=False))
            continue
        # 将参考密度下的 W 换算成当前 Ne 下的未吸收 Stark FWHM，单位 nm。
        width = 2*row['stark_width_nm']*ne/row['stark_reference_ne_cm3']
        _number(width, 'Stark FWHM', positive=True)
        ns = row['species_density_cm3'] if self_absorption else 0.0
        # 自吸收光学厚度的计算：用下能级 Boltzmann 因子与 NIST gA，线强仍保留 NIST 原值。
        # SI 换算：Ns 乘 1e6 得 m^-3，波长乘 1e-9 得 m；q 单位为 m。
        # Te 与 lower_eV 均用 eV，因此指数直接为 -lower_eV/Te。
        try:
            q = (math.exp(math.log(ns)+math.log(1e6)+math.log(row['gA_s'])+
                          4*math.log(center*1e-9)+math.log(config.path_length_m)-
                          math.log(4*math.pi**2*c)-row['log_partition']-row['lower_eV']/te)
                 if self_absorption and ns > 0 and config.path_length_m > 0 else 0.0)
            tau = _number(q/(width*1e-9), 'line-center optical depth')
            sa = float(slab_attenuation_factor(tau))
            # tau 使用未吸收内禀宽度；零光程/零 Ns 对应 tau=0、sa=1。
            absorbed_width = width*sa**WIDTH_EXPONENT
            area = row['nist_strength']
            # 面积乘 SA^0.46、宽度乘 SA^-0.54，使仪器响应前的 Lorentz 峰高比为 SA。
            absorbed_area = area*sa**(1+WIDTH_EXPONENT)
        except (OverflowError, ZeroDivisionError):
            raise ValueError('Self absorption line parameters exceeded numeric range') from None
        _number(absorbed_width, 'absorbed FWHM', positive=True)
        _number(absorbed_area, 'absorbed area')
        # 仪器展宽：统一采用 static/datagen 的 1/e 半宽 lambda/R，故 sigma=lambda/(R*sqrt(2))。
        # Stark 洛伦兹宽度和自吸收先计算，最后与高斯仪器响应组成 Voigt 线型。
        delta = grid-center
        # voigt_profile 的第三个参数 gamma 为 Lorentz 半高半宽，故 FWHM 需要除以 2。
        thin[row['ion']] += area*voigt_profile(delta, sigma, width/2)
        if self_absorption:
            absorbed[row['ion']] += absorbed_area*voigt_profile(delta, sigma, absorbed_width/2)
        diagnostics.append(dict(row, q_m=q, tau_center=tau, SA=sa, thin_area=area,
                                absorbed_area=absorbed_area, thin_fwhm_nm=width,
                                absorbed_fwhm_nm=absorbed_width,
                                thin_peak=2*area/(math.pi*width),
                                absorbed_peak=2*absorbed_area/(math.pi*absorbed_width),
                                instrument_sigma_nm=sigma,
                                stark_broadening_applied=True,
                                self_absorption_applied=self_absorption))

    # 按离子批量投影离散谱线；关闭仪器时保持梯形积分面积和重心，
    # 开启时使用既有的局部高斯算法，避免逐线遍历整个宽波段网格。
    for label, rows in missing_channels.items():
        table = pd.DataFrame({'wavelength': [row['wavelength_nm'] for row in rows],
                              label: [row['nist_strength'] for row in rows]})
        contribution = render_sticks(table, grid, r, instrument_broadening=config.instrument_broadening)
        thin[label] += contribution.intensity.to_numpy()
        if self_absorption:
            absorbed[label] += contribution.intensity.to_numpy()

    def frame(channels):
        """将离子数组汇总成离子宽表和 wavelength/intensity 总谱两张表。"""
        ion = pd.DataFrame({'Wavelength (nm)': grid, **channels})
        ion['Sum(calc)'] = sum(channels.values(), np.zeros(len(grid)))
        if not np.isfinite(ion.to_numpy(dtype=float)).all():
            raise ValueError('Self absorption spectrum contains nonfinite values')
        return ion, pd.DataFrame({'wavelength': grid, 'intensity': ion['Sum(calc)'].to_numpy()})
    ion, spectrum = frame(absorbed)
    # 薄谱保留相同 Stark 和仪器宽度；它可直接用于隔离自吸收本身的影响。
    if self_absorption:
        thin_ion, thin_spectrum = frame(thin)
    else:
        thin_ion, thin_spectrum = ion.copy(deep=True), spectrum.copy(deep=True)
    info = dict(metadata, self_absorption=self_absorption, stark_broadening=True,
                instrument_broadening=config.instrument_broadening,
                parameters=dict(Te_eV=te, Ne_cm3=ne, path_length_m=config.path_length_m),
                output_points=len(grid), output_step_nm=float(grid[1]-grid[0]))
    missing_count = sum(row.get('stark_missing', False) for row in records)
    info['stark_data'] = dict(source_mode=config.stark_source, methods=list(config.stark_methods),
                              missing_policy=config.missing_stark, missing_line_count=missing_count,
                              matched_line_count=len(records)-missing_count,
                              self_absorption_skipped_count=missing_count if self_absorption else 0,
                              local_line_count=sum('stark_dataset_id' not in r and not r.get('stark_missing', False)
                                                   for r in records),
                              stark_b_line_count=sum('stark_dataset_id' in r for r in records),
                               vamdc_line_count=sum(r.get('stark_source_format') == 'vamdc-xsams' for r in records),
                               method_unreported_count=sum(r.get('stark_method') == 'unreported' for r in records),
                               temperature_interpolated_count=sum(r.get('stark_temperature_method') ==
                                   'linear interpolation of tabulated widths' for r in records),
                              isolated_limit_unknown_count=sum('stark_dataset_id' in r and
                                  r.get('stark_isolated_limit_cm3') is None for r in records),
                              sources=sorted({r['stark_source'] for r in records if not r.get('stark_missing', False)}))
    if missing_count:
        info['assumptions'] = [*info.get('assumptions', []),
            'Missing Stark coefficients: retain NIST line areas with optional instrumental broadening only; '
            'no Stark broadening or self-absorption correction applied to those transitions']
    return PaperSpectrumResult(spectrum, thin_spectrum, ion, thin_ion, pd.DataFrame(diagnostics), info)
