"""为 STARK-B 对比采集 NIST ASD 原子数据，严格准备修正半经验模型输入。

本模块导入时不联网、不写文件。由 stark_semiempirical_check.py 的
fetch-atomic/all 子命令显式调用。原始 TSV、URL、SHA256 保存在 sample/raw。
只下载 STARK-B 有记录且当前模型支持 (q=2,3) 的物种。为得到扰动态，
同物种需要完整能级和 E1 跃迁表，不能只查目标光学谱线的波长窗口。

自动处理范围：可解析的单价电子+闭壳层芯、双重态 LS 项，使用完整精细
结构的 (2J+1) 重心和完整 E1 分量求和。复杂组态、缺失分量或多个电离
阈值一律记 missing。不能凭最近波长、随意径向因子或缺失 Aki 补数据。
R² = sum(S_JJ') / [(2L+1)(2S+1)]，其中
S_JJ' = Aki * g_upper * lambda_A**3 / 2.02613e18 (a0²)。
这属于用 NIST 辐射跃迁数据构造的 LS 阵列输入，并非原论文的完整
Bates-Damgaard 径向积分复现。高激发缺表仍会限制覆盖率。

sample/manual_inputs.json 可补复杂离子的经核验输入，结构为 {"models":
[{"key":..., "atomic_source":"文献/数据出处", "lower":{...}, "upper":{...}}]}。
key 取 models.json 的记录；lower/upper 结构同 stark_semiempirical.Level。
任何手工补充都必须说明出处，且与自动结果分组统计。
"""
from collections import defaultdict
import csv
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

import requests

from .stark_semiempirical import Level, Perturber, effective_principal_quantum_number

CM1_PER_EV = 8065.54393734921
ASD_LEVELS = 'https://physics.nist.gov/cgi-bin/ASD/energy1.pl'
ASD_LINES = 'https://physics.nist.gov/cgi-bin/ASD/lines1.pl'
ASD_IE = 'https://physics.nist.gov/cgi-bin/ASD/ie.pl'
ORBITALS = 'spdfghiklmnoqrtuvwxyz'


def table_key(table):
    """原子输入不依赖温度/密度；不同原始文献及身份保持独立。"""
    identity = {k: table.get(k) for k in ('element', 'charge', 'dataset_id', 'lower_label',
                'upper_label', 'calculated_wavelength_angstrom', 'source_ids')}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _clean(text):
    value = str(text or '').strip().strip('\ufeff')
    if value.startswith('='):
        value = value[1:].strip()
    return value.strip('"').strip()


def _number(text):
    value = _clean(text).strip('[]()').replace(' ', '')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value):
        raise ValueError('Uncertain or nonnumeric NIST value: '+str(text))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError('Nonfinite NIST value')
    return out


def _header(name):
    return re.sub(r'[\s_()\-−]', '', _clean(name)).lower()


def _tsv(text):
    if '<html' in text.lower() or '<!doctype' in text.lower():
        raise ValueError('NIST returned HTML instead of tab-separated data')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), delimiter='\t')
    if not reader.fieldnames or len(reader.fieldnames) < 2:
        raise ValueError('NIST response lacks a TSV header')
    rows = []
    for row in reader:
        # Nonempty overflow columns indicate a changed/malformed source layout.
        if row.get(None) and any(_clean(x) for x in row[None]):
            raise ValueError('NIST TSV has unexpected extra columns')
        rows.append({_header(k): _clean(v) for k, v in row.items() if k is not None})
    return {_header(k) for k in reader.fieldnames}, rows


def _ls_term(text):
    token = _clean(text).replace('o', '*')
    if not re.fullmatch(r'\d+[SPDFGHIKLMNOQRTUVWXYZ]\*?', token):
        raise ValueError('Only explicit LS terms can be matched: '+text)
    return token


def _j(text):
    token = _clean(text)
    if not re.fullmatch(r'\d+(?:/\d+|\.\d+)?', token):
        raise ValueError('Unresolved or uncertain J: '+token)
    out = Fraction(token)
    if out < 0 or (2*out).denominator != 1:
        raise ValueError('Invalid J')
    return out


def _config(text):
    return re.sub(r'\s+', '', _clean(text)).replace('.(', '(')


def parse_nist_levels(text):
    """解析 cm^-1 的 ASD 能级 TSV；返回 (resolved_levels, limit_rows)。"""
    headers, raw = _tsv(text)
    energy_key = next((x for x in ('levelcm1', 'levelcm^1', 'energycm1', 'energycm^1') if x in headers), None)
    if not {'configuration', 'term', 'j'} <= headers or energy_key is None:
        raise ValueError('Expected NIST Configuration/Term/J/Level(cm-1) columns')
    levels, limits = [], []
    previous_config, previous_term = '', ''
    for row in raw:
        config, term = row.get('configuration', ''), row.get('term', '')
        # ASD exports uncertainty markers separately from the numeric energy.
        # Keep brackets/parentheses accepted by _number, but reject '?' and
        # unknown '+x' offsets even when exported in a separate Suffix column.
        energy_text = row.get('prefix', '')+row.get(energy_key, '')+row.get('suffix', '')
        if 'limit' in (' '.join((config, term))).lower():
            try:
                energy = _number(energy_text)/CM1_PER_EV
            except ValueError:
                continue
            if energy > 0:
                limits.append(dict(energy_ev=energy, label=config+' '+term, raw=row))
            continue
        # ASD can suppress repeated configuration/term cells within a term.
        if config:
            previous_config = config
            previous_term = term
        elif term:
            previous_term = term
        config, term = config or previous_config, term or previous_term
        try:
            energy, j = _number(energy_text)/CM1_PER_EV, _j(row.get('j', ''))
            term = _ls_term(term)
        except ValueError:
            continue
        if not config or energy < 0:
            continue
        levels.append(dict(configuration=_config(config), term=term, j=str(j),
                           energy_ev=energy, level_id=row.get('id', ''), raw=row))
    return levels, limits


def parse_nist_lines(text, *, diagnostics=None):
    """读取真空 nm、cm^-1 能量、Aki；拒绝用未知 Type 充当 E1。"""
    headers, raw = _tsv(text)
    required = {'ritzwlvacnm', 'akis^1', 'eicm1', 'ekcm1', 'confi', 'termi', 'ji',
                'confk', 'termk', 'jk', 'gi', 'gk', 'type'}
    # NIST's s^-1 header retains '^'; canonical key of Aki(s^-1) is akis^1.
    if not required <= headers:
        # ASD omits classification columns for spectra having only observed,
        # unclassified wavelengths. Recognize the verified sparse export only;
        # never interpret a partial classified export as physical data absence.
        sparse_headers = {'obswlvacnm', 'ritzwlvacnm', 'akis^1', 'acc', 'eicm1', 'ekcm1',
                          'type', 'tpref', 'lineref', 'idi', 'idk'}
        empty_fields = sparse_headers - {'obswlvacnm', 'lineref'}
        observed_only = (headers - {''} == sparse_headers and bool(raw) and
                         all(row.get('obswlvacnm') and row.get('lineref') and
                             not any(row.get(key) for key in empty_fields) for row in raw))
        if not observed_only:
            missing = ', '.join(sorted(required - headers))
            raise ValueError('Expected NIST vacuum Ritz wavelength/Aki/energy/configuration/term/J/g '
                             'columns; missing: '+missing)
        if diagnostics is not None:
            diagnostics.update(status='missing', exported_lines=len(raw), observed_lines=len(raw),
                               e1_lines=0, missing_fields=['Aki', 'Ritz wavelength', 'level energies',
                                                         'level classifications'],
                               reason='NIST ASD contains observed wavelengths only; no Aki, Ritz '
                                      'wavelength, level energies or level classifications; '
                                      'cannot construct E1 Aki arrays')
        return []
    rows = []
    for row in raw:
        kind = row.get('type', '').upper()
        if kind not in ('', 'E1'):
            continue
        try:
            wavelength, aki = _number(row['ritzwlvacnm']), _number(row['akis^1'])
            ei, ek = _number(row['eicm1'])/CM1_PER_EV, _number(row['ekcm1'])/CM1_PER_EV
            ji, jk = _j(row['ji']), _j(row['jk'])
            gi, gk = _number(row['gi']), _number(row['gk'])
            ti, tk = _ls_term(row['termi']), _ls_term(row['termk'])
        except ValueError:
            continue
        if (min(wavelength, aki, gi, gk) <= 0 or ek <= ei or ei < 0 or
                gi != float(2*ji+1) or gk != float(2*jk+1)):
            continue
        # Confirm the exported wavelength is consistent with the energy gap.
        if not math.isclose(1239.8419843320026/wavelength, ek-ei, rel_tol=.002):
            continue
        rows.append(dict(lower_configuration=_config(row['confi']), lower_term=ti, lower_j=str(ji),
                         upper_configuration=_config(row['confk']), upper_term=tk, upper_j=str(jk),
                         lower_energy_ev=ei, upper_energy_ev=ek, wavelength_nm=wavelength, aki=aki,
                         line_strength_a0_sq=aki*gk*(wavelength*10)**3/2.02613e18,
                         reference=row.get('tpref', ''), raw=row))
    if diagnostics is not None:
        diagnostics.update(status='ok', exported_lines=len(raw), e1_lines=len(rows))
    return rows


def valence_configuration(configuration):
    """仅接受明确闭壳层芯+单价电子；返回 (core,n,l)，不删母项猜组态。"""
    config = _config(configuration)
    pieces = config.split('.')
    parsed = []
    for piece in pieces:
        match = re.fullmatch(r'(\d+)([spdfghiklmnoqrtuvwxyz])(\d*)', piece)
        if not match:
            raise ValueError('Complex or ambiguous configuration: '+config)
        n, l, occupation = int(match[1]), ORBITALS.index(match[2]), int(match[3] or '1')
        if n <= l or occupation <= 0 or occupation > 2*(2*l+1):
            raise ValueError('Invalid subshell configuration: '+config)
        parsed.append((n, l, occupation))
    if not parsed or parsed[-1][2] != 1:
        raise ValueError('Configuration does not identify a single valence electron: '+config)
    if any(occupation != 2*(2*l+1) for _, l, occupation in parsed[:-1]):
        raise ValueError('Open-shell core requires sourced manual array data: '+config)
    return '.'.join(pieces[:-1]), parsed[-1][0], parsed[-1][1]


def _groups(levels):
    grouped = defaultdict(dict)
    for level in levels:
        key = (level['configuration'], level['term'])
        j = Fraction(level['j'])
        if j in grouped[key] and grouped[key][j]['energy_ev'] != level['energy_ev']:
            raise ValueError('Conflicting NIST level energies for '+str(key))
        grouped[key][j] = level
    out = {}
    for (config, term), components in grouped.items():
        try:
            core, n, l = valence_configuration(config)
        except ValueError:
            continue
        if term.rstrip('*') != '2'+'SPDFGHIKLMNOQRTUVWXYZ'[l]:
            continue
        expected = {Fraction(1, 2)} if l == 0 else {Fraction(2*l-1, 2), Fraction(2*l+1, 2)}
        if set(components) != expected:
            continue
        weight = sum(float(2*j+1) for j in expected)
        centroid = sum(float(2*j+1)*r['energy_ev'] for j, r in components.items())/weight
        out[(config, term)] = dict(configuration=config, term=term, core=core, n=n, l=l,
                                   components=components, energy_ev=centroid, weight=weight)
    return out


def _state_label(label):
    bits = label.split()
    if bits and re.fullmatch(r'\d+(?:/\d+|\.\d+)?', bits[-1]):
        j = _j(bits.pop())
    else:
        j = None
    if len(bits) < 2:
        raise ValueError('STARK-B label lacks a resolvable configuration/LS term: '+label)
    term = _ls_term(bits.pop())
    return (_config(''.join(bits)), term), j


def _closed_core_label_match(left, right):
    """Match only omitted leading filled subshells, retaining an explicit core.

    ASD can write 2p6.3s where STARK-B writes 2s2.2p6.3s. Both must
    identify the same valence orbital and share their entire outer core.
    This never strips an open shell, a parent term, or the valence orbital.
    """
    try:
        ca, na, la = valence_configuration(left)
        cb, nb, lb = valence_configuration(right)
    except ValueError:
        return False
    if (na, la) != (nb, lb) or not ca or not cb:
        return False
    cores = []
    for core in (ca, cb):
        shells = []
        for shell in core.split('.'):
            match = re.fullmatch(r'([0-9]+)([a-z])([0-9]+)', shell)
            shells.append((int(match[1]), ORBITALS.index(match[2]), int(match[3])))
        if any(a[:2] >= b[:2] for a, b in zip(shells, shells[1:])):
            return False
        cores.append(shells)
    shorter, longer = sorted(cores, key=len)
    return longer[-len(shorter):] == shorter


def _matrix_element(source, destination, lines):
    strengths = {}
    for line in lines:
        a = (line['lower_configuration'], line['lower_term'])
        b = (line['upper_configuration'], line['upper_term'])
        src = (source['configuration'], source['term'])
        dst = (destination['configuration'], destination['term'])
        if a == src and b == dst:
            js, jd = Fraction(line['lower_j']), Fraction(line['upper_j'])
            es, ed = line['lower_energy_ev'], line['upper_energy_ev']
        elif b == src and a == dst:
            js, jd = Fraction(line['upper_j']), Fraction(line['lower_j'])
            es, ed = line['upper_energy_ev'], line['lower_energy_ev']
        else:
            continue
        if js not in source['components'] or jd not in destination['components']:
            continue
        if (not math.isclose(es, source['components'][js]['energy_ev'], abs_tol=1e-5, rel_tol=1e-7) or
                not math.isclose(ed, destination['components'][jd]['energy_ev'], abs_tol=1e-5, rel_tol=1e-7)):
            continue
        pair, strength = (js, jd), line['line_strength_a0_sq']
        if pair in strengths and not math.isclose(strengths[pair], strength, rel_tol=1e-8):
            raise ValueError('Ambiguous Aki values for the same NIST fine-structure pair')
        strengths[pair] = strength
    expected = {(js, jd) for js in source['components'] for jd in destination['components']
                if abs(js-jd) <= 1 and js+jd != 0}
    if not expected <= set(strengths):
        raise ValueError('Incomplete E1 Aki components for '+source['configuration']+' -> '+destination['configuration'])
    return math.fsum(strengths[pair] for pair in expected)/source['weight']


def build_model_input(table, levels, lines, ionization_energy_ev, *, atomic_source):
    """严格由同物种数据构建；缺一条必需扰动阵列即失败，供上层记清单。"""
    if table['charge'] not in (2, 3):
        raise ValueError('The 1980 implementation only supports ion_charge=2 or 3')
    if not levels:
        raise ValueError('No NIST levels to establish a ground-core threshold')
    ground = min(levels, key=lambda r: r['energy_ev'])
    if ground['energy_ev'] > 1e-6:
        raise ValueError('Ground level is missing; cannot assign the ground-core ionization limit')
    ground_core, _, _ = valence_configuration(ground['configuration'])
    groups = _groups(levels)
    result = dict(key=table_key(table), status='ready', atomic_quality='nist-aki-complete',
                  atomic_source=atomic_source, ionization_energy_ev=ionization_energy_ev,
                  approximation='closed-core one-valence-electron LS term centroids; E1 strengths from Aki')
    for name in ('lower', 'upper'):
        key, j = _state_label(table[name+'_label'])
        if key not in groups:
            matches = [candidate for candidate in groups if candidate[1] == key[1] and
                       _closed_core_label_match(key[0], candidate[0])]
            if len(matches) == 1:
                key = matches[0]
        if key not in groups or (j is not None and j not in groups[key]['components']):
            raise ValueError('No complete unambiguous LS term matching '+table[name+'_label'])
        target = groups[key]
        if target['core'] != ground_core:
            raise ValueError('Excited-core series requires a sourced core-specific ionization threshold')
        nstar = effective_principal_quantum_number(ionization_energy_ev-target['energy_ev'], table['charge'])
        perturbations = []
        for lp in (target['l']-1, target['l']+1):
            if lp < 0 or lp >= target['n']:
                continue  # The hydrogenic subshell cannot exist for this nominal n.
            # A filled core subshell cannot receive another valence electron.
            core_orbitals = {re.sub(r'^(\d+[a-z])\d+$', r'\1', shell)
                             for shell in target['core'].split('.') if shell}
            if str(target['n'])+ORBITALS[lp] in core_orbitals:
                continue
            candidates = [r for r in groups.values() if r['core'] == target['core'] and
                          r['n'] == target['n'] and r['l'] == lp and
                          (r['term'].endswith('*') != target['term'].endswith('*'))]
            if len(candidates) != 1:
                raise ValueError('Missing or ambiguous same-n l='+str(lp)+' perturbing LS array')
            dest = candidates[0]
            gap = abs(dest['energy_ev']-target['energy_ev'])
            if gap <= 0:
                raise ValueError('Degenerate same-n term cannot use finite-gap impact formula')
            r2 = _matrix_element(target, dest, lines)
            perturbations.append(dict(delta_e_ev=gap, matrix_element_sq_a0=r2,
                                      label=dest['configuration']+' '+dest['term']))
        if not perturbations:
            raise ValueError('No resolvable same-n perturbing array')
        result[name] = dict(n_eff=nstar, l=target['l'], same_n=perturbations)
    return result


def _roman(number):
    result = ''
    for value, token in ((100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'),
                         (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while number >= value:
            result += token
            number -= value
    return result


def _get_snapshot(path, url, params, *, refresh, delay):
    if path.exists() and not refresh:
        doc = json.loads(path.read_text(encoding='utf-8'))
        if (doc.get('request_params') != params or doc.get('endpoint') != url or
                hashlib.sha256(doc['text'].encode('utf-8')).hexdigest() != doc.get('sha256')):
            raise ValueError('Raw NIST cache integrity mismatch: '+str(path))
        # HTTP-200 ASD error/challenge pages were deliberately saved for
        # diagnostics. They must not poison every subsequent non-refresh run.
        if '<html' not in doc['text'].lower() and '<!doctype' not in doc['text'].lower():
            return doc
    response = None
    for attempt in range(3):
        try:
            if delay:
                time.sleep(delay)
            response = requests.get(url, params=params, timeout=(15, 90))
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    text = response.content.decode('utf-8-sig')
    if response.status_code != 200 or not text.strip():
        raise ValueError('Empty or unexpected NIST response')
    doc = dict(text=text, url=response.url, endpoint=url, request_params=params,
               sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
               retrieved_utc=datetime.now(timezone.utc).isoformat())
    # Preserve original responses even when their schema cannot yet be parsed.
    # Such errors become failed species in manifest, never valid model inputs.
    _atomic_json(path, doc)
    return doc


def _parse_ie(text, element, charge):
    headers, rows = _tsv(text)
    energy = next((h for h in headers if 'ionizationenergy' in h and 'ev' in h), None)
    charge_key = next((h for h in headers if h in ('ioncharge', 'charge')), None)
    species_key = next((h for h in ('sp.name', 'spname') if h in headers), None)
    if not energy or not charge_key or not species_key:
        raise ValueError('NIST IE export lacks species, ion charge or ionization energy (eV)')
    spectrum = element+' '+_roman(charge+1)
    values = set()
    for row in rows:
        if ' '.join(row.get(species_key, '').split()) != spectrum:
            continue
        try:
            energy_text = row.get('prefix', '')+row.get(energy, '')+row.get('suffix', '')
            q, e = _number(row.get(charge_key, '')), _number(energy_text)
        except ValueError:
            continue
        if q == charge and e > 0:
            values.add(e)
    if len(values) != 1:
        raise ValueError('No unique ground-core NIST ionization threshold for '+element)
    return values.pop()


def fetch_atomic_input(element, charge, *, cache, progress=None, cancelled=None):
    """Fetch complete same-species ASD inputs through the task's bounded transport.

    Only validated raw responses enter SourceCache. No checkout/sample discovery
    or writes to installed resources are used by the simulation path.
    """
    from .stark_b import StarkBClient, StarkDataAccessError
    if not re.fullmatch('[A-Z][a-z]?', element) or charge not in (2, 3):
        raise ValueError('DK1980 atomic inputs require an identified q=2/3 species')
    spectrum = element+' '+_roman(charge+1)

    def get(kind, endpoint, params, parser, label):
        if cancelled and cancelled():
            raise InterruptedError('NIST atomic retrieval cancelled')
        if progress:
            progress('NIST：'+spectrum+'，获取'+label)

        def fetch():
            with requests.Session() as session:
                text = StarkBClient._request(session, 'GET', endpoint, params=params)
            parser(text)
            return dict(text=text, url=requests.Request('GET', endpoint, params=params).prepare().url,
                        endpoint=endpoint, request_params=params)
        try:
            snapshot = cache.get('nist-atomic-v1:'+element+':'+str(charge)+':'+kind, fetch)
            payload = snapshot['payload']
            if payload.get('endpoint') != endpoint or payload.get('request_params') != params:
                raise ValueError('atomic snapshot request identity mismatch')
            result = parser(payload['text'])
        except (ValueError, KeyError, TypeError) as exc:
            raise StarkDataAccessError('Invalid NIST '+kind+' response for '+spectrum+': '+str(exc)) from exc
        return result, dict(url=payload['url'], sha256=hashlib.sha256(payload['text'].encode('utf-8')).hexdigest(),
                            snapshot_sha256=snapshot['sha256'])

    level_params = dict(spectrum=spectrum, units=0, format=3, output=0, page_size=1000,
                        conf_out='on', term_out='on', j_out='on', level_out='on',
                        unc_out='on', biblio='on', multiplet_ordered=0, submit='Retrieve Data')
    (levels, limits), level_source = get('levels', ASD_LEVELS, level_params, parse_nist_levels, '能级数据')
    line_params = dict(spectra=spectrum, output_type=0, low_w='', upp_w='', unit=1, de=0,
                       plot_out=0, format=3, line_out=0, remove_js='on', no_spaces='on',
                       en_unit=0, output=0, bibrefs=1, page_size=100, show_obs_wl=1,
                       show_calc_wl=1, unc_out=1, order_out=0, ids_out=1, show_av=3,
                       A_out=0, allowed_out=1, conf_out='on', term_out='on', enrg_out='on',
                       J_out='on', g_out='on')
    line_data = {}
    lines, line_source = get('lines', ASD_LINES, line_params,
                            lambda text: parse_nist_lines(text, diagnostics=line_data), '完整E1跃迁Aki／统计权重')
    ie_params = dict(spectra=spectrum, units=1, format=3, order=0,
                     ion_charge_out='on', sp_name_out='on', e_out=0, biblio='on')
    ionization, ie_source = get('ionization', ASD_IE, ie_params,
                               lambda text: _parse_ie(text, element, charge), '电离阈值')
    return dict(levels=levels, lines=lines, limits=limits, line_data=line_data,
                ionization_energy_ev=ionization,
                atomic_source={prefix+'_'+key: value for prefix, source in
                               [('levels', level_source), ('lines', line_source), ('ionization', ie_source)]
                               for key, value in source.items()})


def prepare_atomic_samples(tables, sample_dir, *, refresh=False, delay=1.0):
    """原子采集阶段；失败物种/谱线保留原因，可续用原始快照并补手工输入。"""
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('delay must be finite and nonnegative')
    directory = Path(sample_dir)
    grouped = defaultdict(list)
    unique = {table_key(t): t for t in tables}
    models, species = [], []
    def save_state(complete=False):
        _atomic_json(directory/'models.json', dict(schema_version=1, models=models))
        manifest = dict(schema_version=1, species=species, candidate_tables=len(unique),
                        input_keys=sorted(unique), processed_tables=len(models),
                        ready=sum(m['status'] == 'ready' for m in models),
                        missing=sum(m['status'] != 'ready' for m in models),
                        complete=complete, retrieved_utc=datetime.now(timezone.utc).isoformat())
        _atomic_json(directory/'manifest.json', manifest)
        return manifest

    # Invalidate a previous completed run before any network operations.
    save_state()
    for table in unique.values():
        if table['charge'] in (2, 3):
            grouped[(table['element'], table['charge'])].append(table)
        else:
            models.append(dict(key=table_key(table), status='missing', reason='unsupported ion charge',
                               element=table['element'], charge=table['charge']))
    for (element, charge), candidates in sorted(grouped.items()):
        spectrum = element+' '+_roman(charge+1)
        stem = element+'_'+str(charge)
        status = dict(element=element, charge=charge, status='failed')
        try:
            common = dict(spectrum=spectrum, units=0, format=3, output=0, page_size=1000,
                          conf_out='on', term_out='on', j_out='on', level_out='on',
                          unc_out='on', biblio='on', multiplet_ordered=0, submit='Retrieve Data')
            energy_doc = _get_snapshot(directory/'raw'/(stem+'_levels.json'), ASD_LEVELS, common,
                                       refresh=refresh, delay=delay)
            levels, limits = parse_nist_levels(energy_doc['text'])
            if not levels:
                raise ValueError('No usable resolved LS levels in NIST response')
            params = dict(spectra=spectrum, output_type=0, low_w='', upp_w='', unit=1, de=0,
                          plot_out=0, format=3, line_out=0, remove_js='on', no_spaces='on',
                          en_unit=0, output=0, bibrefs=1, page_size=100, show_obs_wl=1,
                          show_calc_wl=1, unc_out=1, order_out=0, ids_out=1, show_av=3,
                          A_out=0, allowed_out=1, conf_out='on', term_out='on', enrg_out='on',
                          J_out='on', g_out='on')
            line_doc = _get_snapshot(directory/'raw'/(stem+'_lines.json'), ASD_LINES, params,
                                     refresh=refresh, delay=delay)
            line_data = {}
            lines = parse_nist_lines(line_doc['text'], diagnostics=line_data)
            # Always obtain the explicit ground-ionization threshold; additional
            # excited-core limits in a level table cannot silently replace it.
            ie_params = dict(spectra=spectrum, units=1, format=3, order=0,
                             ion_charge_out='on', sp_name_out='on', e_out=0, biblio='on')
            ie_doc = _get_snapshot(directory/'raw'/(stem+'_ionization.json'), ASD_IE, ie_params,
                                   refresh=refresh, delay=delay)
            ionization = _parse_ie(ie_doc['text'], element, charge)
            atomic_source = dict(levels_url=energy_doc['url'], lines_url=line_doc['url'],
                                 ionization_url=ie_doc['url'], levels_sha256=energy_doc['sha256'],
                                 lines_sha256=line_doc['sha256'], ionization_sha256=ie_doc['sha256'])
            _atomic_json(directory/(stem+'_atomic.json'), dict(levels=levels, lines=lines, limits=limits,
                         ionization_energy_ev=ionization, atomic_source=atomic_source, line_data=line_data))
            for table in candidates:
                if line_data['status'] == 'missing':
                    model = dict(key=table_key(table), status='missing', reason=line_data['reason'],
                                 missing_kind='nist_line_data_unavailable', atomic_source=atomic_source)
                else:
                    try:
                        model = build_model_input(table, levels, lines, ionization, atomic_source=atomic_source)
                    except ValueError as exc:
                        model = dict(key=table_key(table), status='missing', reason=str(exc))
                model.update(element=element, charge=charge)
                models.append(model)
            status.update(status='ok', levels=len(levels), e1_lines=len(lines), line_data=line_data)
        except (requests.RequestException, ValueError, OSError, KeyError) as exc:
            status['reason'] = str(exc)
            models.extend(dict(key=table_key(t), status='missing', reason='atomic source failure: '+str(exc),
                               element=element, charge=charge) for t in candidates)
        species.append(status)
        save_state()
    return save_state(complete=len(models) == len(unique) and all(s['status'] == 'ok' for s in species))


def _validate_model(model):
    if not isinstance(model.get('key'), str) or not model['key']:
        raise ValueError('Model lacks STARK-B table key')
    if not model.get('atomic_source'):
        raise ValueError('Ready/manual model must include atomic_source provenance')
    for name in ('lower', 'upper'):
        raw = dict(model[name])
        raw['same_n'] = tuple(Perturber(**p) for p in raw['same_n'])
        Level(**raw)


def load_model_inputs(sample_dir):
    directory = Path(sample_dir)
    doc = json.loads((directory/'models.json').read_text(encoding='utf-8'))
    if doc.get('schema_version') != 1 or not isinstance(doc.get('models'), list):
        raise ValueError('Unknown atomic models schema')
    models = {}
    for model in doc['models']:
        key = model['key']
        if key in models:
            raise ValueError('Duplicate atomic model key')
        if model['status'] == 'ready':
            _validate_model(model)
        models[key] = model
    manual_path = directory/'manual_inputs.json'
    if manual_path.exists():
        manual = json.loads(manual_path.read_text(encoding='utf-8-sig'))
        seen = set()
        for item in manual['models']:
            _validate_model(item)
            if item['key'] not in models or item['key'] in seen:
                raise ValueError('Manual model key is absent from candidates or duplicated')
            seen.add(item['key'])
            models[item['key']] = dict(item, status='ready', atomic_quality='manual')
    return models
