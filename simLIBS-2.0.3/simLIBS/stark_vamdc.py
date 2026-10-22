"""Official STARK-B XSAMS fallback; preserve raw pages and reject partial data.

The node maps its tabulated FWHM w directly to gammaL (not HWHM). Neither C
nor calculation method nor published temperature fits is exported. Only the
caller may interpolate these real tables within their temperature bounds.
"""
from fractions import Fraction
import math
import re
import xml.etree.ElementTree as ET

import requests


TAP_URL = 'https://stark-b.obspm.fr/12.07/vamdc/tap/sync'
_NS = {'x': 'http://vamdc.org/xml/xsams/1.0'}
_MAX_DEPTH = 24
_MAX_REQUESTS = 256
_MAX_BYTES = 20 * 1024 * 1024
_NOTE = ('STARK-B tabulated FWHM, not HWHM; linear temperature interpolation '
         'only inside the table. C, published fits and calculation method are '
         'not exported; absence of a warning does not establish validity.')


def _conditions(element, charge, ne):
    if (not isinstance(element, str) or not re.fullmatch(r'[A-Z][a-z]?', element)
            or type(charge) is not int or charge < 0):
        raise ValueError('Invalid STARK-B species')
    try:
        ne = float(ne)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Invalid STARK-B density') from exc
    if not math.isfinite(ne) or ne <= 0:
        raise ValueError('STARK-B density must be finite and positive')
    return ne


def _xml(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > _MAX_BYTES:
        raise ValueError('Invalid or oversized XSAMS response')
    if re.search(r'<!\s*(DOCTYPE|ENTITY)\b', text, re.I):
        raise ValueError('DTD/entities are not permitted in XSAMS')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('Invalid XSAMS XML') from exc
    if root.tag != '{%s}XSAMSData' % _NS['x']:
        raise ValueError('Response is not XSAMS 1.0')
    return root


def _one(parent, path, name):
    found = parent.findall(path, _NS)
    if len(found) != 1:
        raise ValueError('Missing or ambiguous XSAMS ' + name)
    return found[0]


def _text(parent, path, name):
    text = _one(parent, path, name).text
    if text is None or not text.strip():
        raise ValueError('Missing XSAMS ' + name)
    return text.strip()


def _value(parent, path, unit):
    node = _one(parent, path, 'value')
    if node.get('units') != unit:
        raise ValueError('Unexpected XSAMS unit: ' + str(node.get('units')))
    try:
        value = float(node.text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Invalid XSAMS number') from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError('XSAMS value must be finite and positive')
    return value


def _index(nodes, attribute):
    out = {}
    for node in nodes:
        key = node.get(attribute)
        if not key or key in out:
            raise ValueError('Missing or ambiguous duplicate XSAMS ' + attribute)
        out[key] = node
    return out


def _lookup(index, key, name):
    if key not in index:
        raise ValueError('Dangling XSAMS ' + name + ': ' + str(key))
    return index[key]


def _label(state):
    component = _one(state, 'x:AtomicComposition/x:Component', 'state component')
    config = _text(component, 'x:Configuration/x:ConfigurationLabel', 'configuration')
    term = _text(component, 'x:Term/x:TermLabel', 'term')
    js = state.findall('x:AtomicQuantumNumbers/x:TotalAngularMomentum', _NS)
    if len(js) > 1:
        raise ValueError('Ambiguous XSAMS state J')
    if not js:
        return config + ' ' + term
    try:
        j = Fraction(js[0].text)
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ValueError('Invalid XSAMS state J') from exc
    if j < 0 or (2 * j).denominator != 1:
        raise ValueError('Invalid XSAMS state J')
    return '{} {} {}'.format(config, term, j)


def _comments(*nodes):
    return '; '.join(c.text.strip() for node in nodes
                     for c in node.findall('.//x:Comments', _NS)
                     if c.text and c.text.strip())


def _page_rows(page, element, charge, ne):
    root = _xml(page['xml'])
    if not isinstance(page.get('url'), str) or not page['url']:
        raise ValueError('Missing XSAMS source URL')
    header = page.get('headers', {}).get('VAMDC-TRUNCATED', 'None')
    if str(header).strip().lower() != 'none':
        raise ValueError('Cannot parse a truncated XSAMS page')
    envs = _index(root.findall('x:Environments/x:Environment', _NS), 'envID')
    sources = _index(root.findall('x:Sources/x:Source', _NS), 'sourceID')
    particles = _index(root.findall('x:Species/x:Particles/x:Particle', _NS), 'speciesID')
    ions, targets, states, owners = {}, set(), {}, {}
    for atom in root.findall('x:Species/x:Atoms/x:Atom', _NS):
        symbol = _text(atom, 'x:ChemicalElement/x:ElementSymbol', 'element')
        for ion in atom.findall('x:Isotope/x:Ion', _NS):
            identifier = ion.get('speciesID')
            if not identifier or identifier in ions or identifier in particles:
                raise ValueError('Ambiguous duplicate XSAMS species')
            ions[identifier] = ion
            ion_charge = _text(ion, 'x:IonCharge', 'ion charge')
            try:
                ion_charge = int(ion_charge)
            except ValueError as exc:
                raise ValueError('Invalid XSAMS ion charge') from exc
            if symbol == element and ion_charge == charge:
                targets.add(identifier)
            for state in ion.findall('x:AtomicState', _NS):
                state_id = state.get('stateID')
                if not state_id or state_id in states:
                    raise ValueError('Ambiguous duplicate XSAMS state')
                states[state_id], owners[state_id] = state, identifier
    rows = []
    transitions = _index(root.findall('x:Processes/x:Radiative/x:RadiativeTransition', _NS), 'id')
    for identifier, transition in transitions.items():
        target = _text(transition, 'x:SpeciesRef', 'transition species')
        _lookup(ions, target, 'transition species')
        if target not in targets:
            continue
        labels, state_ids = [], []
        for path in ('x:LowerStateRef', 'x:UpperStateRef'):
            state_id = _text(transition, path, 'state reference')
            state = _lookup(states, state_id, 'state')
            if owners[state_id] != target:
                raise ValueError('XSAMS state belongs to a different species')
            labels.append(_label(state))
            state_ids.append(state_id)
        wavelength = _value(transition, 'x:EnergyWavelength/x:Wavelength/x:Value', 'A')
        refs = [r.text.strip() for r in transition.findall('x:SourceRef', _NS) if r.text]
        if not refs or len(set(refs)) != len(refs):
            raise ValueError('Missing or ambiguous duplicate XSAMS sources')
        citations = []
        for ref in refs:
            source = _lookup(sources, ref, 'source')
            if source.findtext('x:Category', namespaces=_NS) == 'database':
                raise ValueError('XSAMS original publication is missing')
            _text(source, 'x:Title', 'publication title')
            citations.append(' '.join(t.strip() for t in source.itertext() if t.strip()))
        samples = []
        for broadening in transition.findall('x:Broadening', _NS):
            env_id = broadening.get('envRef')
            env = _lookup(envs, env_id, 'environment')
            composition = env.findall('x:Composition/x:Species', _NS)
            electrons = []
            for species in composition:
                collider = species.get('speciesRef')
                # STARK-B 的 Fe II 数据把平均离子写为无 speciesRef 的
                # meanion；它不是电子碰撞系数，不应阻断同页电子数据。
                # 若与电子混在同一环境中，仍由下方的混合环境校验拒绝。
                if collider is None and species.get('name', '').strip().lower() == 'meanion':
                    continue
                if collider not in particles and collider not in ions:
                    raise ValueError('Dangling XSAMS collider reference')
                if collider in particles and particles[collider].get('name', '').lower() == 'electron':
                    electrons.append(collider)
                elif species.get('name', '').lower() == 'electron':
                    raise ValueError('XSAMS electron reference identifies another collider')
            if not electrons:
                continue
            if len(composition) != 1 or len(electrons) != 1:
                raise ValueError('Ambiguous mixed XSAMS collision environment')
            if broadening.get('name') != 'pressure':
                raise ValueError('Unexpected XSAMS broadening type')
            lineshape = _one(broadening, 'x:Lineshape', 'lineshape')
            parameter = _one(lineshape, 'x:LineshapeParameter', 'width parameter')
            if lineshape.get('name') != 'Lorentzian' or parameter.get('name') != 'gammaL':
                raise ValueError('Unknown STARK-B width convention')
            samples.append(dict(ne=_value(env, 'x:TotalNumberDensity/x:Value', '1/cm3'),
                                temperature_k=_value(env, 'x:Temperature/x:Value', 'K'),
                                fwhm_angstrom=_value(parameter, 'x:Value', 'A'),
                                flag=_comments(env, broadening),
                                environment_id=env_id, collider_ref=electrons[0]))
        covering = [sample['ne'] for sample in samples if sample['ne'] >= ne]
        if not covering:
            continue
        # 保留各可用参考密度；目标温度及有效性检查通过后再选最低密度。
        for reference_ne in sorted(set(covering)):
            selected = sorted((s for s in samples if s['ne'] == reference_ne), key=lambda s: s['temperature_k'])
            temperatures = [s['temperature_k'] for s in selected]
            if len(temperatures) != len(set(temperatures)):
                raise ValueError('Ambiguous duplicate electron samples at the same density/temperature')
            rows.append(dict(element=element, charge=charge, dataset_id='vamdc:' + identifier,
                             transition_id=identifier, method='unreported',
                             lower_label=labels[0], upper_label=labels[1],
                             lower_state_id=state_ids[0], upper_state_id=state_ids[1],
                             calculated_wavelength_angstrom=wavelength,
                             c_angstrom_cm3=None, fit=None, samples=selected,
                             source=' | '.join(citations), source_ids=refs, source_url=page['url'],
                             source_format='vamdc-xsams', temperature_interpolation='linear',
                             metadata={'limitations': _NOTE, 'reference_ne_cm3': reference_ne}))
    return rows


def parse_payload(payload, *, element, charge, ne):
    """Return parse_table-compatible rows without guessing sources or densities."""
    ne = _conditions(element, charge, ne)
    if not isinstance(payload, dict) or payload.get('format') != 'vamdc-xsams':
        raise ValueError('Invalid STARK-B VAMDC payload')
    if not isinstance(payload.get('pages'), list):
        raise ValueError('Missing XSAMS pages')
    rows, seen = [], set()
    for page in payload['pages']:
        if not isinstance(page, dict) or 'xml' not in page:
            raise ValueError('Invalid XSAMS page')
        # Check all transition IDs, including rows excluded by requested density.
        root = _xml(page['xml'])
        ids = _index(root.findall('x:Processes/x:Radiative/x:RadiativeTransition', _NS), 'id')
        if seen.intersection(ids):
            raise ValueError('Ambiguous duplicate XSAMS transition across pages')
        seen.update(ids)
        rows.extend(_page_rows(page, element, charge, ne))
    return rows


def fetch_species(element, charge, ne):
    """Fetch complete wavelength partitions; no partial response reaches cache.

    Start with an unbounded species query. On truncation split the entire
    domain into (low, midpoint] and (midpoint, high], including the unbounded
    tail. Co-located transitions that still exceed the node limit are errors.
    """
    ne = _conditions(element, charge, ne)
    # 仅允许参考密度向下缩放；低于目标 Ne 的原表不能使用，无需下载。
    query = ("SELECT ALL WHERE AtomSymbol = '{}' AND IonCharge = {}"
             " AND EnvironmentTotalNumberDensity >= {!r}").format(element, charge, ne)
    requests_made = [0]

    def fetch(low=None, high=None, depth=0):
        requests_made[0] += 1
        if requests_made[0] > _MAX_REQUESTS:
            raise ValueError('XSAMS truncation cannot be completed within request limit')
        bounded = query
        if low is not None:
            bounded += ' AND RadTransWavelength > ' + repr(low)
        if high is not None:
            bounded += ' AND RadTransWavelength <= ' + repr(high)
        params = dict(REQUEST='doQuery', LANG='VSS2', FORMAT='XSAMS', QUERY=bounded)
        response = requests.get(TAP_URL, params=params, timeout=(10, 60), allow_redirects=False)
        response.raise_for_status()
        if response.status_code == 204:
            return []
        if response.status_code != 200:
            raise ValueError('Unexpected STARK-B HTTP status: ' + str(response.status_code))
        try:
            text = response.content.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('Invalid XSAMS UTF-8') from exc
        root = _xml(text)
        truncated = response.headers.get('VAMDC-TRUNCATED')
        if truncated is None:
            raise ValueError('Missing VAMDC-TRUNCATED completeness header')
        waves = [_value(tr, 'x:EnergyWavelength/x:Wavelength/x:Value', 'A')
                 for tr in root.findall('x:Processes/x:Radiative/x:RadiativeTransition', _NS)]
        if any((low is not None and w <= low) or (high is not None and w > high) for w in waves):
            raise ValueError('XSAMS response lies outside requested wavelength window')
        if str(truncated).strip().lower() != 'none':
            if depth >= _MAX_DEPTH or not waves:
                raise ValueError('XSAMS truncation cannot be completed by wavelength splitting')
            if high is None:
                midpoint = max(waves)
            else:
                midpoint = ((low if low is not None else 0.) + high) / 2.
            if not math.isfinite(midpoint) or (low is not None and midpoint <= low) or (high is not None and midpoint >= high):
                raise ValueError('XSAMS truncated wavelength window cannot be split further')
            return fetch(low, midpoint, depth + 1) + fetch(midpoint, high, depth + 1)
        return [dict(xml=text, url=requests.Request('GET', TAP_URL, params=params).prepare().url,
                     headers=dict(response.headers))]

    pages = fetch()
    payload = dict(format='vamdc-xsams', element=element, charge=charge,
                   requested_ne_cm3=ne, datasets=[], pages=pages,
                   status='ok' if pages else 'no data', metadata={'limitations': _NOTE})
    # Validate the entire retained source, including values below requested Ne,
    # before SourceCache can store anything. No selection hides a malformed row.
    available = parse_payload(payload, element=element, charge=charge, ne=1e-300)
    if not available:
        payload['status'] = 'no data'
    elif not parse_payload(payload, element=element, charge=charge, ne=ne):
        payload['status'] = 'density above available tables'
    return payload
