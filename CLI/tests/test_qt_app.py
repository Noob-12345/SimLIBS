"""Qt 桌面版 App 级测试（offscreen 渲染 + MOCK 引擎，离线跑通）。"""
import os
import sys
import time
import unittest
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLI_ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
os.environ.setdefault('SIMLIBS_WEB_BACKEND', 'mock')


class QtCase(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from simlibs_qt.app import MainWindow
        self.app = QApplication.instance() or QApplication([])
        if not hasattr(self.app, '_qt_tests_made'):
            self.app._qt_tests_made = 0
        self.app._qt_tests_made += 1
        self.win = MainWindow(fade_ms=0)
        self.win.show()
        self.pump(0.3)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self.app.processEvents()

    def pump(self, cond=None, timeout_s: float = 30):
        if isinstance(cond, (int, float)):     # pump(0.3) = 只泵事件 0.3 秒
            cond, timeout_s = None, cond
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            for _ in range(20):
                self.app.processEvents()
                time.sleep(0.005)
            if cond is None or cond():
                return
        self.fail(f'条件 {getattr(cond, "__name__", cond)} 在 {timeout_s}s 内未满足')

    def text_of(self, label) -> str:
        return label.text()


class TestQtApp(QtCase):

    def test_mount_navigation_theme(self):
        w = self.win
        self.assertEqual(w.stack.currentWidget(), w.pages['single'])
        for pid in ('batch', 'scan', 'jobs', 'settings', 'single'):
            w.go(pid)
            self.pump(lambda p=pid: w.stack.currentWidget() is w.pages[pid])
        w.toggle_theme()
        self.pump(lambda: w.theme_name.endswith('light'))
        w.toggle_theme()
        self.pump(lambda: w.theme_name.endswith('dark'))

    def test_composition_validation_intercepts(self):
        w = self.win
        self.assertIn('✓', self.text_of(w.sum_label))
        w._comp_rows[0]['pct'].setText('37')
        self.pump(lambda: '✗' in self.text_of(w.sum_label))
        before = len(w.backend.list_jobs())
        w.start_single()
        self.assertEqual(len(w.backend.list_jobs()), before, '总和≠100% 必须在启动前拦截')
        w.s_te.setText('abc')
        w.start_single()
        self.assertEqual(len(w.backend.list_jobs()), before)
        w.preset_h()
        self.pump(lambda: '✓' in self.text_of(w.sum_label))

    def test_mock_single_end_to_end(self):
        w = self.win
        self.pump(0.5)
        w.start_single()
        self.pump(lambda: w._single_result is not None, timeout_s=40)
        self.assertEqual(len(w.s_chart._series), 1, '图表应显示主谱')
        self.assertIn('MOCK', self.text_of(w.s_meta))
        w.s_view.setCurrentIndex(1)   # 原始谱视图
        self.pump(lambda: 'raw' in str(w.s_legend.text()) or w.s_view.currentIndex() == 1)

    def test_mock_scan_playback(self):
        w = self.win
        w.go('scan')
        self.pump(0.3)
        w.start_scan()
        self.pump(lambda: w._scan_result is not None, timeout_s=60)
        self.assertGreaterEqual(len(w._scan_result['frames']), 2)
        first = w._frame_idx
        self.pump(lambda: w._frame_idx != first, timeout_s=5)  # 自动播放前进
        w.set_playing(False)
        before = w._frame_idx
        w.next_frame()
        self.assertEqual(w._frame_idx, min(before + 1, len(w._scan_result['frames']) - 1))
        self.assertIn('帧', self.text_of(w.sc_frame_label))

    def test_mock_batch(self):
        w = self.win
        w.go('batch')
        self.pump(0.3)
        w.start_batch()   # 候选池为空 → 拦截
        self.assertIsNone(w._batch_result)
        w.batch_use_current()
        self.assertEqual(len(w._batch_pool), 1)
        w.s_resample.setChecked(True)   # 服务器模式 NIST 展宽批量须统一重采样（web 同规则）
        w.start_batch()
        self.pump(lambda: w._batch_result is not None, timeout_s=60)
        self.assertIn('批量完成', self.text_of(w.b_meta))

    def test_export(self):
        import tempfile
        w = self.win
        self.pump(0.5)
        w.start_single()
        self.pump(lambda: w._single_result is not None, timeout_s=40)
        with tempfile.TemporaryDirectory() as td:
            done = {}
            w.do_export(w._single_result, ['csv', 'json'], td)
            self.pump(lambda: len(list(Path(td).rglob('*'))) >= 2, timeout_s=30)
            names = {f.suffix for f in Path(td).rglob('*') if f.is_file()}
            self.assertIn('.csv', names)
            self.assertIn('.json', names)
            done['ok'] = True


if __name__ == '__main__':
    unittest.main()
