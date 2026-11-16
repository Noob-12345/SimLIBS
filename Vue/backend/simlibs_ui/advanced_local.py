"""Local CSV LTE areas adapted to the shared advanced Stark/slab renderer."""
from dataclasses import replace
import csv
import hashlib
import importlib
import io
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from .adapter import source_module
from .advanced_nist import options as shared_options
from .advanced_nist_render import render_plain
from .advanced_stark import StarkTransport, cache_directory, json_value, merge_missing
from .offline_database import load_library, preflight
from .offline_engine import ion_fractions, CM_TO_EV
from .storage import now, write_csv, write_json


def options(raw):
    if not isinstance(raw, dict):
        raise ValueError('高级本地参数须为对象')
    request = dict(raw)
    for name in ('self_absorption', 'stark_broadening', 'instrument_broadening', 'matrix'):
        request.setdefault(name, False)
    out = shared_options(request)
    out['model'] = 'local'
    return out


def effective(p, raw):
    o = options(raw)
    if p.webscraping != 'local':
        raise ValueError('高级本地模拟要求 webscraping=local')
    if set(o['responses']) - set(p.elements):
        raise ValueError('响应系数含组成之外的元素')
    weights = [pct/100*(o['responses'].get(el, 1) if o['matrix'] else 1)
               for el, pct in zip(p.elements, p.percentages)]
    scale = math.fsum(weights)
    if scale <= 0:
        raise ValueError('有效元素响应不能全为零')
    q = replace(p, Te=p.Te*(o['te_factor'] if o['matrix'] else 1),
                Ne=p.Ne*(o['ne_factor'] if o['matrix'] else 1),
                percentages=tuple(100*w/scale for w in weights),
                local_broadening_enabled=o['stark_broadening'] or o['instrument_broadening'], local_temperature_mode='manual',
                local_temperature_K=0, local_gaussian_nm=0, local_lorentz_nm=0).validated()
    if not .01 <= q.Te <= 100 or not 1e10 <= q.Ne <= 1e23:
        raise ValueError('有效Te须为0.01–100 eV，Ne须为1e10–1e23 cm^-3')
    return q, o, scale


def quantum_rows(state):
    """Use exact CSV row numbers; unknown labels stay unknown, never guessed."""
    raw = Path(state['file']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != state['sha256']:
        raise ValueError('本地谱线文件在读取时改变，请重试')
    rows = list(csv.reader(io.StringIO(raw.decode(state['encoding']))))
    indices = {'wavelength': 1, 'aki': 2, 'energy': 3, 'g': 7}
    schemas = {}
    for number, values in enumerate(rows, 1):
        if any('wavelength' in str(value).lower() for value in values):
            # Mirror parse_file's supported numeric header semantics; never
            # assume physical column positions when attaching quantum labels.
            for key, tokens in {'wavelength': ('wavelength',), 'aki': ('aki',),
                                'energy': ('energy', 'levels'), 'g': ('g',)}.items():
                for index, value in enumerate(values):
                    name = str(value).strip().lower()
                    if name in tokens or any(token != 'g' and token in name for token in tokens):
                        indices[key] = index
                        break
            for key, aliases in {'configuration': ('configuration', 'configurations'),
                                 'term': ('term', 'terms'), 'j': ('j',)}.items():
                matches = [i for i, value in enumerate(values) if str(value).strip().lower() in aliases]
                if len(matches) != 1:
                    raise ValueError('本地量子身份表头缺失或歧义：'+key)
                indices[key] = matches[0]
            continue
        schemas[number] = dict(indices)
    return rows, schemas


def quantum_identity(line, rows, schemas):
    """Rejoin exact source rows and verify the parser's numeric identity."""
    pair = []
    for number in line['rows']:
        values, schema = rows[number-1], schemas[number]
        required = ('wavelength', 'aki', 'energy', 'g', 'configuration', 'term', 'j')
        if any(key not in schema or schema[key] >= len(values) for key in required):
            raise ValueError('本地量子身份列缺失，不能按固定位置猜配')
        numeric = {key: float(values[schema[key]]) for key in ('wavelength', 'aki', 'energy', 'g')}
        if not all(math.isfinite(value) for value in numeric.values()):
            raise ValueError('本地源行身份数值非有限')
        pair.append((numeric, values, schema))
    lower, upper = sorted(pair, key=lambda item: item[0]['energy'])
    expected = dict(wavelength_nm=pair[-1][0]['wavelength']*.1, Aki_s=upper[0]['aki']*1e8,
                    lower_cm=lower[0]['energy'], upper_cm=upper[0]['energy'],
                    g_lower=lower[0]['g'], g_upper=upper[0]['g'])
    if any(line[key] != value for key, value in expected.items()):
        raise ValueError('本地源行与已解析跃迁数值身份不一致，拒绝附加量子标签')
    labels = []
    for _, values, schema in (lower, upper):
        # Degree sign is a conventional odd-parity marker. Unknown/corrupted
        # terms and J strings are preserved, not converted into usable labels.
        term = values[schema['term']].strip().replace(chr(176), '*')
        labels.append(' '.join((values[schema['configuration']].strip(), term,
                                values[schema['j']].strip())))
    return dict(lower_label=labels[0], upper_label=labels[1],
                local_quantum_rows=[dict(row=number, raw=rows[number-1], columns=schemas[number])
                                    for number in line['rows']],
                quantum_normalization='header-resolved columns; whitespace and degree-sign odd parity only')


def local_records(p, library, o, factor, cancelled):
    records, populations, coverage = [], {}, {}
    for el, pct in zip(p.elements, p.percentages):
        if pct <= 0:
            continue
        if cancelled():
            raise InterruptedError('高级本地模拟已取消')
        states = library['elements'][el]
        fractions, log_u = ion_fractions(states, library['metadata']['elements'][el], p.Te, p.Ne)
        populations[el] = dict(fractions=fractions, log_partition=log_u)
        coverage[el] = {str(q): dict(valid_lines=len(s['transitions']), levels=len(s['levels']),
                                   excluded=s['excluded'], sha256=s['sha256']) for q, s in states.items()}
        for charge, state in sorted(states.items()):
            if charge > p.max_ion_charge:
                continue
            raw_rows = quantum_rows(state) if o['stark_broadening'] else None
            for line in state['transitions']:
                if cancelled():
                    raise InterruptedError('高级本地逐线准备已取消')
                if not p.low_w <= line['wavelength_nm'] <= p.upper_w:
                    continue
                area = (math.exp(math.log(pct/100)+math.log(fractions[charge])
                        +math.log(line['g_upper'])-line['upper_cm']*CM_TO_EV/p.Te
                        -log_u[charge]+math.log(line['Aki_s'])) if fractions[charge] > 0 else 0.)
                row = dict(line, element=el, charge=charge, ion=el+' '+('I' if charge == 0 else 'II'),
                           lower_eV=line['lower_cm']*CM_TO_EV, upper_eV=line['upper_cm']*CM_TO_EV,
                           gA_s=line['Aki_s']*line['g_upper'], local_lte_area=area*factor,
                           nist_strength=area*factor, strength_source='local CSV LTE/I-II Saha',
                           source_file=state['file'], source_sha256=state['sha256'],
                           source_encoding=state['encoding'])
                # nist_strength is the shared renderer's legacy area slot only.
                if raw_rows is not None:
                    row.update(quantum_identity(line, *raw_rows))
                records.append(row)
    mean_charge = math.fsum(pct/100*populations[el]['fractions'][1]
                            for el, pct in zip(p.elements, p.percentages) if pct > 0)
    density = None
    if o['self_absorption']:
        if o['density_mode'] == 'specified':
            density = o['number_density_cm3']*factor
        elif mean_charge > 0:
            density = p.Ne/mean_charge*factor
        else:
            raise ValueError('本地有限I/II平均电荷为零，无法反推总密度')
        for row in records:
            pop = populations[row['element']]
            pct = p.percentages[p.elements.index(row['element'])]/100
            row.update(species_density_cm3=density*pct*pop['fractions'][row['charge']],
                       log_partition=pop['log_partition'][row['charge']])
    metadata = dict(strength_source='local CSV LTE/I-II Saha relative photon areas',
                    wavelength_convention='original local CSV Angstrom / 10; not relabelled as NIST vacuum',
                    total_number_density_cm3=density, mean_charge=mean_charge,
                    ion_populations={el: pop['fractions'] for el, pop in populations.items()},
                    partition_functions={el: np.exp(pop['log_partition']).tolist() for el, pop in populations.items()},
                    coverage=coverage, assumptions=['Finite local observed-level I/II partition and Saha only; no III/IV invented',
                    'Relative photon areas exactly follow offline_engine; uncalibrated matrix response',
                    'No continuum, line overlap transfer or population feedback'])
    return records, metadata


def simulate(p, s, raw, cancelled=lambda: False, emit=None, request_stark=None):
    q, o, scale = effective(p, raw)
    source_module(s.source)
    engine = importlib.import_module('simLIBS.nist_self_absorption')
    lines_engine = importlib.import_module('simLIBS.nist_lines')
    library = load_library(s.line_database, {el for el, pct in zip(p.elements, p.percentages) if pct > 0})
    preflight(p, s.line_database)
    directory = Path(os.environ['SIMLIBS_TASK_DIR']) if os.environ.get('SIMLIBS_TASK_DIR') else None
    def report(value, message, deadline=180):
        if cancelled():
            raise InterruptedError('高级本地模拟已取消')
        if emit:
            emit('progress', current=value, total=100, message=message, deadline=deadline)
    step = p.step if p.resample else p.broaden_grid_step
    config = engine.NISTSelfAbsorptionConfig(path_length_m=o['path_length_m'], wavelength_step_nm=step,
             instrument_broadening=o['instrument_broadening'], missing_stark=o['missing_stark'],
             stark_cache_dir=cache_directory(), stark_allow_network=o['stark_allow_network'], stark_methods=o['stark_methods'])
    transport = StarkTransport(s, cancelled, report, request_stark)
    results, missing, matched, local_tables = [], [], [], []
    try:
        for actual, condition, factor, progress in ((p, '名义条件', 1, 5), (q, '有效条件', scale, 40)):
            report(progress, condition+'：读取本地CSV，计算有限能级LTE/I-II Saha线面积')
            records, metadata = local_records(actual, library, o, factor, cancelled)
            if not records or not any(r['local_lte_area'] > 0 for r in records):
                raise ValueError('当前本地库与波段没有非零有效跃迁，不向NIST线强回退')
            local_tables.append(records)
            if o['stark_broadening']:
                with transport.stage(condition, progress+15):
                    records = engine.resolve_stark(records, config, te=actual.Te, ne=actual.Ne, cmev=1/CM_TO_EV)
                for i, row in enumerate(records):
                    row['line_id'] = i
                    target = missing if row.get('stark_missing') else matched
                    target.append(json_value(dict(row, condition=condition, Te_eV=actual.Te, Ne_cm3=actual.Ne)))
                report(progress+25, condition+'：共享Stark/自吸收合成，最后应用仪器响应')
                result = engine.render_nist_absorption(records, metadata, te=actual.Te, ne=actual.Ne,
                    low=p.low_w, high=p.upper_w, resolution=p.resolution, config=config, self_absorption=o['self_absorption'])
                model = 'self-absorption' if o['self_absorption'] else 'stark'
            else:
                table = pd.DataFrame({'wavelength': [r['wavelength_nm'] for r in records]})
                for ion in sorted({r['ion'] for r in records}):
                    table[ion] = [r['local_lte_area'] if r['ion'] == ion else 0 for r in records]
                result, _ = render_plain([(table, None)], lines_engine, low=p.low_w, high=p.upper_w, step=step,
                                        resolution=p.resolution, instrument=o['instrument_broadening'], factor=1)
                result.line_diagnostics = pd.DataFrame([dict(r, thin_area=r['local_lte_area'], absorbed_area=r['local_lte_area'],
                    SA=1., tau_center=0., stark_broadening_applied=False, self_absorption_applied=False,
                    stark_source='not applied') for r in records])
                model = 'instrument' if o['instrument_broadening'] else 'sticks'
            # Correct provenance inherited from shared renderer compatibility names.
            result.metadata.update(metadata, model_version='local-lines-'+model+'-1',
                assumptions=metadata['assumptions'])
            for key in ('spectrum', 'thin_spectrum', 'ion_spectrum', 'thin_ion_spectrum'):
                if not np.isfinite(getattr(result, key).to_numpy(dtype=float)).all():
                    raise ValueError('高级本地光谱出现非有限值')
            results.append(result)
    except Exception as error:
        if directory and getattr(error, 'code', '').startswith('stark_'):
            write_json(directory/'stark-error.json', json_value(dict(code=error.code, message=str(error),
                       source_failures=getattr(error, 'stark_access_failures', []))))
        raise
    report(85, '保存本地名义薄谱、有效薄谱、修正谱及逐线诊断')
    nominal, result = results
    reference = result.thin_spectrum.copy()
    if not np.array_equal(reference.wavelength, nominal.thin_spectrum.wavelength):
        raise RuntimeError('本地名义与有效网格不一致')
    reference['nominal_intensity'] = nominal.thin_spectrum.intensity.to_numpy()
    merged = merge_missing(missing)
    coverage = dict(status=('partial' if matched else 'unavailable') if missing else 'complete' if o['stark_broadening'] else 'not-applied',
                    missing_policy=o['missing_stark'], missing_line_count=len(merged), matched_condition_count=len(matched))
    network_used = bool(transport.evidence)
    origin = dict(kind='simulation', mode='advanced', mode_version=2, model_version=result.metadata['model_version'],
        label='高级本地CSV · 有限能级LTE/I-II Saha · 相对photon', parameters=q.to_dict(), requested_parameters=p.to_dict(),
        advanced=o, self_absorption=o['self_absorption'], stark_broadening=o['stark_broadening'],
        instrument_broadening=o['instrument_broadening'], local_broadening_enabled=bool(o['stark_broadening'] or o['instrument_broadening']),
        spectrum_style='continuous' if o['stark_broadening'] or o['instrument_broadening'] else 'sticks',
        actual_resolution=p.resolution if o['instrument_broadening'] else None, requested_resolution=p.resolution,
        intensity_scale='photon', intensity_units='a.u. (local LTE relative photon weights)', network_used=network_used,
        line_strength_network_used=False, line_strength_location='local finite-level LTE/I-II Saha', data_provider='local CSV + sourced atomic metadata',
        library=library['signature'], atomic_sources={el: library['metadata']['elements'][el] for el in library['elements']},
        local_population_model=result.metadata, created_at=now(), stark_coverage=coverage,
        stark_input=dict(mode='automatic', priority=['JSON','STARK-B','NIST + DK1980','missing']),
        stark_data_access=dict(requests=transport.evidence, snapshots=transport.snapshots),
        instrument_convention='w=lambda/R (Gaussian 1/e half width); instrument applied last, R not in tau',
        assumptions=result.metadata['assumptions'])
    if directory:
        columns = ['element','charge','wavelength_nm','stark_source','condition','stark_missing_reason']
        for name, rows in (('missing', merged), ('matched', matched)):
            write_csv(directory/(name+'-stark.csv'), pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns))
            document = (dict(code='stark_coverage', count=len(merged), coverage=coverage,
                             matched_count=len(matched), missing_conditions=missing,
                             csv_sha256=hashlib.sha256((directory/'missing-stark.csv').read_bytes()).hexdigest())
                        if name == 'missing' else rows)
            write_json(directory/(name+'-stark.json'), json_value(document))
        write_csv(directory/'advanced-reference.csv', reference)
        write_csv(directory/'advanced-lines.csv', result.line_diagnostics)
        write_json(directory/'advanced-lines.json', json_value(result.line_diagnostics.to_dict('records')))
        write_csv(directory/'local-lte-lines.csv', pd.DataFrame(local_tables[-1]))
        origin.update(thin_reference=str(directory/'advanced-reference.csv'), line_table=str(directory/'advanced-lines.csv'),
                      local_line_table=str(directory/'local-lte-lines.csv'))
    report(95, '高级本地结果已就绪')
    return dict(raw=result.spectrum, interpolated=result.spectrum.copy(), ion=result.ion_spectrum, ion_interpolated=result.ion_spectrum.copy()), json_value(origin)
