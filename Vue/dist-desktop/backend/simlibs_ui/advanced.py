"""Vue advanced workflow backed by the shared paper Eq. 7/Stark line engine."""
from dataclasses import replace
import importlib
import math
import os
from pathlib import Path

import numpy as np
from scipy.integrate import trapezoid

from .adapter import source_module
from .storage import now, write_csv

VERSION = 'paper-eq7-stark-sa-1'
# The bundled paper Table 1 supplies measured Stark parameters for these elements.
# Other local-library elements cannot substitute for the missing paper inputs.
PAPER_ELEMENTS = frozenset(('Mg', 'Ca', 'Zn'))


def options(raw):
    if not isinstance(raw, dict):
        raise ValueError('高级参数须为对象')
    out = {}
    for name, default in (('self_absorption', True), ('matrix', True), ('instrument_broadening', True)):
        value = raw.get(name, default)
        if type(value) is not bool:
            raise ValueError(name+'须为布尔值')
        out[name] = value
    # Legacy widths/temperature/refinement remain serializable draft fields, but
    # are intentionally not used as replacements for the paper Stark FWHM.
    limits = [('column_cm2', 1e16, 0, 1e24), ('path_length_m', .01, 1e-12, 1e6),
              ('te_factor', 1, 1e-4, 1e4), ('ne_factor', 1, 1e-4, 1e4),
              ('intrinsic_gaussian_nm', .01, 0, 10), ('intrinsic_lorentz_nm', .002, 0, 10),
              ('temperature_K', 10000, 0, 1e8), ('grid_refinement', 1, 1, 4)]
    for name, default, low, high in limits:
        value = raw.get(name, default)
        if isinstance(value, bool):
            raise ValueError(name+'须为数值')
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(name+'须为数值') from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name}须在{low}至{high}之间')
        out[name] = value
    response = raw.get('responses', {})
    if not isinstance(response, dict):
        raise ValueError('元素响应须为对象')
    out['responses'] = {}
    for element, value in response.items():
        if isinstance(value, bool):
            raise ValueError('元素响应须为有限非负数')
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('元素响应须为有限非负数') from None
        if not math.isfinite(value) or not 0 <= value <= 1e6:
            raise ValueError('元素响应须在0至1e6之间')
        out['responses'][element] = value
    return out


def effective(p, raw):
    o = options(raw)
    if p.webscraping != 'local':
        raise ValueError('高级论文模型仅使用本地论文Stark/原子数据快照')
    missing = sorted(element for element, pct in zip(p.elements, p.percentages)
                     if pct > 0 and element not in PAPER_ELEMENTS)
    if missing:
        raise ValueError('、'.join(missing)+' 缺少论文Stark/完整三态原子数据；默认支持Mg、Ca、Zn，不向旧线库或NIST回退')
    if (p.upper_w-p.low_w)/((p.upper_w+p.low_w)/2) > .05:
        raise ValueError('高级窄带仪器近似要求相对波段跨度≤5%，请缩小波长范围')
    if set(o['responses'])-set(p.elements):
        raise ValueError('响应系数含组成之外的元素')
    weights = [pct/100*(o['responses'].get(element, 1) if o['matrix'] else 1)
               for element, pct in zip(p.elements, p.percentages)]
    scale = math.fsum(weights)
    if scale <= 0:
        raise ValueError('有效组成不能全为零，请增大至少一个有含量元素的响应')
    q = replace(p, Te=p.Te*(o['te_factor'] if o['matrix'] else 1),
                Ne=p.Ne*(o['ne_factor'] if o['matrix'] else 1),
                percentages=tuple(100*weight/scale for weight in weights),
                local_broadening_enabled=True, local_temperature_mode='manual',
                local_temperature_K=0, local_gaussian_nm=0, local_lorentz_nm=0).validated()
    if not .01 <= q.Te <= 100 or not 1e10 <= q.Ne <= 1e23:
        raise ValueError('有效Te须为0.01–100 eV，Ne须为1e10–1e23 cm^-3')
    return q, o, scale


def simulate(p, s, raw, cancelled=lambda: False, emit=None):
    def check():
        if cancelled():
            raise InterruptedError('高级模拟已取消')

    def progress(value, message):
        check()
        if emit:
            emit('progress', current=value, total=100, message=message, deadline=180)

    def engine_progress(start, span):
        def report(current, total, message):
            fraction = min(1, max(0, current/total)) if total else 0
            progress(start+span*fraction, message)
        return report

    q, o, scale = effective(p, raw)
    progress(5, '读取共享论文Stark与I/II/III能级数据')
    # Select the configured source package before importing its shared engine.
    module = source_module(s.source)
    engine = importlib.import_module('simLIBS.self_absorption')
    output_step = p.step if p.resample else p.broaden_grid_step
    density = o['column_cm2']/(100*o['path_length_m'])  # cm^-2 / path[cm] -> cm^-3
    config = engine.PaperSelfAbsorptionConfig(
        path_length_m=o['path_length_m'], total_number_density_cm3=density,
        wavelength_step_nm=output_step, instrument_broadening=o['instrument_broadening'],
        intensity_scale='photon')
    nominal = engine.simulate_paper_spectrum(
        Te=p.Te, Ne=p.Ne, elements=p.elements, percentages=p.percentages,
        low_w=p.low_w, upper_w=p.upper_w, resolution=p.resolution,
        max_ion_charge=p.max_ion_charge, config=config, cancelled=cancelled,
        progress=engine_progress(10, 30))
    check()
    result = engine.simulate_paper_spectrum(
        Te=q.Te, Ne=q.Ne, elements=q.elements, percentages=q.percentages,
        low_w=q.low_w, upper_w=q.upper_w, resolution=q.resolution,
        max_ion_charge=q.max_ion_charge,
        config=replace(config, total_number_density_cm3=density*scale),
        cancelled=cancelled, progress=engine_progress(45, 40))
    check()
    main = (result.spectrum if o['self_absorption'] else result.thin_spectrum).copy()
    ion = (result.ion_spectrum if o['self_absorption'] else result.thin_ion_spectrum).copy()
    lines = result.line_diagnostics.copy()
    reference = result.thin_spectrum.copy()
    if not np.isfinite(main.to_numpy(dtype=float)).all():
        raise ValueError('高级论文模型产生非有限值，请检查输入范围')
    x = main['wavelength'].to_numpy()
    if not np.array_equal(x, nominal.thin_spectrum['wavelength'].to_numpy()):
        raise RuntimeError('共享引擎名义谱与基体谱网格不一致')
    reference['nominal_intensity'] = nominal.thin_spectrum['intensity'].to_numpy()
    for channel in result.thin_ion_spectrum:
        if channel not in ('Wavelength (nm)', 'Sum(calc)'):
            reference[channel] = result.thin_ion_spectrum[channel].to_numpy()
    origin = {
        'kind': 'simulation', 'mode': 'advanced', 'mode_version': 2,
        'label': '高级本地 · 论文Eq.7 / Stark逐线自吸收 / 参数化基体（未标定）',
        'parameters': q.to_dict(), 'requested_parameters': p.to_dict(), 'advanced': o,
        'model_version': VERSION, 'network_used': False, 'actual_resolution': q.resolution,
        'intensity_scale': 'photon', 'intensity_units': 'model photon intensity per nm; uncalibrated',
        'spectrum_style': 'continuous', 'created_at': now(),
        'source_file': str(Path(module.__file__).resolve()),
        'paper_model': result.metadata, 'nominal_paper_model': nominal.metadata,
        'opacity_diagnostic_kind': 'per-line-center',
        'opacity_diagnostic_description': 'Each row is one line center: tau=tau_center, beta=SA. Not a continuous total optical-depth field.',
        'matrix': {'yield_scale': scale, 'effective_composition': dict(zip(q.elements, q.percentages)),
                   'effective_Te_eV': q.Te, 'effective_Ne_cm3': q.Ne,
                   'effective_column_cm2': o['column_cm2']*scale,
                   'path_length_m': o['path_length_m'], 'nominal_number_density_cm3': density,
                   'effective_number_density_cm3': density*scale},
        'grid': {'output_points': len(main), 'requested_step_nm': output_step,
                 'output_step_nm': float(x[1]-x[0]),
                 'instrument_broadening': o['instrument_broadening']},
        'diagnostics': {'tau_max': float(lines['tau_center'].max()) if len(lines) else 0.,
                        'beta_min': float(lines['SA'].min()) if len(lines) else 1.,
                        'line_count': len(lines),
                        'thin_integral': float(trapezoid(reference['intensity'], x)),
                        'corrected_integral': float(trapezoid(main['intensity'], x))},
        'assumptions': [
            'Shared RSC Advances 2023 Eq.7/Stark per-line model; paper Table 1 Mg/Ca/Zn and complete bundled NIST I/II/III level tables.',
            'Saha populations use prescribed Te and Ne; total atom/ion density is independently specified from column_cm2/(100*path_length_m).',
            'tau_center=q/Stark_FWHM; SA=-expm1(-tau)/tau; absorbed_FWHM=thin_FWHM*SA^-0.54; normalized Lorentz area scales as SA^0.46.',
            'Each line is modified separately before addition; no second attenuation by a summed opacity/escape factor.',
            'Instrument Gaussian is optional and follows per-line SA; FWHM=lambda_line/R. R never enters q, Stark FWHM, tau or SA; advanced UI retains a narrow window span<=5%.',
            'Photon scale is the paper energy-emission expression divided by the individual photon energy; all three spectra share the same scale.',
            'Parameterized element yields change effective density/composition and optional Te/Ne; no universal calibrated matrix-effect prediction.',
            'Legacy thermal/Gaussian/Lorentz widths and grid_refinement are retained only for draft compatibility and ignored by the paper engine.',
            'No time/space gradients, scattering, continuum, self-reversal, or population feedback; opacity export contains per-line-center diagnostics only.'
        ]}
    progress(90, '保存三谱对照与逐线中心诊断')
    if os.environ.get('SIMLIBS_TASK_DIR'):
        directory = Path(os.environ['SIMLIBS_TASK_DIR'])
        reference_path = directory/'advanced-reference.csv'
        diagnostic_path = directory/'advanced-opacity.csv'
        line_path = directory/'advanced-lines.csv'
        check()
        write_csv(reference_path, reference)
        write_csv(diagnostic_path, lines[['wavelength_nm', 'tau_center', 'SA']].rename(
                  columns={'wavelength_nm': 'wavelength', 'tau_center': 'tau', 'SA': 'beta'}))
        write_csv(line_path, lines)
        origin.update(thin_reference=str(reference_path), opacity_table=str(diagnostic_path),
                      line_table=str(line_path))
    progress(95, '论文逐线计算与三谱保存完成')
    return {'raw': main, 'interpolated': main.copy(), 'ion': ion,
            'ion_interpolated': ion.copy()}, origin
