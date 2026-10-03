import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from simlibs_ui.settings import DEFAULT_PYTHON, UI_ROOT


class CLITests(unittest.TestCase):
    def run_cli(self, *arguments):
        try:
            return subprocess.run([DEFAULT_PYTHON, '-B', str(UI_ROOT / 'run_ui.py'), *arguments], cwd=str(UI_ROOT.parent),
                                  capture_output=True, text=True, encoding='utf-8', timeout=60)
        except subprocess.TimeoutExpired:
            self.fail('CLI 未实现自动完成/关闭，60 秒内未结束')

    def test_diagnose_from_other_cwd_without_network(self):
        result = self.run_cli('--diagnose')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertFalse(data['network_used'])
        self.assertFalse(data['driver_downloaded'])
        self.assertTrue(all(data['dependencies'].values()))

    def test_actual_tk_smoke_history_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli('--smoke-test', '--output', directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = Path(directory) / 'smoke.json'
            self.assertTrue(report.exists(), '尚未执行真正的 Tk smoke')
            data = json.loads(report.read_text(encoding='utf-8'))
            self.assertTrue(data['tk_window_created'])
            self.assertEqual(data['pages'], 3)
            self.assertFalse(data['new_simulation'])
            self.assertGreater(data['heartbeats'], 5)
            for name in ['history.csv', 'history.png', 'history.json']:
                self.assertTrue((Path(directory) / name).exists())

    def test_windows_launchers_from_other_working_directory(self):
        commands = [ ['cmd', '/c', str(UI_ROOT/'start_ui.cmd'), '--diagnose'],
                     ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(UI_ROOT/'start_ui.ps1'), '--diagnose'] ]
        for command in commands:
            result = subprocess.run(command, cwd=str(UI_ROOT.parent), capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout.decode('utf-8', errors='replace')+result.stderr.decode('utf-8', errors='replace'))
            self.assertFalse(json.loads(result.stdout.decode('utf-8-sig'))['network_used'])

    def test_smoke_capture_targets_own_window(self):
        import tkinter as tk
        from unittest.mock import patch, Mock
        from simlibs_ui.app import capture_window
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.update()
        image = Mock()
        with patch('PIL.ImageGrab.grab', return_value=image) as grab:
            capture_window(root, 'unused.png')
        self.assertIn('window', grab.call_args.kwargs)
        self.assertNotIn('bbox', grab.call_args.kwargs)
        self.assertGreater(grab.call_args.kwargs['window'], 0)
        image.save.assert_called_once_with('unused.png')


if __name__ == '__main__':
    unittest.main()
