"""backend / history 离线单元测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from simlibs_cli.backend import CliBackend, discover_python  # noqa: E402


class TestCliBackend(unittest.TestCase):

    def test_discover_python_fallback(self):
        # 两个候选路径不存在时回退当前解释器
        path = discover_python()
        self.assertTrue(Path(path).is_file(), f'回退解释器必须存在：{path}')

    def test_settings_loaded_with_fallback(self):
        b = CliBackend()
        s = b.get_settings()
        self.assertTrue(Path(s['python']).is_file(), '加载后的解释器必须存在（自动回退）')
        self.assertTrue(Path(s['source']).is_dir(), '源库路径必须有效')
        self.assertTrue((Path(s['source']) / 'simLIBS' / 'simulation.py').is_file())
        self.assertTrue(Path(s['output_dir']).is_dir(), '输出目录默认应已存在（UI/output）')
        self.assertTrue(b.settings_path().name == '.cli-settings.json')

    def test_protocol_forwarding(self):
        b = CliBackend()
        for name in ('api_version', 'default_params', 'list_jobs', 'engine_status'):
            self.assertTrue(callable(getattr(b, name)), f'缺少协议方法 {name}')
        self.assertEqual(b.api_version(), '1')

    def test_proxy_roundtrip(self):
        import os
        b = CliBackend()
        saved = b.get_proxy()
        try:
            b.set_proxy('http://127.0.0.1:7890')
            self.assertEqual(b.get_proxy(), 'http://127.0.0.1:7890')
            self.assertEqual(os.environ.get('HTTPS_PROXY'), 'http://127.0.0.1:7890')
            b.set_proxy('')
            self.assertEqual(b.get_proxy(), '')
            self.assertIsNone(os.environ.get('HTTPS_PROXY'))
        finally:
            b.set_proxy(saved)

    def test_save_settings_roundtrip(self):
        import tempfile
        b = CliBackend()
        with tempfile.TemporaryDirectory() as td:
            s = b.get_settings()
            s2 = b.save_settings({'connect_timeout': 12.0})
            self.assertEqual(s2['connect_timeout'], 12.0)
            # 恢复
            b.save_settings({'connect_timeout': s['connect_timeout']})


class TestHistory(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_simple_csv(self):
        from simlibs_cli.history import load_history
        p = self.dir / 'simple.csv'
        p.write_text('wavelength,intensity\n650,0\n650.1,3\n650.2,10\n650.3,3\n650.4,0\n',
                     encoding='utf-8')
        r = load_history(p)
        self.assertEqual(len(r['series']), 1)
        self.assertEqual(len(r['series'][0]['xs']), 5)
        self.assertIn('参数未知', r['meta']['params'])
        self.assertTrue(r['meta']['sha256'])

    def test_nist_csv_single_ion(self):
        from simlibs_cli.history import load_history
        p = self.dir / 'nist.csv'
        p.write_text('Wavelength (nm),H I\n656.1,100\n656.2,500\n656.3,1200\n656.4,400\n',
                     encoding='utf-8')
        r = load_history(p)
        # 单离子省略 Sum(calc) → 复制为总谱：H I 与 Sum(calc)
        labels = [s['label'] for s in r['series']]
        self.assertIn('H I', labels)

    def test_bad_file_rejected(self):
        from simlibs_cli.history import load_history
        p = self.dir / 'bad.csv'
        p.write_text('a,b\n1,2\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_history(p)
        with self.assertRaises(ValueError):
            load_history(self.dir / 'missing.csv')


if __name__ == '__main__':
    unittest.main()
