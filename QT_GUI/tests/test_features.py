"""五个新功能的测试：元素补全、改名、计算方式、滑块同步、打包。"""
import os
import sys
import unittest
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLI_ROOT))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
os.environ.setdefault('SIMLIBS_WEB_BACKEND', 'mock')

import simlibs_cli.backend  # noqa: F401,E402  (注入 UI/web 路径，backend_api 可导入)

import pandas as pd  # noqa: E402



def fake_dataset(tmp: Path, n: int = 5) -> Path:
    rows = []
    for i in range(n):
        h = max(0.0, 100.0 - 20.0 * i)
        rows.append({'650.0': 1.0 + i, '650.5': 2.0 + i, '651.0': 0.5 + i,
                     'H': h, 'He': 100.0 - h,
                     'name': f's{i}', 'Te[eV]': 1.0 + 0.1 * i, 'Ne[cm^-3]': 1e17})
    ds = tmp / 'dataset.csv'
    pd.DataFrame(rows).to_csv(ds, index=False)
    return ds


class TestQtFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from simlibs_qt.app import MainWindow
        cls.app = QApplication.instance() or QApplication([])
        cls.win = MainWindow(fade_ms=0)
        cls.win.show()
        import time
        end = time.time() + 2.0
        while time.time() < end:
            cls.app.processEvents()
            time.sleep(0.01)

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win.deleteLater()
        cls.app.processEvents()

    def pump(self, seconds=0.3):
        import time
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_f3_batch_page_renamed(self):
        from simlibs_qt.app import PAGES
        self.assertIn(('batch', '批量模拟'), PAGES)
        self.assertEqual(self.win._nav_buttons['batch'].text(), '批量模拟')

    def test_f4_computation_mode_options(self):
        labels = [self.win.s_mode.itemText(i) for i in range(self.win.s_mode.count())]
        self.assertEqual(len(labels), 3)
        self.assertIn('本地模拟', labels[0])
        self.assertIn('服务器计算', labels[1])
        self.assertIn('客户端计算', labels[2])
        # 强度尺度：Photon/Energy 可选；本地模式禁用并固定 Photon
        self.assertEqual(self.win.s_scale.count(), 2)
        self.assertIn('Photon', self.win.s_scale.itemText(0))
        self.assertIn('Energy', self.win.s_scale.itemText(1))
        self.assertFalse(self.win.s_scale.isEnabled(), '本地模式下强度尺度应禁用并固定 Photon')
        self.assertEqual(self.win.s_charge.text(), '2')

    def test_f2_element_completer_and_canonicalization(self):
        row = self.win._comp_rows[0]
        el_in = row['el']
        completer = el_in.completer()
        self.assertIsNotNone(completer, '元素输入框应有自动补全')
        # fe → Fe
        self.assertEqual(self.win._canonical_element('fe'), 'Fe')
        self.assertEqual(self.win._canonical_element('hE'), 'He')
        self.assertEqual(self.win._canonical_element('Xx'), 'Xx')   # 无匹配保持原样

    def test_f5_slider_syncs_with_input(self):
        w = self.win
        # 找到滑块：Te 行内 QSlider
        from PySide6.QtWidgets import QSlider
        sliders = w.pages['single'].findChildren(QSlider)
        self.assertGreaterEqual(len(sliders), 3, 'Te/Ne/R 三个滑块')
        te_slider, ne_slider, r_slider = sliders[0], sliders[1], sliders[2]
        # 滑块 → 输入框（先移到与初始值不同的位置）
        te_slider.setValue(500)   # 0.5 + 0.5*9.5 = 5.25
        self.assertAlmostEqual(float(w.s_te.text()), 5.25, places=2)
        ne_slider.setValue(200)   # 1e15
        self.assertEqual(w.s_ne.text(), '1e15')
        ne_slider.setValue(600)   # 1e17
        self.assertEqual(w.s_ne.text(), '1e17')
        r_slider.setValue(300)    # 对数映射：100×200^0.3 ≈ 490
        self.assertAlmostEqual(float(w.s_r.text()), round(100 * 200 ** 0.3), delta=1)
        # 输入框 → 滑块（editingFinished）
        w.s_te.setText('2.0')
        w.s_te.editingFinished.emit()
        self.assertAlmostEqual(te_slider.value(), round((2.0 - 0.5) / 9.5 * 1000), delta=2)
        w.s_ne.setText('1e18')
        w.s_ne.editingFinished.emit()
        self.assertAlmostEqual(ne_slider.value(), 800, delta=2)

    def test_toast_stacking_and_frame(self):
        from simlibs_qt.widgets import Toast, ToastHost
        host = ToastHost(self.win)
        host.show('第一条', timeout=60000)
        self.pump(0.15)
        host.show('第二条', timeout=60000)
        self.pump(0.15)
        host.show('第三条', timeout=60000)
        self.pump(0.4)
        self.assertEqual(len(host._active), 3)
        # QFrame 卡片：有边框样式（对象名匹配 QSS）
        self.assertEqual(host._active[0].objectName(), 'Toast')
        self.assertTrue(isinstance(host._active[0], Toast))
        # 三条互不遮挡：y 坐标严格递减且留有间距
        ys = sorted(t.y() + t.height() for t in host._active)
        rects = [(t.y(), t.y() + t.height()) for t in host._active]
        rects.sort()
        for (top1, bot1), (top2, _bot2) in zip(rects, rects[1:]):
            self.assertGreaterEqual(top2 - bot1, ToastHost.GAP - 2, 'toast 之间不得重叠')
        for t in host._active:
            t.fade_out()
        self.pump(0.4)

    def test_chart_border_complete(self):
        w = self.win
        chart = w.s_chart
        self.assertAlmostEqual(chart.fig.patch.get_alpha(), 0.0, '画布应透明以透出圆角卡片')
        spines = list(chart.ax.spines.values())
        self.assertTrue(all(s.get_visible() for s in spines), '四条边线应可见（完整边框）')
        self.pump(0.2)

    def test_brand_icon_and_github(self):
        w = self.win
        self.assertFalse(w.windowIcon().isNull(), 'graduation.jpg 应作为窗口图标')
        self.assertIn('SimLIBS', w.brand.text())
        self.assertIn('SPECTRUM WORKBENCH FOR SCNU', w.brand.text())
        self.assertTrue((CLI_ROOT / 'assets' / 'github.svg').is_file())

    def test_f6_batch_v2_and_training_package(self):
        w = self.win
        self.pump(0.5)
        w.s_mode.setCurrentIndex(1)
        w.b_mode.setCurrentIndex(1)
        w.b_resample.setChecked(True)
        w.batch_use_current()
        w.pk_size.setText('3')
        # 服务器模式 + NIST 展宽 + 未勾选统一重采样 → 启动前拦截（后端不应被调用）
        w.b_resample.setChecked(False)
        calls = []

        class _Blocked(Exception):
            pass

        def blocked(req):
            calls.append(req)
            raise _Blocked('拦截测试')
        orig_start = w.backend.start_batch
        w.backend.start_batch = blocked
        try:
            w.start_batch()
            self.pump(0.3)
            self.assertEqual(len(calls), 0, '拦截生效时不应调用 backend.start_batch')
        finally:
            w.backend.start_batch = orig_start
        # 勾选后放行；请求携带 batch_size
        w.b_resample.setChecked(True)
        captured = {}
        w.backend.start_batch = lambda req: (captured.__setitem__('req', req) or orig_start(req))
        try:
            w.start_batch()
            self.pump(0.5)
            self.assertIn('req', captured)
            self.assertEqual(captured['req'].batch_size, 3)
            for _ in range(300):
                self.pump(0.2)
                if w._batch_result:
                    break
            self.assertIsNotNone(w._batch_result)
        finally:
            w.backend.start_batch = orig_start
        # MOCK 无训练包 → 按钮禁用 + 下载走 unavailable 分支不崩
        package = w._batch_result.get('training_package') or {}
        self.assertFalse(package.get('available'))
        self.assertFalse(w.pk_btn.isEnabled())
        w.download_training()
        self.pump(0.3)

    def test_lazy_scan_frames(self):
        w = self.win
        lazy = {'kind': 'scan', 'axis': 'te', 'unit': ' eV', 'lazy_frames': True,
                'job_id': 'testjob', 'intensity_scale': 'photon', 'params_summary': '测试',
                'frames': [{'value': 1.0, 'loaded': False}, {'value': 2.0, 'loaded': False}]}
        w._scan_result = lazy
        w._scan_job_id = 'testjob'
        w._scan_cache = {}
        w._scan_fetching = set()
        w._frame_idx = 0
        calls = []
        orig_get = w.backend.get_result

        def fake_get(jid, frame=None):
            calls.append(frame)
            return {'xs': [650.0, 651.0, 652.0], 'ys': [1.0, 2.0, 1.0]}

        w.backend.get_result = fake_get
        try:
            w.render_frame()
            self.pump(0.6)
            self.assertEqual([c for c in calls if c is not None], [0], '懒帧应按帧请求')
            self.assertIn(0, w._scan_cache)
            self.assertGreater(len(w.sc_chart._series), 0, '懒帧加载后应绘制')
            self.assertIn('帧 1/2', str(w.sc_frame_label.text()))
            w.next_frame()
            self.pump(0.6)
            self.assertEqual([c for c in calls if c is not None], [0, 1])
        finally:
            w.backend.get_result = orig_get
        w._scan_result = None
        w.set_playing(False)


if __name__ == '__main__':
    unittest.main()
