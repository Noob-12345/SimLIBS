"""SpectrumCanvas —— 终端半块像素光谱画布。

每个终端单元用 '▀'（U+2580）呈现上下两个"像素"：上半像素=前景色、下半=背景色，
分辨率约为 内容宽 × 2×内容高。交互对齐 Web 版三键约定：
- 左键拖动：框选放大（x/y 同时）；
- 中键拖动：平移（终端里也可用 ←/→）；
- 右键单击 / R：复位；
- 滚轮：以光标为中心缩放 x。
密集数据按"列内 min–max"绘制（保峰，不丢窄尖峰）；稀疏数据用 Bresenham 连线。
"""
from __future__ import annotations

import math

from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseScrollDown, MouseScrollUp, MouseUp
from textual.widget import Widget

HALF = '▀'
LEFT_M = 9          # 左边距（y 轴刻度）
RIGHT_M = 1         # 右边距
BOTTOM_M = 1        # 底行（x 轴刻度）


def _nice_step(span: float) -> float:
    raw = span / 4
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _fmt(v: float) -> str:
    if v == 0:
        return '0'
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        s = f'{v:.2e}'            # 1.23e+05 → 1.23e5
        return s.replace('e+', 'e').replace('e-', 'e-').replace('e0', 'e').replace('e-0', 'e-')
    return f'{v:.4g}'


class SpectrumCanvas(Widget):
    DEFAULT_CSS = """
    SpectrumCanvas { width: 1fr; height: 1fr; overflow: hidden; }
    """
    BINDINGS = [
        ('left', 'pan(-1)', '左移'),
        ('right', 'pan(1)', '右移'),
        ('=', 'zoom_in', '放大'),
        ('-', 'zoom_out', '缩小'),
        ('r', 'reset', '复位'),
    ]

    def __init__(self, palette: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.palette = dict(palette)
        self.watermark: str = ''          # 例如 "示意预览 · 尚未运行（非真实数据）"
        self.empty_text: str = '尚未运行 · 运行后显示真实光谱'
        self._series: list[dict] = []     # {label,xs,ys,dotted}
        self._colors: list[str] = []
        self._version = 0
        self._x0 = self._x1 = 0.0         # 视窗（数据坐标）
        self._y0 = self._y1 = None        # None=自动
        self._buf: list[int] = []
        self._buf_key: tuple = ()
        self._dmin = self._dmax = 0.0     # 数据 x 范围
        self._sel: tuple | None = None    # (c0, r0, c1, r1) 单元坐标
        self._sel_anchor: tuple | None = None
        self._drag_mode = ''              # '' | 'sel' | 'pan'
        self._pan_anchor: tuple | None = None
        self._pan_view: tuple | None = None
        self._hover: tuple | None = None  # (c, r)
        self._down_cell: tuple | None = None

    # ------------------------------------------------------------------ 数据
    def set_series(self, series: list[dict], reset_view: bool = True) -> None:
        """series: [{label, xs, ys, color='#ef4444', dotted=False}]；空列表=清空。"""
        clean, colors = [], []
        for s in series or []:
            xs, ys = s.get('xs') or [], s.get('ys') or []
            if not xs or not ys or len(xs) != len(ys):
                continue
            clean.append({'label': s.get('label', ''), 'xs': list(xs), 'ys': list(ys),
                          'dotted': bool(s.get('dotted'))})
            colors.append(s.get('color') or self.palette['accent'])
        self._series, self._colors = clean, colors
        self._version += 1
        self._sel = None
        if clean:
            all_x = [x for s in clean for x in (s['xs'][0], s['xs'][-1])]
            self._dmin, self._dmax = min(all_x), max(all_x)
            if reset_view or not (self._dmin <= self._x0 < self._x1 <= self._dmax):
                self.reset_view()
        else:
            self._dmin = self._dmax = 0.0
            self._x0 = self._x1 = 0.0
            self._y0 = self._y1 = None
        self._buf_key = ()
        self.refresh()

    def reset_view(self) -> None:
        if self._series:
            self._x0, self._x1 = self._dmin, self._dmax
        else:
            self._x0 = self._x1 = 0.0
        self._y0 = self._y1 = None
        self._sel = None
        self._buf_key = ()
        self.refresh()

    # ------------------------------------------------------------------ 几何
    def _geom(self) -> tuple[int, int, int, int]:
        w = max(0, self.content_size.width)
        h = max(0, self.content_size.height)
        pw = w - LEFT_M - RIGHT_M
        ph = max(0, (h - BOTTOM_M)) * 2
        return w, h, pw, ph

    def _x_to_col(self, x: float, pw: int) -> float:
        if self._x1 <= self._x0:
            return LEFT_M
        return LEFT_M + (x - self._x0) / (self._x1 - self._x0) * (pw - 1)

    def _col_to_x(self, c: float, pw: int) -> float:
        if pw <= 1 or self._x1 <= self._x0:
            return self._x0
        return self._x0 + (c - LEFT_M) / (pw - 1) * (self._x1 - self._x0)

    def _y_range(self) -> tuple[float, float]:
        if self._y0 is not None and self._y1 is not None and self._y1 > self._y0:
            return self._y0, self._y1
        lo = hi = None
        for s in self._series:
            for x, y in zip(s['xs'], s['ys']):
                if self._x0 <= x <= self._x1:
                    if lo is None or y < lo:
                        lo = y
                    if hi is None or y > hi:
                        hi = y
        if lo is None:
            lo, hi = 0.0, 1.0
        pad = (hi - lo) * 0.06 if hi - lo > 1e-300 else abs(hi) * 0.05 + 1e-300
        return lo - pad, hi + pad

    def _v_to_row(self, v: float, ylo: float, yhi: float, ph: int) -> float:
        return (yhi - v) / (yhi - ylo) * (ph - 1)

    def _row_to_v(self, r: float, ylo: float, yhi: float, ph: int) -> float:
        return yhi - r / (ph - 1) * (yhi - ylo)

    # ------------------------------------------------------------------ 缓冲
    def _build_buf(self, pw: int, ph: int) -> list[int]:
        key = (pw, ph, self._version, round(self._x0, 9), round(self._x1, 9), self._y0, self._y1)
        if self._buf_key == key and self._buf:
            return self._buf
        buf = [0] * (pw * ph)
        span = self._x1 - self._x0
        ylo, yhi = self._y_range()
        for si, s in enumerate(self._series):
            cid = si + 1
            pts = [(x, y) for x, y in zip(s['xs'], s['ys'])
                   if self._x0 - span * 0.01 <= x <= self._x1 + span * 0.01]
            if not pts:
                continue

            def put(c: int, r: int) -> None:
                if 0 <= c < pw and 0 <= r < ph and buf[c * ph + r] == 0:
                    buf[c * ph + r] = cid

            def line(c0f: float, r0f: float, c1f: float, r1f: float, dash: bool) -> None:
                c0, r0, c1, r1 = round(c0f), round(r0f), round(c1f), round(r1f)
                dx, dy = abs(c1 - c0), -abs(r1 - r0)
                sx, sy = (1 if c0 < c1 else -1), (1 if r0 < r1 else -1)
                err = dx + dy
                while True:
                    if not (dash and c0 % 2):
                        put(c0, r0)
                    if c0 == c1 and r0 == r1:
                        break
                    e2 = 2 * err
                    if e2 >= dy:
                        err += dy
                        c0 += sx
                    if e2 <= dx:
                        err += dx
                        r0 += sy

            if len(pts) > 2 * pw:      # 密集：列内 min–max（保峰）
                col_min: dict[int, float] = {}
                col_max: dict[int, float] = {}
                for x, y in pts:
                    c = round(self._x_to_col(x, pw))
                    r = self._v_to_row(y, ylo, yhi, ph)
                    if c in col_min:
                        col_min[c] = min(col_min[c], r)
                        col_max[c] = max(col_max[c], r)
                    else:
                        col_min[c] = col_max[c] = r
                for c, rmin in sorted(col_min.items()):
                    if s['dotted'] and c % 2:
                        continue
                    rmax = col_max[c]
                    for r in range(int(min(rmin, rmax)), int(max(rmin, rmax)) + 1):
                        put(c, r)
            else:                       # 稀疏：Bresenham 连线
                prev = None
                for x, y in pts:
                    cur = (self._x_to_col(x, pw), self._v_to_row(y, ylo, yhi, ph))
                    if prev is None:
                        put(round(cur[0]), round(cur[1]))
                    else:
                        line(prev[0], prev[1], cur[0], cur[1], s['dotted'])
                    prev = cur
        self._buf, self._buf_key = buf, key
        return buf

    # ------------------------------------------------------------------ 渲染
    def render(self) -> Text:
        p = self.palette
        w, h, pw, ph = self._geom()
        if not self._series or pw <= 8 or ph <= 8 or h < 4:
            line = f"{(max(0, w - len(self.empty_text))) // 2 * ' '}{self.empty_text}"
            return Text(line[:w] if w else '', style=f'{p["muted"]} on {p["bg"]}')
        ylo, yhi = self._y_range()
        buf = self._build_buf(pw, ph)
        grid_rows = {round(f * (ph - 1)) for f in (0.25, 0.5, 0.75)}
        xticks = self._xticks(pw)
        sel = self._sel

        def in_sel(c: int, r: int) -> bool:
            if not sel:
                return False
            return (min(sel[0], sel[2]) <= c <= max(sel[0], sel[2])
                    and min(sel[1], sel[3]) <= r <= max(sel[1], sel[3]))

        bg, brd, brd_h = p['bg'], p['brd'], p['brd-hover']
        grid = [[[ ' ', None, bg] for _ in range(w)] for _ in range(h)]

        def put_cell(r: int, c: int, char: str, fg: str | None, bgc: str | None) -> None:
            if 0 <= r < h and 0 <= c < w:
                grid[r][c] = [char, fg, bgc]

        # y 轴标签（左边距）
        ylab = {0: _fmt(yhi)[:LEFT_M - 1], max(0, h - 2): _fmt(ylo)[:LEFT_M - 1],
                (h - 1) // 2: 'a.u.'}
        for r, lab in ylab.items():
            for i, ch in enumerate(f'{lab:<{LEFT_M}}'):
                put_cell(r, i, ch, p['muted'], bg)
        # x 轴标签（底行）
        for c in range(LEFT_M, LEFT_M + pw):
            put_cell(h - 1, c, xticks.get(c, ' '), p['muted'], bg)
        for i, ch in enumerate('λ/nm'):
            if LEFT_M + pw + i < w:
                put_cell(h - 1, LEFT_M + pw + i, ch, p['muted'], bg)
        # 数据像素
        for c in range(pw):
            for pr in range(ph // 2):
                top = buf[c * ph + pr * 2]
                bot = buf[c * ph + pr * 2 + 1] if pr * 2 + 1 < ph else 0
                r = pr
                fgc = self._colors[top - 1] if top else None
                bgc = self._colors[bot - 1] if bot else None
                char = HALF if (fgc or bgc) else ' '
                if not fgc and not bgc:      # 网格点
                    if pr * 2 in grid_rows or pr * 2 + 1 in grid_rows:
                        bgc = brd
                    elif c in xticks:
                        bgc = brd
                else:
                    bgc = bgc or bg
                if in_sel(c, r):
                    if fgc:
                        fgc = p['accent2']
                    elif bot:
                        bgc = p['accent2']
                    else:
                        bgc = brd_h
                put_cell(r, LEFT_M + c, char, fgc, bgc)
        # 浮层：右上角 悬停读数 / 框选 Δλ / 水印
        msg, mstyle = '', ''
        if self._drag_mode == 'sel' and self._sel:
            c0, _, c1, _ = self._sel
            xa, xb = sorted((self._col_to_x(c0, pw), self._col_to_x(c1, pw)))
            msg, mstyle = f'Δλ {abs(xb - xa):.4g} nm', f'{p["accent2"]} on {bg}'
        elif self._hover and self._x1 > self._x0:
            hc, hr = self._hover
            if LEFT_M <= hc < LEFT_M + pw and hr < h - 1:
                x = self._col_to_x(hc, pw)
                v = self._row_to_v(hr * 2 + 1, ylo, yhi, ph)
                msg, mstyle = f'{x:.4g} nm · {_fmt(v)}', f'{p["muted"]} on {bg}'
        if not msg and self.watermark:
            msg, mstyle = self.watermark, f'{p["warn"]} on {bg}'
        if msg:
            start = max(LEFT_M + 1, w - RIGHT_M - len(msg))
            for i, ch in enumerate(msg):
                put_cell(0, start + i, ch, p['text'] if 'warn' not in mstyle else p['warn'], bg)

        # 合成
        out = Text()
        for r in range(h):
            if r:
                out.append('\n')
            row = grid[r]
            run, run_style, run_fg = [], None, None
            for c in range(w):
                char, fg, bgc = row[c]
                style = (fg or '') + (f' on {bgc}' if bgc else '')
                if run and style != run_style:
                    out.append(''.join(run), style=run_style)
                    run = []
                run_style = style
                run.append(char)
            if run:
                out.append(''.join(run), style=run_style)
        return out

    def _xticks(self, pw: int) -> dict[int, str]:
        if self._x1 <= self._x0:
            return {}
        step = _nice_step(self._x1 - self._x0)
        first = math.ceil(self._x0 / step) * step
        out: dict[int, str] = {}
        for k in range(64):
            x = first + k * step
            if x > self._x1:
                break
            c = round(self._x_to_col(x, pw))
            label = _fmt(x)
            if LEFT_M <= c < LEFT_M + pw - len(label):
                out[c] = label
        return out

    # ------------------------------------------------------------------ 交互
    def on_mouse_down(self, event: MouseDown) -> None:
        self._down_cell = (event.x, event.y)
        if event.button == 'left':
            self._drag_mode = 'sel'
            self._sel_anchor = (event.x, event.y)
            self._sel = (event.x, event.y, event.x, event.y)
            self.capture_mouse(event)
        elif event.button == 'middle':
            self._drag_mode = 'pan'
            self._pan_anchor = (event.x, event.y)
            self._pan_view = (self._x0, self._x1)
            self.capture_mouse(event)
        self.refresh()

    def on_mouse_move(self, event: MouseMove) -> None:
        _, _, pw, _ = self._geom()
        cell = (event.x, event.y)
        if self._drag_mode == 'sel' and self._sel_anchor:
            ax, ay = self._sel_anchor
            self._sel = (ax, ay, event.x, event.y)
        elif self._drag_mode == 'pan' and self._pan_anchor and self._pan_view:
            dx = event.x - self._pan_anchor[0]
            x0, x1 = self._pan_view
            if pw > 1 and x1 > x0:
                span = x1 - x0
                shift = -dx / (pw - 1) * span
                new0, new1 = x0 + shift, x1 + shift
                if new0 < self._dmin:
                    new0, new1 = self._dmin, self._dmin + span
                if new1 > self._dmax:
                    new0, new1 = self._dmax - span, self._dmax
                self._x0, self._x1 = new0, new1
                self._buf_key = ()
        else:
            if cell != self._hover:
                self._hover = cell
                self.refresh()
            return
        self._hover = cell
        self.refresh()

    def on_mouse_up(self, event: MouseUp) -> None:
        if event.button == 'left' and self._drag_mode == 'sel':
            sel, self._drag_mode, self._sel = self._sel, '', None
            if sel and abs(sel[2] - sel[0]) >= 3 and abs(sel[3] - sel[1]) >= 2:
                self._apply_box(sel)
        elif event.button == 'middle':
            self._drag_mode = ''
        elif event.button == 'right':
            moved = bool(self._down_cell
                         and abs(event.x - self._down_cell[0]) + abs(event.y - self._down_cell[1]) > 2)
            if not moved:
                self.reset_view()
        self._down_cell = None
        self._pan_anchor = None
        self.refresh()

    def _apply_box(self, sel: tuple) -> None:
        c0, r0, c1, r1 = sel
        _, _, pw, ph = self._geom()
        if pw < 2 or ph < 2 or self._x1 <= self._x0:
            return
        ylo, yhi = self._y_range()
        xa, xb = sorted((self._col_to_x(c0, pw), self._col_to_x(c1, pw)))
        va, vb = sorted((self._row_to_v(r0 * 2, ylo, yhi, ph), self._row_to_v(r1 * 2, ylo, yhi, ph)))
        if xb - xa > (self._x1 - self._x0) * 1e-9 and vb - va > 1e-300:
            self._x0, self._x1 = xa, xb
            self._y0, self._y1 = va, vb
            self._buf_key = ()
        self.refresh()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        self._zoom(event.x, 1.25)

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        self._zoom(event.x, 0.8)

    def _zoom(self, col: float, factor: float) -> None:
        if self._x1 <= self._x0:
            return
        _, _, pw, _ = self._geom()
        if pw < 2:
            return
        focus = self._col_to_x(max(LEFT_M, min(col, LEFT_M + pw - 1)), pw)
        full = self._dmax - self._dmin
        span = min((self._x1 - self._x0) * factor, full)
        frac = (focus - self._x0) / (self._x1 - self._x0)
        new0 = focus - frac * span
        new0 = min(max(new0, self._dmin), self._dmax - span)
        new1 = new0 + span
        if new1 > new0:
            self._x0, self._x1 = new0, new1
            self._buf_key = ()
            self.refresh()

    def action_pan(self, direction: float) -> None:
        if self._x1 <= self._x0:
            return
        span = self._x1 - self._x0
        shift = span * 0.1 * direction
        new0, new1 = self._x0 + shift, self._x1 + shift
        if new0 < self._dmin:
            new0, new1 = self._dmin, self._dmin + span
        if new1 > self._dmax:
            new0, new1 = self._dmax - span, self._dmax
        self._x0, self._x1 = new0, new1
        self._buf_key = ()
        self.refresh()

    def action_zoom_in(self) -> None:
        self._zoom_center(0.67)

    def action_zoom_out(self) -> None:
        self._zoom_center(1.5)

    def _zoom_center(self, factor: float) -> None:
        if self._x1 <= self._x0:
            return
        self._zoom(LEFT_M + (self._geom()[2] - 1) / 2, factor)

    def action_reset(self) -> None:
        self.reset_view()
