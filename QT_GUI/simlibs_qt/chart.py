"""SpectrumChart —— matplotlib 嵌入图表，交互对齐 Web 版设计：
左键拖动框选放大（x/y）、中键/Shift+左键平移、右键单击复位、滚轮以光标为中心缩放 x。
大数据按保峰抽样（复用 UI/web/sampling.sample_indices，预算 6000 点）。
新结果可带"画入"动画：曲线从左向右扫描出现（约 450ms，OutCubic）。
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer

WEB_DIR = Path(__file__).resolve().parents[2] / 'UI' / 'web'
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import matplotlib
matplotlib.use('qtagg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402


def sample_series(xs, ys, budget=6000):
    """保峰抽样：窄尖峰不丢失；峰谷数超预算时降级为均匀抽样（不丢前置数据）。"""
    if len(xs) <= budget:
        return np.asarray(xs, float), np.asarray(ys, float)
    from sampling import sample_indices
    try:
        idx = sample_indices(np.asarray(xs, float), np.asarray(ys, float), budget)
    except ValueError:
        n = len(xs)
        step = max(1, n // budget)
        idx = np.arange(0, n, step)
        if idx[-1] != n - 1:
            idx = np.append(idx, n - 1)
    return np.asarray(xs, float)[idx], np.asarray(ys, float)[idx]


class SpectrumChart(FigureCanvasQTAgg):
    def __init__(self, palette: dict, parent=None) -> None:
        self._pal = dict(palette)
        self.fig = Figure(figsize=(5, 3), dpi=100, constrained_layout=True)
        super().__init__(self.fig)
        if parent is not None:
            self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self._series: list[dict] = []      # {label, xs, ys, color, dotted}
        self._x0 = self._x1 = 0.0
        self._y0 = self._y1 = None         # None=自动
        self._dmin = self._dmax = 0.0
        self._mode = ''                    # '' | 'zoom' | 'pan'
        self._anchor = None                # (x, y) 数据坐标
        self._moved = False
        self._band: Rectangle | None = None   # 框选橡皮筋选框
        self._reveal = 1.0                 # 画入动画进度（1=完整）
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(16)
        self._reveal_timer.timeout.connect(self._tick_reveal)
        self.mpl_connect('button_press_event', self._on_press)
        self.mpl_connect('motion_notify_event', self._on_motion)
        self.mpl_connect('button_release_event', self._on_release)
        self.mpl_connect('scroll_event', self._on_scroll)
        self.setMinimumHeight(160)
        self._draw_empty()

    # ------------------------------------------------------------------ 数据
    def set_palette(self, palette: dict) -> None:
        self._pal = dict(palette)
        if self._series:
            self.redraw()
        else:
            self._draw_empty()

    def set_series(self, series: list[dict], reset_view: bool = True,
                   animate: bool = False) -> None:
        clean = []
        for s in series or []:
            xs, ys = s.get('xs') or [], s.get('ys') or []
            if not xs or not ys or len(xs) != len(ys):
                continue
            clean.append({'label': s.get('label', ''), 'xs': xs, 'ys': ys,
                          'color': s.get('color') or self._pal['accent'],
                          'dotted': bool(s.get('dotted'))})
        self._series = clean
        if clean:
            all_x = [x for s in clean for x in (np.min(s['xs']), np.max(s['xs']))]
            self._dmin, self._dmax = float(min(all_x)), float(max(all_x))
            if reset_view or not (self._dmin <= self._x0 < self._x1 <= self._dmax):
                self.reset_view()
        else:
            self._dmin = self._dmax = 0.0
            self._x0 = self._x1 = 0.0
            self._y0 = self._y1 = None
            self._reveal_timer.stop()
            self._reveal = 1.0
            self._draw_empty()
            return
        if animate and self._reveal_timer and not self._reveal_timer.isActive():
            self._start_reveal()
        else:
            self._reveal = 1.0
        self.redraw()

    def _start_reveal(self, duration_ms: int = 450) -> None:
        self._reveal = 0.0
        self._reveal_t0 = time.monotonic()
        self._reveal_ms = duration_ms
        self._reveal_timer.start()

    def _tick_reveal(self) -> None:
        t = (time.monotonic() - self._reveal_t0) / (self._reveal_ms / 1000)
        if t >= 1.0:
            self._reveal = 1.0
            self._reveal_timer.stop()
        else:
            self._reveal = 1.0 - (1.0 - t) ** 3   # OutCubic
        self.redraw()

    def reset_view(self) -> None:
        if self._series:
            self._x0, self._x1 = self._dmin, self._dmax
        else:
            self._x0 = self._x1 = 0.0
        self._y0 = self._y1 = None
        self._reveal = 1.0
        self._reveal_timer.stop()
        if self._series:
            self.redraw()
        else:
            self._draw_empty()

    # ------------------------------------------------------------------ 绘制
    def _style_axes(self) -> None:
        p, ax = self._pal, self.ax
        # 画布透明：透出外层圆角卡片；坐标区背景同色
        self.fig.patch.set_alpha(0.0)
        self.setStyleSheet('background-color: transparent;')
        ax.set_facecolor('none')
        # 四条边线组成完整边框（之前隐藏导致边界"断开"）
        for side in ax.spines.values():
            side.set_visible(True)
            side.set_color(p['brd'])
            side.set_linewidth(0.9)
        ax.grid(True, color=p['brd'], linewidth=0.7, alpha=0.9)
        ax.tick_params(colors=p['muted'], labelsize=9)
        for lbl in ax.get_xticklabels() + ax.get_yticklabels():
            lbl.set_fontfamily(['Consolas', 'monospace'])
        ax.set_xlabel('λ / nm', color=p['muted'], fontsize=9)
        ax.set_ylabel('a.u.', color=p['muted'], fontsize=9)

    def _draw_empty(self) -> None:
        self.ax.clear()
        self._style_axes()
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.text(0.5, 0.5, '尚未运行 · 运行后显示真实光谱', transform=self.ax.transAxes,
                     ha='center', va='center', color=self._pal['muted'], fontsize=11)
        self.draw_idle()

    def redraw(self) -> None:
        if not self._series:
            self._draw_empty()
            return
        p, ax = self._pal, self.ax
        ax.clear()
        self._style_axes()
        x0, x1 = self._x0, self._x1
        pad = (x1 - x0) * 0.02
        ylo, yhi = self._y_range()
        for s in self._series:
            xs, ys = sample_series(s['xs'], s['ys'])
            style = ':' if s['dotted'] else '-'
            lw = 1.0 if s['dotted'] else 1.5
            ax.plot(xs, ys, style, color=s['color'], linewidth=lw,
                    label=s['label'] or None, dash_capstyle='round')
        if self._y0 is not None:
            ax.set_ylim(self._y0, self._y1)
        span = x1 - x0 + 2 * pad
        ax.set_xlim(x0 - pad, x0 - pad + span * max(1e-6, self._reveal))
        if self._mode == 'zoom' and self._band is not None:
            ax.add_patch(self._band)   # 拖拽中发生重绘（如滚轮缩放）时恢复选框
        self.draw_idle()

    def _y_range(self):
        if self._y0 is not None and self._y1 is not None and self._y1 > self._y0:
            return self._y0, self._y1
        lo = hi = None
        for s in self._series:
            arr_x, arr_y = np.asarray(s['xs'], float), np.asarray(s['ys'], float)
            mask = (arr_x >= self._x0) & (arr_x <= self._x1)
            if mask.any():
                v0, v1 = float(np.min(arr_y[mask])), float(np.max(arr_y[mask]))
                lo = v0 if lo is None else min(lo, v0)
                hi = v1 if hi is None else max(hi, v1)
        if lo is None:
            lo, hi = 0.0, 1.0
        pad = (hi - lo) * 0.08 if hi - lo > 1e-300 else abs(hi) * 0.05 + 1e-300
        return lo - pad, hi + pad

    # ------------------------------------------------------------------ 交互
    def _on_press(self, ev) -> None:
        if ev.xdata is None or not self._series:
            return
        if ev.button == 1:
            self._mode = 'zoom' if not (ev.key == 'shift') else 'pan'
        elif ev.button == 2:
            self._mode = 'pan'
        else:
            self._mode = ''
            return
        self._anchor = (ev.xdata, ev.ydata)
        self._moved = False
        if self._mode == 'zoom':
            self.ax.set_facecolor(self._pal['bg'])
            edge = to_rgba(self._pal['accent'], 0.9)
            fill = to_rgba(self._pal['accent'], 0.10)
            # 选框始终占满整个绘图区高度（x=数据坐标，y=坐标区比例 0..1）
            self._band = Rectangle((ev.xdata, 0), 0, 1, facecolor=fill,
                                   edgecolor=edge, linewidth=1.1, linestyle=(0, (4, 3)),
                                   zorder=5, transform=self.ax.get_xaxis_transform())
            self.ax.add_patch(self._band)

    def _on_motion(self, ev) -> None:
        if not self._mode or ev.xdata is None or self._anchor is None:
            return
        self._moved = True
        if self._mode == 'pan':
            dx = self._anchor[0] - ev.xdata
            span = self._x1 - self._x0
            new0 = self._x0 + dx
            new0 = min(max(new0, self._dmin), self._dmax - span)
            self._x0, self._x1 = new0, new0 + span
            self._anchor = (ev.xdata, ev.ydata)
            self.redraw()
        elif self._band is not None:   # zoom：全高选框随光标水平伸缩
            xa = self._anchor[0]
            self._band.set_xy((min(xa, ev.xdata), 0))
            self._band.set_width(abs(ev.xdata - xa))
            self.draw_idle()

    def _on_release(self, ev) -> None:
        if ev.button == 3 and not self._moved and not self._mode:
            self.reset_view()
            return
        if self._band is not None:
            try:
                self._band.remove()
            except (ValueError, RuntimeError):
                pass
            self._band = None
        if self._mode == 'zoom' and self._anchor and ev.xdata is not None:
            xa, xb = sorted((self._anchor[0], ev.xdata))
            span = self._x1 - self._x0
            if (xb - xa) > span * 1e-3:
                self._x0, self._x1 = xa, xb
                self._y0 = self._y1 = None   # y 轴按可见数据自适应（Web 同约定）
        self._mode, self._anchor, self._moved = '', None, False
        if self._series:
            self.redraw()

    def _on_scroll(self, ev) -> None:
        if ev.xdata is None or not self._series or self._x1 <= self._x0:
            return
        factor = 1.25 if ev.step < 0 else 0.8
        full = self._dmax - self._dmin
        span = min((self._x1 - self._x0) * factor, full)
        frac = (ev.xdata - self._x0) / (self._x1 - self._x0)
        new0 = min(max(ev.xdata - frac * span, self._dmin), self._dmax - span)
        self._x0, self._x1 = new0, new0 + span
        self.redraw()

    # ------------------------------------------------------------------ 视图查询
    def view_range(self):
        return self._x0, self._x1
