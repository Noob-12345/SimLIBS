"""Offline contract tests for Vue's shared paper self-absorption backend."""
from dataclasses import replace
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from simlibs_ui.advanced import effective, options, simulate
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings


def parameters(**values):
    defaults = dict(webscraping='local', mode_version=2, broadening='local',
                    broaden_convention='physics', elements=('Mg',), percentages=(100,),
                    low_w=284.5, upper_w=286., max_ion_charge=2,
                    broaden_grid_step=.005, step=.005)
    return replace(Parameters(), **dict(defaults, **values)).validated()


class AdvancedPaperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = replace(Settings(), line_database=str(self.root/'no-legacy-line-library'))
        self.raw = {'column_cm2': 1e16, 'path_length_m': .01, 'matrix': True,
                    'responses': {'Mg': .7}, 'te_factor': 1.1, 'ne_factor': 1.2}

    def run_model(self, p=None, raw=None, **kwargs):
        # Any accidental database/network/browser fallback must fail this real calculation.
        with patch.dict(os.environ, {'SIMLIBS_TASK_DIR': str(self.root)}), \
             patch('requests.get', side_effect=AssertionError('unexpected HTTP')), \
             patch('socket.create_connection', side_effect=AssertionError('unexpected TCP')), \
             patch('selenium.webdriver.Chrome', side_effect=AssertionError('unexpected browser')):
            try:
                return simulate(p or parameters(), self.settings, self.raw if raw is None else raw, **kwargs)
            except ValueError as error:
                if 'no-legacy-line-library' in str(error):
                    self.fail('论文模型必须使用共享Stark快照，不能依赖旧本地线库：'+str(error))
                raise

    def engine(self):
        from simlibs_ui.adapter import source_module
        source_module(self.settings.source)
        return importlib.import_module('simLIBS.self_absorption')

    def test_path_length_is_validated_and_missing_stark_elements_are_rejected(self):
        self.assertEqual(options({}).get('path_length_m'), .01)
        for value in (0, -1, True, 'nan', 'inf'):
            with self.assertRaises(ValueError, msg=str(value)):
                options({'path_length_m': value})
        with self.assertRaisesRegex(ValueError, 'Fe.*Stark|Stark.*Fe'):
            effective(parameters(elements=('Fe',)), {})
        # A zero-abundance unsupported symbol contributes no population or opacity.
        q, _, _ = effective(parameters(elements=('Mg', 'Fe'), percentages=(100, 0)), {})
        self.assertEqual(q.percentages, (100., 0.))

    def test_actual_shared_engine_produces_three_spectra_and_per_line_exports(self):
        frames, origin = self.run_model()
        self.assertFalse(origin['network_used'])
        self.assertEqual(origin['intensity_scale'], 'photon')
        self.assertEqual(origin['model_version'], 'paper-eq7-stark-sa-1')
        self.assertEqual(origin['opacity_diagnostic_kind'], 'per-line-center')
        self.assertAlmostEqual(origin['matrix']['effective_number_density_cm3'], 7e15)
        reference = pd.read_csv(origin['thin_reference'])
        lines = pd.read_csv(origin['line_table'], float_precision='round_trip')
        opacity = pd.read_csv(origin['opacity_table'], float_precision='round_trip')
        self.assertEqual(list(opacity), ['wavelength', 'tau', 'beta'])
        np.testing.assert_allclose(opacity['wavelength'], lines['wavelength_nm'])
        np.testing.assert_allclose(opacity['tau'], lines['tau_center'])
        np.testing.assert_allclose(opacity['beta'], lines['SA'])
        self.assertGreater(float(lines['tau_center'].max()), 0)
        self.assertLess(float(lines['SA'].min()), 1)
        p = parameters()
        q, _, scale = effective(p, self.raw)
        engine = self.engine()
        config = engine.PaperSelfAbsorptionConfig(path_length_m=.01,
                  total_number_density_cm3=1e16/(100*.01)*scale,
                  wavelength_step_nm=.005, instrument_broadening=True, intensity_scale='photon')
        expected = engine.simulate_paper_spectrum(Te=q.Te, Ne=q.Ne, elements=q.elements,
                     percentages=q.percentages, low_w=q.low_w, upper_w=q.upper_w,
                     resolution=q.resolution, max_ion_charge=q.max_ion_charge, config=config)
        np.testing.assert_allclose(frames['raw']['intensity'], expected.spectrum['intensity'], rtol=1e-13)
        np.testing.assert_allclose(reference['intensity'], expected.thin_spectrum['intensity'], rtol=1e-13)
        nominal = engine.simulate_paper_spectrum(Te=p.Te, Ne=p.Ne, elements=p.elements,
                    percentages=p.percentages, low_w=p.low_w, upper_w=p.upper_w,
                    resolution=p.resolution, max_ion_charge=p.max_ion_charge,
                    config=replace(config, total_number_density_cm3=1e16))
        np.testing.assert_allclose(reference['nominal_intensity'], nominal.thin_spectrum['intensity'], rtol=1e-13)
        ions = frames['ion']
        np.testing.assert_allclose(ions.drop(columns=['Wavelength (nm)', 'Sum(calc)']).sum(axis=1),
                                   ions['Sum(calc)'], rtol=1e-13)
        self.assertTrue(np.isfinite(frames['raw'].to_numpy()).all())
        json.dumps(origin, allow_nan=False)

    def test_absorption_off_returns_matrix_thin_and_legacy_widths_do_not_change_stark(self):
        frames, origin = self.run_model(raw=dict(self.raw, self_absorption=False))
        reference = pd.read_csv(origin['thin_reference'])
        np.testing.assert_allclose(frames['raw']['intensity'], reference['intensity'], rtol=1e-13)
        baseline, _ = self.run_model()
        changed, _ = self.run_model(raw=dict(self.raw, intrinsic_gaussian_nm=8,
                         intrinsic_lorentz_nm=9, temperature_K=1e7))
        np.testing.assert_array_equal(baseline['raw'], changed['raw'])

    def test_instrument_resolution_does_not_change_line_center_tau_or_sa(self):
        first, origin = self.run_model(p=parameters(resolution=1000))
        diagnostics = pd.read_csv(origin['line_table'], float_precision='round_trip')
        second, other = self.run_model(p=parameters(resolution=10000))
        changed = pd.read_csv(other['line_table'], float_precision='round_trip')
        np.testing.assert_array_equal(diagnostics['tau_center'], changed['tau_center'])
        np.testing.assert_array_equal(diagnostics['SA'], changed['SA'])
        self.assertFalse(np.array_equal(first['raw']['intensity'], second['raw']['intensity']))

    def test_density_conversion_preserves_column_when_changing_path(self):
        first, origin = self.run_model()
        lines = pd.read_csv(origin['line_table'], float_precision='round_trip')
        second, other = self.run_model(raw=dict(self.raw, path_length_m=.02))
        changed = pd.read_csv(other['line_table'], float_precision='round_trip')
        self.assertAlmostEqual(other['matrix']['effective_number_density_cm3'], 3.5e15)
        np.testing.assert_allclose(lines['tau_center'], changed['tau_center'], rtol=1e-13)
        # Population-dependent emission per unit path length changes with specified density.
        np.testing.assert_allclose(second['raw']['intensity'], first['raw']['intensity']/2, rtol=1e-13)

    def test_progress_is_monotonic_and_cancellation_stops_before_export(self):
        events = []
        self.run_model(emit=lambda kind, **data: events.append((kind, data)))
        values = [data['current'] for kind, data in events if kind == 'progress']
        self.assertEqual(values, sorted(values))
        self.assertGreater(len(values), 2)
        with self.assertRaises(InterruptedError):
            self.run_model(cancelled=lambda: True)
        self.root = self.root/'cancelled-during-calculation'
        stop = [False]
        def cancel_during_line_progress(kind, **data):
            if kind == 'progress' and data['current'] >= 20:
                stop[0] = True
        with self.assertRaises(InterruptedError):
            self.run_model(cancelled=lambda: stop[0], emit=cancel_during_line_progress)
        self.assertFalse(self.root.exists(), '取消后不能创建成功三谱/诊断导出')

    def test_zero_column_and_disabled_matrix_keep_finite_physical_limits(self):
        frames, origin = self.run_model(raw=dict(self.raw, column_cm2=0))
        self.assertTrue((frames['raw']['intensity'] == 0).all())
        self.assertEqual(origin['diagnostics']['tau_max'], 0)
        self.assertEqual(origin['diagnostics']['beta_min'], 1)
        frames, origin = self.run_model(raw=dict(self.raw, matrix=False))
        reference = pd.read_csv(origin['thin_reference'], float_precision='round_trip')
        np.testing.assert_array_equal(reference['intensity'], reference['nominal_intensity'])
        self.assertEqual(origin['matrix']['yield_scale'], 1)
        self.assertEqual(origin['matrix']['effective_Te_eV'], 1)
        self.assertEqual(origin['matrix']['effective_Ne_cm3'], 1e17)

    def web_backend(self):
        web = str(Path(__file__).resolve().parents[1]/'web')
        if web not in sys.path:
            sys.path.insert(0, web)
        from real_backend import RealBackend
        backend = RealBackend.__new__(RealBackend)
        backend._settings = self.settings
        backend._lock = threading.Lock()
        return backend

    def api_body(self):
        return {'params': {'te': 1., 'ne': 1e17, 'resolution': 1000,
                    'low_w': 284.5, 'up_w': 286., 'max_ion_charge': 2,
                    'mode': 'local', 'mode_version': 2, 'intensity_scale': 'photon',
                    'broadening': 'local', 'broaden_convention': 'physics',
                    'broaden_grid_step': .005},
                'composition': [{'el': 'Mg', 'pct': 100}], 'advanced': self.raw}

    def test_advanced_api_accepts_paper_inputs_without_legacy_library_preflight(self):
        backend = self.web_backend()
        from backend_api import ApiError
        with patch.object(backend, '_launch', return_value='paper-job') as launch:
            try:
                job = backend.start_advanced(self.api_body())
            except ApiError as error:
                self.fail('高级API必须独立于旧本地线库：'+str(error))
        self.assertEqual(job, 'paper-job')
        self.assertEqual(launch.call_args.args[1], 'advanced')
        self.assertEqual(launch.call_args.args[2]['advanced']['path_length_m'], .01)
        self.assertIn('Stark', launch.call_args.args[3])

    def test_advanced_api_rejects_missing_stark_data_and_zero_path_before_launch(self):
        backend = self.web_backend()
        from backend_api import ApiError
        for change, message in (({'composition': [{'el': 'Fe', 'pct': 100}]}, 'Fe.*Stark'),
                                ({'advanced': dict(self.raw, path_length_m=0)}, 'path_length_m')):
            with self.subTest(change=change), patch.object(backend, '_launch') as launch:
                with self.assertRaisesRegex(ApiError, message):
                    backend.start_advanced(dict(self.api_body(), **change))
                launch.assert_not_called()

    def test_advanced_api_exports_real_three_spectra_and_line_center_json(self):
        from simlibs_ui.storage import save_result, read_manifest
        frames, origin = self.run_model()
        path = save_result(self.root/'result', frames, origin)
        manifest = read_manifest(path)
        backend = self.web_backend()
        backend._jobs = {'fixture': {'status': 'completed', 'result_path': path, 'manifest': manifest}}
        csv = pd.read_csv(io.StringIO(backend.export('fixture', 'csv').payload), float_precision='round_trip')
        reference = pd.read_csv(origin['thin_reference'], float_precision='round_trip')
        np.testing.assert_array_equal(csv['corrected'], frames['raw']['intensity'])
        np.testing.assert_array_equal(csv['matrix_thin'], reference['intensity'])
        np.testing.assert_array_equal(csv['nominal_thin'], reference['nominal_intensity'])
        data = json.loads(backend.export('fixture', 'json').payload)
        self.assertEqual(data['origin']['opacity_diagnostic_kind'], 'per-line-center')
        self.assertEqual(len(data['opacity']['tau']), len(data['origin']['line_diagnostics']))
        self.assertEqual(data['opacity']['beta'], [row['SA'] for row in data['origin']['line_diagnostics']])
        self.assertTrue(any(row['stark_reference_temperature_K'] is None for row in data['origin']['line_diagnostics']))
        png = backend.export('fixture', 'png').payload
        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))


if __name__ == '__main__':
    unittest.main()
