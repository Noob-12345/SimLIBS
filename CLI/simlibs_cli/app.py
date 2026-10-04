"""simLIBS Studio CLI —— Textual 终端应用。

复用 CliBackend（= UI/web/real_backend.RealBackend 进程内包装），五个页面：
单次模拟 / 批量 dataset / 扫描动画 / 任务记录 / 设置，外加全局任务栏（进度 + 日志）。
界面语言（黑红 Plasma Dark 主题、chip 徽章、toast、框选缩放）与 Web 版设计稿对齐；
真实引擎语义（配比 100%±1e-6、专属 worker 子进程、协作取消、来源证据）完全同源。
"""
from __future__ import annotations

import math
import threading
from datetime import datetime
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (Button, Checkbox, Collapsible, ContentSwitcher,
                            DataTable, Footer, Input, Label, ProgressBar,
                            RichLog, Select, Static, Switch)

from .backend import CLI_ROOT, create_backend
from .history import load_history
from .spectrum_canvas import SpectrumCanvas
from .theme import DARK, LIGHT, PLASMA_DARK, PLASMA_LIGHT, canvas_palette

PAGES = [
    ('page-single', '单次模拟', 'f2'),
    ('page-batch', '批量 dataset', 'f3'),
    ('page-scan', '扫描动画', 'f4'),
    ('page-jobs', '任务记录', 'f5'),
    ('page-settings', '设置', 'f6'),
]
PAGE_TITLES = {pid: label for pid, label, _ in PAGES}
ION_COLORS = ('ion', 'ion2', 'info', 'good')
SCAN_DEFAULTS = {'te': ('0.5', '5.0'), 'ne': ('-1', '1'), 'r': ('500', '5000')}
EXPORT_DIR = str(CLI_ROOT / 'output' / 'exports')


def _pal(theme_name: str) -> dict:
    return canvas_palette(DARK if theme_name.endswith('dark') else LIGHT)


class NavItem(Static):
    """侧边导航项（可点击，选中态高亮）。"""

    def __init__(self, page_id: str, label: str, key: str) -> None:
        super().__init__(label, id='nav-' + page_id.removeprefix('page-'), classes='nav-item')
        self.page_id = page_id
        self.tooltip = f'{label}（{key.upper()}）'

    def on_click(self) -> None:
        self.app.switch_page(self.page_id)


class SimlibsCLI(App):
    TITLE = 'simLIBS Studio · CLI'
    CSS = """
    Screen { background: $bg; }
    #shell { height: 1fr; }
    #sidebar { width: 30; background: $bg; padding: 1 0 1 1; }
    #brand { color: $accent; text-style: bold; padding: 0 0 1 0; }
    .nav-item { height: 3; padding: 1 0 0 2; color: $muted; background: $bg; }
    .nav-item:hover { color: $text; background: $card; }
    .nav-item.active { color: $accent; background: $card; border-left: thick $accent; text-style: bold; }
    #engine-card { margin-top: 1; border: round $brd; background: $card; padding: 1; color: $muted; }
    #main { height: 1fr; }
    #topbar { height: 3; padding: 0 1; background: $bg; }
    #page-title { color: $text; text-style: bold; width: 1fr; padding-top: 1; }
    .chip { height: 3; width: auto; padding: 0 1; border: round $brd; background: $card; color: $muted; }
    .chip.good { color: $good; } .chip.bad { color: $bad; }
    #theme-btn { width: auto; min-width: 5; margin-left: 1; }
    #pages { height: 1fr; }
    .page { height: 1fr; padding: 0 1 0 0; }
    .page-body { height: 1fr; }
    .panel { width: 48; min-width: 40; border: round $brd; background: $card; padding: 1; overflow-y: auto; }
    .right { width: 1fr; padding-left: 1; }
    .canvas-wrap { height: 1fr; border: round $brd; background: $card; }
    .legend { height: 1; color: $muted; padding: 0 1; }
    .meta { height: 2; color: $muted; padding: 0 1; }
    .field { height: 3; }
    .field Label { width: 15; padding-top: 1; color: $muted; }
    .field Input { width: 1fr; background: $input-bg; }
    .field Select { width: 1fr; }
    .hr { height: 1; color: $brd-hover; padding-top: 1; }
    .btnrow { height: auto; }
    .btnrow Button, .btnrow Checkbox { margin-right: 1; }
    .primary { background: $accent; color: #ffffff; text-style: bold; min-width: 12; }
    .primary:hover { background: $accent2; }
    .ghost { background: $card; border: tall $brd; color: $muted; }
    .ghost:hover { border: tall $brd-hover; color: $text; }
    .danger { background: $card; border: tall $bad; color: $bad; }
    .danger:hover { background: $bad; color: #ffffff; }
    .comp-row { height: 3; }
    .comp-row Input.el { width: 12; background: $input-bg; }
    .comp-row Input.pct { width: 1fr; background: $input-bg; }
    .comp-row Button { width: 5; min-width: 5; background: $card; border: tall $brd; color: $muted; }
    #s-comp-rows { height: auto; }
    #s-comp-sum { color: $muted; height: 1; padding-top: 1; }
    Collapsible { background: $card; border: none; padding: 0; height: auto; }
    Collapsible > Contents { padding: 0 0 0 1; }
    #taskbar { height: 10; border-top: tall $brd; background: $bg; padding: 0 1; }
    #task-line { height: 3; }
    #task-status { width: 40; color: $muted; padding-top: 1; }
    #task-progress { width: 1fr; padding-top: 1; }
    #task-log { height: 1fr; border: round $brd; background: $card; padding: 0 1; }
    DataTable { background: $card; }
    .table-wrap { height: 1fr; border: round $brd; background: $card; }
    #job-detail { height: 1fr; border: round $brd; padding: 0 1; }
    """

    BINDINGS = [
        ('f2', 'page("page-single")', '单次'),
        ('f3', 'page("page-batch")', '批量'),
        ('f4', 'page("page-scan")', '扫描'),
        ('f5', 'page("page-jobs")', '任务'),
        ('f6', 'page("page-settings")', '设置'),
        ('[', 'cycle(-1)', '上一页'),
        (']', 'cycle(1)', '下一页'),
        ('ctrl+t', 'toggle_theme', '主题'),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.register_theme(PLASMA_DARK)
        self.register_theme(PLASMA_LIGHT)
        self.theme = 'plasma-dark'
        self.backend = None
        self.current_job: str | None = None
        self._single_result: dict | None = None
        self._scan_result: dict | None = None
        self._batch_result: dict | None = None
        self._batch_pool: list[dict] = []
        self._frame_idx = 0
        self._playing = False
        self._jobs_rows: dict[str, str] = {}

    # ------------------------------------------------------------------ UI
    def compose(self) -> ComposeResult:
        with Horizontal(id='shell'):
            with Vertical(id='sidebar'):
                yield Static('⚡ simLIBS [i]Studio[/i] · CLI', id='brand', markup=True)
                for pid, label, key in PAGES:
                    yield NavItem(pid, label, key)
                yield Static('…', id='engine-card')
            with Vertical(id='main'):
                with Horizontal(id='topbar'):
                    yield Static('单次模拟', id='page-title')
                    yield Static('NIST 探测中…', id='nist-chip', classes='chip', markup=True)
                    yield Static('空闲', id='status-pill', classes='chip', markup=True)
                    yield Button('☾', id='theme-btn', flat=True, classes='ghost')
                with ContentSwitcher(initial='page-single', id='pages'):
                    yield from self._page_single()
                    yield from self._page_batch()
                    yield from self._page_scan()
                    yield from self._page_jobs()
                    yield from self._page_settings()
        with Vertical(id='taskbar'):
            with Horizontal(id='task-line'):
                yield Static('就绪', id='task-status', markup=True)
                yield ProgressBar(total=100.0, show_eta=False, id='task-progress')
                yield Button('取消任务', id='task-cancel', classes='danger')
            yield RichLog(id='task-log', markup=False, max_lines=600, wrap=True)
        yield Footer()

    # ------------------------------------------------------------------ 页面构建
    @staticmethod
    def _field(label: str, widget) -> Horizontal:
        return Horizontal(Label(label), widget, classes='field')

    @staticmethod
    def _btn(label: str, btn_id: str, classes: str = 'ghost') -> Button:
        return Button(label, id=btn_id, classes=classes)

    def _page_single(self) -> Vertical:
        with Vertical(id='page-single', classes='page'):
            with Horizontal(classes='page-body'):
                with Vertical(classes='panel'):
                    yield self._field('Te [eV]', Input(value='1.0', id='s-te'))
                    yield self._field('Ne [cm⁻³]', Input(value='1e17', id='s-ne'))
                    yield self._field('分辨率 R', Input(value='1000', id='s-r'))
                    with Horizontal(classes='field'):
                        yield Label('λ 范围 [nm]')
                        yield Input(value='650', id='s-low')
                        yield Input(value='660', id='s-up')
                    yield self._field('最大离子电荷', Input(value='3', id='s-charge'))
                    yield self._field('抓取模式', Select([('static（NIST 服务端）', 'static'),
                                                        ('dynamic（浏览器）', 'dynamic')],
                                                       value='static', id='s-mode', allow_blank=False))
                    yield self._field('强度尺度', Select([('光子通量 (photon)', 'photon'),
                                                        ('能量通量 (energy)', 'energy')],
                                                       value='photon', id='s-scale', allow_blank=False))
                    yield self._field('谱线展宽', Select([('NIST 服务端', 'nist'),
                                                        ('本地线表（无需浏览器）', 'local')],
                                                       value='nist', id='s-broad', allow_blank=False))
                    yield self._field('图表标题', Input(value='', placeholder='可选', id='s-title'))
                    with Collapsible(title='高级参数（展宽/重采样/浏览器）', collapsed=True):
                        yield self._field('展宽约定', Select([('NIST：w=λ/R（1/e 半宽）', 'nist'),
                                                            ('Physics：FWHM=λ/R', 'physics')],
                                                           value='nist', id='s-conv', allow_blank=False))
                        yield self._field('展宽网格步长', Input(value='0.005', id='s-grid'))
                        yield self._field('选线阈值', Input(value='0', id='s-minrel'))
                        yield self._field('重采样步长', Input(value='0.005', id='s-step'))
                        with Horizontal(classes='field'):
                            yield Label('本地插值')
                            yield Switch(value=False, id='s-resample')
                            yield Label('  headless')
                            yield Switch(value=True, id='s-headless')
                    yield Static('配比（总和须为 100%，元素区分大小写）', classes='hr')
                    yield Vertical(id='s-comp-rows')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('＋ 元素', 's-comp-add')
                        yield self._btn('归一化', 's-comp-norm')
                    yield Static('总和 0%', id='s-comp-sum')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('H 窄波段', 's-preset-h')
                        yield self._btn('W/Fe/Mo', 's-preset-wfm')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('▶ 开始模拟', 's-run', classes='primary')
                with Vertical(classes='right'):
                    yield Static('', id='s-legend', classes='legend', markup=True)
                    with Vertical(classes='canvas-wrap'):
                        yield SpectrumCanvas(_pal('plasma-dark'), id='canvas-single')
                    yield Static('', id='s-meta', classes='meta', markup=True)
                    with Horizontal(classes='btnrow'):
                        yield self._field('视图', Select([('插值谱', 'interpolated'), ('原始谱', 'raw'),
                                                        ('离子分量', 'ion')],
                                                       value='interpolated', id='s-view', allow_blank=False))
                        yield self._field('导出目录', Input(value=EXPORT_DIR, id='s-export-dir'))
                    with Horizontal(classes='btnrow'):
                        yield self._btn('导出 CSV', 's-exp-csv')
                        yield self._btn('导出 JSON', 's-exp-json')
                        yield self._btn('导出 PNG', 's-exp-png')

    def _page_batch(self) -> Vertical:
        with Vertical(id='page-batch', classes='page'):
            with Horizontal(classes='page-body'):
                with Vertical(classes='panel'):
                    yield self._field('样本数', Input(value='10', id='b-n'))
                    yield self._field('随机种子', Input(value='0', id='b-seed'))
                    with Horizontal(classes='field'):
                        yield Label('Te 范围 [eV]')
                        yield Input(value='1.0', id='b-temin')
                        yield Input(value='2.0', id='b-temax')
                    with Horizontal(classes='field'):
                        yield Label('Ne 指数 (10^x)')
                        yield Input(value='17', id='b-nemin')
                        yield Input(value='18', id='b-nemax')
                    yield Static('组成候选池（CSV 元素列 + 可选 name 列）', classes='hr')
                    yield self._field('组成 CSV', Input(value='', placeholder='路径…', id='b-csv-path'))
                    with Horizontal(classes='btnrow'):
                        yield self._btn('导入 CSV', 'b-import')
                        yield Checkbox('导入时归一化', value=False, id='b-norm-import')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('用当前配比', 'b-use-current')
                    with Vertical(classes='table-wrap'):
                        yield DataTable(id='b-comp-table', cursor_type='row')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('▶ 开始批量', 'b-run', classes='primary')
                with Vertical(classes='right'):
                    yield Static('', id='b-meta', classes='meta', markup=True)
                    with Vertical(classes='table-wrap'):
                        yield DataTable(id='b-samples', cursor_type='row')
                    yield Static('', id='b-wide', classes='meta', markup=True)
                    with Horizontal(classes='btnrow'):
                        yield self._field('导出目录', Input(value=EXPORT_DIR, id='b-export-dir'))
                        yield self._btn('导出数据集 CSV', 'b-exp-dataset')

    def _page_scan(self) -> Vertical:
        with Vertical(id='page-scan', classes='page'):
            with Horizontal(classes='page-body'):
                with Vertical(classes='panel'):
                    yield self._field('扫描轴', Select([('Te [eV]', 'te'), ('Ne 指数 (10^x)', 'ne'),
                                                      ('分辨率 R', 'r')],
                                                     value='te', id='sc-axis', allow_blank=False))
                    with Horizontal(classes='field'):
                        yield Label('起 → 止')
                        yield Input(value='0.5', id='sc-start')
                        yield Input(value='5.0', id='sc-end')
                    yield self._field('帧数', Input(value='10', id='sc-frames'))
                    with Horizontal(classes='btnrow'):
                        yield self._btn('▶ 开始扫描', 'sc-run', classes='primary')
                    yield Static('播放控制', classes='hr')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('⏮', 'sc-prev')
                        yield self._btn('▶', 'sc-play')
                        yield self._btn('⏭', 'sc-next')
                    yield Static('无扫描结果', id='sc-frame', classes='hr')
                with Vertical(classes='right'):
                    yield Static('', id='sc-legend', classes='legend', markup=True)
                    with Vertical(classes='canvas-wrap'):
                        yield SpectrumCanvas(_pal('plasma-dark'), id='canvas-scan')
                    yield Static('', id='sc-meta', classes='meta', markup=True)
                    with Horizontal(classes='btnrow'):
                        yield self._field('导出目录', Input(value=EXPORT_DIR, id='sc-export-dir'))
                    with Horizontal(classes='btnrow'):
                        yield self._btn('导出当前帧 PNG', 'sc-exp-png')
                        yield self._btn('导出 GIF', 'sc-exp-gif')

    def _page_jobs(self) -> Vertical:
        with Vertical(id='page-jobs', classes='page'):
            with Horizontal(classes='page-body'):
                with Vertical(classes='panel'):
                    yield self._field('历史 CSV', Input(value='', placeholder='wavelength,intensity 或 NIST 格式',
                                                       id='j-path'))
                    with Horizontal(classes='btnrow'):
                        yield self._btn('离线打开', 'j-open')
                        yield self._btn('刷新任务', 'j-refresh')
                        yield self._btn('查看结果', 'j-view-result')
                    with Vertical(classes='table-wrap'):
                        yield DataTable(id='j-table', cursor_type='row')
                with Vertical(classes='right'):
                    yield RichLog(id='job-detail', markup=False, max_lines=400, wrap=True)

    def _page_settings(self) -> Vertical:
        with Vertical(id='page-settings', classes='page'):
            with Horizontal(classes='page-body'):
                with Vertical(classes='panel'):
                    yield self._field('连接超时 [s]', Input(id='st-connect'))
                    yield self._field('读取超时 [s]', Input(id='st-read'))
                    yield self._field('页面加载 [s]', Input(id='st-page'))
                    yield self._field('static 期限 [s]', Input(id='st-static-dl'))
                    yield self._field('dynamic 期限 [s]', Input(id='st-dynamic-dl'))
                    yield self._field('输出目录', Input(id='st-output'))
                    yield self._field('源库路径', Input(id='st-source'))
                    yield self._field('Python 解释器', Input(id='st-python'))
                    yield self._field('Chrome 路径', Input(id='st-chrome'))
                    yield self._field('ChromeDriver 路径', Input(id='st-driver'))
                    with Horizontal(classes='field'):
                        yield Label('TLS 证书校验')
                        yield Switch(value=True, id='st-tls')
                    with Horizontal(classes='btnrow'):
                        yield self._btn('保存设置', 'st-save', classes='primary')
                        yield self._btn('恢复默认', 'st-reset')
                with Vertical(classes='right'):
                    yield Static('', id='st-info', markup=True)

    # ------------------------------------------------------------------ 生命周期
    def on_mount(self) -> None:
        self.backend = create_backend()
        self._play_timer = self.set_interval(0.45, self._advance_frame, pause=True)
        jtable = self.query_one('#j-table', DataTable)
        jtable.add_columns('创建', '类型', '状态', '进度', '耗时', '摘要', '任务 ID')
        self.query_one('#b-comp-table', DataTable).add_columns('name', '组成', '总和')
        self.query_one('#b-samples', DataTable).add_columns('name', 'Te [eV]', 'Ne [cm⁻³]', '组成')
        self._preset_h()
        self._load_settings_form()
        self._refresh_engine_bg()
        self._refresh_jobs_table()
        self._log('[ui] simLIBS Studio CLI 就绪 · 左键框选缩放 / 中键平移 / 右键或 R 复位 · F2–F6 切页 · Ctrl+T 换主题')

    # ------------------------------------------------------------------ 导航
    def switch_page(self, page_id: str) -> None:
        switcher = self.query_one('#pages', ContentSwitcher)
        if switcher.current == page_id:
            return
        switcher.current = page_id
        self.query_one('#page-title', Static).update(PAGE_TITLES.get(page_id, ''))
        for item in self.query(NavItem):
            item.set_class(item.page_id == page_id, 'active')
        try:  # 页面淡入（上滑进入；失败不影响功能）
            from textual.geometry import Offset
            page = switcher.query_one(f'#{page_id}')
            page.offset = Offset(0, 6)
            page.animate('offset', Offset(0, 0), duration=0.22, easing='out_cubic')
        except Exception:
            pass

    def action_page(self, page_id: str) -> None:
        self.switch_page(page_id)

    def action_cycle(self, delta: int) -> None:
        ids = [p[0] for p in PAGES]
        cur = self.query_one('#pages', ContentSwitcher).current or ids[0]
        self.switch_page(ids[(ids.index(cur) + delta) % len(ids)])

    def action_toggle_theme(self) -> None:
        self.theme = 'plasma-light' if self.theme.endswith('dark') else 'plasma-dark'
        pal = _pal(self.theme)
        for canvas in self.query(SpectrumCanvas):
            canvas.palette = dict(pal)
            canvas._buf_key = ()
            canvas.refresh()
        self.query_one('#theme-btn', Button).label = '☀' if self.theme.endswith('dark') else '☾'
        self.notify(f'已切换主题：{self.theme}', timeout=2)

    # ------------------------------------------------------------------ 工具
    def _log(self, msg: str, level: str = 'info') -> None:
        key = {'info': 'muted', 'ok': 'good', 'warn': 'warn', 'error': 'bad'}.get(level, 'muted')
        ts = datetime.now().strftime('%H:%M:%S')
        try:
            self.query_one('#task-log', RichLog).write(Text(f'[{ts}] {msg}', style=_pal(self.theme)[key]))
        except Exception:
            pass

    def _bg(self, fn, on_done=None) -> None:
        def run():
            try:
                result = fn()
            except Exception as exc:
                self.call_from_thread(self._toast_error, exc)
                return
            if on_done:
                self.call_from_thread(on_done, result)
        threading.Thread(target=run, daemon=True).start()

    def _toast_error(self, exc: Exception) -> None:
        self.notify(str(exc), title='出错了', severity='error', timeout=6)
        self._log(f'[error] {exc}', 'error')

    @staticmethod
    def _parse_float(raw: str, name: str) -> float:
        try:
            v = float(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f'{name} 不是合法数字：{raw!r}') from None
        if not math.isfinite(v):
            raise ValueError(f'{name} 必须是有限数值')
        return v

    @staticmethod
    def _parse_int(raw: str, name: str) -> int:
        f = SimlibsCLI._parse_float(raw, name)
        if f != int(f):
            raise ValueError(f'{name} 必须是整数')
        return int(f)

    def _q(self, selector: str, expect=None):
        return self.query_one(selector, expect) if expect else self.query_one(selector)

    # ------------------------------------------------------------------ 配比编辑
    def _add_comp_row(self, el: str = '', pct: str = '') -> None:
        el_in = Input(value=el, placeholder='元素', classes='el')
        pct_in = Input(value=pct, placeholder='%', classes='pct')
        del_btn = Button('✕', classes='comp-del')
        self._q('#s-comp-rows', Vertical).mount(
            Horizontal(el_in, pct_in, del_btn, classes='comp-row'))

    def _comp_values(self) -> list[tuple[str, float]]:
        out = []
        for row in self._q('#s-comp-rows', Vertical).query('.comp-row'):
            inputs = [w for w in row.children if isinstance(w, Input)]
            if len(inputs) < 2:
                continue
            el, pct_raw = inputs[0].value.strip(), inputs[1].value.strip()
            if not el and not pct_raw:
                continue
            out.append((el, self._parse_float(pct_raw, f'配比 {el or "?"}')))
        return out

    def _update_comp_sum(self, *_) -> None:
        try:
            vals = self._comp_values()
            total = sum(p for _, p in vals)
            ok = bool(vals) and abs(total - 100.0) <= 1e-6
        except ValueError as exc:
            self._q('#s-comp-sum', Static).update(f'[bad]✗ {escape(str(exc))}[/]')
            return
        icon, cls = ('✓', 'good') if ok else ('✗', 'bad')
        self._q('#s-comp-sum', Static).update(
            f'[{cls}]{icon} 总和 {total:.6g}%[/]' + ('' if ok else '（须为 100%）'))

    # ------------------------------------------------------------------ 预设
    def _fill_single(self, te, ne, r, low, up, charge, comp) -> None:
        self._q('#s-te', Input).value = str(te)
        self._q('#s-ne', Input).value = f'{ne:.3e}'.replace('e+', 'e') if ne >= 1e4 else f'{ne:g}'
        self._q('#s-r', Input).value = str(r)
        self._q('#s-low', Input).value = str(low)
        self._q('#s-up', Input).value = str(up)
        self._q('#s-charge', Input).value = str(charge)
        self._q('#s-comp-rows', Vertical).remove_children('.comp-row')
        for el, pct in comp:
            self._add_comp_row(el, f'{pct:g}')
        self.call_after_refresh(self._after_fill)

    def _after_fill(self) -> None:
        self._update_comp_sum()
        self._placeholder_schematic()

    def _preset_h(self) -> None:
        self._fill_single(1.0, 1e17, 1000, 650, 660, 3, [('H', 100.0)])

    def _preset_wfm(self) -> None:
        self._fill_single(1.0, 1e17, 1000, 200, 1000, 3,
                          [('W', 50.0), ('Fe', 25.0), ('Mo', 25.0)])

    # ------------------------------------------------------------------ 单次模拟
    def _single_params_dict(self) -> dict:
        def f(sel, name):
            return self._parse_float(self._q(sel, Input).value, name)
        broad = self._q('#s-broad', Select).value
        resample = self._q('#s-resample', Switch).value
        d = {
            'te': f('#s-te', 'Te'), 'ne': f('#s-ne', 'Ne'),
            'resolution': self._parse_int(self._q('#s-r', Input).value, '分辨率 R'),
            'low_w': f('#s-low', 'λ 下界'), 'up_w': f('#s-up', 'λ 上界'),
            'max_ion_charge': self._parse_int(self._q('#s-charge', Input).value, '最大离子电荷'),
            'mode': self._q('#s-mode', Select).value,
            'headless': self._q('#s-headless', Switch).value,
            'resample': resample,
            'intensity_scale': self._q('#s-scale', Select).value,
            'broadening': broad,
        }
        if resample:
            d['resample_step'] = f('#s-step', '重采样步长')
        if broad == 'local':
            d['broaden_convention'] = self._q('#s-conv', Select).value
            d['broaden_grid_step'] = f('#s-grid', '展宽网格步长')
            d['broaden_min_rel_int'] = f('#s-minrel', '选线阈值')
        return d

    def _start_single(self) -> None:
        from backend_api import CommonParams, CompositionItem, SingleRequest, validate_composition
        try:
            params = CommonParams.from_api(self._single_params_dict())
            params.check_points()
            comp = [CompositionItem(el, pct) for el, pct in self._comp_values()]
            validate_composition(comp)
        except Exception as exc:
            self.notify(str(exc), severity='warning', timeout=6)
            return
        req = SingleRequest(params=params, composition=comp,
                            title=self._q('#s-title', Input).value.strip())
        try:
            jid = self.backend.start_single(req)
        except Exception as exc:
            self.notify(str(exc), severity='error', timeout=6)
            return
        self._watch(jid, f'单次模拟 · {params.summary()}')

    # ------------------------------------------------------------------ 批量
    def _import_batch_csv(self) -> None:
        import pandas as pd
        from backend_api import CompositionItem, validate_composition
        from simlibs_ui.models import ELEMENTS

        def el_of(col):
            s = str(col).strip()
            if s in ELEMENTS:
                return s
            if s.endswith('_at%') and s[:-4] in ELEMENTS:
                return s[:-4]
            return None

        path = self._q('#b-csv-path', Input).value.strip().strip('"')
        if not path:
            self.notify('请先填写组成 CSV 路径', severity='warning')
            return
        try:
            df = pd.read_csv(path, encoding='utf-8-sig')
        except Exception as exc:
            self.notify(f'无法读取 CSV：{exc}', severity='error', timeout=6)
            return
        df = df.loc[:, [c for c in df.columns if not str(c).startswith('Unnamed:')]]
        name_col = next((c for c in df.columns
                         if str(c).strip().lower() in ('name', 'samples', 'sample')), None)
        el_map = {c: el_of(c) for c in df.columns if c != name_col and el_of(c)}
        if not el_map:
            self.notify('CSV 中没有可识别的元素列（如 H、He、Fe 或 *_at%）', severity='error', timeout=6)
            return
        normalize = self._q('#b-norm-import', Checkbox).value
        rows, errors = [], []
        for i, (_, rec) in enumerate(df.iterrows()):
            items = []
            for col, el in el_map.items():
                try:
                    v = float(rec[col])
                except (TypeError, ValueError):
                    v = float('nan')
                if math.isfinite(v):
                    items.append(CompositionItem(el, v))
            total = sum(it.pct for it in items)
            if normalize and total > 0 and abs(total - 100.0) > 1e-6:
                items = [CompositionItem(it.el, it.pct / total * 100) for it in items]
                total = 100.0
            try:
                validate_composition(items, f'第 {i + 1} 行')
            except Exception as exc:
                errors.append(str(exc))
                continue
            name = str(rec[name_col]) if name_col and pd.notna(rec[name_col]) else f'sample-{i + 1}'
            rows.append({'name': name, 'items': items, 'total': total})
        self._batch_pool = rows
        table = self._q('#b-comp-table', DataTable)
        table.clear(columns=True)
        table.add_columns('name', '组成', '总和')
        for r in rows:
            table.add_row(r['name'], ' '.join(f'{it.el}{it.pct:g}' for it in r['items']),
                          f"{r['total']:.6g}%")
        if errors:
            self.notify(f'{len(rows)} 行导入，{len(errors)} 行未通过校验（可勾选"导入时归一化"）\n{errors[0]}',
                        severity='warning', timeout=8)
        else:
            self.notify(f'已导入 {len(rows)} 行组成', timeout=3)

    def _batch_use_current(self) -> None:
        from backend_api import CompositionItem, validate_composition
        try:
            vals = self._comp_values()
            if not vals:
                raise ValueError('当前配比为空')
            items = [CompositionItem(el, pct) for el, pct in vals]
            validate_composition(items)
        except Exception as exc:
            self.notify(str(exc), severity='warning', timeout=5)
            return
        self._batch_pool = [{'name': 'current', 'items': items, 'total': 100.0}]
        table = self._q('#b-comp-table', DataTable)
        table.clear(columns=True)
        table.add_columns('name', '组成', '总和')
        table.add_row('current', ' '.join(f'{el}{p:g}' for el, p in vals), '100%')
        self.notify('已用单次模拟页当前配比作为候选池（1 行）', timeout=3)

    def _start_batch(self) -> None:
        from backend_api import (BatchRequest, BatchSample, CommonParams)
        try:
            if not self._batch_pool:
                raise ValueError('组成候选池为空：先导入 CSV 或使用当前配比')
            params = CommonParams.from_api(self._single_params_dict())
            params.check_points()
            n = self._parse_int(self._q('#b-n', Input).value, '样本数')
            seed = self._parse_int(self._q('#b-seed', Input).value, '随机种子')
            te0 = self._parse_float(self._q('#b-temin', Input).value, 'Te min')
            te1 = self._parse_float(self._q('#b-temax', Input).value, 'Te max')
            ne0 = self._parse_float(self._q('#b-nemin', Input).value, 'Ne 指数 min')
            ne1 = self._parse_float(self._q('#b-nemax', Input).value, 'Ne 指数 max')
            if te0 > te1 or ne0 > ne1:
                raise ValueError('范围的 min 不能大于 max（允许相等=固定值）')
            req = BatchRequest(
                params=params, n_samples=n, seed=seed, te_range=(te0, te1), ne_range=(ne0, ne1),
                compositions=[BatchSample(name=r['name'], items=r['items']) for r in self._batch_pool])
        except Exception as exc:
            self.notify(str(exc), severity='warning', timeout=6)
            return
        try:
            jid = self.backend.start_batch(req)
        except Exception as exc:
            self.notify(str(exc), severity='error', timeout=6)
            return
        self._watch(jid, f'批量 dataset · {n} 样本 · seed={seed}')

    def _show_batch(self, result: dict) -> None:
        self._batch_result = result
        table = self._q('#b-samples', DataTable)
        table.clear()
        for s in result.get('samples', []):
            comp = ' '.join(f"{c['el']}{c['pct']:g}" for c in s.get('composition', []))
            table.add_row(s.get('name', ''), f"{s.get('te', 0):g}", f"{s.get('ne', 0):.3g}", comp)
        summary = result.get('summary') or {}
        scale = result.get('intensity_scale')
        scale_txt = {'photon': 'Photon flux', 'energy': 'Energy flux'}.get(scale, '尺度 unknown')
        self._q('#b-meta', Static).update(
            f'[good]批量完成[/] · 请求 {summary.get("total", 0)} · 完成 {summary.get("completed", 0)}'
            + (' · [warn]partial（部分样本未完成）[/]' if summary.get('partial') else '')
            + f' · {scale_txt} (a.u.)')
        self._q('#b-wide', Static).update(escape(str((result.get('wide') or {}).get('note', ''))))

    # ------------------------------------------------------------------ 扫描
    def _start_scan(self) -> None:
        from backend_api import CommonParams, CompositionItem, ScanRequest, validate_composition
        try:
            params = CommonParams.from_api(self._single_params_dict())
            params.check_points()
            axis = self._q('#sc-axis', Select).value
            raw_start = self._q('#sc-start', Input).value
            raw_end = self._q('#sc-end', Input).value
            if axis == 'r':
                start, end = self._parse_int(raw_start, 'R 起点'), self._parse_int(raw_end, 'R 终点')
            else:
                start = self._parse_float(raw_start, '起点')
                end = self._parse_float(raw_end, '终点')
            frames = self._parse_int(self._q('#sc-frames', Input).value, '帧数')
            if frames < 2:
                raise ValueError('帧数至少为 2')
            comp = [CompositionItem(el, pct) for el, pct in self._comp_values()]
            validate_composition(comp)
            req = ScanRequest(params=params, axis=axis, start=start, end=end, frames=frames,
                              composition=comp)
        except Exception as exc:
            self.notify(str(exc), severity='warning', timeout=6)
            return
        try:
            jid = self.backend.start_scan(req)
        except Exception as exc:
            self.notify(str(exc), severity='error', timeout=6)
            return
        self._watch(jid, f'扫描动画 · {req.axis} {req.start:g}→{req.end:g} · {req.frames} 帧')

    def _show_scan(self, result: dict) -> None:
        self._scan_result = result
        self._frame_idx = 0
        frames = result.get('frames') or []
        self._q('#sc-meta', Static).update(
            f"扫描轴 {escape(str(result.get('axis', '')))}{escape(str(result.get('unit', '')))}"
            f" · {escape(str(result.get('params_summary', '')))}"
            f" · {result.get('intensity_units', 'a.u.')}")
        self._render_frame()
        self._set_playing(len(frames) > 1)

    def _render_frame(self) -> None:
        result = self._scan_result
        if not result:
            return
        frames = result.get('frames') or []
        if not frames:
            return
        idx = max(0, min(self._frame_idx, len(frames) - 1))
        frame = frames[idx]
        series = frame.get('series')
        if not series and frame.get('xs'):        # MOCK 引擎的帧直接是 xs/ys
            series = {'interpolated': {'label': 'frame', 'xs': frame['xs'], 'ys': frame['ys']}}
        pairs = self._paint_canvas(self._q('#canvas-scan', SpectrumCanvas), series or {},
                                   result.get('intensity_scale'))
        self._q('#sc-legend', Static).update(self._legend_text(pairs, result.get('intensity_scale')))
        unit = escape(str(result.get('unit', '')))
        axis = str(result.get('axis', '')).upper()
        state = '（自动播放中）' if self._playing else ''
        self._q('#sc-frame', Static).update(f'帧 {idx + 1}/{len(frames)} · {axis}={frame.get("value"):g}{unit}{state}')

    def _set_playing(self, playing: bool) -> None:
        self._playing = playing
        self._play_timer.pause() if not playing else self._play_timer.resume()
        self._q('#sc-play', Button).label = '⏸' if playing else '▶'

    def _advance_frame(self) -> None:
        if not self._scan_result:
            self._set_playing(False)
            return
        n = len(self._scan_result.get('frames') or [])
        if n < 2:
            self._set_playing(False)
            return
        self._frame_idx = (self._frame_idx + 1) % n
        self._render_frame()

    # ------------------------------------------------------------------ 画布填充
    def _paint_canvas(self, canvas: SpectrumCanvas, series: dict, scale: str | None) -> None:
        pal = _pal(self.theme)
        out, pairs = [], []
        main = series.get('interpolated') or series.get('raw')
        if main:
            out.append({'label': main.get('label', 'main'), 'xs': main['xs'], 'ys': main['ys'],
                        'color': pal['accent']})
            pairs.append(('accent', '主线'))
        for i, ion in enumerate(series.get('ions') or []):
            key = ION_COLORS[i % len(ION_COLORS)]
            out.append({'label': ion.get('label', f'ion{i}'), 'xs': ion['xs'], 'ys': ion['ys'],
                        'color': pal[key]})
            pairs.append((key, str(ion.get('label'))))
        if series.get('raw') and main and series['raw'] is not main:
            out.append({'label': 'raw', 'xs': series['raw']['xs'], 'ys': series['raw']['ys'],
                        'color': pal['raw'], 'dotted': True})
            pairs.append(('raw', 'raw'))
        canvas.watermark = ''
        canvas.set_series(out)
        return pairs

    def _legend_text(self, pairs, scale: str | None) -> str:
        pal = _pal(self.theme)
        name = {'photon': 'Photon flux', 'energy': 'Energy flux'}.get(scale or '', '尺度 unknown')
        parts = []
        for key, label in pairs:
            color = pal.get(key, key) if isinstance(key, str) else '#ffffff'
            tag = color if str(color).startswith('#') else f'#{color}'
            parts.append(f'[{tag}]●[/] {escape(label)}')
        return ' · '.join(parts) + f'　[i]{name} (a.u.)[/]'

    def _show_single(self, result: dict) -> None:
        self._single_result = result
        self._paint_current_single()
        meta = result.get('meta') or {}
        bits = [f'[b]{escape(str(meta.get("source", "")))}[/]']
        if meta.get('points'):
            bits.append(escape(str(meta['points'])))
        if meta.get('sha256'):
            bits.append(f'SHA {escape(str(meta["sha256"]))}')
        if meta.get('ne_actual') is not None:
            try:
                bits.append(f'实际 Ne={float(meta["ne_actual"]):.3g}')
            except (TypeError, ValueError):
                bits.append(f'实际 Ne={escape(str(meta["ne_actual"]))}')
        if meta.get('intensity_scale'):
            name = {'photon': 'Photon', 'energy': 'Energy'}.get(meta.get('intensity_scale'), '尺度 unknown')
            bits.append(f'{name} flux (a.u.)')
        for key, label in (('computation_location', '计算'), ('broadening', '展宽'),
                           ('actual_resolution', '实际R')):
            if meta.get(key) is not None:
                bits.append(f'{label}={escape(str(meta[key]))}')
        txt = ' · '.join(bits)
        if meta.get('resolution_warning'):
            txt += f'\n[bad]⚠ {escape(str(meta["resolution_warning"]))}[/]'
        self._q('#s-meta', Static).update(txt)

    def _paint_current_single(self) -> None:
        result = self._single_result
        if not result:
            return
        view = self._q('#s-view', Select).value
        series = result.get('series') or {}
        if not series and result.get('xs'):       # MOCK 引擎返回顶层 xs/ys
            series = {'interpolated': {'label': 'spectrum', 'xs': result['xs'], 'ys': result['ys']}}
        if view == 'raw':
            shown = {'raw': series.get('raw')}
        elif view == 'ion':
            shown = {'interpolated': series.get('interpolated') or series.get('raw'),
                     'ions': series.get('ions')}
        else:
            shown = {'interpolated': series.get('interpolated') or series.get('raw')}
        scale = (result.get('meta') or {}).get('intensity_scale')
        pairs = self._paint_canvas(self._q('#canvas-single', SpectrumCanvas), shown, scale)
        if view == 'raw' and pairs and pairs[0][1] == '主线':
            pairs[0] = ('raw', 'raw')
        self._q('#s-legend', Static).update(self._legend_text(pairs, scale))

    def _placeholder_schematic(self) -> None:
        """运行前的本地示意图（明确标注，不冒充真实数据）。"""
        try:
            low = self._parse_float(self._q('#s-low', Input).value, 'λ')
            up = self._parse_float(self._q('#s-up', Input).value, 'λ')
            if not (0 < low < up):
                raise ValueError
        except ValueError:
            low, up = 650.0, 660.0
        try:
            comp = [el for el, _ in self._comp_values()] or ['H']
        except ValueError:
            comp = ['H']
        n = 400
        xs = [low + (up - low) * i / (n - 1) for i in range(n)]
        seeds = {'H': 656.28, 'He': 587.56, 'Fe': 438.35, 'W': 400.87, 'Mo': 390.30}
        centers = [seeds.get(el, 450.0 + 37.0 * i) for i, el in enumerate(comp)][:5]
        if up - low > 50:
            centers = [low + (up - low) * (0.3 + 0.1 * i) for i in range(len(centers))]
        ys = []
        for x in xs:
            v = 0.05
            for c in centers:
                w = max(0.3, (up - low) * 0.004)
                v += math.exp(-((x - c) ** 2) / (2 * w * w))
            ys.append(v)
        canvas = self._q('#canvas-single', SpectrumCanvas)
        canvas.watermark = '示意预览 · 尚未运行（非真实数据）'
        canvas.set_series([{'label': '示意', 'xs': xs, 'ys': ys,
                            'color': _pal(self.theme)['muted'], 'dotted': True}])
        self._q('#s-legend', Static).update('[i]示意预览 · 运行后替换为真实光谱[/]')

    # ------------------------------------------------------------------ 任务事件
    def _watch(self, job_id: str, summary: str) -> None:
        self.current_job = job_id
        self._q('#task-status', Static).update(f'[warn]● 运行中[/] {escape(summary)}')
        self._q('#task-progress', ProgressBar).update(progress=0)
        self._log(f'[worker] 已提交任务 {job_id[:8]}… · {summary}')
        self._refresh_jobs_table()
        try:
            queue = self.backend.subscribe(job_id)
        except Exception as exc:
            self._toast_error(exc)
            return

        def pump():
            while True:
                try:
                    kind, ev = queue.get(timeout=1.0)
                except Exception:
                    break
                if kind == 'close':
                    break
                if kind == 'timeout':
                    continue
                try:
                    self.call_from_thread(self._on_event, ev)
                except Exception:
                    break
                if getattr(ev, 'final', False):
                    break
        threading.Thread(target=pump, daemon=True, name=f'events-{job_id[:8]}').start()

    def _on_event(self, ev) -> None:
        if getattr(ev, 'message', ''):
            self._log(ev.message, getattr(ev, 'level', 'info'))
        if getattr(ev, 'progress', None) is not None:
            self._q('#task-progress', ProgressBar).update(progress=float(ev.progress))
            if getattr(ev, 'status', None) is None and self.current_job:
                self._q('#task-status', Static).update(f'[warn]● 运行中[/] {ev.progress:.0f}%')
        if getattr(ev, 'final', False):
            self._finalize(getattr(ev, 'status', 'failed'))

    def _finalize(self, status: str) -> None:
        jid, self.current_job = self.current_job, None
        pill = self._q('#status-pill', Static)
        if status == 'completed':
            pill.update('[good]● 完成[/]')
            self._q('#task-progress', ProgressBar).update(progress=100)
            self._log('[done] 任务完成 · 读取结果与来源证据…', 'ok')
            self._bg(lambda: self._fetch_result(jid), on_done=self._route_result)
        elif status == 'cancelled':
            pill.update('[warn]● 已取消[/]')
            self._log('[ui] 已取消 · 保留上一次成功结果', 'warn')
            self.notify('任务已取消（保留上一次成功结果）', severity='warning', timeout=4)
        else:
            pill.update('[bad]● 失败[/]')
            self.notify('任务失败，详情见任务日志', severity='error', timeout=6)
        self._refresh_jobs_table()

    def _fetch_result(self, job_id: str) -> dict:
        result = self.backend.get_result(job_id) or {}
        result['job_id'] = job_id
        return result

    def _route_result(self, result: dict) -> None:
        kind = result.get('kind')
        if kind == 'single':
            self._show_single(result)
            self.switch_page('page-single')
        elif kind == 'scan':
            self._show_scan(result)
            self.switch_page('page-scan')
        elif kind == 'batch':
            self._show_batch(result)
            self.switch_page('page-batch')
        self.notify('结果已就绪（来源证据已保存 manifest）', timeout=3)

    def _refresh_jobs_table(self, *_) -> None:
        try:
            jobs = self.backend.list_jobs()
        except Exception:
            return
        table = self._q('#j-table', DataTable)
        table.clear()
        self._jobs_rows = {}
        for j in jobs:
            status = j.get('status', '?')
            styled = {'completed': '[good]✓ 完成[/]', 'running': '[warn]● 运行[/]',
                      'queued': '[warn]◌ 排队[/]', 'failed': '[bad]✗ 失败[/]',
                      'cancelled': '[warn]⊘ 取消[/]'}.get(status, status)
            key = table.add_row(j.get('created', ''), j.get('kind', ''), styled,
                                f"{j.get('progress') or 0:.0f}%", j.get('duration', '-'),
                                str(j.get('summary', ''))[:60], str(j.get('job_id', ''))[:8])
            self._jobs_rows[str(key)] = j.get('job_id')

    def _show_job_detail(self, job_id: str) -> None:
        try:
            detail = self.backend.get_job(job_id)
        except Exception as exc:
            self._toast_error(exc)
            return
        log = self._q('#job-detail', RichLog)
        log.clear()
        pal = _pal(self.theme)
        log.write(Text(f"任务 {job_id} · {detail.get('kind')} · {detail.get('status')}", style=pal['text']))
        for ev in detail.get('events', []):
            log.write(Text(f"[{ev.get('ts')}] {ev.get('message')}",
                           style=pal.get({'info': 'muted', 'ok': 'good', 'warn': 'warn',
                                          'error': 'bad'}.get(ev.get('level'), 'muted'))))

    # ------------------------------------------------------------------ 导出
    def _do_export(self, jid: str | None, kinds: list[str], dir_sel: str,
                   frame: int | None = None) -> None:
        target = jid or self._current_completed_job()
        if not target:
            self.notify('没有可导出的成功任务', severity='warning')
            return
        out_dir = Path(self._q(dir_sel, Input).value.strip().strip('"') or EXPORT_DIR)
        self._q('#task-status', Static).update('[warn]● 导出中…[/]')

        def work():
            paths = []
            for kind in kinds:
                payload = self.backend.export(target, kind, frame=frame)
                ext = {'text/csv': 'csv', 'application/json': 'json', 'image/png': 'png',
                       'image/gif': 'gif'}.get(payload.media_type.split(';')[0], 'bin')
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / (payload.filename or f'{target}_{kind}.{ext}')
                data = payload.payload
                if isinstance(data, str):
                    path.write_text(data, encoding='utf-8')
                else:
                    path.write_bytes(data)
                paths.append(str(path))
            return paths
        self._bg(work, on_done=self._export_done)

    def _export_done(self, paths: list[str]) -> None:
        self._q('#task-status', Static).update('[good]● 导出完成[/]')
        for p in paths:
            self._log(f'[export] {p}', 'ok')
        self.notify('已导出：\n' + '\n'.join(paths), timeout=6)

    def _current_completed_job(self) -> str | None:
        try:
            for j in reversed(self.backend.list_jobs()):
                if j.get('status') == 'completed':
                    return j.get('job_id')
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------ 设置
    def _load_settings_form(self) -> None:
        try:
            s = self.backend.get_settings()
        except Exception:
            return
        values = {'#st-connect': s.get('connect_timeout'), '#st-read': s.get('read_timeout'),
                  '#st-page': s.get('page_load'), '#st-static-dl': s.get('static_deadline'),
                  '#st-dynamic-dl': s.get('dynamic_deadline'), '#st-output': s.get('output_dir'),
                  '#st-source': s.get('source'), '#st-python': s.get('python'),
                  '#st-chrome': s.get('chrome') or '', '#st-driver': s.get('driver') or ''}
        for sel, v in values.items():
            self._q(sel, Input).value = '' if v is None else str(v)
        self._q('#st-tls', Switch).value = bool(s.get('tls_verify', True))
        info = '设置文件：MOCK 引擎使用固定演示配置，不可修改。' \
            if not hasattr(self.backend, 'settings_path') \
            else f'设置文件：{escape(str(self.backend.settings_path()))}\n' \
                 '修改解释器/Chrome/输出目录后保存；TLS 校验默认开启（关闭需自担风险）。'
        self._q('#st-info', Static).update(info)

    def _save_settings(self) -> None:
        def num(sel, name):
            raw = self._q(sel, Input).value.strip()
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f'{name} 不是合法数字：{raw!r}') from None
        try:
            self.backend.save_settings({
                'connect_timeout': num('#st-connect', '连接超时'),
                'read_timeout': num('#st-read', '读取超时'),
                'page_load': num('#st-page', '页面加载'),
                'static_deadline': num('#st-static-dl', 'static 期限'),
                'dynamic_deadline': num('#st-dynamic-dl', 'dynamic 期限'),
                'output_dir': self._q('#st-output', Input).value.strip(),
                'source': self._q('#st-source', Input).value.strip(),
                'python': self._q('#st-python', Input).value.strip(),
                'chrome': self._q('#st-chrome', Input).value.strip(),
                'driver': self._q('#st-driver', Input).value.strip(),
                'tls_verify': self._q('#st-tls', Switch).value,
            })
        except Exception as exc:
            self.notify(f'保存失败：{exc}', severity='error', timeout=8)
            return
        self.notify('设置已保存', timeout=3)
        self._log('[settings] 设置已保存', 'ok')
        self._refresh_engine_bg()

    def _reset_settings(self) -> None:
        if hasattr(self.backend, 'settings_path'):
            try:
                self.backend.settings_path().unlink(missing_ok=True)
            except Exception:
                pass
            self.backend._inst._settings = self.backend._load_settings(self.backend._inst, fallback=True)
        self._load_settings_form()
        self.notify('已恢复默认设置', timeout=3)

    # ------------------------------------------------------------------ 引擎状态
    def _refresh_engine_bg(self, *_) -> None:
        self._bg(self.backend.engine_status, on_done=self._update_engine)

    def _update_engine(self, st: dict) -> None:
        lines = ['[b]引擎状态[/]',
                 f'Python  {escape(str(st.get("python", "?")))}',
                 f'NIST    {escape(str(st.get("nist", "?")))}',
                 f'Chrome  {escape(str(st.get("chrome", "?")))}',
                 f'运行中  {st.get("jobs_running", 0)} 个任务']
        self._q('#engine-card', Static).update('\n'.join(lines))
        ok = bool(st.get('nist_ok'))
        chip = self._q('#nist-chip', Static)
        chip.set_class(ok, 'good')
        chip.set_class(not ok, 'bad')
        chip.update(('[good]● NIST 可达[/] ' if ok else '[bad]● NIST 不可达[/] ')
                    + escape(str(st.get('nist', '')).split('·')[-1]).strip())

    # ------------------------------------------------------------------ 事件分发
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ''
        handlers = {
            'theme-btn': self.action_toggle_theme,
            's-comp-add': self._on_comp_add,
            's-comp-norm': self._normalize_comp,
            's-preset-h': self._preset_h,
            's-preset-wfm': self._preset_wfm,
            's-run': self._start_single,
            's-exp-csv': lambda: self._do_export(self._job_of('_single_result'), ['csv'], '#s-export-dir'),
            's-exp-json': lambda: self._do_export(self._job_of('_single_result'), ['json'], '#s-export-dir'),
            's-exp-png': lambda: self._do_export(self._job_of('_single_result'), ['png'], '#s-export-dir'),
            'b-import': self._import_batch_csv,
            'b-use-current': self._batch_use_current,
            'b-run': self._start_batch,
            'b-exp-dataset': lambda: self._do_export(self._job_of('_batch_result'), ['dataset'], '#b-export-dir'),
            'sc-run': self._start_scan,
            'sc-prev': self._prev_frame,
            'sc-play': self._toggle_play,
            'sc-next': self._next_frame,
            'sc-exp-png': lambda: self._do_export(self._job_of('_scan_result'), ['png'], '#sc-export-dir',
                                                  frame=self._frame_idx),
            'sc-exp-gif': lambda: self._do_export(self._job_of('_scan_result'), ['gif'], '#sc-export-dir'),
            'j-open': self._open_history,
            'j-refresh': self._refresh_jobs_table,
            'j-view-result': self._view_selected_job,
            'st-save': self._save_settings,
            'st-reset': self._reset_settings,
            'task-cancel': self._cancel_job,
        }
        fn = handlers.get(bid)
        if fn:
            fn()
        elif 'comp-del' in str(event.button.classes):
            row = event.button.parent
            if row is not None:
                row.remove()
                self.call_after_refresh(self._update_comp_sum)

    def _job_of(self, attr: str) -> str | None:
        result = getattr(self, attr, None)
        return result.get('job_id') if result else None

    def _on_comp_add(self) -> None:
        self._add_comp_row()
        self.call_after_refresh(self._update_comp_sum)

    def _normalize_comp(self) -> None:
        try:
            vals = self._comp_values()
        except ValueError as exc:
            self.notify(str(exc), severity='warning')
            return
        if not vals:
            self.notify('配比为空', severity='warning')
            return
        total = sum(p for _, p in vals)
        if total <= 0:
            self.notify('总和必须为正数才能归一化', severity='warning')
            return
        before = ' '.join(f'{el}{p:g}' for el, p in vals)
        rows = list(self._q('#s-comp-rows', Vertical).query('.comp-row'))
        for row, (el, pct) in zip(rows, vals):
            inputs = [w for w in row.children if isinstance(w, Input)]
            if len(inputs) >= 2:
                inputs[1].value = f'{pct / total * 100:.6g}'
        after = ' '.join(f'{el}{pct / total * 100:g}' for el, pct in vals)
        self._update_comp_sum()
        self._log(f'[norm] 归一化：{before} → {after}')
        self.notify(f'已归一化（主动操作，共 {len(vals)} 项）', timeout=3)

    def _toggle_play(self) -> None:
        if not self._scan_result:
            self.notify('还没有扫描结果：先运行一次扫描', severity='warning')
            return
        self._set_playing(not self._playing)

    def _prev_frame(self) -> None:
        if self._scan_result:
            self._set_playing(False)
            self._frame_idx = max(0, self._frame_idx - 1)
            self._render_frame()

    def _next_frame(self) -> None:
        if self._scan_result:
            self._set_playing(False)
            n = len(self._scan_result.get('frames') or [])
            self._frame_idx = min(n - 1, self._frame_idx + 1)
            self._render_frame()

    def _open_history(self) -> None:
        path = self._q('#j-path', Input).value.strip().strip('"')
        if not path:
            self.notify('请先填写历史 CSV 路径', severity='warning')
            return
        self._bg(lambda: load_history(path), on_done=self._history_loaded)

    def _history_loaded(self, loaded: dict) -> None:
        meta = loaded['meta']
        canvas = self._q('#canvas-single', SpectrumCanvas)
        canvas.watermark = '历史数据 · 参数未知（非本次模拟）'
        canvas.set_series([{**s, 'color': _pal(self.theme)['info']} for s in loaded['series']])
        self.switch_page('page-single')
        self._q('#s-meta', Static).update(
            f"[b]{escape(str(meta['source']))}[/] · {escape(str(meta.get('points', '')))} · "
            f"SHA {escape(str(meta.get('sha256', '')))} · [warn]{escape(str(meta.get('params', '')))}[/]")
        self._q('#s-legend', Static).update(
            self._legend_text([('info', loaded['series'][0]['label'])], None))
        self._log(f"[history] 已离线载入 {meta.get('path')}", 'ok')

    def _view_selected_job(self) -> None:
        table = self._q('#j-table', DataTable)
        if not table.row_count:
            self.notify('任务列表为空', severity='warning')
            return
        try:
            key = str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.key)
        except Exception:
            key = None
        jid = self._jobs_rows.get(key or '')
        if not jid:
            self.notify('先在表格中选择一个任务', severity='warning')
            return
        try:
            self._route_result(self._fetch_result(jid))
        except Exception as exc:
            self.notify(f'暂无结果：{exc}', severity='warning', timeout=5)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if getattr(event, 'data_table', None) is not None and event.data_table.id == 'j-table':
            jid = self._jobs_rows.get(str(event.row_key.key))
            if jid:
                self._show_job_detail(jid)

    def _cancel_job(self) -> None:
        jid = self.current_job
        if not jid:
            self.notify('当前没有运行中的任务', severity='warning')
            return
        if self.backend.cancel(jid):
            self._log('[ui] 已发送协作取消标记（0.8 秒宽限后清理任务进程树）', 'warn')

    def on_input_changed(self, event: Input.Changed) -> None:
        parent = event.input.parent
        if parent is not None and 'comp-row' in str(parent.classes or ''):
            self._update_comp_sum()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == 's-view' and self._single_result:
            self._paint_current_single()
        if event.select.id == 'sc-axis' and event.value in SCAN_DEFAULTS:
            s, e = SCAN_DEFAULTS[event.value]
            self._q('#sc-start', Input).value = s
            self._q('#sc-end', Input).value = e


def main() -> None:
    SimlibsCLI().run()
