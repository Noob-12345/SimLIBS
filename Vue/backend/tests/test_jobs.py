from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from simlibs_ui.models import Parameters, ScanSpec
from simlibs_ui.settings import Settings

try:
    from simlibs_ui.jobs import JobController
except ImportError:
    JobController = None


def alive(pid):
    if sys.platform == 'win32':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        kernel.CloseHandle(ctypes.c_void_p(handle))
        return code.value == 259
    import os
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class JobTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(JobController, '后台任务行为尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = replace(Settings(), output=self.temp.name)
        self.job = JobController(self.settings, worker_module='tests.job_fixture')
        self.addCleanup(self.job.force_close)

    def finish(self, limit=5):
        deadline = time.monotonic() + limit
        while self.job.busy and time.monotonic() < deadline:
            self.job.poll()
            time.sleep(.01)
        self.assertFalse(self.job.busy)

    def test_validation_happens_before_spawn(self):
        with self.assertRaises(ValueError):
            self.job.start('single', parameters=replace(Parameters(), Ne=0).to_dict())
        self.assertIsNone(self.job.process)
        self.assertEqual(self.job.state, 'IDLE')

    def test_invalid_derived_scan_never_spawns_or_transports(self):
        for axis, values in [('Te', [1., float('nan')]), ('Ne', [1., float('inf')]), ('R', [1, 0])]:
            with self.subTest(axis=axis), patch('simlibs_ui.models.scan_values', return_value=values), \
                 patch('simlibs_ui.jobs.subprocess.Popen', side_effect=RuntimeError('SPAWN_SENTINEL')) as spawn, \
                 patch('requests.get') as get, self.assertRaises(ValueError):
                self.job.start('scan', parameters=Parameters().to_dict(), spec=asdict(ScanSpec(axis=axis, start=1, stop=2)))
            spawn.assert_not_called()
            get.assert_not_called()
            self.assertIsNone(self.job.process)
        for spec in [ScanSpec(axis='R', start=.1, stop=.4), ScanSpec(axis='Te', step=5e-324),
                     ScanSpec(axis='Ne', stop=float('inf'))]:
            with self.subTest(spec=spec), patch('simlibs_ui.jobs.subprocess.Popen') as spawn, \
                 patch('requests.get') as get, self.assertRaises(ValueError):
                self.job.start('scan', parameters=Parameters().to_dict(), spec=asdict(spec))
            spawn.assert_not_called()
            get.assert_not_called()

    def test_failure_retains_success_and_retry(self):
        self.job.start('fixture')
        self.finish()
        successful = self.job.last_result
        self.assertEqual(successful['value'], 7)
        self.job.start('fixture', error=True)
        self.finish()
        self.assertEqual(self.job.state, 'FAILED')
        self.assertEqual(self.job.last_result, successful)
        self.job.start('fixture')
        self.finish()
        self.assertEqual(self.job.state, 'SUCCEEDED')

    def test_corrupt_dynamic_worker_fails_without_success_manifest_and_keeps_result(self):
        import json
        self.job.worker_module = 'tests.mock_dynamic_worker'
        params = replace(Parameters(), webscraping='dynamic').to_dict()
        good = 'Wavelength (nm),H I\n650,0\n655,2\n660,0\n'
        self.job.start('single', parameters=params, csv=good)
        self.finish(limit=10)
        self.assertEqual(self.job.state, 'SUCCEEDED', self.job.error)
        prior = self.job.last_result
        prior_path = self.job.result_path
        for csv in ['Wavelength (nm),H I,Sum(calc)\n650,0,0\n,2,2\n660,0,0\n',
                    'Wavelength (nm),H I,Sum(calc)\n650,0,0\n655,2,NaN\n660,0,0\n']:
            with self.subTest(csv=csv):
                self.job.start('single', parameters=params, csv=csv)
                self.finish(limit=10)
                self.assertEqual(self.job.state, 'FAILED')
                self.assertEqual(self.job.last_result, prior)
                self.assertEqual(self.job.result_path, prior_path)
                self.assertFalse((self.job.directory/'result'/'manifest.json').exists())
                self.assertTrue((self.job.directory/'error.json').exists())
                self.assertEqual(json.loads((self.job.directory/'mock-browser.json').read_text(encoding='utf-8'))['quit_count'], 1)

    def test_nonblocking_poll_and_cancel_owned_tree_only(self):
        heartbeat = []
        poll_times = []
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        unrelated = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(15)'], creationflags=flags)
        def cleanup_unrelated():
            unrelated.terminate()
            unrelated.wait(timeout=5)
        self.addCleanup(cleanup_unrelated)
        self.job.start('fixture', delay=20, child=True)
        deadline = time.monotonic() + 3
        while not (self.job.directory / 'child.pid').exists() and time.monotonic() < deadline:
            heartbeat.append(time.monotonic())
            poll_start = time.monotonic()
            self.job.poll()
            poll_times.append(time.monotonic()-poll_start)
            time.sleep(.01)
        self.assertTrue((self.job.directory / 'child.pid').exists())
        child = int((self.job.directory / 'child.pid').read_text())
        self.assertTrue(alive(child))
        self.assertGreater(len(heartbeat), 2)
        self.assertLess(max(poll_times), .5, '轮询不能等待受控慢 worker 完成')
        start = time.monotonic()
        self.job.cancel()
        self.finish()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.job.state, 'CANCELLED')
        self.assertFalse(alive(child))
        self.assertIsNone(unrelated.poll())

    def test_deadline_stops_worker_and_late_messages_ignored(self):
        self.job.start('fixture', delay=20, deadline=.2)
        self.finish()
        self.assertEqual(self.job.state, 'FAILED')
        self.assertIn('超时', self.job.error)
        self.job.start('fixture', delay=.2)
        with (self.job.directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('{"job_id":"old","event":"success","path":"missing"}\n')
        self.finish()
        self.assertEqual(self.job.state, 'SUCCEEDED')
        self.assertEqual(self.job.last_result['value'], 7)


if __name__ == '__main__':
    unittest.main()
