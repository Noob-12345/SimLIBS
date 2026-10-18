"""Captured Si II through the application adapter; every HTTP boundary is a fixture."""
from dataclasses import replace
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

from simlibs_ui.adapter import source_module
from simlibs_ui.advanced_nist import options, simulate, parse_stark_csv
from simlibs_ui.settings import Settings
from simlibs_ui.models import Parameters
from simlibs_ui.storage import save_result, read_manifest

FIXTURES = Path(__file__).parent/'fixtures'
NIST = (FIXTURES/'nist_si_634_638.html').read_bytes()
STARK = (FIXTURES/'starkb_si_ii_6347.html').read_bytes()
IDENTITY = (FIXTURES/'nist_si_ii_identity.tsv').read_bytes()


class Response:
    def __init__(self, body, url='fixture://captured', on_read=None):
        self.body, self.url, self.on_read = body, url, on_read
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def close(self): pass
    def raise_for_status(self): pass
    def iter_content(self, size):
        if self.on_read: self.on_read()
        yield self.body


class Provider:
    def __init__(self, duplicate=False): self.calls, self.duplicate = [], duplicate
    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if 'physics.nist.gov' in url: return Response(IDENTITY, url)
        action = kwargs.get('data', {}).get('action')
        if action == 'periodictable:datasets': body = '<table id="ion-datasets"><a href="/index.php/data/ion/35">Si II</a></table>'
        elif method == 'GET':
            body = '<select id="dataset"><option value="223">Si II, electron, method : SCP</option>'
            body += '<option value="224">Si II, electron, method : SCP</option>' if self.duplicate else ''
            body += '</select>'
        elif action == 'querypage:densities': body = '<select id="density"><option value="1e17">1e17</option></select>'
        elif action == 'querypage:transitions': body = '<select id="transition"><option value="all">All</option></select>'
        elif action == 'querypage:temperatures': body = '<select id="temperature"><option value="all">All</option></select>'
        elif action == 'querypage:query': return Response(STARK, url)
        else: raise AssertionError('Unexpected provider action: '+str(action))
        return Response(body.encode(), url)


class StarkAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.s = replace(Settings(), output=str(self.root))
        self.p = replace(Parameters(), webscraping='local', mode_version=2, broadening='local', broaden_convention='physics',
                         elements=('Si',), percentages=(100,), Te=1., Ne=1e17,
                         low_w=634.88, upper_w=634.90, max_ion_charge=1, broaden_grid_step=.001, step=.001).validated()
        self.raw = dict(model='nist', matrix=False, self_absorption=False)
        self.provider = Provider()
        self.environment = patch.dict(os.environ, {'SIMLIBS_TASK_DIR': str(self.root), 'SIMLIBS_STARK_CACHE_DIR': str(self.root/'cache')})
        self.environment.start(); self.addCleanup(self.environment.stop)
        source_module(self.s.source)
        self.core = importlib.import_module('simLIBS.nist_self_absorption')
        self.source = importlib.import_module('simLIBS.stark_b')

    def run_model(self, raw=None, p=None, provider=None, **kwargs):
        return simulate(p or self.p, self.s, self.raw if raw is None else raw,
                        request_get=lambda *a, **k: Response(NIST), request_stark=provider or self.provider, **kwargs)

    def backend(self, status='failed', path=None):
        web = str(Path(__file__).parents[1]/'web')
        if web not in sys.path: sys.path.insert(0, web)
        from real_backend import RealBackend
        backend = RealBackend.__new__(RealBackend)
        backend._lock, backend._settings = threading.Lock(), self.s
        job = dict(job_id='fixture', kind='高级模拟', status=status,
                   expected_result_path=str(self.root/'result'/'manifest.json'), events=[])
        if path: job.update(result_path=path, manifest=read_manifest(path))
        backend._jobs = {'fixture': job}
        return backend, job

    def test_config_strict_defaults_and_non_stark_ignores_unused(self):
        self.assertEqual(options(self.raw)['stark_source'], 'auto')
        for change in ({'stark_source':'guess'}, {'stark_allow_network':1}, {'stark_methods':[]},
                       {'stark_methods':['SCP','SCP']}, {'stark_methods':['other']}, {'stark_cache_dir':'C:/arbitrary'}):
            with self.subTest(change=change), self.assertRaises(ValueError): options(dict(self.raw, **change))
        self.assertEqual(options(dict(self.raw, stark_methods=['MSE','SCP']))['stark_methods'], ('MSE','SCP'))
        value = options(dict(self.raw, stark_broadening=False, stark_source='invalid', stark_allow_network=7, stark_methods=[]))
        self.assertEqual(value['stark_source'], 'local'); self.assertFalse(value['stark_allow_network'])

    def test_auto_sourced_stark_and_cache_repeat_without_provider_network(self):
        original = self.source.StarkBClient._request
        frames, origin = self.run_model()
        self.assertIs(self.source.StarkBClient._request, original)
        self.assertEqual(origin['paper_model']['stark_data']['stark_b_line_count'], 1)
        self.assertTrue(self.provider.calls)
        for _, _, call in self.provider.calls:
            self.assertIs(call['verify'], True); self.assertTrue(call['stream'])
            self.assertEqual(call['timeout'], (self.s.connect_timeout, self.s.read_timeout))
        def denied(*a, **k): raise AssertionError('provider network used during cache repeat')
        again, repeat = self.run_model(raw=dict(self.raw, stark_allow_network=False), provider=denied)
        np.testing.assert_array_equal(frames['raw'], again['raw'])
        self.assertEqual(repeat['stark_data_access']['requests'], [])
        self.assertTrue(all(row['cache_hit'] for row in repeat['stark_data_access']['snapshots']))
        self.assertEqual(repeat['stark_data_access']['cache_directory'], str((self.root/'cache').resolve()))

    def test_self_absorption_and_temperature_fit_with_sourced_diagnostics(self):
        for te in (1., 1.2):
            frames, origin = self.run_model(raw=dict(self.raw, self_absorption=True, density_mode='specified', number_density_cm3=1e16, path_length_m=.001), p=replace(self.p, Te=te))
            lines = json.loads((self.root/'advanced-lines.json').read_text(encoding='utf-8'))
            self.assertEqual(len(lines), 1); self.assertLess(lines[0]['SA'], 1.)
            self.assertEqual(lines[0]['stark_temperature_method'], 'published log10 fit')
            self.assertIsInstance(lines[0]['stark_temperature_range_k'], list)
            self.assertIsNone(lines[0]['stark_isolated_limit_cm3'])
            self.assertIn('nist_lower_id', lines[0]); self.assertIn('stark_snapshot_sha256', lines[0])

    def test_user_csv_and_builtin_priority_avoid_provider(self):
        _, _ = self.run_model()
        line = json.loads((self.root/'advanced-lines.json').read_text(encoding='utf-8'))[0]
        keys = ('element','charge','wavelength_nm','lower_eV','upper_eV','stark_width_nm','stark_reference_ne_cm3')
        csv = pd.DataFrame([dict({key:line[key] for key in keys}, source='TEST published user override')]).to_csv(index=False)
        def denied(*a, **k): raise AssertionError('provider used despite local coefficient')
        self.run_model(raw=dict(self.raw, stark_csv=csv), provider=denied)
        p = replace(self.p, elements=('Mg',), low_w=285.27, upper_w=285.33)
        mg = (FIXTURES/'nist_mg_280_290.html').read_bytes()
        simulate(p, self.s, self.raw, request_get=lambda *a, **k: Response(mg), request_stark=denied)

    def test_partial_missing_matched_report_and_editable_csv_roundtrip(self):
        p = replace(self.p, upper_w=637.33)
        with self.assertRaises(self.core.MissingStarkDataError) as raised: self.run_model(p=p)
        self.assertEqual(raised.exception.code, 'missing_stark')
        self.assertGreater(len(raised.exception.matched_lines), 0)
        missing = pd.read_csv(self.root/'missing-stark.csv', float_precision='round_trip')
        self.assertTrue(all(len(json.loads(value)) == 2 for value in missing.conditions))
        self.assertFalse(missing.duplicated(subset=['element','charge','wavelength_nm','lower_eV','upper_eV']).any())
        backend, job = self.backend()
        self.assertEqual(backend._job_view(job)['error_code'], 'missing_stark')
        self.assertGreater(backend._job_view(job)['stark_matched']['count'], 0)
        self.assertTrue(backend.export('fixture','stark-matched').payload)
        report = json.loads(backend.export('fixture','stark-report').payload)
        self.assertGreater(len(report['matched']), 0)
        missing['stark_width_nm'] = .002; missing['source'] = 'TEST ONLY supplemented coefficient'
        text = missing.to_csv(index=False)
        self.assertEqual(len(parse_stark_csv(text)), len(missing))
        self.run_model(p=p, raw=dict(self.raw, stark_csv=text))

    def test_network_and_source_format_errors_are_not_physical_missing(self):
        for provider, expected in ((lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError('offline')), 'stark_network'),
                                   (lambda *a, **k: Response(b'<h1>temporary service problem</h1>'), 'stark_service_format')):
            with self.subTest(expected=expected), self.assertRaises(self.source.StarkDataAccessError) as raised:
                self.run_model(provider=provider)
            self.assertEqual(raised.exception.code, expected)
            self.assertFalse((self.root/'missing-stark.csv').exists())
            backend, job = self.backend(); view = backend._job_view(job)
            self.assertEqual(view['error_code'], expected); self.assertNotIn('stark_missing', view)

    def test_offline_miss_corrupt_cache_and_cache_io_are_distinct(self):
        with self.assertRaises(self.source.StarkDataAccessError) as raised: self.run_model(raw=dict(self.raw, stark_allow_network=False))
        self.assertEqual(raised.exception.code, 'stark_cache_miss')
        self.run_model()
        file = next((self.root/'cache').glob('*.json'))
        corrupt = json.loads(file.read_text(encoding='utf-8')); corrupt['sha256'] = '0'*64
        file.write_text(json.dumps(corrupt), encoding='utf-8')
        with self.assertRaises(self.source.StarkDataAccessError) as raised: self.run_model()
        self.assertEqual(raised.exception.code, 'stark_cache_corrupt')
        with patch.object(self.source.SourceCache, 'get', side_effect=PermissionError('denied')):
            with self.assertRaises(self.source.StarkDataAccessError) as raised: self.run_model()
        self.assertEqual(raised.exception.code, 'stark_cache_io')

    def test_equal_priority_ambiguity_preserved(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous STARK-B') as raised: self.run_model(provider=Provider(duplicate=True))
        self.assertEqual(raised.exception.code, 'stark_ambiguous')
        self.assertFalse((self.root/'missing-stark.csv').exists())

    def test_cancellation_deadline_and_response_size_are_bounded(self):
        original = self.source.StarkBClient._request
        flag = [False]
        def interrupted(*a, **k): return Response(b'x', on_read=lambda:flag.__setitem__(0,True))
        with self.assertRaises(InterruptedError): self.run_model(provider=interrupted, cancelled=lambda:flag[0])
        self.assertIs(self.source.StarkBClient._request, original)
        now = [0.]
        def expired(*a, **k): return Response(b'x', on_read=lambda:now.__setitem__(0,1000.))
        with patch('simlibs_ui.advanced_stark.time.monotonic', side_effect=lambda:now[0]):
            with self.assertRaises(self.source.StarkDataAccessError) as raised: self.run_model(provider=expired)
        self.assertEqual(raised.exception.code, 'stark_timeout')
        with self.assertRaises(self.source.StarkDataAccessError) as raised: self.run_model(provider=lambda *a, **k:Response(b'x'*4_000_001))
        self.assertEqual(raised.exception.code, 'stark_response_size')

    def test_tls_failure_never_downgrades_verification_or_retries(self):
        calls = []
        def certificate_failure(*args, **kwargs):
            calls.append(kwargs)
            raise requests.exceptions.SSLError('certificate validation failed')
        with self.assertRaises(self.source.StarkDataAccessError) as raised: self.run_model(provider=certificate_failure)
        self.assertEqual(raised.exception.code, 'stark_network')
        self.assertEqual(len(calls), 1); self.assertIs(calls[0]['verify'], True)

    def test_transient_retry_and_stark_stage_progress_have_finite_bounds(self):
        attempts, events = [], []
        def transient(*args, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1: raise requests.ConnectTimeout('temporary fixture outage')
            return self.provider(*args, **kwargs)
        self.run_model(provider=transient, emit=lambda event, **data: events.append(data))
        self.assertEqual(len(attempts), len(self.provider.calls)+1)
        self.assertLess(len(attempts), 20)
        self.assertEqual([item['current'] for item in events], sorted(item['current'] for item in events))
        self.assertTrue(any(item['deadline'] > self.s.static_deadline for item in events if 'STARK-B' in item['message']))

    def test_json_csv_exports_keep_lists_null_sources_and_legacy_reader(self):
        frames, origin = self.run_model()
        path = save_result(self.root/'result', frames, origin)
        backend, job = self.backend('completed', path)
        data = json.loads(backend.export('fixture','json').payload)
        row = data['origin']['line_diagnostics'][0]
        self.assertIsInstance(row['stark_temperature_range_k'], list)
        self.assertIsNone(row['stark_isolated_limit_cm3'])
        self.assertIn('STARK-B', row['stark_source'])
        for kind in ('csv','diagnostics'): self.assertTrue(backend.export('fixture',kind).payload)
        (self.root/'advanced-lines.json').unlink()
        self.assertIn('line_diagnostics', backend._single_result(job,job['manifest'])['origin'])
        self.assertIsNone(backend._advanced_file(job, '../cache/secret.json'))

    def test_no_stark_skips_all_provider_and_identity_calls(self):
        def denied(*a, **k): raise AssertionError('Stark/identity called')
        self.run_model(raw=dict(self.raw, stark_broadening=False), provider=denied)

    def test_worker_keeps_typed_error_and_cooperative_cancel_events(self):
        from simlibs_ui import worker
        request = self.root/'request.json'
        request.write_text(json.dumps({'job_id':'typed-fixture'}), encoding='utf-8')
        (self.root/'go').touch()
        error = self.source.StarkDataAccessError('fixture cache unavailable'); error.code = 'stark_cache_miss'
        with patch.object(sys,'argv',['worker',str(request)]), patch.object(worker,'execute',side_effect=error):
            self.assertEqual(worker.main(), 1)
        self.assertEqual(json.loads((self.root/'error.json').read_text(encoding='utf-8'))['code'], 'stark_cache_miss')
        (self.root/'cancel').touch()
        with patch.object(sys,'argv',['worker',str(request)]), patch.object(worker,'execute',side_effect=InterruptedError('cancelled')):
            self.assertEqual(worker.main(), 0)
        events = [json.loads(line) for line in (self.root/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events[-1]['event'], 'cancelled')


if __name__ == '__main__': unittest.main()
