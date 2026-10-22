"""主入口的真实自动取数路径与离线缓存重用；网络边界用捕获响应替代。"""
from pathlib import Path
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from scipy.constants import e, k

from simLIBS import SimulatedLIBS, NISTSelfAbsorptionConfig, MissingStarkDataError
from simLIBS.nist_self_absorption import resolve_stark
from simLIBS.stark_b import parse_table, StarkDataAccessError


FIXTURES = Path(__file__).parent/'fixtures'
HTML = (FIXTURES/'starkb_si_ii_6347.html').read_text(encoding='utf-8')
TSV = (FIXTURES/'nist_si_ii_identity.tsv').read_text(encoding='utf-8')
CMEV = 8065.54393734921


class AutoStarkTests(unittest.TestCase):
    def line(self, **change):
        return dict(dict(element='Si', charge=1, wavelength_nm=634.886, gA_s=233600000.,
                         lower_eV=65500.47/CMEV, upper_eV=81251.32/CMEV), **change)

    def test_automatic_sourced_width_and_offline_repeat(self):
        payload = dict(datasets=[dict(id='223', method='SCP', url='https://stark-b.obspm.fr/index.php/data/ion/35', html=HTML)])
        with tempfile.TemporaryDirectory() as folder:
            config = NISTSelfAbsorptionConfig(stark_cache_dir=folder)
            with patch('simLIBS.stark_b.StarkBClient._fetch', return_value=payload) as source, \
                 patch('simLIBS.nist_stark._fetch_identities', return_value=dict(text=TSV, url='https://physics.nist.gov')):
                rows = resolve_stark([self.line()], config, te=10000*k/e, ne=1e17, cmev=CMEV)
            self.assertEqual(source.call_count, 1)
            self.assertAlmostEqual(rows[0]['stark_width_nm'], .0965*(634.886/634.7)**2)
            self.assertIn('STARK-B', rows[0]['stark_source'])
            config = NISTSelfAbsorptionConfig(stark_cache_dir=folder, stark_allow_network=False)
            with patch('requests.sessions.Session.request', side_effect=AssertionError('network used')):
                cached = resolve_stark([self.line()], config, te=10000*k/e, ne=1e17, cmev=CMEV)
            self.assertEqual(rows, cached)

    def test_local_override_prevents_external_requests(self):
        supplied = [dict(self.line(), stark_width_nm=.123, source='user published coefficient')]
        with patch('simLIBS.nist_stark.resolve_online', side_effect=AssertionError('provider called')):
            rows = resolve_stark([self.line()], NISTSelfAbsorptionConfig(stark_data=supplied), te=1, ne=1e17, cmev=CMEV)
        self.assertEqual(rows[0]['stark_width_nm'], .123)

    def test_successful_source_without_usable_density_reports_the_actual_limit(self):
        document = dict(payload=dict(format='vamdc-xsams', status='ok', datasets=[]))
        with tempfile.TemporaryDirectory() as folder, \
             patch('simLIBS.stark_b.StarkBClient.species', return_value=([], document)):
            with self.assertRaises(MissingStarkDataError) as raised:
                resolve_stark([self.line()], NISTSelfAbsorptionConfig(stark_cache_dir=folder),
                              te=1., ne=1e19, cmev=CMEV)
        reason = raised.exception.missing_lines.stark_missing_reason.iloc[0]
        self.assertNotEqual(reason, 'ok')
        self.assertIn('density', reason)

    def test_partial_coverage_preserves_supported_and_missing_diagnostics(self):
        other = self.line(wavelength_nm=637.313, gA_s=136000000., upper_eV=81191.34/CMEV)
        with tempfile.TemporaryDirectory() as folder:
            config = NISTSelfAbsorptionConfig(stark_cache_dir=folder)
            tables = parse_table(HTML, element='Si', charge=1, dataset_id='223', method='SCP')
            doc = dict(payload=dict(datasets=[{}]))
            with patch('simLIBS.stark_b.StarkBClient.species', return_value=(tables, doc)), \
                 patch('simLIBS.nist_stark._fetch_identities', return_value=dict(text=TSV, url='test')):
                with self.assertRaises(MissingStarkDataError) as raised:
                    resolve_stark([self.line(), other], config, te=10000*k/e, ne=1e17, cmev=CMEV)
        self.assertEqual(len(raised.exception.matched_lines), 1)
        self.assertEqual(len(raised.exception.missing_lines), 1)
        self.assertIn('state', raised.exception.missing_lines.stark_missing_reason.iloc[0])

    def test_configuration_validation(self):
        for change in ({'stark_source': 'guessed'}, {'stark_allow_network': 1}, {'stark_methods': []},
                       {'stark_methods': ['unknown']}, {'stark_methods': ['SCP', 'SCP']}):
            with self.subTest(), self.assertRaises(ValueError):
                NISTSelfAbsorptionConfig(**change)

    def test_temporary_NIST_error_page_is_not_persisted_in_cache(self):
        tables = parse_table(HTML, element='Si', charge=1, dataset_id='223', method='SCP')
        replies = [dict(text='<h1>Temporary service error</h1>', url='NIST'), dict(text=TSV, url='NIST')]
        with tempfile.TemporaryDirectory() as folder, \
             patch('simLIBS.stark_b.StarkBClient.species', return_value=(tables, {})), \
             patch('simLIBS.nist_stark._fetch_identities', side_effect=replies) as fetch:
            config = NISTSelfAbsorptionConfig(stark_cache_dir=folder)
            with self.assertRaises(StarkDataAccessError):
                resolve_stark([self.line()], config, te=1, ne=1e17, cmev=CMEV)
            self.assertFalse(list(Path(folder).glob('*.json')))
            rows = resolve_stark([self.line()], config, te=1, ne=1e17, cmev=CMEV)
            self.assertEqual(len(rows), 1)
            self.assertEqual(fetch.call_count, 2)

    def test_main_class_uses_real_Si_data_for_stark_and_self_absorption(self):
        body = (FIXTURES/'nist_si_634_638.html').read_text(encoding='utf-8')
        tables = parse_table(HTML, element='Si', charge=1, dataset_id='223', method='SCP')
        response = Mock(text=body)
        response.raise_for_status.return_value = None
        for absorption in (False, True):
            with self.subTest(absorption=absorption), tempfile.TemporaryDirectory() as folder:
                with patch('simLIBS.simulation.requests.get', return_value=response), \
                     patch('simLIBS.stark_b.StarkBClient.species', return_value=(tables, {})), \
                     patch('simLIBS.nist_stark._fetch_identities', return_value=dict(text=TSV, url='NIST fixture')):
                    simulation = SimulatedLIBS(Te=1., Ne=1e17, elements=['Si'], percentages=[100.],
                        low_w=634.88, upper_w=634.90, webscraping='static', self_absorption=absorption,
                        stark_broadening=True, self_absorption_config={'stark_cache_dir': folder,
                                                                   'path_length_m': .001})
                diagnostics = simulation.self_absorption_diagnostics
                self.assertEqual(len(diagnostics), 1)
                self.assertEqual(diagnostics.stark_method.iloc[0], 'SCP')
                self.assertEqual(simulation.self_absorption_metadata['stark_data']['stark_b_line_count'], 1)
                self.assertEqual(diagnostics.SA.iloc[0] < 1, absorption)
                with patch('requests.sessions.Session.request', side_effect=AssertionError('network used')):
                    simulation.interpolate(resolution=.001)

    def test_cli_accepts_element_and_exports_sourced_metadata(self):
        path = Path(__file__).parents[1]/'examples'/'nist_self_absorption_demo.py'
        spec = importlib.util.spec_from_file_location('automatic_stark_cli_test', path)
        example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
        response = Mock(text=(FIXTURES/'nist_si_634_638.html').read_text(encoding='utf-8'))
        response.raise_for_status.return_value = None
        payload = dict(datasets=[dict(id='223', method='SCP', url='STARK-B', html=HTML)])
        with tempfile.TemporaryDirectory() as folder:
            args = [str(path), '--element', 'Si', '--low', '634.88', '--high', '634.90',
                    '--stark-only', '--cache-dir', str(Path(folder)/'cache'), '--output', folder]
            with patch.object(sys, 'argv', args), patch('simLIBS.simulation.requests.get', return_value=response), \
                 patch('simLIBS.stark_b.StarkBClient._fetch', return_value=payload), \
                 patch('simLIBS.nist_stark._fetch_identities', return_value=dict(text=TSV, url='NIST fixture')), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(example.main(), 0)
            metadata = json.loads((Path(folder)/'metadata.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['stark_data']['stark_b_line_count'], 1)


if __name__ == '__main__':
    unittest.main()
