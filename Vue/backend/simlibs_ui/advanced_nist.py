"""Advanced-only transport/configuration adapter; physics stays in the copied engine."""
from dataclasses import replace
import csv
import hashlib
import importlib
import io
import math
import os
from pathlib import Path
import time
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import requests

from .adapter import source_module
from .models import ELEMENTS, MAX_POINTS
from .storage import now, write_csv, write_json

VERSION = 'nist-lines-self-absorption-1'
MAX_CSV_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 4_000_000
MAX_TOTAL_RESPONSE_BYTES = 32_000_000


def number(value, name, low=0, high=1e30):
    if isinstance(value, bool):
        raise ValueError(name+'须为有限数值')
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(name+'须为有限数值') from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name}须在{low}至{high}之间')
    return value


def parse_stark_csv(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_CSV_BYTES:
        raise ValueError('Stark CSV 最大支持 2 MB')
    if not text.strip():
        return []
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
        headers = reader.fieldnames or []
        required = {'element', 'charge', 'stark_width_nm'}
        if len(headers) != len(set(headers)) or not required <= set(headers):
            raise ValueError('Stark CSV 须含唯一列 element、charge、stark_width_nm')
        result = []
        for index, row in enumerate(reader, 2):
            if index > 20001:
                raise ValueError('Stark CSV 最多支持 20000 条记录')
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'Stark CSV 第{index}行列数不一致')
            element = row['element'].strip()
            if element not in ELEMENTS:
                raise ValueError(f'Stark CSV 第{index}行元素无效：{element}')
            charge = number(row['charge'], f'第{index}行charge', 0, 118)
            if not charge.is_integer():
                raise ValueError(f'Stark CSV 第{index}行charge须为非负整数')
            item = {'element': element, 'charge': int(charge),
                    'stark_width_nm': number(row['stark_width_nm'], f'第{index}行W', 1e-300),
                    'stark_reference_ne_cm3': number(row.get('stark_reference_ne_cm3', '1e16'), f'第{index}行参考Ne', 1e-300),
                    'source': row.get('source', '').strip()[:1000] or '用户 Stark CSV（未提供出处）'}
            for key in ('wavelength_nm', 'lower_eV', 'upper_eV'):
                if row.get(key, '').strip():
                    item[key] = number(row[key], f'第{index}行{key}', 1e-300 if key == 'wavelength_nm' else 0)
            if ('lower_eV' in item) != ('upper_eV' in item):
                raise ValueError(f'Stark CSV 第{index}行上下能级须成对填写')
            if 'wavelength_nm' not in item and not {'lower_eV', 'upper_eV'} <= item.keys():
                raise ValueError(f'Stark CSV 第{index}行须有真空波长或上下能级')
            result.append(item)
        if not result:
            raise ValueError('Stark CSV 没有数据行')
        return result
    except (csv.Error, UnicodeError) as error:
        raise ValueError('Stark CSV 格式错误：'+str(error)) from error


def options(raw):
    out = {'model': 'nist'}
    for name in ('self_absorption', 'stark_broadening', 'matrix', 'instrument_broadening'):
        value = raw.get(name, True)
        if type(value) is not bool:
            raise ValueError(name+'须为布尔值')
        out[name] = value
    if out['self_absorption'] and not out['stark_broadening']:
        raise ValueError('开启自吸收必须启用 Stark 展宽')
    for name, default, low, high in [('te_factor', 1, 1e-4, 1e4), ('ne_factor', 1, 1e-4, 1e4)]:
        out[name] = number(raw.get(name, default), name, low, high)
    # Missing Stark flag keeps the accepted advanced Stark-thin default.
    out['path_length_m'] = number(raw.get('path_length_m', .01), 'path_length_m', 0, 1e6) if out['self_absorption'] else 0.
    out['number_density_cm3'] = number(raw.get('number_density_cm3', 1e16), 'number_density_cm3', 1e-30, 1e24) if out['self_absorption'] else 1e16
    out['density_mode'] = raw.get('density_mode', 'charge_balance') if out['self_absorption'] else 'not_applied'
    if out['self_absorption'] and out['density_mode'] not in ('charge_balance', 'specified'):
        raise ValueError('密度方式须为charge_balance或specified')
    responses = raw.get('responses', {})
    if not isinstance(responses, dict) or any(element not in ELEMENTS for element in responses):
        raise ValueError('元素响应须为有效元素组成的对象')
    out['responses'] = {element: number(value, element+'响应', 0, 1e6) for element, value in responses.items()}
    out['stark_csv'] = raw.get('stark_csv', '') if out['stark_broadening'] else ''
    if out['stark_broadening']:
        parse_stark_csv(out['stark_csv'])
    name = raw.get('stark_name', '') if out['stark_broadening'] else ''
    if not isinstance(name, str):
        raise ValueError('Stark文件名须为文本')
    out['stark_name'] = name.replace('\\', '/').split('/')[-1][:240]
    return out


def effective(p, raw):
    o = options(raw)
    if set(o['responses'])-set(p.elements):
        raise ValueError('响应系数含组成之外的元素')
    weights = [pct/100*(o['responses'].get(el, 1) if o['matrix'] else 1) for el, pct in zip(p.elements, p.percentages)]
    scale = math.fsum(weights)
    if scale <= 0:
        raise ValueError('有效元素响应不能全为零')
    q = replace(p, webscraping='client', mode_version=2, broadening='local', broaden_convention='nist',
                Te=p.Te*(o['te_factor'] if o['matrix'] else 1), Ne=p.Ne*(o['ne_factor'] if o['matrix'] else 1),
                percentages=tuple(100*w/scale for w in weights), intensity_scale='photon',
                local_broadening_enabled=True, local_temperature_mode='manual', local_temperature_K=0,
                local_gaussian_nm=0, local_lorentz_nm=0).validated()
    if not .01 <= q.Te <= 100 or not 1e10 <= q.Ne <= 1e23:
        raise ValueError('有效Te须为0.01–100 eV，Ne须为1e10–1e23 cm^-3')
    return q, o, scale


def simulate(p, s, raw, cancelled=lambda: False, emit=None, request_get=None):
    q, o, scale = effective(p, raw)
    source_module(s.source)
    engine = importlib.import_module('simLIBS.nist_self_absorption')
    lines_engine = importlib.import_module('simLIBS.nist_lines')
    step = p.step if p.resample else p.broaden_grid_step
    if round((p.upper_w-p.low_w)/step)+1 > MAX_POINTS:
        raise ValueError('高级输出超过200000节点，请加大步长或缩小范围')
    density = o['number_density_cm3'] if o['density_mode'] == 'specified' else None
    config = engine.NISTSelfAbsorptionConfig(path_length_m=o['path_length_m'], total_number_density_cm3=density,
            wavelength_step_nm=step, instrument_broadening=o['instrument_broadening'], stark_data=parse_stark_csv(o['stark_csv']))
    request_get = request_get or requests.get
    directory = Path(os.environ['SIMLIBS_TASK_DIR']) if os.environ.get('SIMLIBS_TASK_DIR') else None
    cache, evidence = {}, []
    response_bytes = 0

    def check():
        if cancelled():
            raise InterruptedError('高级NIST模拟已取消')

    def report(value, message, deadline=180):
        check()
        if emit:
            emit('progress', current=value, total=100, message=message, deadline=deadline)

    def pause(seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            check()
            time.sleep(min(.05, max(0, until-time.monotonic())))

    def fetch(actual, condition, start):
        nonlocal response_bytes
        elements, pcts = actual.request_composition()
        bands = list(lines_engine.bands_for(actual.low_w, actual.upper_w))
        output = []
        for index, (low, high, req_low, req_high) in enumerate(bands):
            check()
            fields = {'composition': ';'.join(f'{el}:{float(pct):.17g}' for el, pct in zip(elements, pcts)),
                'spectra': ','.join(f'{el}0-{actual.max_ion_charge}' for el in elements), 'limits_type': 0,
                'show_av': 3, 'unit': 1, 'resolution': actual.resolution, 'temp': f'{actual.Te:.17g}',
                'eden': f'{actual.Ne:.17g}', 'maxcharge': actual.max_ion_charge, 'min_rel_int': 0,
                'int_scale': 2, 'libs': 1, 'low_w': f'{req_low:.17g}', 'upp_w': f'{req_high:.17g}'}
            url = 'https://physics.nist.gov/cgi-bin/ASD/lines1.pl?'+urlencode(fields)
            detail = '及全阶段能级' if o['self_absorption'] else '及跃迁' if o['stark_broadening'] else ''
            report(start+25*index/len(bands), f'{condition}：获取NIST线强{detail} {index+1}/{len(bands)}', s.static_deadline)
            if url not in cache:
                end = time.monotonic()+s.static_deadline
                for attempt in range(3):
                    check()
                    remaining = end-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('NIST当前波段请求超时')
                    try:
                        with request_get(url, stream=True, timeout=(min(s.connect_timeout, remaining), min(s.read_timeout, remaining)), verify=s.tls_verify) as response:
                            response.raise_for_status()
                            chunks, size = [], 0
                            for chunk in response.iter_content(65536):
                                check()
                                if time.monotonic() > end:
                                    raise TimeoutError('NIST当前波段读取超时')
                                size += len(chunk)
                                if size > MAX_RESPONSE_BYTES or response_bytes+size > MAX_TOTAL_RESPONSE_BYTES:
                                    raise ValueError('NIST响应超过安全大小上限，请缩小波段')
                                chunks.append(chunk)
                            content = b''.join(chunks)
                        html = content.decode('utf-8')
                        table = lines_engine.parse_sticks(html)
                        payload = engine.parse_atomic_payload(html, include_levels=o['self_absorption']) if o['stark_broadening'] else None
                        cache[url] = (table, payload)
                        response_bytes += size
                        evidence.append({'url': url, 'response_sha256': hashlib.sha256(content).hexdigest(), 'bytes': size})
                        break
                    except (requests.RequestException, TimeoutError) as error:
                        if attempt == 2:
                            raise RuntimeError('NIST请求失败：'+str(error)) from error
                        pause(min(1, max(0, end-time.monotonic())))
            table, payload = cache[url]
            wave = table['wavelength']
            upper = wave <= high if index == len(bands)-1 else wave < high
            output.append((table.loc[(wave >= low) & upper].copy(), payload))
        return output

    report(2, '校验Stark系数与高级参数')
    prepared, missing = [], []
    for actual, condition, start, factor in [(p, '名义条件', 5, 1), (q, '有效条件', 35, scale)]:
        bands = fetch(actual, condition, start)
        check()
        cfg = replace(config, total_number_density_cm3=density*factor if density is not None else None)
        if not o['stark_broadening']:
            prepared.append((actual, bands, None, cfg))
            continue
        try:
            records, metadata = engine.prepare_nist_absorption(bands, te=actual.Te, ne=actual.Ne,
                    elements=actual.elements, percentages=actual.percentages, config=cfg, self_absorption=o['self_absorption'])
            if not records:
                raise ValueError('当前波段未找到非零 NIST 跃迁，请调整波长范围')
            if o['self_absorption'] and density is None and factor != 1:
                cfg = replace(cfg, total_number_density_cm3=metadata['total_number_density_cm3']*factor)
                records, metadata = engine.prepare_nist_absorption(bands, te=actual.Te, ne=actual.Ne,
                        elements=actual.elements, percentages=actual.percentages, config=cfg, self_absorption=True)
            # Explicit, uncalibrated matrix yield: retain fetched NIST weights for audit.
            records = [dict(row, nist_strength_original=row['nist_strength'], nist_strength=row['nist_strength']*factor) for row in records]
            prepared.append((actual, records, metadata, cfg))
        except engine.MissingStarkDataError as error:
            missing.extend(dict(row, condition=condition) for row in error.missing_lines.to_dict('records'))
    if missing:
        table = pd.DataFrame(missing).drop_duplicates(subset=['element', 'charge', 'wavelength_nm', 'lower_eV', 'upper_eV', 'gA_s'])
        error = engine.MissingStarkDataError(table.to_dict('records'))
        if directory:
            # Default pandas CSV uses round-trip double precision; never UI formatting.
            write_csv(directory/'missing-stark.csv', table)
            write_json(directory/'missing-stark.json', {'code': 'missing_stark', 'count': len(table),
                       'csv_sha256': hashlib.sha256((directory/'missing-stark.csv').read_bytes()).hexdigest()})
        raise error
    results, plain_tables = [], []
    for index, (actual, records, metadata, cfg) in enumerate(prepared):
        report(65+index*15, '合成名义参考谱' if index == 0 else '合成有效条件光谱')
        if o['stark_broadening']:
            results.append(engine.render_nist_absorption(records, metadata, te=actual.Te, ne=actual.Ne,
                    low=actual.low_w, high=actual.upper_w, resolution=actual.resolution, config=cfg, self_absorption=o['self_absorption']))
        else:
            from .advanced_nist_render import render_plain
            result, table = render_plain(records, lines_engine, low=actual.low_w, high=actual.upper_w, step=step,
                    resolution=actual.resolution, instrument=o['instrument_broadening'], factor=1 if index == 0 else scale)
            results.append(result)
            plain_tables.append(table)
    check()
    nominal, result = results
    main, ion = result.spectrum.copy(), result.ion_spectrum.copy()
    reference = result.thin_spectrum.copy()
    if not np.array_equal(reference.wavelength, nominal.thin_spectrum.wavelength):
        raise RuntimeError('名义与有效条件网格不一致')
    reference['nominal_intensity'] = nominal.thin_spectrum.intensity.to_numpy()
    diagnostics = result.line_diagnostics
    user_rows = parse_stark_csv(o['stark_csv'])
    public_options = {key: value for key, value in o.items() if key != 'stark_csv'}
    mode_label = '逐线自吸收' if o['self_absorption'] else 'Stark / Voigt' if o['stark_broadening'] else '仪器高斯' if o['instrument_broadening'] else '未展宽网格投影'
    origin = {'kind': 'simulation', 'mode': 'advanced', 'mode_version': 2, 'model_version': result.metadata['model_version'],
        'label': f'高级NIST {mode_label} / 参数化基体（未标定）', 'parameters': q.to_dict(), 'requested_parameters': p.to_dict(),
        'advanced': public_options, 'network_used': True, 'bands': evidence, 'nist_url': evidence[0]['url'],
        'actual_resolution': q.resolution if o['instrument_broadening'] else None, 'requested_resolution': q.resolution,
        'self_absorption': o['self_absorption'], 'stark_broadening': o['stark_broadening'], 'instrument_broadening': o['instrument_broadening'],
        'intensity_scale': 'photon', 'intensity_units': 'relative NIST photon intensity per nm / a.u.',
        'spectrum_style': 'continuous' if o['stark_broadening'] or o['instrument_broadening'] else 'sticks',
        'created_at': now(), 'paper_model': result.metadata, 'nominal_paper_model': nominal.metadata,
        'instrument_convention': 'w=lambda/R (Gaussian 1/e half width); FWHM=2*sqrt(ln(2))*lambda/R',
        'opacity_diagnostic_kind': 'per-line-center' if o['stark_broadening'] else 'not-applicable',
        'stark_input': {'name': o['stark_name'], 'rows': len(user_rows), 'text_utf8_sha256': hashlib.sha256(o['stark_csv'].encode()).hexdigest(),
                        'sources': sorted({row['source'] for row in user_rows})},
        'engine_sha256': hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),
        'matrix': {'yield_scale': scale, 'effective_composition': dict(zip(q.elements, q.percentages)), 'effective_Te_eV': q.Te,
                   'effective_Ne_cm3': q.Ne, 'effective_number_density_cm3': result.metadata.get('total_number_density_cm3')},
        'diagnostics': {'tau_max': float(diagnostics.tau_center.max()) if len(diagnostics) else None,
                        'beta_min': float(diagnostics.SA.min()) if len(diagnostics) else None, 'line_count': result.metadata['line_count']},
        'assumptions': ['NIST photon weights; atomic populations only when SA is enabled; Stark coefficients only when Stark is enabled.',
            'Matrix yield scales effective NIST weights and absorber density; this optional response model is uncalibrated.',
            'Independent per-line SA/Voigt; no continuum, self-reversal or coupled radiative transfer. R never enters tau.']}
    report(93, '保存三谱及完整逐线诊断')
    if directory:
        write_csv(directory/'advanced-reference.csv', reference)
        origin['thin_reference'] = str(directory/'advanced-reference.csv')
        if o['stark_broadening']:
            write_csv(directory/'advanced-lines.csv', diagnostics)
            write_csv(directory/'advanced-opacity.csv', diagnostics[['wavelength_nm', 'tau_center', 'SA']].rename(columns={'wavelength_nm': 'wavelength', 'tau_center': 'tau', 'SA': 'beta'}))
            origin.update(line_table=str(directory/'advanced-lines.csv'), opacity_table=str(directory/'advanced-opacity.csv'))
        else:
            write_csv(directory/'advanced-nist-lines.csv', plain_tables[-1])
            origin['nist_line_table'] = str(directory/'advanced-nist-lines.csv')
    report(95, '高级NIST计算完成，正在发布结果')
    return {'raw': main, 'interpolated': main.copy(), 'ion': ion, 'ion_interpolated': ion.copy()}, origin
