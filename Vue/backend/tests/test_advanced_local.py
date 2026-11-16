"""Actual local CSV/LTE plus labelled width fixtures; real network forbidden."""
from copy import deepcopy
from dataclasses import replace
import csv
import importlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from scipy.constants import e, k
from scipy.integrate import trapezoid

from simlibs_ui import advanced_local as local
from simlibs_ui.advanced import effective, simulate
from simlibs_ui.adapter import source_module
from simlibs_ui.models import Parameters
from simlibs_ui.offline_database import load_library, parse_file
from simlibs_ui.offline_lines import simulate_lines
from simlibs_ui.settings import Settings
from simlibs_ui.storage import read_manifest
from simlibs_ui.worker import execute


class AdvancedLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('SIMLIBS_TEST_TMP'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = replace(Settings(), output=str(self.root))
        self.p = replace(Parameters(), webscraping='local', mode_version=2, broadening='local',
                         broaden_convention='physics', local_broadening_enabled=False,
                         elements=('Ca',), percentages=(100,), low_w=392, upper_w=398,
                         broaden_grid_step=.002, resolution=5000).validated()
        source_module(self.s.source)
        self.resolver = importlib.import_module('simLIBS.stark_resolver')
        self.stark = importlib.import_module('simLIBS.nist_stark')
        self.addCleanup(patch.stopall)
        patch('requests.sessions.Session.request', side_effect=AssertionError('Real network forbidden')).start()
        patch.dict(os.environ, SIMLIBS_TASK_DIR=str(self.root), SIMLIBS_STARK_CACHE_DIR=str(self.root/'cache')).start()

    def raw(self, **changes):
        return dict(model='local', stark_broadening=False, self_absorption=False,
                    instrument_broadening=False, matrix=False, **changes)

    def fixture_database(self, p=None):
        p = p or self.p
        library = load_library(self.s.line_database, set(p.elements))
        records, _ = local.local_records(p, library, local.options(self.raw()), 1, lambda: False)
        # Source labels need Stark enabled; no coefficient fetching occurs here.
        records, _ = local.local_records(p, library, local.options({**self.raw(), 'stark_broadening': True}), 1, lambda: False)
        from simLIBS.stark_b import parse_table
        base = parse_table((Path(__file__).parent/'fixtures/starkb_si_ii_6347.html').read_text(encoding='utf-8'),
                           element='Si', charge=1, dataset_id='fixture-base', method='SCP')[0]
        tables = []
        for i, record in enumerate(records):
            if not all(self.stark._state(record.get(key, '')) for key in ('lower_label', 'upper_label')):
                continue
            row = deepcopy(base)
            row.update(element=record['element'], charge=record['charge'], dataset_id='fixture-'+str(i),
                       lower_label=record['lower_label'], upper_label=record['upper_label'],
                       calculated_wavelength_angstrom=record['wavelength_nm']*10, fit=None,
                       c_angstrom_cm3=None, source='SYNTHETIC width fixture; not measured local coefficients')
            row['samples'] = [dict(temperature_k=p.Te*e/k, ne=p.Ne, fwhm_angstrom=.2, flag='')]
            tables.append(row)
        return dict(rows=tables, manifest={'complete': True}, path='SYNTHETIC width fixture', file_sha256='fixture'), records

    def run_local(self, **flags):
        return simulate(self.p, self.s, {**self.raw(), **flags})

    def test_reordered_csv_columns_preserve_quantum_and_numeric_identity(self):
        library = load_library(self.s.line_database, {'Ca'})
        options = local.options({**self.raw(), 'stark_broadening': True})
        original, _ = local.local_records(self.p, library, options, 1, lambda: False)
        keys = ('element', 'charge', 'wavelength_nm', 'gA_s', 'lower_eV', 'upper_eV',
                'g_lower', 'g_upper', 'local_lte_area', 'lower_label', 'upper_label', 'rows')
        for order in ([0, 1, 2, 4, 3, 5, 6, 7, 8], [6, 7, 5, 4, 2, 3, 1, 0, 8]):
            changed = deepcopy(library)
            for charge, state in changed['elements']['Ca'].items():
                rows = list(csv.reader(io.StringIO(Path(state['file']).read_bytes().decode(state['encoding']))))
                target = self.root/f'reordered-{charge}.csv'
                with target.open('w', encoding='utf-8', newline='') as stream:
                    csv.writer(stream).writerows([[row[i] if i < len(row) else '' for i in order]
                                                 for row in rows])
                changed['elements']['Ca'][charge] = parse_file(target)
            actual, _ = local.local_records(self.p, changed, options, 1, lambda: False)
            self.assertEqual([{key: row[key] for key in keys} for row in actual],
                             [{key: row[key] for key in keys} for row in original])
            for row in actual:
                self.assertIsNotNone(self.stark.identify(row, [row]))
                shifted = dict(row, wavelength_nm=row['wavelength_nm']+32*math.ulp(row['wavelength_nm']))
                self.assertIsNone(self.stark.identify(row, [shifted]))
                for evidence in row['local_quantum_rows']:
                    self.assertIn('energy', evidence['columns'])
                    self.assertIn('configuration', evidence['columns'])
            state = changed['elements']['Ca'][actual[0]['charge']]
            altered = dict(state['transitions'][0], upper_cm=state['transitions'][0]['upper_cm']+1)
            with self.assertRaisesRegex(ValueError, '数值身份不一致'):
                local.quantum_identity(altered, *local.quantum_rows(state))

    def test_actual_mg_ca_areas_match_single_and_no_coefficient_access(self):
        with patch.object(self.resolver, 'load_database', side_effect=AssertionError('No coefficients when off')):
            for el, low, high in [('Mg', 280, 286), ('Ca', 392, 398)]:
                p = replace(self.p, elements=(el,), low_w=low, upper_w=high)
                original, _ = simulate_lines(p, self.s, lambda: False)
                frames, origin = simulate(p, self.s, self.raw())
                rows = json.loads((self.root/'advanced-lines.json').read_text())
                self.assertAlmostEqual(sum(r['local_lte_area'] for r in rows), original['raw'].intensity.sum(), places=7)
                self.assertAlmostEqual(trapezoid(frames['raw'].intensity, frames['raw'].wavelength), original['raw'].intensity.sum(), places=7)
                self.assertFalse(origin['network_used'])
                self.assertFalse(origin['line_strength_network_used'])
                self.assertTrue(origin['model_version'].startswith('local-lines-'))
                for row in rows:
                    self.assertEqual(row['gA_s'], row['Aki_s']*row['g_upper'])
                    self.assertEqual(row['upper_eV'], row['upper_cm']*local.CM_TO_EV)
            frames, _ = self.run_local(instrument_broadening=True)
            self.assertTrue(np.isfinite(frames['raw'].to_numpy()).all())

    def test_real_resolver_json_width_and_sa_limits_r_independence(self):
        database, original = self.fixture_database()
        self.assertTrue(database['rows'])
        with patch.object(self.resolver, 'load_database', return_value=database), \
             patch.object(self.stark, 'resolve_online', side_effect=AssertionError('JSON must short circuit')):
            self.run_local(stark_broadening=True)
            thin = json.loads((self.root/'advanced-lines.json').read_text())
            self.assertTrue(all(r['stark_resolution_layer'] == 'JSON' for r in thin))
            for row in thin:
                self.assertAlmostEqual(row['thin_fwhm_nm'], .02, places=12)
                self.assertEqual(row['thin_area'], row['local_lte_area'])
                self.assertEqual(row['lower_label'], next(r for r in original if r['rows'] == row['rows'])['lower_label'])
            self.run_local(stark_broadening=True, self_absorption=True, path_length_m=0,
                           density_mode='specified', number_density_cm3=1e16)
            zero = json.loads((self.root/'advanced-lines.json').read_text())
            self.assertTrue(all(r['SA'] == 1 and r['tau_center'] == 0 for r in zero))
            self.run_local(stark_broadening=True, self_absorption=True, path_length_m=.001,
                           density_mode='specified', number_density_cm3=1e16)
            absorbed = json.loads((self.root/'advanced-lines.json').read_text())
            self.assertTrue(all(0 < r['SA'] < 1 and r['absorbed_area'] < r['thin_area'] for r in absorbed))
            p = replace(self.p, resolution=10000)
            simulate(p, self.s, {**self.raw(), 'stark_broadening': True, 'self_absorption': True,
                                'instrument_broadening': True, 'path_length_m': .001,
                                'density_mode': 'specified', 'number_density_cm3': 1e16})
            instrument = json.loads((self.root/'advanced-lines.json').read_text())
            self.assertEqual([r['tau_center'] for r in absorbed], [r['tau_center'] for r in instrument])
            self.assertTrue(all(r['instrument_sigma_nm'] > 0 for r in instrument))

    def test_missing_width_preserves_local_area_and_q01_cannot_use_dk1980(self):
        def absent(records, **kwargs):
            return {}, {i: dict(r, stark_missing_reason='LABELLED offline fixture: no published width') for i, r in enumerate(records)}
        with patch.object(self.resolver, 'load_database', return_value=None), patch.object(self.stark, 'resolve_online', side_effect=absent):
            frames, origin = self.run_local(stark_broadening=True, self_absorption=True)
            rows = json.loads((self.root/'advanced-lines.json').read_text())
            self.assertEqual(origin['stark_coverage']['status'], 'unavailable')
            for row in rows:
                self.assertTrue(row['stark_missing'])
                self.assertFalse(row['self_absorption_applied'])
                self.assertEqual(row['thin_area'], row['absorbed_area'])
                self.assertEqual(row['thin_area'], row['local_lte_area'])
                self.assertIn('q=2 or 3', row['stark_mse_missing_reason'])
            self.assertAlmostEqual(trapezoid(frames['raw'].intensity, frames['raw'].wavelength), sum(r['local_lte_area'] for r in rows), places=7)
            report = json.loads((self.root/'missing-stark.json').read_text())
            self.assertGreater(report['count'], 0)

    def test_errors_and_cancel_are_not_missing(self):
        from simLIBS.stark_b import StarkDataAccessError
        error = StarkDataAccessError('LABELLED source failure'); error.code = 'stark_network'
        with patch.object(self.resolver, 'load_database', return_value=None), patch.object(self.stark, 'resolve_online', side_effect=error):
            with self.assertRaises(StarkDataAccessError):
                self.run_local(stark_broadening=True)
        with self.assertRaises(InterruptedError):
            simulate(self.p, self.s, self.raw(), cancelled=lambda: True)

    def test_start_config_worker_saved_result_and_export_contract(self):
        # Real worker.execute/save_result and API methods, isolated in-memory jobs.
        sys.path.insert(0, str(Path(__file__).parents[1]/'web'))
        from real_backend import RealBackend
        api = RealBackend.__new__(RealBackend); api._lock = threading.Lock(); api._jobs = {}; api._settings = self.s
        body = dict(params=dict(te=1, ne=1e17, resolution=5000, low_w=392, up_w=398, max_ion_charge=2,
                    mode='local', mode_version=2, broadening='local', broaden_convention='physics',
                    broaden_grid_step=.002, local_broadening_enabled=False), composition=[dict(el='Ca', pct=100)],
                    advanced={**self.raw(), 'stark_broadening': True, 'self_absorption': True,
                              'density_mode': 'specified', 'number_density_cm3': 1e16, 'path_length_m': 0})
        captured = {}
        api._launch = lambda kind, worker, payload, summary: captured.update(kind=kind, worker=worker, payload=payload) or 'fixture-job'
        api.start_advanced(body)
        self.assertTrue(captured['payload']['advanced']['stark_broadening'])
        self.assertTrue(captured['payload']['advanced']['self_absorption'])
        self.assertEqual(captured['payload']['advanced']['path_length_m'], 0)
        database, _ = self.fixture_database()
        with patch.object(self.resolver, 'load_database', return_value=database), patch.object(self.stark, 'resolve_online', side_effect=AssertionError('no network')):
            result = execute(dict(kind='advanced', settings=self.s.to_dict(), directory=str(self.root),
                             **captured['payload']), lambda *args, **kwargs: None, lambda: False)
        manifest = read_manifest(result)
        api._jobs['fixture-job'] = dict(job_id='fixture-job', kind='高级模拟', status='completed', manifest=manifest, result_path=result)
        response = api.get_result('fixture-job')
        self.assertEqual(response['origin']['model_version'], 'local-lines-self-absorption-1')
        self.assertEqual(response['series']['raw']['xs'], response['series']['interpolated']['xs'])
        self.assertEqual(response['comparison']['xs'], response['series']['raw']['xs'])
        self.assertTrue(response['origin']['line_diagnostics'])
        self.assertIn('local_lte_area', api.export('fixture-job', 'diagnostics').payload.decode('utf-8-sig'))
        self.assertIn('nominal', api.export('fixture-job', 'csv').payload)
        document = json.loads(api.export('fixture-job', 'json').payload)
        self.assertFalse(document['origin']['line_strength_network_used'])
        self.assertTrue(api.export('fixture-job', 'stark-missing').payload)


if __name__ == '__main__':
    unittest.main()
