from pathlib import Path
import csv, io, re, json, hashlib, datetime, collections, math
from fractions import Fraction
from bs4 import BeautifulSoup

root = Path('D:/LIBS/SimLIBS')
downloads = root / 'tmp/pdfs/d3ra06226k-review/atomic-downloads'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value):
    return value[2:-1] if value.startswith('="') and value.endswith('"') else value


def read_csv(path):
    return [{k: clean(v) for k, v in row.items() if k is not None}
            for row in csv.DictReader(io.StringIO(path.read_text(encoding='utf8')))]


def metadata(stem, rawfile):
    result = json.loads((downloads / stem).read_text())
    path = downloads / rawfile
    assert result['response_sha256'] == digest(path)
    result['response_bytes'] = path.stat().st_size
    result['local_response_path'] = path.relative_to(root).as_posix()
    return result


raw_table = '''Zn 0 213.857 0.003 7.14e8 3 0 5.795 1 3
Zn 0 334.501 0.048 1.70e8 10 4.077 7.783 5 7
Zn 1 206.200 0.004 3.86e8 7 0 6.010 2 2
Zn 1 209.992 0.006 5.60e8 25 6.119 12.02 4 6
Ca 0 239.856 0.114 1.67e7 18 0 5.167 1 3
Ca 0 318.052 1.670 2.90e6 50 1.898 5.796 5 3
Ca 0 322.590 3.860 1.60e7 50 1.898 5.741 5 7
Ca 0 397.371 0.190 1.75e7 25 1.898 5.018 5 3
Ca 0 422.673 0.012 2.18e8 7 0 2.932 1 3
Ca 0 443.496 0.126 6.70e7 25 1.885 4.680 3 5
Ca 0 445.478 0.126 8.70e7 25 1.898 4.681 5 7
Ca 0 518.885 0.581 4.00e7 50 2.932 5.321 3 5
Ca 0 585.745 0.790 6.60e7 50 2.932 5.048 3 5
Ca 1 211.276 0.048 9.70e7 25 3.150 9.017 4 6
Ca 1 213.230 0.024 2.00e6 50 1.692 7.505 4 2
Ca 1 317.933 0.045 3.60e8 25 3.150 7.049 4 6
Ca 1 393.366 0.022 1.47e8 25 0 3.150 2 4
Ca 1 396.846 0.023 1.44e8 25 0 3.123 2 2
Mg 0 273.654 2.610 1.25e7 25 2.716 7.245 5 7
Mg 0 285.166 1.270 2.35e7 25 2.716 7.063 5 7
Mg 0 285.212 0.007 4.91e8 3 0 4.345 1 3
Mg 0 294.199 0.237 6.83e6 30 2.716 6.929 5 3
Mg 0 309.689 0.450 4.96e7 18 2.716 6.718 5 7
Mg 0 333.667 0.104 1.70e7 10 2.716 6.431 5 3
Mg 0 383.829 0.151 1.61e8 7 2.716 5.945 5 7
Mg 0 405.750 4.950 1.02e7 18 4.345 7.400 3 5
Mg 1 244.959 1.420 2.02e7 7 8.863 13.92 4 6
Mg 1 266.075 0.881 3.81e7 7 8.863 13.52 6 8
Mg 1 279.077 0.136 4.01e8 3 4.422 8.863 2 4
Mg 1 279.552 0.019 2.60e8 2 0 4.433 2 4
Mg 1 292.863 0.148 1.15e8 3 4.422 8.654 2 2'''

lines = []
for i, line in enumerate(raw_table.splitlines(), 1):
    e, q, wl, w, a, acc, lo, up, gl, gu = line.split()
    lines.append({'element': e, 'charge': int(q), 'wavelength_nm': float(wl),
                  'stark_width_nm': float(w), 'stark_reference_ne_cm3': 1e16,
                  'Aki_s': float(a), 'lower_eV': float(lo), 'upper_eV': float(up),
                  'g_lower': int(gl), 'g_upper': int(gu),
                  'Aki_accuracy_error_percent': float(acc), 'table_row': i,
                  'stark_reference_temperature_K': None})

paper_pdf = Path('D:/LIBS/Research-Proposal/Matrix_effect/Self-aborption/d3ra06226k.pdf')
ip_path = root / 'Linedatabase/simlibs-atomic-metadata.json'
ipmeta = json.loads(ip_path.read_text())
snapshot = {
    'schema_version': 1,
    'paper': {
        'doi': '10.1039/D3RA06226K',
        'title': 'A numerical procedure for understanding the self-absorption effects in laser induced breakdown spectroscopy',
        'authors': ['Lekha Mary John', 'K. K. Anoop'],
        'journal': 'RSC Advances', 'year': 2023, 'volume': 13,
        'pages': '29613-29624', 'url': 'https://doi.org/10.1039/D3RA06226K',
        'table': 1, 'pdf_page': 5, 'journal_page': 29617,
        'local_pdf_path': str(paper_pdf), 'pdf_sha256': digest(paper_pdf)},
    'lines': lines,
    'elements': {},
    'provenance': {
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'line_data_source': 'Paper Table 1, all 31 rows; values retained exactly as printed, including rounding.',
        'table_verification': 'All 31 rows manually transcribed and visually verified against rendered PDF page 5 (page-05.png), then compared numerically with all Table 1 rows extracted by pdftotext.',
        'table_render_path': 'tmp/pdfs/d3ra06226k-review/page-05.png',
        'table_render_sha256': digest(root / 'tmp/pdfs/d3ra06226k-review/page-05.png'),
        'table_text_path': 'tmp/pdfs/d3ra06226k-review/paper.txt',
        'table_text_sha256': digest(root / 'tmp/pdfs/d3ra06226k-review/paper.txt'),
        'stark_width_definition': 'Fixed electron-impact width W in nm from Table 1. Paper Eq. (4): FWHM_nm = 2 * W_nm * (Ne_cm^-3 / 1e16).',
        'stark_reference_ne_cm3': 1e16,
        'stark_reference_temperature_K': None,
        'stark_temperature_limitation': 'Table 1 does not specify a reference temperature for W and does not tabulate its temperature dependence. The snapshot uses the fixed printed W values; no temperature scaling is invented.',
        'level_data_source': 'NIST Atomic Spectra Database, official public energy1.pl complete-output CSV; each spectrum independently checked against complete-output ASCII and the advertised Levels Found count.',
        'nist_asd_version': '5.12', 'nist_asd_doi': '10.18434/T4W30F',
        'paper_vs_snapshot_level_data_limitation': 'The paper cites NIST ASD version 5.10 (2022); this independently retrieved level snapshot is version 5.12. The paper does not publish its full partition-function level list, so the snapshot cannot establish an exact match to the authors original partition functions.',
        'nist_levels_form_url': 'https://physics.nist.gov/PhysRefData/ASD/levels_form.html',
        'level_identity_policy': 'Preserve each NIST level ID as an independent state. Never deduplicate by equal energy_eV and g.',
        'level_acceptance_policy': 'Accept only a finite nonnegative scalar energy, positive integer g, and a unique numeric J with g = 2J + 1. Exclude Limit rows and missing, compound, or qualified J. Preserve numeric energies with NIST prefix/suffix qualifiers without inventing missing degeneracies.',
        'partition_function_policy': 'The levels arrays preserve all accepted NIST states, including above-threshold states marked is_bound=false. Finite bound-state partition sums must use only is_bound=true. is_bound compares energy to the lowest NIST Limit row of that spectrum.',
        'level_completeness_limitation': 'This is a finite NIST ASD level list, not an infinite complete atomic spectrum. Missing/unresolved J states are excluded and recorded. No density-dependent continuum lowering, occupation probability, or missing high-lying state model is supplied.',
        'ionization_energy_source': 'Royal Society of Chemistry Periodic Table values copied from existing local simlibs-atomic-metadata.json; these Saha input ionization energies are not claimed to be NIST ASD values. NIST Limit energies are retained separately only for bound-state flags.',
        'supplementary_downloads': [metadata('levels_form.request.json', 'levels_form.html'), metadata('Mg_III.request.json', 'Mg_III.txt')],
        'retrieval_notes': ['Initial Mg III CSV requests with the optional de=0 parameter twice ended with TLS UNEXPECTED_EOF_WHILE_READING and no HTTP response. Ordinary public ASCII and CSV requests without that optional parameter succeeded. No access controls or CAPTCHA were bypassed.'],
        'line_data_notes': ['Mg II 280.270 nm is mentioned in the paper narrative but absent from Table 1, so it is not added to this table snapshot.', 'Table 1 lower/upper energy values have only the printed precision and can differ slightly from the current NIST level tables.']}}


for element in ['Mg', 'Ca', 'Zn']:
    atomic = ipmeta['elements'][element]
    entry = {
        'ionization_energies_eV': [atomic['ionization_energies'][str(i)]['eV'] for i in [1, 2]],
        'levels': {},
        'provenance': {
            'ionization_energies': {'publisher': ipmeta['publisher'], 'source_url': atomic['source_url'],
                                    'response_sha256': atomic['response_sha256'], 'collected_at': ipmeta['collected_at'],
                                    'conversion': ipmeta['conversion'], 'local_metadata_path': ip_path.relative_to(root).as_posix(),
                                    'local_metadata_sha256': digest(ip_path), 'not_nist': True},
            'levels': {}}}
    for charge, roman in enumerate(['I', 'II', 'III']):
        stem = element + '_' + roman
        rows = read_csv(downloads / (stem + '.csv'))
        ids = [r['Level ID'] for r in rows]
        assert len(ids) == len(set(ids))
        csvmeta = metadata(stem + ('.csv.request.json' if stem == 'Mg_III' else '.request.json'), stem + '.csv')
        ameta = metadata(stem + '.ascii.request.json', stem + '.ascii.html')
        soup = BeautifulSoup((downloads / (stem + '.ascii.html')).read_text(encoding='utf8'), 'html.parser')
        text = soup.get_text()
        pre = soup.find('pre').get_text()
        found = re.search(r'(\d+)\s+Levels Found', text)
        assert found is not None
        ascii_rows = {}
        for line in pre.splitlines():
            if re.search(r'\d{6}\.(?:\d{6}|Lim\d{3})', line):
                cells = [v.strip() for v in line.split('|')]
                ascii_rows[cells[6]] = cells
        assert len(rows) == len(ascii_rows) == int(found.group(1)) and set(ids) == set(ascii_rows)
        for row in rows:
            cells = ascii_rows[row['Level ID']]
            assert float(row['Level (eV)']) == float(re.sub(r'[\[\]?]', '', cells[4]).strip())
            assert row['g'] == cells[3] and row['J'] == cells[2]
        limit_rows = [r for r in rows if r['Term'] == 'Limit']
        limit = min(float(r['Level (eV)']) for r in limit_rows)
        valid, excluded = [], []
        reasons = collections.Counter()
        for source_row, row in enumerate(rows, 2):
            reason = None
            if row['Term'] == 'Limit':
                reason = 'ionization_limit_not_an_atomic_level'
            elif not re.fullmatch(r'\d+(?:/\d+)?', row['J']):
                reason = 'missing_or_nonunique_J'
            elif not re.fullmatch(r'\d+', row['g']):
                reason = 'missing_or_noninteger_g'
            else:
                try:
                    energy, g, j = float(row['Level (eV)']), int(row['g']), Fraction(row['J'])
                    if not math.isfinite(energy) or energy < 0:
                        reason = 'invalid_energy'
                    elif g <= 0 or 2*j + 1 != g:
                        reason = 'g_not_equal_2J_plus_1'
                except (ValueError, ZeroDivisionError):
                    reason = 'unparseable_energy_or_J'
            if reason:
                reasons[reason] += 1
                excluded.append({'source_csv_row': source_row, 'reason': reason, 'nist_level_id': row['Level ID'],
                                 'configuration': row['Configuration'], 'term': row['Term'], 'J': row['J'],
                                 'g': row['g'], 'energy_eV_text': row['Level (eV)'],
                                 'energy_prefix': row['Prefix'], 'energy_suffix': row['Suffix']})
                continue
            level = {'energy_eV': energy, 'g': g, 'nist_level_id': row['Level ID'],
                     'configuration': row['Configuration'], 'term': row['Term'], 'J': row['J'],
                     'is_bound': energy < limit, 'source_csv_row': source_row}
            if row['Prefix'] or row['Suffix']:
                level['nist_energy_prefix'], level['nist_energy_suffix'] = row['Prefix'], row['Suffix']
            if row['Uncertainty (eV)']:
                try:
                    level['uncertainty_eV'] = float(row['Uncertainty (eV)'])
                except ValueError:
                    level['uncertainty_eV_text'] = row['Uncertainty (eV)']
            valid.append(level)
        assert valid[0]['energy_eV'] == 0 and valid[0]['is_bound']
        assert len(rows) == len(valid) + len(excluded)
        entry['levels'][str(charge)] = valid
        stats = {'total_rows': len(rows), 'valid_rows': len(valid), 'excluded_rows': len(excluded),
                 'exclusion_reason_counts': dict(reasons), 'bound_level_count': sum(l['is_bound'] for l in valid),
                 'above_or_at_first_ionization_limit_level_count': sum(not l['is_bound'] for l in valid),
                 'energy_qualified_valid_rows': sum('nist_energy_prefix' in l for l in valid),
                 'distinct_nist_level_ids': len(set(l['nist_level_id'] for l in valid)),
                 'equal_energy_g_states_preserved_count': sum(n for n in collections.Counter((l['energy_eV'], l['g']) for l in valid).values() if n > 1)}
        csvmeta['statistics'] = stats
        ameta['statistics'] = {'total_rows': len(ascii_rows), 'nist_advertised_levels_found': int(found.group(1)),
                               'matched_csv_level_id_count': len(rows), 'energy_J_g_mismatches': 0,
                               'valid_rows': len(valid), 'excluded_rows': len(excluded)}
        entry['provenance']['levels'][str(charge)] = {
            'spectrum': element + ' ' + roman, 'format': 'CSV', 'units': 'eV',
            'output': 'in its entirety (output=0)', 'nist_advertised_levels_found': int(found.group(1)),
            'download': csvmeta, 'cross_check_download': ameta, 'statistics': stats,
            'first_nist_ionization_limit_eV': limit,
            'ionization_limit_rows': [{'energy_eV': float(r['Level (eV)']), 'nist_level_id': r['Level ID'],
                                      'configuration': r['Configuration']} for r in limit_rows],
            'excluded': excluded}
    snapshot['elements'][element] = entry

# Check every Table 1 cell against the separate PDF text extraction.
paper_text = (root / 'tmp/pdfs/d3ra06226k-review/paper.txt').read_text(encoding='utf8')
raw_rows = []
for textline in paper_text.splitlines():
    match = re.match(r'^\s*(Zn|Ca|Mg)\s+(I|II)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+\u00d7\s+10([678])\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s*$', textline)
    if match:
        e, q, wl, w, mant, exp, acc, lo, up, gl, gu = match.groups()
        raw_rows.append((e, 0 if q == 'I' else 1, float(wl), float(w), float(mant + 'e' + exp),
                         float(acc), float(lo), float(up), int(gl), int(gu)))
assert len(raw_rows) == len(lines) == 31, (len(raw_rows), len(lines))
for a, line in zip(raw_rows, lines):
    b = tuple(line[k] for k in ['element', 'charge', 'wavelength_nm', 'stark_width_nm', 'Aki_s',
                                'Aki_accuracy_error_percent', 'lower_eV', 'upper_eV', 'g_lower', 'g_upper'])
    assert a == b, (a, b)
snapshot['provenance']['verification_statistics'] = {
    'table_rows': len(lines), 'table_rows_matched_to_pdf_text': len(raw_rows),
    'element_count': len(snapshot['elements']), 'level_tables': 9,
    'level_response_total_rows': sum(p['statistics']['total_rows'] for e in snapshot['elements'].values() for p in e['provenance']['levels'].values()),
    'valid_level_rows': sum(len(l) for e in snapshot['elements'].values() for l in e['levels'].values()),
    'excluded_level_response_rows': sum(p['statistics']['excluded_rows'] for e in snapshot['elements'].values() for p in e['provenance']['levels'].values()),
    'bound_level_rows': sum(l['is_bound'] for e in snapshot['elements'].values() for levels in e['levels'].values() for l in levels),
    'csv_vs_ascii_energy_J_g_mismatches': 0}
snapshot['provenance']['supplementary_downloads'][0]['statistics'] = {
    'total_rows': 0, 'valid_rows': 0, 'excluded_rows': 0,
    'purpose': 'Public query form metadata; contains no atomic level rows.'}
snapshot['provenance']['supplementary_downloads'][1]['statistics'] = dict(
    snapshot['elements']['Mg']['provenance']['levels']['2']['cross_check_download']['statistics'])
out = root / 'simLIBS-2.0.3/simLIBS/data/paper_atomic_data.json'
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
print(out)
print(json.dumps(snapshot['provenance']['verification_statistics'], indent=2))
for e, data in snapshot['elements'].items():
    print(e, data['ionization_energies_eV'])
    for charge, provenance in data['provenance']['levels'].items():
        print(charge, provenance['statistics'])
