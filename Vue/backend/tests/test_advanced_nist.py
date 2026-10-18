"""Real math with a captured NIST response; transport is isolated, never an online claim."""
from dataclasses import replace
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import requests

from simlibs_ui.advanced import effective, options, simulate
from simlibs_ui.advanced_nist import parse_stark_csv, simulate as nist_simulate
from simlibs_ui.adapter import source_module
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings
from simlibs_ui.storage import read_manifest, save_result

HTML = (Path(__file__).parent/'fixtures/nist_mg_280_290.html').read_bytes()


class Response:
    def __init__(self, content=HTML): self.content = content
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size):
        for i in range(0, len(self.content), size): yield self.content[i:i+size]


def parameters(**kw):
    return replace(Parameters(), **dict(dict(webscraping='local', mode_version=2, broadening='local',
        broaden_convention='physics', elements=('Mg',), percentages=(100,), low_w=285.27, upper_w=285.33,
        broaden_grid_step=.001, step=.001), **kw)).validated()


class AdvancedNISTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = replace(Settings(), output=str(self.root), line_database=str(self.root/'missing-library'))
        self.raw = {'model': 'nist', 'matrix': False}
        source_module(self.s.source)
        self.engine = importlib.import_module('simLIBS.nist_self_absorption')
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response()

    def run_model(self, p=None, raw=None, **kwargs):
        with patch.dict(os.environ, {'SIMLIBS_TASK_DIR': str(self.root)}):
            return nist_simulate(p or parameters(), self.s, self.raw if raw is None else raw, request_get=self.fetch, **kwargs)

    def full_stark(self):
        rows = self.engine.parse_atomic_payload(HTML.decode())['transitions']
        # Deliberately synthetic coefficients, test fixture only.
        return pd.DataFrame([dict(r, stark_width_nm=.002, stark_reference_ne_cm3=1e16, source='TEST ONLY') for r in rows]).to_csv(index=False)

    def backend(self):
        web = str(Path(__file__).resolve().parents[1]/'web')
        if web not in sys.path: sys.path.insert(0, web)
        from real_backend import RealBackend
        backend = RealBackend.__new__(RealBackend)
        backend._settings, backend._settings_path, backend._lock = self.s, self.root/'settings.json', threading.Lock()
        backend._jobs = {}
        return backend

    def test_source_modules_are_byte_identical_and_regular_source_untouched(self):
        original = Path(__file__).resolve().parents[3]/'simLIBS-2.0.3/simLIBS'
        for name in ('nist_lines.py', 'nist_self_absorption.py'):
            self.assertEqual((Path(self.s.source)/'simLIBS'/name).read_bytes(), (original/name).read_bytes())

    def test_narrow_builtin_math_and_deduplicated_http(self):
        frames, origin = self.run_model()
        self.assertEqual(origin['model_version'], 'nist-lines-self-absorption-1')
        self.assertEqual(origin['parameters']['webscraping'], 'client')
        self.assertEqual(origin['parameters']['broaden_convention'], 'nist')
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.calls[0][1]['verify'])
        self.assertIn('int_scale=2', self.calls[0][0])
        self.assertEqual(origin['bands'][0]['response_sha256'], hashlib.sha256(HTML).hexdigest())
        self.assertGreater(len(frames['raw']), 2)
        np.testing.assert_allclose(frames['ion'].drop(columns=['Wavelength (nm)', 'Sum(calc)']).sum(axis=1), frames['raw'].intensity)
        lines = pd.read_csv(origin['line_table'])
        self.assertGreater(len(lines), 0)
        self.assertTrue((lines.SA <= 1).all())
        self.assertIn('charge_balance', origin['paper_model']['density_mode'])

    def test_zero_path_and_disabled_absorption_are_same_voigt_thin(self):
        for extra in ({'path_length_m': 0}, {'self_absorption': False}):
            frames, origin = self.run_model(raw=dict(self.raw, **extra))
            thin = pd.read_csv(origin['thin_reference'], float_precision='round_trip')
            np.testing.assert_array_equal(frames['raw'].intensity, thin.intensity)

    def test_r_does_not_change_tau_and_instrument_uses_nist_width(self):
        _, origin = self.run_model(p=parameters(resolution=1000))
        first = pd.read_csv(origin['line_table'])
        _, origin = self.run_model(p=parameters(resolution=5000))
        second = pd.read_csv(origin['line_table'])
        np.testing.assert_array_equal(first.tau_center, second.tau_center)
        np.testing.assert_array_equal(first.SA, second.SA)
        np.testing.assert_allclose(first.instrument_sigma_nm, first.wavelength_nm/1000/np.sqrt(2))

    def test_canonical_numeric_requests_reuse_int_float_conditions(self):
        self.run_model(p=replace(parameters(), percentages=(100,)))
        self.assertEqual(len(self.calls), 1)

    def test_specified_density_and_zero_yield_validation(self):
        _, origin = self.run_model(raw=dict(self.raw, density_mode='specified', number_density_cm3=3e15))
        self.assertEqual(origin['paper_model']['density_mode'], 'specified_total')
        self.assertEqual(origin['matrix']['effective_number_density_cm3'], 3e15)
        with self.assertRaisesRegex(ValueError, '全为零'):
            effective(parameters(), dict(self.raw, matrix=True, responses={'Mg': 0}))

    def test_input_grid_and_empty_wavelength_window_errors_are_explicit(self):
        with self.assertRaisesRegex(ValueError, '200000'):
            nist_simulate(replace(parameters(), broaden_grid_step=1e-10), self.s, self.raw, request_get=self.fetch)
        with self.assertRaisesRegex(ValueError, '未找到非零'):
            self.run_model(p=parameters(low_w=279, upper_w=279.1))

    def test_cooperative_cancel_after_first_response_never_renders(self):
        with self.assertRaises(InterruptedError):
            self.run_model(cancelled=lambda: bool(self.calls))
        self.assertFalse((self.root/'advanced-reference.csv').exists())

    def test_matrix_fetches_nominal_and_effective_conditions_and_scales_yield(self):
        _, origin = self.run_model(raw=dict(self.raw, matrix=True, te_factor=1.1, ne_factor=1.2, responses={'Mg': .7}))
        self.assertEqual(len(self.calls), 2)
        self.assertNotEqual(self.calls[0][0], self.calls[1][0])
        self.assertAlmostEqual(origin['matrix']['effective_Te_eV'], 1.1)
        line = pd.read_csv(origin['line_table'])
        np.testing.assert_allclose(line.nist_strength, line.nist_strength_original*.7)
        self.assertEqual(origin['matrix']['yield_scale'], .7)

    def test_missing_csv_full_precision_fill_upload_and_recompute(self):
        with self.assertRaises(self.engine.MissingStarkDataError) as raised:
            self.run_model(p=parameters(low_w=280, upper_w=290, broaden_grid_step=.01))
        missing = self.root/'missing-stark.csv'
        table = pd.read_csv(missing, float_precision='round_trip')
        self.assertGreater(len(table), 8)
        metadata = json.loads((self.root/'missing-stark.json').read_text())
        self.assertEqual(metadata['count'], len(table))
        self.assertEqual(len(raised.exception.missing_lines), len(table))
        table['stark_width_nm'] = .002
        text = '\ufeff'+table.to_csv(index=False)
        frames, origin = self.run_model(p=parameters(low_w=280, upper_w=290, broaden_grid_step=.01), raw=dict(self.raw, stark_csv=text))
        self.assertGreater(len(frames['raw']), 0)
        self.assertEqual(origin['stark_input']['rows'], len(table))
        self.assertEqual(origin['diagnostics']['line_count'], 20)

    def test_csv_validation_and_ambiguous_coefficients(self):
        valid = 'element,charge,wavelength_nm,stark_width_nm\nMg,0,285.2963529978273,.002\n'
        self.assertEqual(len(parse_stark_csv(valid)), 1)
        for text in (valid.replace('Mg,0', 'Unknown,0'), valid.replace(',0,', ',.5,'), valid.replace(',.002', ',nan'),
                     valid.replace(',.002', ',0'), valid.replace('285.2963529978273', ''), valid+'bad', 'x'*2_000_001):
            with self.subTest(text=text[:50]), self.assertRaises(ValueError): parse_stark_csv(text)
        rows = pd.read_csv(io.StringIO(self.full_stark()))
        duplicate = pd.concat([rows, rows], ignore_index=True).to_csv(index=False)
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.run_model(p=parameters(low_w=280, upper_w=290, broaden_grid_step=.01), raw=dict(self.raw, stark_csv=duplicate))

    def test_no_five_percent_or_element_gate_in_nist_but_legacy_preserved(self):
        p = parameters(elements=('Fe',), low_w=200, upper_w=500, broaden_grid_step=.1)
        effective(p, self.raw)
        with self.assertRaisesRegex(ValueError, 'Stark'): effective(p, {})
        self.assertEqual(options({})['path_length_m'], .01)
        self.assertNotIn('model', options({}))
        with self.assertRaises(ValueError): options({'path_length_m': 0})
        with self.assertRaises(ValueError): options({'model': 'nist', 'density_mode': 'invalid'})

    def test_cancellation_network_failure_response_size_and_progress(self):
        progress = []
        self.run_model(emit=lambda event, **data: progress.append(data['current']))
        self.assertEqual(progress, sorted(progress))
        with self.assertRaises(InterruptedError): self.run_model(cancelled=lambda: True)
        with patch('simlibs_ui.advanced_nist.requests.get', side_effect=requests.ConnectionError('offline')), patch('simlibs_ui.advanced_nist.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'NIST请求失败'):
                nist_simulate(parameters(), self.s, self.raw)
        with self.assertRaisesRegex(ValueError, '安全大小'):
            nist_simulate(parameters(), self.s, self.raw, request_get=lambda *a, **k: Response(b'X'*4_000_001))

    def test_api_missing_download_roundtrip_restore_and_job_binding(self):
        from simlibs_ui.worker import execute
        backend = self.backend()
        body = {'params': {'te': 1, 'ne': 1e17, 'resolution': 1000, 'low_w': 280, 'up_w': 290,
            'max_ion_charge': 2, 'mode': 'local', 'mode_version': 2, 'broadening': 'local',
            'broaden_convention': 'physics', 'broaden_grid_step': .01}, 'composition': [{'el': 'Mg', 'pct': 100}], 'advanced': self.raw}
        captured = {}
        with patch.object(backend, '_launch', side_effect=lambda *args: captured.update(args=args) or 'a'*32):
            self.assertEqual(backend.start_advanced(body), 'a'*32)
        payload = captured['args'][2]
        jobroot = self.root/'.jobs'/('a'*32); jobroot.mkdir(parents=True)
        with patch.dict(os.environ, {'SIMLIBS_TASK_DIR': str(jobroot)}), patch('simlibs_ui.advanced_nist.requests.get', side_effect=self.fetch):
            with self.assertRaises(self.engine.MissingStarkDataError):
                execute(dict(payload, kind='advanced', settings=self.s.to_dict(), directory=str(jobroot)), lambda *a, **k: None, lambda: False)
        job = {'job_id': 'a'*32, 'kind': '高级模拟', 'status': 'failed', 'expected_result_path': str(jobroot/'result/manifest.json'), 'events': []}
        backend._jobs = {'a'*32: job}
        self.assertGreater(backend.get_job('a'*32)['stark_missing']['count'], 8)
        self.assertNotIn('wavelength_nm', json.dumps(backend.get_job('a'*32)))
        download = backend.export('a'*32, 'stark-missing').payload
        self.assertEqual(download, (jobroot/'missing-stark.csv').read_bytes())
        backend._persist_session()
        restored = self.backend(); restored._restore_session()
        self.assertEqual(restored.export('a'*32, 'stark-missing').payload, download)
        # An unrelated job cannot request this job's diagnostic by supplying a path.
        backend._jobs['b'*32] = dict(job, kind='单次模拟')
        from backend_api import ApiError
        with self.assertRaises(ApiError): backend.export('b'*32, 'stark-missing')

    def test_success_exports_and_earliest_history_are_defensive(self):
        frames, origin = self.run_model()
        path = save_result(self.root/'result', frames, origin)
        backend = self.backend(); backend._jobs = {'success': {'status': 'completed', 'result_path': path, 'manifest': read_manifest(path)}}
        self.assertIn('nominal_thin', backend.export('success', 'csv').payload)
        self.assertIn(b'tau_center', backend.export('success', 'diagnostics').payload)
        self.assertEqual(json.loads(backend.export('success', 'json').payload)['origin']['model_version'], 'nist-lines-self-absorption-1')
        self.assertTrue(backend.export('success', 'png').payload.startswith(b'\x89PNG'))
        legacy = dict(origin); [legacy.pop(k, None) for k in ('line_table', 'thin_reference', 'opacity_table')]
        oldpath = save_result(self.root/'old/result', frames, legacy)
        backend._jobs['old'] = {'status': 'completed', 'result_path': oldpath, 'manifest': read_manifest(oldpath)}
        self.assertNotIn('comparison', backend.get_result('old'))
        json.loads(backend.export('old', 'json').payload)

    def test_http_submit_missing_download_fill_resubmit_and_exports(self):
        import importlib.util
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from simlibs_ui.worker import execute
        backend = self.backend()
        counter = []
        def launch(kind, task_kind, payload, summary):
            jid = f'{len(counter)+1:032x}'; counter.append(jid)
            directory = self.root/'.jobs'/jid; directory.mkdir(parents=True)
            job = {'job_id': jid, 'kind': kind, 'status': 'running', 'summary': summary, 'progress': 0,
                   'events': [], 'expected_result_path': str(directory/'result/manifest.json')}
            backend._jobs[jid] = job
            try:
                with patch.dict(os.environ, {'SIMLIBS_TASK_DIR': str(directory)}):
                    path = execute(dict(payload, kind=task_kind, settings=self.s.to_dict(), directory=str(directory)), lambda *a, **k: None, lambda: False)
                job.update(status='completed', progress=100, result_path=path, manifest=read_manifest(path))
            except self.engine.MissingStarkDataError as error:
                job.update(status='failed', error=str(error))
            return jid
        spec = importlib.util.spec_from_file_location('advanced_nist_http', Path(__file__).resolve().parents[1]/'web/server.py')
        with patch.dict(os.environ, {'SIMLIBS_SESSION_TOKEN': 'test-nist-token'}), patch('real_backend.RealBackend', return_value=backend):
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        server = ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        def http(path, data=None, token='test-nist-token'):
            body = json.dumps(data).encode() if data is not None else None
            req = Request(base+path, body, {'Content-Type': 'application/json', 'X-SimLIBS-Token': token})
            with urlopen(req, timeout=15) as response: return response.read()
        body = {'params': {'te': 1, 'ne': 1e17, 'resolution': 1000, 'low_w': 280, 'up_w': 290,
            'max_ion_charge': 2, 'mode': 'local', 'mode_version': 2, 'broadening': 'local',
            'broaden_convention': 'physics', 'broaden_grid_step': .01}, 'composition': [{'el': 'Mg', 'pct': 100}], 'advanced': self.raw}
        with patch.object(backend, '_launch', side_effect=launch), patch('simlibs_ui.advanced_nist.requests.get', side_effect=self.fetch):
            failed = json.loads(http('/api/simulate/advanced', body))['job_id']
            view = json.loads(http('/api/jobs/'+failed))
            self.assertEqual(view['status'], 'failed'); self.assertGreater(view['stark_missing']['count'], 8)
            csv = http('/api/jobs/'+failed+'/export?kind=stark-missing')
            filled = pd.read_csv(io.BytesIO(csv), float_precision='round_trip'); filled['stark_width_nm'] = .002
            body['advanced'] = dict(self.raw, stark_csv=filled.to_csv(index=False), stark_name='filled.csv')
            success = json.loads(http('/api/simulate/advanced', body))['job_id']
            self.assertNotEqual(failed, success)
            data = json.loads(http('/api/jobs/'+success+'/result'))
            self.assertEqual(len(data['origin']['line_diagnostics']), 20)
            self.assertIn(b'tau_center', http('/api/jobs/'+success+'/export?kind=diagnostics'))
            self.assertTrue(http('/api/jobs/'+success+'/export?kind=png').startswith(b'\x89PNG'))
            self.assertIn(b'nominal_thin', http('/api/jobs/'+success+'/export?kind=csv'))
            json.loads(http('/api/jobs/'+success+'/export?kind=json'))
            self.assertEqual(http('/api/jobs/'+failed+'/export?kind=stark-missing'), csv)
            with self.assertRaises(HTTPError): http('/api/jobs/'+failed+'/export?kind=stark-missing', token='invalid')
            # UI evidence contains actual engine arrays from captured-response math, explicitly marked as a fixture.
            target = Path(__file__).resolve().parents[2]/'.ai-workflow/20261016-advanced-nist/ui-result.json'
            target.write_text(json.dumps({'test_fixture': True, 'result': data}, ensure_ascii=False, allow_nan=False), encoding='utf-8')


if __name__ == '__main__': unittest.main()
