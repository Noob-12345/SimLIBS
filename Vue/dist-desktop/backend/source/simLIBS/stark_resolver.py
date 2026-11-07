"""Strict JSON -> STARK-B -> sourced NIST/DK1980 -> missing resolution.

The offline database contains normalized electron FWHM tables, never renderer W.
Atomic files are the sourced output of stark_atomic_data.prepare_atomic_samples.
Reading either format performs no network requests.
"""
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
import base64
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

from scipy.constants import e, k

from . import nist_stark
from .stark_b import SourceCache, StarkDataAccessError, _roman
from .stark_atomic_data import build_model_input, fetch_atomic_input, load_model_inputs, table_key
from .stark_semiempirical import Level, Perturber, calculate_stark_width


def default_database_path():
    override = os.environ.get('SIMLIBS_STARK_DATABASE')
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent/'data'/'stark_broadening.json'


def report_progress(message):
    """Task bridge supplies an element-level callback inside the worker."""


def check_cancelled():
    """Task bridge supplies cooperative cancellation and finite stage deadline."""
    return False


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise StarkDataAccessError(f'Invalid Stark data file {path}: {exc}') from exc


def load_database(path=None):
    """None discovers the official export; empty string disables auto discovery."""
    if path == '' or (path is None and os.environ.get('SIMLIBS_STARK_DATABASE') == ''):
        return None
    explicit = path is not None or bool(os.environ.get('SIMLIBS_STARK_DATABASE'))
    path = Path(path) if path is not None else default_database_path()
    if not path.is_file() and not explicit:
        return None
    try:
        stamp = path.stat()
    except OSError as exc:
        raise StarkDataAccessError(f'Cannot stat STARK-B database {path}: {exc}') from exc
    return _load_database(str(path.resolve()), stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size)


@lru_cache(maxsize=2)
def _load_database(path, mtime_ns, ctime_ns, size):
    """Read/validate once per file revision; discard potentially large raw XSAMS."""
    doc = _json(path)
    try:
        if (doc['schema_version'] != 1 or doc['source'] != 'STARK-B'
                or not isinstance(doc['rows'], list) or not isinstance(doc['manifest'], dict)):
            raise ValueError('expected STARK-B schema_version=1, rows and manifest')
        required = {'element', 'charge', 'lower_label', 'upper_label', 'dataset_id',
                    'method', 'source', 'source_url', 'samples', 'fit',
                    'calculated_wavelength_angstrom', 'c_angstrom_cm3'}
        for row in doc['rows']:
            if not isinstance(row, dict) or not required <= row.keys():
                raise ValueError('incomplete normalized electron table')
            if (type(row['charge']) is not int or row['charge'] < 0
                    or not isinstance(row['element'], str)
                    or not isinstance(row['samples'], list) or not row['source'] or not row['source_url']):
                raise ValueError('invalid species or samples')
            for value in (row['calculated_wavelength_angstrom'],):
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('invalid calculated wavelength')
            for sample in row['samples']:
                for name in ('temperature_k', 'ne'):
                    if not math.isfinite(sample[name]) or sample[name] <= 0:
                        raise ValueError('invalid table '+name)
                width = sample['fwhm_angstrom']
                if width is not None and not math.isfinite(width):
                    raise ValueError('invalid electron FWHM')
                if not isinstance(sample['flag'], str):
                    raise ValueError('missing impact validity flag')
                if (width is None or width <= 0) and not sample['flag']:
                    raise ValueError('nonpositive or missing source electron width requires a flag')
        raw = json.dumps(doc['rows'], ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
        if doc.get('rows_sha256') not in (hashlib.sha256(raw).hexdigest(), hashlib.sha256(raw+bytes([10])).hexdigest()):
            raise ValueError('rows_sha256 checksum mismatch')
        if type(doc['manifest'].get('complete')) is not bool:
            raise ValueError('collection manifest lacks explicit completeness')
        if 'raw_payloads' in doc:
            manifest_raw = json.dumps(doc['manifest'], ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':'), allow_nan=False).encode('utf-8')+bytes([10])
            if hashlib.sha256(manifest_raw).hexdigest() != doc.get('manifest_sha256'):
                raise ValueError('embedded manifest checksum mismatch')
            species = {(r['element'], r['charge']): r for r in doc['manifest']['species']}
            seen = set()
            for payload in doc['raw_payloads']:
                check_cancelled()
                key = payload['element'], payload['charge']
                if key in seen or key not in species or payload['encoding'] != 'gzip+base64':
                    raise ValueError('invalid or duplicate retained source payload')
                seen.add(key)
                raw_payload = gzip.decompress(base64.b64decode(payload['payload_gzip_base64'], validate=True))
                if (hashlib.sha256(raw_payload).hexdigest() != payload['uncompressed_sha256']
                        or payload['sha256'] != species[key]['sha256']):
                    raise ValueError('retained source payload checksum mismatch')
                parsed = json.loads(raw_payload)
                if (parsed['element'], parsed['charge']) != key:
                    raise ValueError('retained source species mismatch')
            if seen != set(species):
                raise ValueError('retained source payloads incomplete')
            counts = doc['counts']
            if (len(doc['rows']) != counts['tables'] or sum(len(r['samples']) for r in doc['rows']) != counts['samples']
                    or len({r['element'] for r in doc['rows']}) != counts['elements'] or len(species) != counts['species']):
                raise ValueError('export counts inconsistent')
    except (KeyError, TypeError, ValueError, OSError, EOFError) as exc:
        raise StarkDataAccessError(f'Invalid STARK-B database {path}: {exc}') from exc
    stamp = Path(path).stat()
    if (stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size) != (mtime_ns, ctime_ns, size):
        raise StarkDataAccessError(f'STARK-B database changed while being read: {path}; retry after export completes')
    return dict(rows=doc['rows'], manifest=doc['manifest'], path=path,
                file_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest())


def _atomic_directory(config, database):
    if config.stark_atomic_dir is not None:
        return Path(config.stark_atomic_dir)
    override = os.environ.get('SIMLIBS_STARK_ATOMIC_DIR')
    if override:
        return Path(override).expanduser()
    return None


def _atomic_identities(data, element, charge):
    """Exact numerical identity from the normalized, sourced NIST E1 export."""
    return [dict(element=element, charge=charge, wavelength_nm=r['wavelength_nm'],
                 lower_eV=r['lower_energy_ev'], upper_eV=r['upper_energy_ev'],
                 gA_s=r['aki']*float(2*Fraction(r['upper_j'])+1),
                 lower_label=' '.join(r[n] for n in ('lower_configuration', 'lower_term', 'lower_j')),
                 upper_label=' '.join(r[n] for n in ('upper_configuration', 'upper_term', 'upper_j')))
            for r in data['lines']]


def _mse_width(line, identity, atomic, explicit, cached, tables, temperature, ne):
    if line['charge'] not in (2, 3):
        return None, 'unsupported ion charge; DK1980 requires q=2 or 3'
    model = nist_stark.identify(line, explicit) if explicit else None
    if model is None and identity is not None:
        candidates = {table_key(t): cached[table_key(t)] for t in tables
                      if table_key(t) in cached and cached[table_key(t)]['status'] == 'ready'
                      and nist_stark.same_state(t['lower_label'], identity['lower_label'])
                      and nist_stark.same_state(t['upper_label'], identity['upper_label'])}
        if len(candidates) > 1:
            raise ValueError(f'Ambiguous DK1980 atomic model sources for {line["element"]} {line["wavelength_nm"]} nm')
        if candidates:
            model = next(iter(candidates.values()))
    if model is None:
        if identity is None:
            return None, 'exact numerical/quantum transition identity unavailable'
        if atomic is None:
            return None, 'no sourced atomic input; prepare sample/*_atomic.json or supply stark_mse_inputs'
        if not atomic.get('atomic_source'):
            return None, 'atomic input lacks provenance'
        if atomic.get('line_data', {}).get('status') == 'missing':
            return None, atomic['line_data'].get('reason', 'NIST E1 arrays unavailable')
        exact = nist_stark.identify(line, _atomic_identities(atomic, line['element'], line['charge']))
        if exact is None or any(not nist_stark.same_state(identity[key], exact[key])
                                for key in ('lower_label', 'upper_label')):
            return None, 'target numerical identity and quantum states not found in complete NIST E1 input'
        probe = dict(element=line['element'], charge=line['charge'],
                     lower_label=identity['lower_label'], upper_label=identity['upper_label'],
                     dataset_id='NIST atomic input', calculated_wavelength_angstrom=line['wavelength_nm']*10)
        try:
            model = build_model_input(probe, atomic['levels'], atomic['lines'],
                                      atomic['ionization_energy_ev'], atomic_source=atomic['atomic_source'])
        except (ValueError, KeyError, TypeError) as exc:
            if str(exc).startswith(('Ambiguous Aki', 'Conflicting NIST')):
                error = StarkDataAccessError('Ambiguous or conflicting NIST atomic data: '+str(exc))
                error.code = 'stark_ambiguous'
                raise error from exc
            return None, str(exc)
    elif not model.get('atomic_source'):
        raise ValueError('stark_mse_inputs require atomic_source provenance')
    try:
        levels = {}
        for name in ('lower', 'upper'):
            raw = dict(model[name])
            raw['same_n'] = tuple(Perturber(**p) for p in raw['same_n'])
            levels[name] = Level(**raw)
        width = calculate_stark_width(wavelength_nm=line['wavelength_nm'], temperature_k=temperature,
                    electron_density_cm3=ne, ion_charge=line['charge'], **levels)
        if not math.isfinite(width.hwhm_nm) or width.hwhm_nm <= 0:
            raise ValueError('nonpositive DK1980 width')
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return None, 'unusable atomic input or formula domain: '+str(exc)
    return dict(line, stark_width_nm=width.hwhm_nm, stark_reference_ne_cm3=ne,
                stark_source='DK1980 modified semiempirical', stark_method='DK1980',
                stark_source_format='dk1980-calculated', stark_temperature_k=temperature,
                stark_match='exact numerical identity with sourced atomic input',
                stark_atomic_source=model['atomic_source'],
                stark_atomic_quality=model.get('atomic_quality', 'explicit'),
                stark_model_doi='10.1016/0022-4073(80)90014-X',
                stark_model_assumptions=['isolated line', 'electron impact', 'LS coupling',
                                         'isolation and impact validity not automatically established'],
                stark_fwhm_nm=width.fwhm_nm), ''


def _check():
    if check_cancelled():
        raise InterruptedError('Stark cascade cancelled')


def _identity(line, identities):
    if all(nist_stark._state(line.get(key, '')) and nist_stark._state(line[key])[2] is not None
           for key in ('lower_label', 'upper_label')):
        return line
    return nist_stark.identify(line, identities)


def resolve_widths(records, config, *, te, ne, cmev):
    """Resolve only pending transitions at each tier; no access fault becomes missing."""
    _check()
    report_progress('Json抓取：读取并校验本地Stark数据库')
    database = load_database(config.stark_database_path)
    atomic_dir = _atomic_directory(config, database)
    explicit = config.stark_mse_inputs or ()
    if not isinstance(explicit, (list, tuple)):
        raise ValueError('stark_mse_inputs must be sourced exact atomic models')
    for model in explicit:
        if (not isinstance(model, dict) or not model.get('atomic_source') or not
                {'element','charge','wavelength_nm','lower_eV','upper_eV','gA_s','lower','upper'} <= model.keys()):
            raise ValueError('stark_mse_inputs require full numerical identity and atomic_source')
    cached = {}
    if atomic_dir is not None and (atomic_dir/'models.json').is_file():
        try:
            cached = load_model_inputs(atomic_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StarkDataAccessError('Invalid sourced atomic models: '+str(exc)) from exc
    cache = SourceCache(config.stark_cache_dir, allow_network=config.stark_allow_network)
    groups = defaultdict(list)
    for index, line in enumerate(records):
        groups[(line['element'], line['charge'])].append(index)
    found, missing = {}, {}
    temperature = te*e/k
    for number, ((element, charge), indices) in enumerate(groups.items(), 1):
        _check()
        species = element+' '+_roman(charge+1)
        report_progress(f'Json抓取：{species}，查找Stark系数（{number}/{len(groups)}）')
        tables = [r for r in database['rows'] if r['element'] == element and r['charge'] == charge] if database else []
        reasons = {i: {'JSON': 'no matching electron table in JSON' if database else 'bundled JSON unavailable'} for i in indices}
        faults, identities, atomic = [], [], None
        atomic_path = atomic_dir/f'{element}_{charge}_atomic.json' if atomic_dir is not None else None
        if charge in (2, 3) and atomic_path is not None and atomic_path.is_file():
            atomic = _json(atomic_path)
            try:
                identities = _atomic_identities(atomic, element, charge)
            except (KeyError, ValueError, TypeError) as exc:
                raise StarkDataAccessError('Invalid local atomic input '+str(atomic_path)+': '+str(exc)) from exc
        if tables and any(_identity(records[i], identities) is None for i in indices):
            report_progress('NIST：'+species+'，核对JSON所需完整跃迁身份')
            try:
                identities = nist_stark.transition_identities([records[i] for i in indices], cmev=cmev, cache=cache)
            except StarkDataAccessError as exc:
                faults.append(dict(layer='JSON identity', code=getattr(exc, 'code', 'stark_data_access'), message=str(exc)))
        for i in indices:
            _check()
            if tables:
                out, reason = nist_stark.match_width(records[i], _identity(records[i], identities), tables,
                    temperature_k=temperature, ne=ne, methods=config.stark_methods)
                reasons[i]['JSON'] = reason
                if out is not None:
                    found[i] = dict(out, stark_resolution_layer='JSON', stark_layer_reasons=dict(reasons[i]))
        pending = [i for i in indices if i not in found]
        report_progress(f'Json抓取：{species}，命中{len(indices)-len(pending)}/{len(indices)}条'+
                        ('；未命中继续在线STARK-B补查' if pending else '；无需在线补查'))
        if pending:
            try:
                online, absent = nist_stark.resolve_online([records[i] for i in pending], te=te, ne=ne, cmev=cmev,
                    cache_dir=config.stark_cache_dir, allow_network=config.stark_allow_network,
                    methods=config.stark_methods, progress=report_progress, cancelled=check_cancelled)
                for local, i in enumerate(pending):
                    if local in online:
                        found[i] = dict(online[local], stark_resolution_layer='STARK-B', stark_layer_reasons=dict(reasons[i]))
                    else:
                        reasons[i]['STARK-B'] = absent[local]['stark_missing_reason']
                        if absent[local].get('stark_access_failures'):
                            faults.extend(absent[local]['stark_access_failures'])
            except StarkDataAccessError as exc:
                faults.append(dict(layer='STARK-B', code=getattr(exc, 'code', 'stark_data_access'), message=str(exc)))
                for i in pending:
                    reasons[i]['STARK-B'] = 'source access failure: '+str(exc)
        pending = [i for i in indices if i not in found]
        # Trusted explicit/prepared models can be used offline; ordinary production
        # fetches the complete same-species ASD arrays only for remaining q=2/3 lines.
        requires_atomic = [i for i in pending if charge in (2, 3)
                           and nist_stark.identify(records[i], explicit) is None]
        if requires_atomic and atomic is None:
            ready = [cached[table_key(t)] for t in tables if table_key(t) in cached
                     and cached[table_key(t)]['status'] == 'ready']
            if not ready or any(_identity(records[i], identities) is None for i in requires_atomic):
                try:
                    atomic = fetch_atomic_input(element, charge, cache=cache,
                                                progress=report_progress, cancelled=check_cancelled)
                    identities = _atomic_identities(atomic, element, charge)
                except StarkDataAccessError as exc:
                    faults.append(dict(layer='NIST atomic', code=getattr(exc, 'code', 'stark_data_access'), message=str(exc)))
        if pending:
            report_progress(f'修正半经验：{species}，计算{len(pending)}条展宽系数' if charge in (2,3)
                            else '修正半经验：'+species+'，实际电荷q不在2/3适用范围')
        for i in pending:
            _check()
            out, reason = _mse_width(records[i], _identity(records[i], identities), atomic,
                                     explicit, cached, tables, temperature, ne)
            reasons[i]['DK1980'] = reason
            shared = dict(stark_layer_reasons=dict(reasons[i]),
                          stark_b_missing_reason=reasons[i].get('STARK-B', reasons[i]['JSON']))
            if out is not None:
                found[i] = dict(out, stark_resolution_layer='DK1980', **shared)
            else:
                missing[i] = dict(records[i], stark_width_nm=None, stark_resolution_layer='missing',
                    stark_mse_missing_reason=reason, stark_missing_reason='; '.join(k+': '+v for k,v in reasons[i].items()), **shared)
        for i in indices:
            row = found.get(i) or missing[i]
            if database:
                row.update(stark_database_path=database['path'], stark_database_sha256=database['file_sha256'],
                           stark_collection_complete=database['manifest']['complete'])
            if faults:
                row['stark_access_failures'] = faults+row.get('stark_access_failures', [])
        if faults and any(i in missing for i in indices):
            error = StarkDataAccessError('Unresolved Stark cascade after source access failure for '+species)
            error.code = next((f['code'] for f in faults if f['code'].startswith('stark_')), 'stark_data_access')
            error.stark_access_failures = faults
            raise error
    if database:
        for group in (found, missing):
            if group:
                group[min(group)]['stark_collection_manifest'] = database['manifest']
    return found, missing
