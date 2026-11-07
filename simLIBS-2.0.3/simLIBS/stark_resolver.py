"""Strict STARK-B -> DK1980 -> missing resolution; no wavelength guessing.

The offline database contains normalized electron FWHM tables, never renderer W.
Atomic files are the sourced output of stark_atomic_data.prepare_atomic_samples.
Reading either format performs no network requests.
"""
from collections import defaultdict
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path

from scipy.constants import e, k

from . import nist_stark
from .stark_b import SourceCache, StarkDataAccessError
from .stark_atomic_data import build_model_input, load_model_inputs, table_key
from .stark_semiempirical import Level, Perturber, calculate_stark_width


def default_database_path():
    override = os.environ.get('SIMLIBS_STARK_DATABASE')
    if override:
        return Path(override).expanduser()
    # Source checkout and the Vue/backend/source copy share the repository data.
    for parent in Path(__file__).resolve().parents:
        for path in (parent/'stark-b'/'stark_broadening.json',
                     parent/'simLIBS-2.0.3'/'stark-b'/'stark_broadening.json'):
            if path.is_file():
                return path
    return Path(__file__).resolve().parents[1]/'stark-b'/'stark_broadening.json'


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
                    or not isinstance(row['samples'], list)):
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
                if width is not None and width < 0 and 'nonpositive' not in sample['flag']:
                    raise ValueError('negative source electron width requires nonpositive flag')
        if 'rows_sha256' in doc:
            raw = json.dumps(doc['rows'], ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
            if hashlib.sha256(raw).hexdigest() != doc['rows_sha256']:
                raise ValueError('rows_sha256 checksum mismatch')
    except (KeyError, TypeError, ValueError) as exc:
        raise StarkDataAccessError(f'Invalid STARK-B database {path}: {exc}') from exc
    stamp = Path(path).stat()
    if (stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size) != (mtime_ns, ctime_ns, size):
        raise StarkDataAccessError(f'STARK-B database changed while being read: {path}; retry after export completes')
    return dict(rows=doc['rows'], manifest=doc['manifest'], path=path)


def _atomic_directory(config, database):
    if config.stark_atomic_dir is not None:
        return Path(config.stark_atomic_dir)
    override = os.environ.get('SIMLIBS_STARK_ATOMIC_DIR')
    if override:
        return Path(override).expanduser()
    if database is not None:
        return Path(database['path']).parent.parent/'sample'
    for parent in Path(__file__).resolve().parents:
        for path in (parent/'sample', parent/'simLIBS-2.0.3'/'sample'):
            if path.is_dir():
                return path
    return Path(__file__).resolve().parents[1]/'sample'


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
        probe = dict(element=line['element'], charge=line['charge'],
                     lower_label=identity['lower_label'], upper_label=identity['upper_label'],
                     dataset_id='NIST atomic input', calculated_wavelength_angstrom=line['wavelength_nm']*10)
        try:
            model = build_model_input(probe, atomic['levels'], atomic['lines'],
                                      atomic['ionization_energy_ev'], atomic_source=atomic['atomic_source'])
        except (ValueError, KeyError, TypeError) as exc:
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


def resolve_widths(records, config, *, te, ne, cmev):
    """Resolve each transition once; preserve layer diagnostics and input order.

    An existing export is the offline STARK-B snapshot. Missing rows never trigger
    an implicit live STARK-B crawl. Optional ASD identity requests obey the network
    flag. Without an export, the existing live/cache database client is retained.
    """
    database = load_database(config.stark_database_path)
    atomic_dir = _atomic_directory(config, database)
    explicit = config.stark_mse_inputs or ()
    if not isinstance(explicit, (list, tuple)):
        raise ValueError('stark_mse_inputs must be a list of sourced atomic models with exact line identities')
    for model in explicit:
        if (not isinstance(model, dict) or not model.get('atomic_source')
                or not {'element', 'charge', 'wavelength_nm', 'lower_eV', 'upper_eV', 'gA_s',
                        'lower', 'upper'} <= model.keys()):
            raise ValueError('stark_mse_inputs require full numerical transition identity and atomic_source')
    cached = None
    found, missing = {}, {}
    access_error = None
    identity_errors = {}
    if database is None:
        try:
            found, missing = nist_stark.resolve_online(records, te=te, ne=ne, cmev=cmev,
                    cache_dir=config.stark_cache_dir, allow_network=config.stark_allow_network,
                    methods=config.stark_methods)
        except StarkDataAccessError as exc:
            access_error = exc
            missing = {i: dict(r, stark_missing_reason='data access failure: '+str(exc))
                       for i, r in enumerate(records)}
    else:
        missing = {i: dict(r) for i, r in enumerate(records)}
    groups = defaultdict(list)
    for index in missing:
        row = records[index]
        groups[(row['element'], row['charge'])].append(index)
    cache = SourceCache(config.stark_cache_dir, allow_network=config.stark_allow_network)
    temperature = te*e/k
    for (element, charge), indices in groups.items():
        atomic = None
        atomic_loaded = False
        atomic_path = atomic_dir/f'{element}_{charge}_atomic.json'
        def complete_identity(line):
            return all(nist_stark._state(line.get(name, ''))
                       and nist_stark._state(line[name])[2] is not None
                       for name in ('lower_label', 'upper_label'))
        # Only numerical-only lines may need atomic data before the database
        # lookup. Complete states must not depend on fallback file integrity.
        if charge in (2, 3) and any(not complete_identity(records[i]) for i in indices) and atomic_path.is_file():
            atomic = _json(atomic_path)
            atomic_loaded = True
        identities = []
        if atomic is not None:
            try:
                identities = _atomic_identities(atomic, element, charge)
            except (KeyError, ValueError, TypeError) as exc:
                raise StarkDataAccessError(f'Invalid atomic input {atomic_path}: {exc}') from exc
        tables = ([r for r in database['rows'] if r['element'] == element and r['charge'] == charge]
                  if database is not None else [])
        identity_reason = ''
        identity_error = None
        if tables and any(nist_stark.identify(records[i], identities) is None
                          and not records[i].get('lower_label') for i in indices):
            try:
                identities = nist_stark.transition_identities(
                    [records[i] for i in indices], cmev=cmev, cache=cache)
            except StarkDataAccessError as exc:
                identity_reason = str(exc)
                identity_error = exc
        for index in indices:
            line = records[index]
            identity = nist_stark.identify(line, identities)
            if identity is None and complete_identity(line):
                identity = line
            reason = missing[index].get('stark_missing_reason', '')
            if database is not None:
                out, reason = nist_stark.match_width(line, identity, tables,
                        temperature_k=temperature, ne=ne, methods=config.stark_methods)
                if out is not None:
                    found[index] = dict(out, stark_resolution_layer='STARK-B',
                                        stark_database_path=database['path'],
                                        stark_collection_complete=database['manifest'].get('complete', False))
                    del missing[index]
                    continue
                if not tables:
                    reason = 'no electron table for species in offline snapshot'
                if identity_reason:
                    reason += '; identity data access: '+identity_reason
                if not database['manifest'].get('complete', False):
                    reason += '; collection incomplete (see stark_collection_manifest)'
            if charge in (2, 3):
                if cached is None:
                    cached = {}
                    if (atomic_dir/'models.json').is_file():
                        try:
                            cached = load_model_inputs(atomic_dir)
                        except (OSError, ValueError, KeyError, TypeError) as exc:
                            raise StarkDataAccessError(f'Invalid atomic models {atomic_dir}: {exc}') from exc
                if not atomic_loaded and atomic_path.is_file():
                    atomic = _json(atomic_path)
                    atomic_loaded = True
            out, mse_reason = _mse_width(line, identity, atomic, explicit, cached or {}, tables, temperature, ne)
            faults = []
            if access_error is not None:
                faults.append(dict(layer='STARK-B', code=getattr(access_error, 'code', 'stark_data_access'),
                                   message=str(access_error), alternative='DK1980'))
            if identity_error is not None and identity is None:
                identity_errors[index] = identity_error
                faults.append(dict(layer='NIST identity', code=getattr(identity_error, 'code', 'stark_data_access'),
                                   message=str(identity_error), alternative='DK1980'))
            if out is not None:
                found[index] = dict(out, stark_resolution_layer='DK1980', stark_b_missing_reason=reason)
                if faults:
                    found[index]['stark_access_failures'] = faults
                del missing[index]
            else:
                missing[index] = dict(line, stark_width_nm=None, stark_b_missing_reason=reason,
                                      stark_mse_missing_reason=mse_reason,
                                      stark_missing_reason=f'STARK-B: {reason}; DK1980: {mse_reason}',
                                      stark_resolution_layer='missing')
            if database is not None:
                (found.get(index) or missing[index]).update(
                    stark_database_path=database['path'],
                    stark_collection_complete=database['manifest'].get('complete', False))
    for row in found.values():
        row.setdefault('stark_resolution_layer', 'STARK-B')
    if database is not None:
        # Preserve the full collection evidence once, rather than multiplying a
        # whole-catalog manifest by every rendered transition and CSV row.
        for group in (found, missing):
            if group:
                group[min(group)]['stark_collection_manifest'] = database['manifest']
    unresolved_identity_error = next((identity_errors[i] for i in missing if i in identity_errors), None)
    if unresolved_identity_error is not None:
        unresolved_identity_error.stark_missing_lines = [missing[i] for i in sorted(missing)]
        raise unresolved_identity_error
    if access_error is not None and missing:
        # Transport failure remains an access error, never a claim of physical absence.
        access_error.stark_missing_lines = [missing[i] for i in sorted(missing)]
        raise access_error
    return found, missing
