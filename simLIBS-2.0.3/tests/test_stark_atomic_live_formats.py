"""Offline regressions against verbatim NIST ASD responses fetched in Nov 2026.

Fixture JSON contains the original response, request URL/parameters, timestamp
and SHA256. Label-only model probes below are not STARK-B measurements and
must never be written into the comparison's models.json.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import stark_atomic_data as atomic

FIXTURES = Path(__file__).parent / 'fixtures' / 'nist_live'


def snapshot(stem):
    return json.loads((FIXTURES / (stem + '.json')).read_text(encoding='utf-8'))


def species_data(element, charge):
    stem = element + '_' + str(charge)
    docs = {name: snapshot(stem + '_' + name + '_initial')
            for name in ('levels', 'lines', 'ionization')}
    levels, limits = atomic.parse_nist_levels(docs['levels']['text'])
    lines = atomic.parse_nist_lines(docs['lines']['text'])
    ie = atomic._parse_ie(docs['ionization']['text'], element, charge)
    source = {name + '_url': doc['url'] for name, doc in docs.items()}
    source.update({name + '_sha256': doc['sha256'] for name, doc in docs.items()})
    return levels, limits, lines, ie, source


class LiveFormatTests(unittest.TestCase):
    def test_verbatim_fixtures_have_valid_hashes_and_request_provenance(self):
        paths = list(FIXTURES.glob('*.json'))
        self.assertGreaterEqual(len(paths), 11)
        for path in paths:
            with self.subTest(path=path.name):
                doc = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(hashlib.sha256(doc['text'].encode('utf-8')).hexdigest(),
                                 doc['sha256'])
                self.assertTrue(doc['url'].startswith(doc['endpoint'] + '?'))
                self.assertTrue(doc['request_params'])
                self.assertTrue(doc['retrieved_utc'])

    def test_live_level_and_line_exports(self):
        # Exclude six C IV levels with unknown '+x' offsets and two Na III
        # explicitly questionable LS levels; none defines a resolved energy.
        for element, charge, counts, ie in [('Si', 3, (54, 1, 269), 45.14179),
                                           ('C', 3, (100, 1, 224), 64.49352),
                                           ('Na', 2, (85, 5, 396), 71.6200),
                                           ('B', 2, (63, 1, 106), 37.93059),
                                           ('Al', 2, (83, 1, 258), 28.447642)]:
            with self.subTest(element=element):
                levels, limits, lines, energy, _ = species_data(element, charge)
                self.assertEqual((len(levels), len(limits), len(lines)), counts)
                self.assertEqual(min(r['energy_ev'] for r in levels), 0.)
                self.assertAlmostEqual(energy, ie)

    def test_separate_question_mark_suffix_is_not_a_resolved_level(self):
        text = snapshot('Na_2_levels_initial')['text']
        _, raw = atomic._tsv(text)
        self.assertTrue(any(r.get('suffix') == '?' and r.get('term') == '4P' for r in raw))
        levels, _ = atomic.parse_nist_levels(text)
        self.assertFalse(any('?' in r['raw'].get('suffix', '') for r in levels))

    def test_unknown_energy_offsets_are_not_silently_dropped(self):
        text = snapshot('C_3_levels_initial')['text']
        _, raw = atomic._tsv(text)
        self.assertEqual(sum('+x' in r.get('suffix', '') for r in raw), 6)
        levels, _ = atomic.parse_nist_levels(text)
        self.assertFalse(any('+x' in r['raw'].get('suffix', '') for r in levels))

    def test_bracketed_levels_and_ie_keep_their_source_annotations(self):
        levels, _, _, _, _ = species_data('C', 3)
        bracketed = next(r for r in levels if r['configuration'] == '1s2.6f')
        self.assertEqual((bracketed['raw']['prefix'], bracketed['raw']['suffix']), ('[', ']'))
        self.assertAlmostEqual(bracketed['energy_ev'], 471403.2 / atomic.CM1_PER_EV)
        text = snapshot('Na_2_ionization_initial')['text']
        _, rows = atomic._tsv(text)
        self.assertEqual((rows[0]['ioncharge'], rows[0]['prefix'], rows[0]['suffix']),
                         ('+2', '[', ']'))
        self.assertEqual(atomic._parse_ie(text, 'Na', 2), 71.62)

    def test_ie_rejects_a_different_element_with_the_same_charge(self):
        with self.assertRaisesRegex(ValueError, 'unique|species|element'):
            atomic._parse_ie(snapshot('C_3_ionization_initial')['text'], 'Si', 3)

    def test_ie_rejects_wrong_charge(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            atomic._parse_ie(snapshot('Si_3_ionization_initial')['text'], 'Si', 2)

    def test_type_column_excludes_real_forbidden_lines(self):
        text = snapshot('Si_3_lines_with_forbidden')['text']
        _, raw = atomic._tsv(text)
        self.assertEqual({r['type'] for r in raw}, {'', 'E2', 'M1', 'M2'})
        parsed = atomic.parse_nist_lines(text)
        baseline = atomic.parse_nist_lines(snapshot('Si_3_lines_initial')['text'])
        self.assertEqual(parsed, baseline)
        self.assertEqual(len(parsed), 269)
        self.assertTrue(all(r['raw']['type'] == '' for r in parsed))

    def test_type_column_is_required_to_interpret_blank_e1(self):
        text = snapshot('Si_3_lines_initial')['text'].replace('\tType\t', '\tUnknown\t', 1)
        with self.assertRaisesRegex(ValueError, 'columns'):
            atomic.parse_nist_lines(text)

    def test_real_error_response_is_rejected_by_parsers(self):
        text = snapshot('levels_invalid_spectrum')['text']
        self.assertIn('Input Error', text)
        for parser in (atomic.parse_nist_levels, atomic.parse_nist_lines):
            with self.subTest(parser=parser.__name__), self.assertRaisesRegex(ValueError, 'HTML'):
                parser(text)

    def test_real_aki_components_build_label_only_si_iv_and_c_iv_probes(self):
        for element, lower, upper in [('Si', '2p6.3s 2S', '2p6.3p 2Po'),
                                       ('Si', '2p6.4s 2S', '2p6.4p 2Po'),
                                       ('C', '1s2.2s 2S', '1s2.2p 2Po'),
                                       ('C', '1s2.3s 2S', '1s2.3p 2Po')]:
            with self.subTest(element=element, lower=lower):
                levels, _, lines, ie, source = species_data(element, 3)
                table = dict(element=element, charge=3, lower_label=lower, upper_label=upper,
                             dataset_id='label-match-probe-only-not-stark-measurement')
                model = atomic.build_model_input(table, levels, lines, ie, atomic_source=source)
                atomic._validate_model(model)
                self.assertEqual(model['status'], 'ready')
                self.assertEqual(model['atomic_quality'], 'nist-aki-complete')
                self.assertEqual(len(model['lower']['same_n']), 1)
                expected_upper = 1 if lower == '1s2.2s 2S' else 2
                self.assertEqual(len(model['upper']['same_n']), expected_upper)
                self.assertTrue(all(math.isfinite(p['matrix_element_sq_a0']) and
                                    p['matrix_element_sq_a0'] > 0
                                    for name in ('lower', 'upper') for p in model[name]['same_n']))
                if element == 'Si' and lower == '2p6.3s 2S':
                    self.assertAlmostEqual(model['lower']['same_n'][0]['matrix_element_sq_a0'],
                                           3.527537720102231)

    def test_missing_real_si_iv_fine_structure_component_still_rejects_build(self):
        levels, _, lines, ie, source = species_data('Si', 3)
        removed = [r for r in lines if not (r['lower_configuration'] == '2p6.3s' and
                                           r['upper_configuration'] == '2p6.3p' and
                                           r['upper_j'] == '3/2')]
        self.assertEqual(len(removed), len(lines) - 1)
        table = dict(element='Si', charge=3, lower_label='2p6.3s 2S', upper_label='2p6.3p 2Po')
        with self.assertRaisesRegex(ValueError, 'Incomplete E1 Aki'):
            atomic.build_model_input(table, levels, removed, ie, atomic_source=source)

    def test_real_stark_b_iii_table_builds_ready_model_with_exact_identity(self):
        fixture = json.loads((FIXTURES.parent / 'starkb_b_iii_first_atomic_ready.json').read_text(
            encoding='utf-8'))
        table = fixture['table']
        self.assertEqual(table['dataset_id'], 'vamdc:Pstarkb-R123')
        self.assertEqual(table['source_ids'], ['Bstarkb-51', 'Bstarkb-55'])
        self.assertEqual(table['calculated_wavelength_angstrom'], 2066.9)
        self.assertTrue(table['samples'])
        levels, _, lines, ie, source = species_data('B', 2)
        model = atomic.build_model_input(table, levels, lines, ie, atomic_source=source)
        atomic._validate_model(model)
        self.assertEqual(model['key'],
                         '7761d8deb6c28c680a536962758c706959f7716989cfb9367b59f4db07bddafe')
        self.assertEqual(model['status'], 'ready')
        self.assertEqual(model['atomic_quality'], 'nist-aki-complete')
        self.assertAlmostEqual(model['ionization_energy_ev'], 37.93059)
        self.assertAlmostEqual(model['lower']['same_n'][0]['matrix_element_sq_a0'],
                               2.47100662607962)
        self.assertAlmostEqual(model['upper']['same_n'][0]['matrix_element_sq_a0'],
                               0.8236688753598734)

    def test_real_al_iii_expanded_closed_core_matches_compact_nist_label(self):
        models = []
        levels, _, lines, ie, source = species_data('Al', 2)
        for form in ('expanded', 'compact'):
            fixture = json.loads((FIXTURES.parent / ('starkb_al_iii_' + form + '_core.json')).read_text(
                encoding='utf-8'))
            table = fixture['table']
            model = atomic.build_model_input(table, levels, lines, ie, atomic_source=source)
            atomic._validate_model(model)
            self.assertEqual(model['status'], 'ready')
            self.assertEqual(model['key'], atomic.table_key(table))
            models.append(model)
        self.assertNotEqual(models[0]['key'], models[1]['key'])
        self.assertEqual(models[0]['lower'], models[1]['lower'])
        self.assertEqual(models[0]['upper'], models[1]['upper'])
        self.assertAlmostEqual(models[0]['lower']['same_n'][0]['matrix_element_sq_a0'],
                               5.136023857479942)

    def test_closed_core_prefix_match_rejects_open_or_conflicting_subshells(self):
        levels, _, lines, ie, source = species_data('Al', 2)
        for core in ('2s.2p6', '2s2.2p5', '2p5', '3s2.2p6'):
            table = dict(element='Al', charge=2, lower_label=core + '.3s 2S',
                         upper_label='2p6.3p 2Po')
            with self.subTest(core=core), self.assertRaisesRegex(ValueError, 'unambiguous'):
                atomic.build_model_input(table, levels, lines, ie, atomic_source=source)

    def test_open_core_na_iii_is_not_promoted_to_an_automatic_model(self):
        levels, _, lines, ie, source = species_data('Na', 2)
        table = dict(element='Na', charge=2, lower_label='2s2.2p5 2Po', upper_label='2s.2p6 2S')
        with self.assertRaisesRegex(ValueError, 'single valence|Open-shell'):
            atomic.build_model_input(table, levels, lines, ie, atomic_source=source)


class SparseLineExportTests(unittest.TestCase):
    def test_real_observation_only_exports_are_data_missing_not_schema_failures(self):
        expected = {'Bi_3': 45, 'Cd_2': 95, 'Cu_2': 100, 'Cu_3': 60,
                    'Eu_2': 229, 'Ge_2': 55, 'Ge_3': 27, 'La_2': 122, 'Lu_2': 64}
        for stem, count in expected.items():
            with self.subTest(species=stem):
                doc = snapshot(stem + '_lines_sparse')
                diagnostics = {}
                self.assertEqual(atomic.parse_nist_lines(doc['text'], diagnostics=diagnostics), [])
                self.assertEqual(diagnostics['status'], 'missing')
                self.assertEqual(diagnostics['observed_lines'], count)
                self.assertEqual(diagnostics['missing_fields'],
                                 ['Aki', 'Ritz wavelength', 'level energies', 'level classifications'])
                self.assertIn('observed wavelengths only', diagnostics['reason'])
                self.assertEqual(atomic.parse_nist_lines(doc['text']), [])

    def test_real_sparse_spectra_have_no_probability_or_classification_matches(self):
        for stem in ('Ge_3', 'Cu_2', 'Bi_3'):
            for mode in (1, 2):
                with self.subTest(species=stem, line_out=mode):
                    doc = snapshot(stem + '_lines_filter_' + str(mode))
                    self.assertEqual(doc['request_params']['line_out'], mode)
                    self.assertIn('No lines are available in ASD with the parameters selected',
                                  doc['text'])

    def test_partial_or_unknown_schema_does_not_masquerade_as_sparse_atomic_data(self):
        good = snapshot('Si_3_lines_initial')['text']
        sparse = snapshot('Ge_3_lines_sparse')['text']
        unexpected = [good.replace('conf_i', 'unknown_conf_i', 1),
                      sparse.replace('Type', 'UnknownType', 1),
                      sparse.replace('obs_wl_vac(nm)', 'obs_wl_air(nm)', 1),
                      sparse.replace('Aki(s^-1)', 'UnknownAki', 1)]
        header, *rows = sparse.splitlines()
        fields = rows[0].split('\t')
        fields[2] = '"1e8"'
        unexpected.append('\n'.join([header, '\t'.join(fields)] + rows[1:]))
        for text in unexpected:
            with self.subTest(header=text.splitlines()[0]), self.assertRaisesRegex(ValueError, 'columns'):
                atomic.parse_nist_lines(text)

    def test_prepare_records_retrieved_sparse_data_without_source_failure_or_ready_model(self):
        table = dict(element='Ge', charge=3, dataset_id='data-absence-regression-only',
                     lower_label='3d10.4s 2S', upper_label='3d10.4p 2Po')
        docs = {atomic.ASD_LEVELS: snapshot('Ge_3_levels_sparse_support'),
                atomic.ASD_LINES: snapshot('Ge_3_lines_sparse'),
                atomic.ASD_IE: snapshot('Ge_3_ionization_sparse_support')}
        def get_snapshot(path, url, params, **kwargs):
            self.assertEqual(docs[url]['request_params'], params)
            return docs[url]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(atomic, '_get_snapshot', side_effect=get_snapshot):
                manifest = atomic.prepare_atomic_samples([table], directory, delay=0)
            self.assertTrue(manifest['complete'])
            self.assertEqual((manifest['ready'], manifest['missing']), (0, 1))
            species, = manifest['species']
            self.assertEqual(species['status'], 'ok')
            self.assertEqual(species['e1_lines'], 0)
            self.assertEqual(species['line_data']['status'], 'missing')
            model, = json.loads((Path(directory) / 'models.json').read_text(encoding='utf-8'))['models']
            self.assertEqual(model['status'], 'missing')
            self.assertEqual(model['missing_kind'], 'nist_line_data_unavailable')
            self.assertIn('Aki', model['reason'])
            self.assertIn('Ritz wavelength', model['reason'])
            self.assertNotIn('atomic source failure', model['reason'])
            self.assertEqual(model['atomic_source']['lines_sha256'], docs[atomic.ASD_LINES]['sha256'])
            parsed = json.loads((Path(directory) / 'Ge_3_atomic.json').read_text(encoding='utf-8'))
            self.assertEqual(parsed['lines'], [])
            self.assertEqual(parsed['line_data'], species['line_data'])


class SnapshotRecoveryTests(unittest.TestCase):
    def response(self, doc):
        response = atomic.requests.Response()
        response.status_code = 200
        response._content = doc['text'].encode('utf-8')
        response.url = doc['url']
        return response

    def test_cached_real_html_error_page_is_refetched_without_refresh(self):
        good = snapshot('Si_3_levels_initial')
        # Emulate an HTTP-200 HTML failure at the otherwise correct request URL.
        cached = dict(good, text=snapshot('levels_invalid_spectrum')['text'])
        cached['sha256'] = hashlib.sha256(cached['text'].encode('utf-8')).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'levels.json'
            atomic._atomic_json(path, cached)
            with patch.object(atomic.requests, 'get', return_value=self.response(good)) as get:
                actual = atomic._get_snapshot(path, good['endpoint'], good['request_params'],
                                              refresh=False, delay=0)
            self.assertEqual(actual['text'], good['text'])
            self.assertEqual(actual['sha256'], good['sha256'])
            self.assertEqual(get.call_count, 1)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), actual)

    def test_valid_cache_is_reused_without_network(self):
        doc = snapshot('Si_3_levels_initial')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'levels.json'
            atomic._atomic_json(path, doc)
            with patch.object(atomic.requests, 'get', side_effect=AssertionError('unexpected network')):
                self.assertEqual(atomic._get_snapshot(path, doc['endpoint'], doc['request_params'],
                                                     refresh=False, delay=0), doc)

    def test_tampered_or_mismatched_cache_still_fails_integrity_check(self):
        doc = snapshot('Si_3_levels_initial')
        for field in ('text', 'endpoint', 'request_params'):
            changed = deepcopy(doc)
            changed[field] = 'tampered' if field != 'request_params' else {}
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'levels.json'
                atomic._atomic_json(path, changed)
                with patch.object(atomic.requests, 'get', side_effect=AssertionError('unexpected network')):
                    with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                        atomic._get_snapshot(path, doc['endpoint'], doc['request_params'],
                                             refresh=False, delay=0)

    def test_fresh_error_page_is_preserved_for_diagnostics(self):
        doc = snapshot('levels_invalid_spectrum')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'levels.json'
            with patch.object(atomic.requests, 'get', return_value=self.response(doc)):
                actual = atomic._get_snapshot(path, doc['endpoint'], doc['request_params'],
                                              refresh=True, delay=0)
            self.assertEqual(actual['text'], doc['text'])
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['sha256'], doc['sha256'])
            with self.assertRaisesRegex(ValueError, 'HTML'):
                atomic.parse_nist_levels(actual['text'])


if __name__ == '__main__':
    unittest.main()
