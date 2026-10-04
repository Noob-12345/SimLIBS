"""SpectrumCanvas 渲染与交互的离线单元测试（不连 NIST）。"""
import asyncio
import unittest

from textual.app import App, ComposeResult
from textual.containers import Vertical

from simlibs_cli.spectrum_canvas import SpectrumCanvas
from simlibs_cli.theme import DARK, canvas_palette

PAL = canvas_palette(DARK)


def spectrum(n=2000, spike=True):
    xs = [400 + 200 * i / (n - 1) for i in range(n)]
    ys = []
    for x in xs:
        v = 0.05 + 0.5 * ((x % 37) < 1.0)          # 规则小峰
        if spike and 499.9 <= x <= 500.1:          # 单列窄尖峰（保峰检查）
            v = 10.0
        ys.append(v)
    return xs, ys


class Host(App):
    def compose(self) -> ComposeResult:
        with Vertical():
            yield SpectrumCanvas(PAL, id='c')

    def on_mount(self) -> None:
        self.query_one('#c').styles.height = '1fr'


def run(coro):
    return asyncio.run(coro)


class TestSpectrumCanvas(unittest.TestCase):

    def test_render_contains_line_and_axis(self):
        async def go():
            app = Host()
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                canvas = app.query_one('#c', SpectrumCanvas)
                xs, ys = spectrum()
                canvas.set_series([{'label': 'm', 'xs': xs, 'ys': ys, 'color': PAL['accent']}])
                await pilot.pause()
                lines = canvas.render().plain.split('\n')
                self.assertGreaterEqual(len(lines), 10)
                self.assertTrue(any('▀' in ln for ln in lines))       # 有数据像素
                self.assertIn('a.u.', text_of(canvas))                # y 轴单位
                self.assertIn('λ', lines[-1])                         # x 轴单位（窄终端可能截断）
                self.assertIn('400', lines[-1])                       # x 刻度
        run(go())

    def test_narrow_spike_preserved(self):
        """λ=500 的单列尖峰在列内 min–max 模式下不可丢失。"""
        async def go():
            app = Host()
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                canvas = app.query_one('#c', SpectrumCanvas)
                xs, ys = spectrum()
                canvas.set_series([{'label': 'm', 'xs': xs, 'ys': ys}])
                pw, ph = canvas._geom()[2], canvas._geom()[3]
                buf = canvas._build_buf(pw, ph)
                spike_col = round(canvas._x_to_col(500.0, pw))
                col_pixels = [buf[spike_col * ph + r] for r in range(ph)]
                self.assertTrue(any(col_pixels), '尖峰列必须画到缓冲')
                self.assertGreater(max(r for r, v in enumerate(col_pixels) if v),
                                   ph * 0.5, '尖峰应到达上半区（高值）')
        run(go())

    def test_zoom_pan_reset_math(self):
        async def go():
            app = Host()
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                canvas = app.query_one('#c', SpectrumCanvas)
                xs, ys = spectrum()
                canvas.set_series([{'label': 'm', 'xs': xs, 'ys': ys}])
                self.assertAlmostEqual(canvas._x0, 400)
                self.assertAlmostEqual(canvas._x1, 600)
                canvas._zoom(50, 0.5)
                self.assertLess(canvas._x1 - canvas._x0, 200)
                lo = canvas._x0
                canvas.action_pan(1)
                self.assertGreater(canvas._x0, lo)
                canvas.action_reset()
                self.assertAlmostEqual(canvas._x0, 400)
                self.assertAlmostEqual(canvas._x1, 600)
                self.assertIsNone(canvas._y0)
        run(go())

    def test_box_zoom_fixes_y(self):
        async def go():
            app = Host()
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                canvas = app.query_one('#c', SpectrumCanvas)
                xs, ys = spectrum()
                canvas.set_series([{'label': 'm', 'xs': xs, 'ys': ys}])
                canvas._apply_box((20, 2, 60, 6))
                self.assertIsNotNone(canvas._y0)      # 框选后 y 固定
                self.assertLess(canvas._x1 - canvas._x0, 200)
        run(go())

    def test_empty_state_and_watermark(self):
        async def go():
            app = Host()
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                canvas = app.query_one('#c', SpectrumCanvas)
                self.assertIn('尚未运行', text_of(canvas))
                canvas.watermark = '示意预览 · 非真实数据'
                xs, ys = spectrum(400, spike=False)
                canvas.set_series([{'label': '示意', 'xs': xs, 'ys': ys, 'dotted': True}])
                self.assertIn('示意预览 · 非真实数据', text_of(canvas))
        run(go())

    def test_multi_series_colors(self):
        async def go():
            app = Host()
            async with app.run_test(size=(100, 24)) as pilot:
                await pilot.pause()
                canvas = app.query_one('#c', SpectrumCanvas)
                xs, ys = spectrum(400, spike=False)
                canvas.set_series([
                    {'label': 'main', 'xs': xs, 'ys': ys, 'color': PAL['accent']},
                    {'label': 'H I', 'xs': xs, 'ys': [y * 0.5 for y in ys], 'color': PAL['ion']},
                ])
                styles = {str(s.style) for s in canvas.render().spans}
                self.assertTrue(any(PAL['accent'] in s for s in styles))
                self.assertTrue(any(PAL['ion'] in s for s in styles))
        run(go())


def text_of(widget) -> str:
    return widget.render().plain


if __name__ == '__main__':
    unittest.main()
