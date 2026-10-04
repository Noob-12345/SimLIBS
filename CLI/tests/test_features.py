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

from simlibs_cli.packing import pack_dataset  # noqa: E402


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


class TestPacking(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def test_basic_packing_reference_format(self):
        written = pack_dataset(fake_dataset(self.tmp, 5), self.tmp / 'out', batch_size=2)
        names = sorted(Path(p).name for p in written)
        self.assertEqual(names, ['Random_contents.csv', 'Random_contents_2.csv',
                                 'Random_contents_3.csv', 'Random_spectra.csv',
                                 'Random_spectra_2.csv', 'Random_spectra_3.csv'])
        lines = (self.tmp / 'out' / 'Random_spectra.csv').read_text().splitlines()
        self.assertEqual(len(lines), 4, '每条光谱两行 × 每包 2 条')
        row0 = lines[0].split(',')
        row1 = lines[1].split(',')
        self.assertEqual([float(v) for v in row0], [1.0, 2.0, 0.5])   # 强度行
        self.assertEqual([float(v) for v in row1], [650.0, 650.5, 651.0])  # 波长行
        ct = pd.read_csv(self.tmp / 'out' / 'Random_contents.csv')
        self.assertEqual(list(ct.columns), ['H', 'He'])
        self.assertEqual(len(ct), 2)

    def test_continues_incomplete_batch(self):
        out = self.tmp / 'out'
        pack_dataset(fake_dataset(self.tmp, 1), out, batch_size=3)      # batch1: 1/3
        pack_dataset(fake_dataset(self.tmp, 3), out, batch_size=3)      # 补 2 条 → 满，再开新批
        self.assertEqual(len((out / 'Random_spectra.csv').read_text().splitlines()), 6)
        self.assertEqual(len((out / 'Random_spectra_2.csv').read_text().splitlines()), 2)
        # 续写时沿用已有表头并补零
        ct = pd.read_csv(out / 'Random_contents_2.csv')
        self.assertEqual(list(ct.columns), ['H', 'He'])

    def test_rejects_invalid(self):
        from simlibs_cli.packing import pack_dataset as pack
        with self.assertRaises(ValueError):
            pack(fake_dataset(self.tmp), self.tmp / 'o', batch_size=0)
        bad = self.tmp / 'bad.csv'
        bad.write_text('name\nabc\n')
        with self.assertRaises(ValueError):
            pack(bad, self.tmp / 'o')


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
        self.assertEqual(len(labels), 2)
        self.assertIn('服务器计算', labels[0])
        self.assertIn('客户端计算', labels[1])

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

    def test_popcat_icon(self):
        w = self.win
        gif = CLI_ROOT / 'assets' / 'popcat.gif'
        if not gif.is_file():
            self.skipTest('assets/popcat.gif 未下载')
        self.assertIsNotNone(getattr(w, '_popcat_movie', None), 'popcat 动画应已加载')
        self.assertGreaterEqual(w._popcat_movie.frameCount(), 2, '至少两帧（张嘴/闭嘴）')
        self.assertFalse(w.windowIcon().isNull())

    def test_f6_pack_after_batch(self):
        import tempfile
        w = self.win
        self.pump(0.5)
        w.batch_use_current()
        w.start_batch()
        for _ in range(300):
            self.pump(0.2)
            if w._batch_result:
                break
        self.assertIsNotNone(w._batch_result)
        w.pk_size.setText('3')
        # MOCK 引擎不支持 dataset 导出 → 打桩为真实数据集格式（打包逻辑另有单测）
        from backend_api import ExportPayload
        ds = fake_dataset(Path(tempfile.gettempdir()), n=8)
        orig_export = w.backend.export
        w.backend.export = lambda jid, kind, frame=None: ExportPayload(
            ds.read_text(encoding='utf-8'), 'text/csv; charset=utf-8', 'dataset.csv')
        try:
            with tempfile.TemporaryDirectory() as td:
                w.b_export_dir.setText(td)
                w.pack_batches()
                for _ in range(200):
                    self.pump(0.2)
                    files = list(Path(td).glob('Random_*.csv'))
                    if files:
                        break
                self.assertTrue(files, '打包应产出 Random_* 文件')
                names = {f.name for f in files}
                self.assertTrue(any('spectra' in n for n in names))
                self.assertTrue(any('contents' in n for n in names))
                # 每包样本数生效：spectra 行数 = 2×每包样本数
                spectra = next(f for f in files if 'spectra' in f.name and '_2' not in f.name)
                lines = spectra.read_text().splitlines()
                self.assertEqual(len(lines), 2 * 3)
        finally:
            w.backend.export = orig_export


if __name__ == '__main__':
    unittest.main()
