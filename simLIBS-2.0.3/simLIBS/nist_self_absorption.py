"""NIST line strengths with per-transition self absorption (no JS execution).

NIST LIBS payload conventions follow its published saha_lte.js: lines contain
[vacuum wavelength, g_upper*Aki, upper energy/cm-1, Z, stage+1, lower energy/cm-1].
Stark coefficients are separate measured/input data, never inferred from R.
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

from .nist_lines import wavelength_grid
from .self_absorption import (
    PaperSpectrumResult, _number, load_paper_data, slab_attenuation_factor,
    WIDTH_EXPONENT, MAX_LINE_POINT_WORK, MAX_SPECTRUM_CELLS,
)


@dataclass(frozen=True)
class NISTSelfAbsorptionConfig:
    path_length_m: float = 0.01
    total_number_density_cm3: object = None
    wavelength_step_nm: float = 0.005
    instrument_broadening: bool = True
    stark_data: object = None
    data_path: object = None

    def __post_init__(self):
        for key in ('path_length_m', 'wavelength_step_nm'):
            object.__setattr__(self, key, _number(getattr(self, key), key,
                                               positive=key == 'wavelength_step_nm'))
        if self.total_number_density_cm3 is not None:
            object.__setattr__(self, 'total_number_density_cm3',
                               _number(self.total_number_density_cm3, 'total_number_density_cm3'))
        if type(self.instrument_broadening) is not bool:
            raise ValueError('instrument_broadening must be boolean')


class MissingStarkDataError(ValueError):
    """All missing transitions are available in missing_lines for CSV export."""
    def __init__(self, rows):
        self.missing_lines = pd.DataFrame(rows)
        examples = ', '.join(f"{r['element']} charge={r['charge']} {r['wavelength_nm']:.8g} nm" for r in rows[:8])
        super().__init__(f'Missing Stark coefficients for {len(rows)} NIST transitions: {examples}. '
                         'Supply self_absorption_config.stark_data; no lines were silently skipped. '
                         'The complete list is in exception.missing_lines.')


def _array(text):
    try:
        value = np.asarray(json.loads(text), dtype=float)
    except (ValueError, TypeError):
        raise ValueError('Invalid numeric array in NIST response') from None
    if not np.isfinite(value).all():
        raise ValueError('Nonfinite NIST atomic data')
    return value


def _scalar(html, name):
    match = re.search(r'\bvar\s+' + name + r'\s*=\s*([\d.eE+-]+)\s*;', html)
    if match is None:
        raise ValueError('NIST response missing ' + name)
    return _number(match.group(1), name, positive=True)


def parse_atomic_payload(html):
    # 能级的获取：直接读取同一 NIST 响应中的 levels、gValues、ips，禁止执行网页 JavaScript。
    matrices = {}
    for name in ('levels', 'gValues', 'ips'):
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
    for z, element in symbols.items():
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
    return dict(atoms=atoms, transitions=transitions, cmeV=cmev, koeff=_scalar(html, 'koeff'))


def attach_nist_strengths(table, payload, te):
    """Resolve coincident transitions while preserving every NIST stick area."""
    grouped = defaultdict(list)
    for row in payload['transitions']:
        grouped[(row['element'], row['charge'], row['wavelength_nm'])].append(row)
    result = []
    for col in table:
        match = re.match(r'^([A-Z][a-z]?) ([IVXLCDM]+)(?:\s|$)', col)
        if not match:
            continue
        element, roman = match.groups()
        # Roman stages in the response can extend past III.
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
            logs = np.array([math.log(row['gA_s'])-row['upper_eV']/te for row in candidates])
            fractions = np.exp(logs-logsumexp(logs))
            for row, fraction in zip(candidates, fractions):
                result.append(dict(row, nist_strength=float(strength*fraction), ion=f'{element} {roman}'))
    return result


def nist_populations(atom, te, ne, cmev, koeff):
    # 粒子布居的计算：采用 NIST 页面全部电离阶段及其配分函数，并加入裸核阶段。
    # 与 NIST saha_lte.js 一致，使用页面提供的能级集合，不限定为旧 JSON 的 I/II/III。
    log_u = [float(logsumexp(np.log(atom['weights'][s])-
                            np.asarray(atom['levels'][s])/(cmev*te)))
             for s in range(1, atom['z']+1)] + [0.0]
    logs = [0.0]
    log_rw = math.log(koeff)+1.5*math.log(te)-math.log(ne)
    for stage in range(1, atom['z']+1):
        logs.append(logs[-1]+log_rw+log_u[stage]-log_u[stage-1]-
                    atom['ionization_cm1'][stage]/(cmev*te))
    fractions = np.exp(np.asarray(logs)-logsumexp(logs))
    return dict(fractions=fractions, log_partition=np.asarray(log_u))


def resolve_stark(records, config):
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
        if candidate['element'] != line['element'] or candidate['charge'] != line['charge']:
            return False
        # 内置论文波长可能采用空气波长：通过上下能级和 gA 联合匹配，避免空气/真空混用。
        if builtin:
            return (abs(candidate['lower_eV']-line['lower_eV']) <= .002 and
                    abs(candidate['upper_eV']-line['upper_eV']) <= .002 and
                    math.isclose(candidate['Aki_s']*candidate['g_upper'], line['gA_s'], rel_tol=.03))
        return (('wavelength_nm' not in candidate or
                 math.isclose(candidate['wavelength_nm'], line['wavelength_nm'], rel_tol=0, abs_tol=1e-6)) and
                all(key not in candidate or abs(candidate[key]-line[key]) <= 1e-6
                    for key in ('lower_eV', 'upper_eV')))

    missing, resolved = [], []
    for line in records:
        candidates = [r for r in supplied if matches(r, line, False)]
        source = 'user stark_data'
        if not candidates:
            candidates = [r for r in builtins if matches(r, line, True)]
            source = 'paper coefficient table'
        if len(candidates) > 1:
            raise ValueError(f'Ambiguous Stark coefficients for {line["element"]} {line["wavelength_nm"]} nm')
        if not candidates:
            missing.append(dict(line, stark_width_nm=None, stark_reference_ne_cm3=1e16))
            continue
        row = candidates[0]
        resolved.append(dict(line, stark_width_nm=float(row['stark_width_nm']),
                             stark_reference_ne_cm3=float(row.get('stark_reference_ne_cm3', 1e16)),
                             stark_source=str(row.get('source', source))))
    if missing:
        raise MissingStarkDataError(missing)
    return resolved


def prepare_nist_absorption(bands, *, te, ne, elements, percentages, config):
    te = _number(te, 'Te', positive=True)
    ne = _number(ne, 'Ne', positive=True)
    pcts = [_number(p, 'percentage') for p in percentages]
    if len(set(elements)) != len(elements) or not math.isclose(sum(pcts), 100, abs_tol=1e-6, rel_tol=0):
        raise ValueError('Self absorption requires unique elements with atomic percentages summing to 100')
    records, atoms = [], {}
    constants = None
    for table, payload in bands:
        current = (payload['cmeV'], payload['koeff'])
        if constants is not None and constants != current:
            raise ValueError('Inconsistent NIST constants across bands')
        constants = current
        for element, atom in payload['atoms'].items():
            if element in atoms and atoms[element] != atom:
                raise ValueError('Inconsistent NIST atomic data across bands')
            atoms[element] = atom
        records.extend(attach_nist_strengths(table, payload, te))
    if constants is None:
        raise ValueError('No NIST response available')
    active = {el: p/100 for el, p in zip(elements, pcts) if p > 0}
    populations = {}
    for el in active:
        if el not in atoms:
            raise ValueError(f'NIST response missing level data for {el}')
        populations[el] = nist_populations(atoms[el], te, ne, *constants)
    mean_charge = sum(active[el]*float(np.dot(np.arange(len(pop['fractions'])), pop['fractions']))
                      for el, pop in populations.items())
    if config.total_number_density_cm3 is None:
        if mean_charge <= 0:
            raise ValueError('Cannot infer total density from zero mean charge')
        density = _number(ne/mean_charge, 'total density', positive=True)
    else:
        density = config.total_number_density_cm3
    records = resolve_stark(records, config)
    for index, row in enumerate(records):
        pop = populations[row['element']]
        row['line_id'] = index
        row['species_density_cm3'] = density*active[row['element']]*pop['fractions'][row['charge']]
        row['log_partition'] = pop['log_partition'][row['charge']]
    charge_error = _number(density*mean_charge, 'charge density')/ne-1
    if not math.isfinite(charge_error):
        raise ValueError('Charge balance exceeded numeric range')
    metadata = dict(model_version='nist-lines-self-absorption-1', line_count=len(records),
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
                                 'Stark coefficients scale linearly with electron density; no invented temperature law'])
    return records, metadata


def render_nist_absorption(records, metadata, *, te, ne, low, high, resolution, config):
    grid = wavelength_grid(low, high, config.wavelength_step_nm)
    r = _number(resolution, 'resolution', positive=True)
    labels = sorted({row['ion'] for row in records})
    if len(grid)*len(records) > MAX_LINE_POINT_WORK or len(grid)*(len(labels)+2)*2 > MAX_SPECTRUM_CELLS:
        raise ValueError('Self absorption output exceeds work/memory limits; increase wavelength_step_nm')
    thin = {label: np.zeros(len(grid)) for label in labels}
    absorbed = {label: np.zeros(len(grid)) for label in labels}
    diagnostics = []
    for row in records:
        center = row['wavelength_nm']
        width = 2*row['stark_width_nm']*ne/row['stark_reference_ne_cm3']
        _number(width, 'Stark FWHM', positive=True)
        ns = row['species_density_cm3']
        # 自吸收光学厚度的计算：用下能级 Boltzmann 因子与 NIST gA，线强仍保留 NIST 原值。
        try:
            q = (math.exp(math.log(ns)+math.log(1e6)+math.log(row['gA_s'])+
                          4*math.log(center*1e-9)+math.log(config.path_length_m)-
                          math.log(4*math.pi**2*c)-row['log_partition']-row['lower_eV']/te)
                 if ns > 0 and config.path_length_m > 0 else 0.0)
            tau = _number(q/(width*1e-9), 'line-center optical depth')
            sa = float(slab_attenuation_factor(tau))
            absorbed_width = width*sa**WIDTH_EXPONENT
            area = row['nist_strength']
            absorbed_area = area*sa**(1+WIDTH_EXPONENT)
        except (OverflowError, ZeroDivisionError):
            raise ValueError('Self absorption line parameters exceeded numeric range') from None
        _number(absorbed_width, 'absorbed FWHM', positive=True)
        _number(absorbed_area, 'absorbed area')
        # 仪器展宽：统一采用 static/datagen 的 1/e 半宽 lambda/R，故 sigma=lambda/(R*sqrt(2))。
        # Stark 洛伦兹宽度和自吸收先计算，最后与高斯仪器响应组成 Voigt 线型。
        sigma = center/r/math.sqrt(2) if config.instrument_broadening else 0.0
        delta = grid-center
        thin[row['ion']] += area*voigt_profile(delta, sigma, width/2)
        absorbed[row['ion']] += absorbed_area*voigt_profile(delta, sigma, absorbed_width/2)
        diagnostics.append(dict(row, q_m=q, tau_center=tau, SA=sa, thin_area=area,
                                absorbed_area=absorbed_area, thin_fwhm_nm=width,
                                absorbed_fwhm_nm=absorbed_width,
                                thin_peak=2*area/(math.pi*width),
                                absorbed_peak=2*absorbed_area/(math.pi*absorbed_width),
                                instrument_sigma_nm=sigma))

    def frame(channels):
        ion = pd.DataFrame({'Wavelength (nm)': grid, **channels})
        ion['Sum(calc)'] = sum(channels.values(), np.zeros(len(grid)))
        if not np.isfinite(ion.to_numpy(dtype=float)).all():
            raise ValueError('Self absorption spectrum contains nonfinite values')
        return ion, pd.DataFrame({'wavelength': grid, 'intensity': ion['Sum(calc)'].to_numpy()})
    ion, spectrum = frame(absorbed)
    thin_ion, thin_spectrum = frame(thin)
    info = dict(metadata, instrument_broadening=config.instrument_broadening,
                parameters=dict(Te_eV=te, Ne_cm3=ne, path_length_m=config.path_length_m),
                output_points=len(grid), output_step_nm=float(grid[1]-grid[0]))
    return PaperSpectrumResult(spectrum, thin_spectrum, ion, thin_ion, pd.DataFrame(diagnostics), info)
