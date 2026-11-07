"""simLIBS Studio Qt —— 原生桌面主窗口（PySide6，无 HTML/无终端）。

后端与 Tk 桌面版 / Web 版完全同源：simlibs_cli.backend.CliBackend =
UI/web/real_backend.RealBackend 的进程内包装（专属 worker 子进程、协作取消、来源证据）。
界面按 UI/design/DESIGN.md 的 Plasma Dark 设计实现：黑红主题、chip 徽章、toast、
流光进度条、页面淡入、图表左键框选/中键平移/右键复位。
"""
from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, QThread, Signal
from PySide6.QtCore import QUrl, QSize
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu
from PySide6.QtWidgets import QCompleter, QSlider
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from simlibs_cli.backend import CLI_ROOT, create_backend
from simlibs_cli.history import load_history
from simlibs_qt.chart import SpectrumChart
from simlibs_qt.theme_qt import (DARK, LIGHT, THEME_PRESETS, apply_dark_titlebar,
                                 apply_fusion_palette, build_qss, chart_palette,
                                 palette_with_accent)
from simlibs_qt.widgets import (EngineCard, ShimmerProgress, ThemeCatalogDialog, ToastHost,
                                fade_between, field_label, make_chip, pulse, stagger_entrance,
                                svg_icon)

PAGES = [('single', '单次模拟'), ('batch', '批量模拟'), ('scan', '扫描动画'),
         ('jobs', '任务记录'), ('settings', '设置')]
EXPORT_DIR = str(CLI_ROOT / 'output' / 'exports')
ION_KEYS = ('ion', 'ion2', 'info', 'good')


def pal_of(theme_name: str) -> dict:
    return dict(LIGHT if theme_name.endswith('light') else DARK)


def hlay(margins=(0, 0, 0, 0), spacing=8):
    lay = QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def vlay(margins=(0, 0, 0, 0), spacing=8):
    lay = QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return lay


def field(label: str, widget) -> QWidget:
    box = QWidget()
    lay = hlay((0, 0, 0, 0), 8)
    lbl = field_label(label)
    lbl.setMinimumWidth(96)
    lay.addWidget(lbl)
    lay.addWidget(widget, 1)
    box.setLayout(lay)
    return box


def card(parent_lay, title: str = '') -> QVBoxLayout:
    frame = QFrame()
    frame.setObjectName('Card')
    lay = vlay((14, 12, 14, 12), 9)
    frame.setLayout(lay)
    if title:
        t = QLabel(title)
        t.setObjectName('PanelTitle')
        t.setWordWrap(True)   # 长标题换行，不撑宽面板（否则窄面板下内容被裁剪）
        lay.addWidget(t)
    parent_lay.addWidget(frame, 0) if isinstance(parent_lay, QHBoxLayout) else parent_lay.addWidget(frame)
    return lay


class JobEventBridge(QObject):
    """worker 事件队列（阻塞）→ Qt 主线程信号。"""
    event = Signal(object)
    finished = Signal()


class EventPump(QThread):
    def __init__(self, queue, bridge: JobEventBridge, parent=None) -> None:
        super().__init__(parent)
        self._q = queue
        self._bridge = bridge

    def run(self) -> None:  # noqa: D102
        while True:
            try:
                kind, ev = self._q.get(timeout=1.0)
            except Exception:
                break
            if kind == 'close':
                break
            if kind == 'timeout':
                continue
            self._bridge.event.emit(ev)
            if getattr(ev, 'final', False):
                break
        self._bridge.finished.emit()


class BackgroundTask(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, backend=None, fade_ms: int = 220) -> None:
        super().__init__()
        self.fade_ms = fade_ms
        self.backend = backend or create_backend()
        self.theme_pref = self._load_theme_pref()      # {'mode': dark|light|system, 'preset': key}
        self.theme_name = f"{self.theme_pref['preset']}-{self.theme_pref['mode']}"
        self._current_palette = self._build_palette()
        self.current_job: str | None = None
        self._single_result: dict | None = None
        self._scan_result: dict | None = None
        self._scan_job_id: str | None = None
        self._scan_cache: dict = {}
        self._scan_fetching: set = set()
        self._batch_result: dict | None = None
        self._batch_pool: list[dict] = []
        self._frame_idx = 0
        self._playing = False
        self._series_spec: list[dict] = []      # 最近一次图表数据（换主题重绘用）
        self._pumps: list[EventPump] = []
        self._threads: list[QThread] = []
        self._last_launch = None
        self._last_error_msg = ''
        self.setWindowTitle('SimLIBS · SPECTRUM WORKBENCH FOR SCNU')
        self.resize(1440, 900)
        self.setMinimumSize(1120, 700)
        self._build_ui()
        self._apply_theme()
        self._setup_brand_icon()
        self._watch_system_scheme()
        for key, fn in (('F2', self._go_single), ('F3', lambda: self._go('batch')),
                        ('F4', lambda: self._go('scan')), ('F5', lambda: self._go('jobs')),
                        ('F6', lambda: self._go('settings'))):
            QShortcut(QKeySequence(key), self, activated=fn)
        QShortcut(QKeySequence('Ctrl+T'), self, activated=self.toggle_theme)
        # 启动逻辑
        QTimer.singleShot(80, self._startup)

    # ================================================================== 主题
    THEME_FILE = CLI_ROOT / '.ui-theme.json'

    def _load_theme_pref(self) -> dict:
        pref = {'mode': 'dark', 'preset': 'violet'}
        try:
            data = json.loads(self.THEME_FILE.read_text(encoding='utf-8'))
            if data.get('mode') in ('dark', 'light', 'system'):
                pref['mode'] = data['mode']
            if data.get('preset') in THEME_PRESETS:
                pref['preset'] = data['preset']
        except Exception:
            pass
        return pref

    def _save_theme_pref(self) -> None:
        try:
            self.THEME_FILE.write_text(
                json.dumps(self.theme_pref, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass

    def _effective_dark(self) -> bool:
        if self.theme_pref['mode'] == 'system':
            try:
                scheme = QGuiApplication.styleHints().colorScheme()
                return scheme != Qt.ColorScheme.Light   # Unknown 视为暗色
            except Exception:
                return True
        return self.theme_pref['mode'] == 'dark'

    def _build_palette(self) -> dict:
        dark = self._effective_dark()
        base = DARK if dark else LIGHT
        accent = THEME_PRESETS[self.theme_pref['preset']]['dark' if dark else 'light']
        return palette_with_accent(base, accent)

    def _pal(self) -> dict:
        return self._current_palette

    def _watch_system_scheme(self) -> None:
        try:
            hints = QGuiApplication.styleHints()
            hints.colorSchemeChanged.connect(
                lambda *_: self.theme_pref['mode'] == 'system' and self._apply_theme())
        except Exception:
            pass

    def toggle_theme(self) -> None:
        # Ctrl+T：在日间/夜间间快速切换（固定为手动模式）
        self.theme_pref['mode'] = 'light' if self._effective_dark() else 'dark'
        self._apply_theme()
        self.toast(f'已切换到{("日间" if self.theme_pref["mode"] == "light" else "夜间")}模式', timeout=2000)

    # ================================================================== UI 构建
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName('Root')
        outer = hlay((0, 0, 0, 0), 0)
        root.setLayout(outer)
        self.setCentralWidget(root)

        # ---- 侧边栏
        sidebar = QWidget()
        sidebar.setObjectName('Sidebar')
        sidebar.setFixedWidth(236)
        side = vlay((16, 16, 12, 12), 4)
        sidebar.setLayout(side)
        # 品牌图标（graduation.jpg 副本）+ 双行品牌文字
        brand_box = QWidget()
        brand_lay = vlay((0, 0, 0, 0), 4)
        brand_box.setLayout(brand_lay)
        brand_img = QLabel()
        brand_img.setAlignment(Qt.AlignHCenter)
        brand_img.setMinimumHeight(76)
        popcat = CLI_ROOT / 'assets' / 'popcat.gif'
        grad = CLI_ROOT / 'assets' / 'graduation.jpg'
        brand_file = popcat if popcat.is_file() else grad
        if brand_file.suffix.lower() == '.gif':
            from PySide6.QtGui import QMovie
            movie = QMovie(str(brand_file), parent=self)
            movie.setScaledSize(QSize(72, 72))
            if movie.isValid():
                self._brand_movie = movie   # 持有引用防 GC；parent=self 便于查找
                brand_img.setMovie(movie)
                movie.start()
            else:
                brand_file = grad
        if brand_file.suffix.lower() != '.gif' and brand_file.is_file():
            from PySide6.QtGui import QPixmap
            pm = QPixmap(str(brand_file)).scaled(
                72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            brand_img.setPixmap(pm)
        brand_lay.addWidget(brand_img)
        self.brand = QLabel('SimLIBS<br><small style="color:%s;letter-spacing:1px">'
                            'SPECTRUM WORKBENCH FOR SCNU</small>' % self._pal()['muted'])
        self.brand.setObjectName('Brand')
        self.brand.setTextFormat(Qt.RichText)
        self.brand.setAlignment(Qt.AlignHCenter)
        brand_lay.addWidget(self.brand)
        side.addWidget(brand_box)
        side.addSpacing(10)
        self._nav_buttons = {}
        for pid, label in PAGES:
            btn = QPushButton(label)
            btn.setProperty('nav', True)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, p=pid: self.go(p))
            side.addWidget(btn)
            self._nav_buttons[pid] = btn
        side.addStretch(1)
        self.engine_card = EngineCard()
        side.addWidget(self.engine_card)
        outer.addWidget(sidebar)

        # ---- 主列
        main = QWidget()
        main_lay = vlay((0, 0, 0, 0), 0)
        main.setLayout(main_lay)
        outer.addWidget(main, 1)

        # 顶栏
        topbar = QWidget()
        top = hlay((14, 12, 14, 10), 10)
        topbar.setLayout(top)
        self.page_title = QLabel('单次模拟')
        self.page_title.setObjectName('PageTitle')
        top.addWidget(self.page_title)
        top.addStretch(1)
        self.nist_chip = make_chip('检测中…')
        self.status_chip = make_chip('空闲')
        # GitHub 仓库按钮（SVG 图标）
        github_btn = QPushButton()
        github_btn.setObjectName('Ghost')
        github_btn.setCursor(Qt.PointingHandCursor)
        github_btn.setFixedWidth(40)
        github_btn.setToolTip('打开 SimLIBS GitHub 仓库')
        from PySide6.QtGui import QIcon
        github_btn.setIcon(QIcon(str(CLI_ROOT / 'assets' / 'github.svg')))
        github_btn.setIconSize(QSize(22, 22))
        github_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl('https://github.com/Noob-12345/SimLIBS')))
        top.addWidget(self.nist_chip)
        top.addWidget(self.status_chip)
        # 主题色预设（5 张预览卡）+ 日/夜/系统菜单
        self.theme_catalog_btn = QPushButton('🎨')
        self.theme_catalog_btn.setObjectName('Ghost')
        self.theme_catalog_btn.setCursor(Qt.PointingHandCursor)
        self.theme_catalog_btn.setFixedWidth(40)
        self.theme_catalog_btn.setToolTip('选择页面主题颜色')
        self.theme_catalog_btn.clicked.connect(self.open_theme_catalog)
        self.theme_mode_btn = QPushButton()
        self.theme_mode_btn.setObjectName('Ghost')
        self.theme_mode_btn.setCursor(Qt.PointingHandCursor)
        self.theme_mode_btn.setFixedWidth(40)
        self.theme_mode_btn.setToolTip('选择日间、夜间或跟随系统')
        self.theme_mode_btn.clicked.connect(self.show_theme_mode_menu)
        top.addWidget(github_btn)
        top.addWidget(self.theme_catalog_btn)
        top.addWidget(self.theme_mode_btn)
        main_lay.addWidget(topbar)

        # 页面栈
        self.stack = QStackedWidget()
        self.pages = {}
        self.pages['single'] = self._build_single()
        self.pages['batch'] = self._build_batch()
        self.pages['scan'] = self._build_scan()
        self.pages['jobs'] = self._build_jobs()
        self.pages['settings'] = self._build_settings()
        for pid, _ in PAGES:
            self.stack.addWidget(self.pages[pid])
        main_lay.addWidget(self.stack, 1)

        # 任务栏
        taskbar = QFrame()
        taskbar.setObjectName('Taskbar')
        task = vlay((12, 8, 12, 10), 6)
        taskbar.setLayout(task)
        line = QWidget()
        tl = hlay((0, 0, 0, 0), 12)
        line.setLayout(tl)
        self.task_status = QLabel('就绪')
        self.task_status.setMinimumWidth(360)
        self.task_progress = ShimmerProgress(self._pal())
        self.cancel_btn = QPushButton('取消任务')
        self.cancel_btn.setObjectName('Danger')
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel_job)
        tl.addWidget(self.task_status, 0)
        tl.addWidget(self.task_progress, 1)
        tl.addWidget(self.cancel_btn)
        task.addWidget(line)
        self.task_log = QPlainTextEdit()
        self.task_log.setObjectName('LogView')
        self.task_log.setReadOnly(True)
        self.task_log.setFixedHeight(104)
        self.task_log.setMaximumBlockCount(500)
        task.addWidget(self.task_log)
        main_lay.addWidget(taskbar)

        self.toasts = ToastHost(self)
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(450)
        self.play_timer.timeout.connect(self.advance_frame)

    # ---------------------------------------------------------------- 单次模拟
    def _build_single(self) -> QWidget:
        page = QWidget()
        lay = hlay((14, 4, 14, 6), 12)
        page.setLayout(lay)

        # 左列 = 滚动参数区 + 固定底部按钮
        left = QWidget()
        llay = vlay((0, 0, 0, 0), 8)
        left.setLayout(llay)
        lay.addWidget(left)

        # 左参数面板（QScrollArea 包裹，窗口小也可用）
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel = QWidget()
        pl = vlay((0, 0, 0, 0), 9)
        panel.setLayout(pl)
        panel.setMaximumWidth(350)
        scroll.setWidget(panel)
        llay.addWidget(scroll, 1)

        card_lay = card(pl)
        self.s_te = QLineEdit('1.0')
        self.s_ne = QLineEdit('1e17')
        self.s_r = QLineEdit('1000')
        self.s_low = QLineEdit('200')
        self.s_up = QLineEdit('700')
        self.s_charge = QLineEdit('2')
        # 滑块 + 数字输入双向同步
        te_to_text = lambda pos: f'{0.5 + pos / 1000 * 9.5:.4g}'                       # 0.5–10 eV
        te_from_text = lambda s: round((self.parse_float(s, 'Te') - 0.5) / 9.5 * 1000)
        ne_to_text = lambda pos: '1e' + f'{14 + pos / 1000 * 5:g}'                     # 1e14–1e19
        ne_from_text = lambda s: round((math.log10(self.parse_float(s, 'Ne')) - 14) / 5 * 1000)
        r_to_text = lambda pos: f'{round(100 * 200 ** (pos / 1000)):d}'                # 100–20000 对数
        r_from_text = lambda s: round(math.log(self.parse_float(s, 'R') / 100, 200) * 1000)

        def safe_field(make, *args):
            try:
                return make(*args)
            except (ValueError, ZeroDivisionError):
                return None
        self._slider_specs = {
            's_te': (te_to_text, te_from_text), 's_ne': (ne_to_text, ne_from_text),
            's_r': (r_to_text, r_from_text)}
        card_lay.addWidget(self._make_slider_row('Te [eV]', 's_te', safe_field))
        card_lay.addWidget(self._make_slider_row('Ne [cm⁻³]', 's_ne', safe_field))
        card_lay.addWidget(self._make_slider_row('分辨率 R', 's_r', safe_field))
        range_row = QWidget()
        rl = hlay((0, 0, 0, 0), 8)
        range_row.setLayout(rl)
        rl.addWidget(field_label('λ 范围 [nm]'), 0)
        rl.addWidget(self.s_low, 1)
        rl.addWidget(self.s_up, 1)
        card_lay.addWidget(range_row)
        card_lay.addWidget(field('最大离子电荷', self.s_charge))
        self.s_mode = QComboBox()
        self.s_mode.addItems(['本地模拟', '服务器计算', '客户端计算'])
        for i, tip in enumerate(('离线谱线库 · LTE/Saha 相对光子谱，无需网络/浏览器',
                                 'NIST 页面数据 + 浏览器内官方 JS 重算（要求 R≥100）',
                                 'NIST 线表 + Python 高斯核合成，无需浏览器')):
            self.s_mode.setItemData(i, tip, Qt.ToolTipRole)
        self.s_mode.setCurrentIndex(0)
        self.s_mode.currentIndexChanged.connect(self._mode_changed)
        self.s_scale = QComboBox()
        self.s_scale.addItems(['Photon Flux', 'Energy Flux'])
        self.s_scale.setItemData(0, '相对光子数（local 仅支持此项）', Qt.ToolTipRole)
        self.s_scale.setItemData(1, '能量通量（仅在线 server/client 可用）', Qt.ToolTipRole)
        self.s_title = QLineEdit()
        self.s_title.setPlaceholderText('图表标题（可选）')
        card_lay.addWidget(field('计算方式', self.s_mode))
        card_lay.addWidget(field('强度尺度', self.s_scale))
        card_lay.addWidget(field('图表标题', self.s_title))

        adv_lay = card(pl, '模式专属参数（随计算方式启用）')
        # 离线 local 专属（与 Web 同默认：展宽关闭 = 未展宽线谱，R/热/额外宽度均不应用）
        self.s_broaden = QCheckBox('离线展宽')
        self.s_broaden.setToolTip('开启后应用仪器 R、热 Doppler 与额外高斯/洛伦兹宽度；'
                                  '关闭（默认）= 未展宽线谱，R/热/额外宽度均不应用')
        adv_lay.addWidget(self.s_broaden)
        self.s_local_gauss = QLineEdit('0')
        self.s_local_lorentz = QLineEdit('0')
        self.s_temp_mode = QComboBox()
        self.s_temp_mode.addItems(['随电子温度（linked）', '独立温度（manual）'])
        self.s_temp_mode.setItemData(0, '单温度 LTE 假设：T_h = Te·e/k_B', Qt.ToolTipRole)
        self.s_temp_mode.setItemData(1, '独立输入重粒子温度 K（0 = 关闭热 Doppler）', Qt.ToolTipRole)
        self.s_temp_k = QLineEdit('0')
        self._rows_local = [
            adv_lay.addWidget(field('额外高斯宽度 [nm]', self.s_local_gauss)),
            adv_lay.addWidget(field('洛伦兹 FWHM [nm]', self.s_local_lorentz)),
            adv_lay.addWidget(field('重粒子温度模式', self.s_temp_mode)),
            adv_lay.addWidget(field('重粒子温度 [K]', self.s_temp_k)),
        ]
        self.s_temp_mode.currentIndexChanged.connect(lambda _: self._sync_local_rows())
        self.s_broaden.toggled.connect(lambda _: self._sync_local_rows())
        self._sync_local_rows()
        # 客户端 client 专属
        self.s_conv = QComboBox()
        self.s_conv.addItems(['NIST：w=λ/R', 'Physics：FWHM=λ/R'])
        self.s_conv.setItemData(0, 'NIST 官方约定：w=λ/R（1/e 半宽）', Qt.ToolTipRole)
        self.s_conv.setItemData(1, '物理约定：FWHM=λ/R', Qt.ToolTipRole)
        self.s_conv.setCurrentIndex(0)
        self.s_grid = QLineEdit('0.01')
        self.s_minrel = QLineEdit('0')
        self._rows_client = [
            adv_lay.addWidget(field('展宽约定', self.s_conv)),
            adv_lay.addWidget(field('展宽网格步长', self.s_grid)),
            adv_lay.addWidget(field('选线阈值', self.s_minrel)),
        ]
        # 通用
        self.s_step = QLineEdit('0.005')
        self.s_resample = QCheckBox('本地插值（重采样）')
        self.s_headless = QCheckBox('后台抓取')
        self.s_headless.setChecked(True)
        self.s_step_row = field('插值目标步长 [nm]', self.s_step)
        adv_lay.addWidget(self.s_step_row)
        adv_lay.addWidget(self.s_resample)
        adv_lay.addWidget(self.s_headless)
        self.s_resample.toggled.connect(
            lambda on: self.s_step_row.setVisible(on))

        comp_lay = card(pl, '配比（总和须为 100%，元素区分大小写）')
        self.comp_rows_widget = QWidget()
        self.comp_grid = QGridLayout(self.comp_rows_widget)
        self.comp_grid.setContentsMargins(0, 0, 0, 0)
        self.comp_grid.setSpacing(6)
        comp_lay.addWidget(self.comp_rows_widget)
        self._comp_rows: list[dict] = []
        btn_row = QWidget()
        bl = hlay((0, 0, 0, 0), 8)
        btn_row.setLayout(bl)
        add_btn = QPushButton('＋ 元素')
        norm_btn = QPushButton('归一化')
        add_btn.clicked.connect(lambda: self.comp_add_row())
        norm_btn.clicked.connect(self.comp_normalize)
        bl.addWidget(add_btn)
        bl.addWidget(norm_btn)
        bl.addStretch(1)
        comp_lay.addWidget(btn_row)
        self.sum_label = QLabel('✓ 100%')
        self.sum_label.setObjectName('SumLabel')
        comp_lay.addWidget(self.sum_label)
        self.local_capability_label = QLabel('')
        self.local_capability_label.setObjectName('MetaChips')
        self.local_capability_label.setWordWrap(True)
        comp_lay.addWidget(self.local_capability_label)
        pl.addStretch(1)
        self.comp_card_widget = panel

        # 开始模拟固定在面板底部（不随参数滚动）
        footer = QWidget()
        fl = hlay((0, 0, 0, 0), 8)
        footer.setLayout(fl)
        run_btn = QPushButton('▶  开始模拟')
        run_btn.setObjectName('Primary')
        run_btn.setCursor(Qt.PointingHandCursor)
        run_btn.clicked.connect(self.start_single)
        fl.addWidget(run_btn, 1)
        llay.addWidget(footer)

        # 右结果区
        right = QWidget()
        rl2 = vlay((0, 0, 0, 0), 6)
        right.setLayout(rl2)
        lay.addWidget(right, 1)

        self.s_legend = QLabel('')
        self.s_legend.setObjectName('Legend')
        rl2.addWidget(self.s_legend)
        chart_frame = QFrame()
        chart_frame.setObjectName('Card')
        cf = vlay((2, 2, 2, 2), 0)
        chart_frame.setLayout(cf)
        self.s_chart = SpectrumChart(chart_palette(self._pal()))
        cf.addWidget(self.s_chart)
        rl2.addWidget(chart_frame, 1)
        self.s_meta = QLabel('')
        self.s_meta.setObjectName('MetaChips')
        self.s_meta.setTextFormat(Qt.RichText)
        self.s_meta.setWordWrap(True)
        rl2.addWidget(self.s_meta)

        view_row = QWidget()
        vr = hlay((0, 0, 0, 0), 8)
        view_row.setLayout(vr)
        vr.addWidget(field_label('视图'))
        self.s_view = QComboBox()
        self.s_view.addItems(['插值谱', '原始谱', '元素贡献'])
        self.s_view.currentIndexChanged.connect(lambda _: self.paint_single())
        self.s_export_dir = QLineEdit(EXPORT_DIR)
        vr.addWidget(self.s_view)
        vr.addWidget(field_label('导出目录'), 0)
        vr.addWidget(self.s_export_dir, 1)
        rl2.addWidget(view_row)
        exp_row = QWidget()
        er = hlay((0, 0, 0, 0), 8)
        exp_row.setLayout(er)
        for label, kind in (('导出 CSV', 'csv'), ('导出 JSON', 'json'), ('导出 PNG', 'png')):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=kind: self.do_export(self._single_result, [k], self.s_export_dir.text()))
            er.addWidget(b)
        er.addStretch(1)
        rl2.addWidget(exp_row)
        self._mode_changed(self.s_mode.currentIndex())
        return page

    # ---------------------------------------------------------------- 批量
    def _build_batch(self) -> QWidget:
        page = QWidget()
        lay = hlay((14, 4, 14, 6), 12)
        page.setLayout(lay)
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)   # 兜底：内容超宽时可横向滚动
        scroll.setFixedWidth(410)   # 加宽：右侧结果区不再挤压左侧控件（含 5 列随机规则表）
        panel = QWidget()
        pl = vlay((0, 0, 0, 0), 9)
        panel.setLayout(pl)
        scroll.setWidget(panel)
        lay.addWidget(scroll)

        c1 = card(pl, '批量参数（独立于单次页，模式可任选）')
        self.b_mode = QComboBox()
        self.b_mode.addItems(['本地模拟', '服务器计算', '客户端计算'])
        for i, tip in enumerate(('离线谱线库 · LTE/Saha 相对光子谱，无需网络/浏览器',
                                 'NIST 页面数据 + 浏览器内官方 JS 重算（要求 R≥100）',
                                 'NIST 线表 + Python 高斯核合成，无需浏览器')):
            self.b_mode.setItemData(i, tip, Qt.ToolTipRole)
        self.b_mode.setCurrentIndex(0)
        self.b_te = QLineEdit('1.0')
        self.b_ne = QLineEdit('1e17')
        self.b_r = QLineEdit('3000')
        self.b_low = QLineEdit('200')
        self.b_up = QLineEdit('700')
        self.b_charge = QLineEdit('2')
        self.b_headless = QCheckBox('后台抓取')
        self.b_headless.setChecked(True)
        self.b_resample = QCheckBox('本地插值（统一重采样网格）')
        self.b_step = QLineEdit('0.01')
        self.b_grid = QLineEdit('0.01')
        self.b_minrel = QLineEdit('0')
        self.b_gauss = QLineEdit('0')
        self.b_lorentz = QLineEdit('0')
        self.b_temp_mode = QComboBox()
        self.b_temp_mode.addItems(['随电子温度（linked）', '独立温度（manual）'])
        self.b_temp_mode.setItemData(0, '单温度 LTE 假设：T_h = Te·e/k_B', Qt.ToolTipRole)
        self.b_temp_mode.setItemData(1, '独立输入重粒子温度 K（0 = 关闭热 Doppler）', Qt.ToolTipRole)
        self.b_temp_k = QLineEdit('0')
        c1.addWidget(field('计算方式', self.b_mode))
        self.b_scale = QComboBox()
        self.b_scale.addItems(['Photon Flux', 'Energy Flux'])
        c1.addWidget(field('强度尺度', self.b_scale))
        c1.addWidget(field('Te [eV]', self.b_te))
        c1.addWidget(field('Ne [cm⁻³]', self.b_ne))
        c1.addWidget(field('分辨率 R', self.b_r))
        row_lu = QWidget()
        rlu = hlay((0, 0, 0, 0), 8)
        row_lu.setLayout(rlu)
        rlu.addWidget(field_label('λ 范围 [nm]'), 0)
        rlu.addWidget(self.b_low, 1)
        rlu.addWidget(self.b_up, 1)
        c1.addWidget(row_lu)
        c1.addWidget(field('最大离子电荷', self.b_charge))
        c1.addWidget(self.b_headless)
        c1.addWidget(self.b_resample)
        self.b_step_row = field('插值目标步长 [nm]', self.b_step)
        c1.addWidget(self.b_step_row)
        self.b_step_row.setVisible(False)
        self.b_resample.toggled.connect(lambda on: self.b_step_row.setVisible(on))
        c1.addWidget(field('展宽网格步长 [nm]', self.b_grid))
        self.b_conv = QComboBox()
        self.b_conv.addItems(['NIST：w=λ/R', 'Physics：FWHM=λ/R'])
        self.b_conv.setItemData(0, 'NIST 官方约定：w=λ/R（1/e 半宽）', Qt.ToolTipRole)
        self.b_conv.setItemData(1, '物理约定：FWHM=λ/R', Qt.ToolTipRole)
        c1.addWidget(field('展宽约定', self.b_conv))
        c1.addWidget(field('选线阈值', self.b_minrel))
        self.b_broaden = QCheckBox('离线展宽')
        self.b_broaden.setToolTip('开启后应用仪器 R、热 Doppler 与额外高斯/洛伦兹宽度；'
                                  '关闭（默认）= 未展宽线谱，R/热/额外宽度均不应用')
        c1.addWidget(self.b_broaden)
        c1.addWidget(field('额外高斯宽度 [nm]', self.b_gauss))
        c1.addWidget(field('洛伦兹 FWHM [nm]', self.b_lorentz))
        c1.addWidget(field('重粒子温度模式', self.b_temp_mode))
        c1.addWidget(field('重粒子温度 [K]', self.b_temp_k))
        self.b_mode.currentIndexChanged.connect(self._batch_mode_changed)
        self.b_temp_mode.currentIndexChanged.connect(lambda _: self._sync_batch_local_rows())
        self.b_broaden.toggled.connect(lambda _: self._sync_batch_local_rows())

        c1b = card(pl)
        self.b_n = QLineEdit('10')
        self.b_seed = QLineEdit('0')
        self.b_temin = QLineEdit('1.0')
        self.b_temax = QLineEdit('2.0')
        self.b_nemin = QLineEdit('17')
        self.b_nemax = QLineEdit('18')
        c1b.addWidget(field('样本总数', self.b_n))
        c1b.addWidget(field('随机种子', self.b_seed))
        row_te = QWidget()
        r1 = hlay((0, 0, 0, 0), 8)
        row_te.setLayout(r1)
        self._te_label = field_label('Te 范围 [eV]')
        r1.addWidget(self._te_label, 0)
        r1.addWidget(self.b_temin, 1)
        r1.addWidget(self.b_temax, 1)
        c1b.addWidget(row_te)
        self._row_te = row_te
        row_ne = QWidget()
        r2 = hlay((0, 0, 0, 0), 8)
        row_ne.setLayout(r2)
        r2.addWidget(field_label('Ne 指数 (10^x)'), 0)
        r2.addWidget(self.b_nemin, 1)
        r2.addWidget(self.b_nemax, 1)
        c1b.addWidget(row_ne)
        self._row_ne = row_ne

        c_gen = card(pl, '生成方式（固定 / 随机 / CSV 模板，与 Web 版同协议）')
        self.b_generation = QComboBox()
        self.b_generation.addItems(['固定组成池', '随机采样', 'CSV 模板'])
        for i, tip in enumerate(('组成池随机选行 · Te/Ne 在范围内均匀采样',
                                 'Te/实际 Ne 与逐元素浓度在边界内有界顺序分配（种子确定）',
                                 '严格按行执行 · 行内参数列可覆盖')):
            self.b_generation.setItemData(i, tip, Qt.ToolTipRole)
        c_gen.addWidget(self.b_generation)
        self.b_rand_te = QCheckBox('随机 Te（用上方 Te 边界）')
        self.b_rand_te.setToolTip('启用后每个样本的 Te 在上方 Te 范围内均匀采样')
        c_gen.addWidget(self.b_rand_te)
        self.b_rand_ne = QCheckBox('随机实际 Ne [cm⁻³]')
        c_gen.addWidget(self.b_rand_ne)
        ne_bounds = QWidget()
        nb = hlay((0, 0, 0, 0), 8)
        ne_bounds.setLayout(nb)
        nb.addWidget(field_label('Ne 边界'), 0)
        self.b_ne_lo = QLineEdit('1e17')
        self.b_ne_hi = QLineEdit('2e17')
        nb.addWidget(self.b_ne_lo, 1)
        nb.addWidget(self.b_ne_hi, 1)
        c_gen.addWidget(ne_bounds)
        self._ne_bounds_row = ne_bounds
        rule_lbl = field_label('逐元素浓度规则（可编辑；随机元素在边界内有界顺序分配，总和恒 100%）')
        rule_lbl.setWordWrap(True)
        c_gen.addWidget(rule_lbl)
        self.b_rand_table = QTableWidget(0, 5)
        self.b_rand_table.setHorizontalHeaderLabels(['元素', '固定%', '随机', '下界', '上界'])
        self.b_rand_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 62), (2, 46), (3, 62), (4, 62)):
            self.b_rand_table.setColumnWidth(col, width)
        self.b_rand_table.verticalHeader().setVisible(False)
        self.b_rand_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.b_rand_table.setMinimumHeight(110)
        c_gen.addWidget(self.b_rand_table)
        rand_row = QWidget()
        rr2 = hlay((0, 0, 0, 0), 8)
        rand_row.setLayout(rr2)
        self.b_rand_from_pool = QPushButton('从组成池/当前配比生成规则')
        self.b_rand_from_pool.clicked.connect(self.batch_random_from_pool)
        rr2.addWidget(self.b_rand_from_pool)
        rr2.addStretch(1)
        c_gen.addWidget(rand_row)
        self.b_generation.currentIndexChanged.connect(lambda _: self._sync_batch_generation_ui())
        self.b_rand_te.toggled.connect(lambda _: self._sync_batch_generation_ui())
        self.b_rand_ne.toggled.connect(lambda _: self._sync_batch_generation_ui())

        c_tpl = card(pl, '模板 CSV（生成方式 = CSV 模板时使用 · 严格按行执行，行内可覆盖参数）')
        self.b_tpl_path = QLineEdit()
        self.b_tpl_path.setPlaceholderText('模板 CSV 路径…（元素列/参数列混排）')
        c_tpl.addWidget(self.b_tpl_path)
        self.b_repeats = QLineEdit('1')
        c_tpl.addWidget(field('每行重复次数', self.b_repeats))
        tpl_row = QWidget()
        tr = hlay((0, 0, 0, 0), 8)
        tpl_row.setLayout(tr)
        tpl_btn = QPushButton('校验模板')
        tpl_btn.clicked.connect(self.validate_template)
        tr.addWidget(tpl_btn)
        tr.addStretch(1)
        c_tpl.addWidget(tpl_row)
        self.b_tpl_info = QLabel('')
        self.b_tpl_info.setObjectName('MetaChips')
        self.b_tpl_info.setWordWrap(True)
        c_tpl.addWidget(self.b_tpl_info)
        self._template_widgets = [self.b_tpl_path, self.b_repeats, tpl_btn, self.b_tpl_info]

        c2 = card(pl, '组成候选池（CSV 元素列 + 可选 name 列）')
        self.b_csv = QLineEdit()
        self.b_csv.setPlaceholderText('组成 CSV 路径…')
        c2.addWidget(self.b_csv)
        imp_row = QWidget()
        ir = hlay((0, 0, 0, 0), 8)
        imp_row.setLayout(ir)
        imp_btn = QPushButton('导入 CSV')
        imp_btn.clicked.connect(self.import_batch_csv)
        self.b_norm_import = QCheckBox('导入时归一化')
        use_btn = QPushButton('用当前配比')
        use_btn.clicked.connect(self.batch_use_current)
        ir.addWidget(imp_btn)
        ir.addWidget(self.b_norm_import)
        ir.addWidget(use_btn)
        c2.addWidget(imp_row)
        self.b_comp_table = QTableWidget(0, 3)
        self.b_comp_table.setHorizontalHeaderLabels(['name', '组成', '总和'])
        self.b_comp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.b_comp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.b_comp_table.setAlternatingRowColors(True)
        self.b_comp_table.verticalHeader().setVisible(False)
        self.b_comp_table.setMinimumHeight(180)
        c2.addWidget(self.b_comp_table)
        self._pool_widgets = [self.b_csv, imp_btn, self.b_norm_import, use_btn, self.b_comp_table]
        run_btn = QPushButton('▶  开始批量')
        run_btn.setObjectName('Primary')
        run_btn.setCursor(Qt.PointingHandCursor)
        run_btn.clicked.connect(self.start_batch)
        c2.addWidget(run_btn)

        c3 = card(pl, '训练数据包（神经网络训练 · 参照 nist_R3000_min0 格式）')
        self.pk_size = QLineEdit('32')
        c3.addWidget(field('每包样本数', self.pk_size))
        self.pk_count = QLabel('预计 1 包 · 末包 10 条')
        self.pk_count.setObjectName('MetaChips')
        c3.addWidget(self.pk_count)
        self.b_n.textChanged.connect(self._update_pack_estimate)
        self.pk_size.textChanged.connect(self._update_pack_estimate)
        pk_hint = QLabel(' 批量成功后自动打包：ZIP 内 Random_spectra/contents 系列'
                         '（光谱两行交替、固定 28 元素标签列）+ package-manifest.json')
        pk_hint.setObjectName('MetaChips')
        pk_hint.setWordWrap(True)
        c3.addWidget(pk_hint)
        self.pk_btn = QPushButton('⬇ 下载训练数据包 ZIP')
        self.pk_btn.setEnabled(False)
        self.pk_btn.clicked.connect(self.download_training)
        c3.addWidget(self.pk_btn)

        right = QWidget()
        rl = vlay((0, 0, 0, 0), 6)
        right.setLayout(rl)
        lay.addWidget(right, 1)
        self.b_meta = QLabel('')
        self.b_meta.setObjectName('MetaChips')
        self.b_meta.setTextFormat(Qt.RichText)
        self.b_meta.setWordWrap(True)
        rl.addWidget(self.b_meta)
        self.b_samples = QTableWidget(0, 4)
        self.b_samples.setHorizontalHeaderLabels(['name', 'Te [eV]', 'Ne [cm⁻³]', '组成'])
        self.b_samples.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.b_samples.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.b_samples.setAlternatingRowColors(True)
        self.b_samples.verticalHeader().setVisible(False)
        self.b_samples.setStyleSheet('QTableWidget { background: transparent; border: 1px solid %s; border-radius: 12px; }'
                                     % self._pal()['brd'])
        rl.addWidget(self.b_samples, 1)
        self.b_wide = QLabel('')
        self.b_wide.setObjectName('MetaChips')
        self.b_wide.setWordWrap(True)
        rl.addWidget(self.b_wide)
        exp_row = QWidget()
        er = hlay((0, 0, 0, 0), 8)
        exp_row.setLayout(er)
        self.b_export_dir = QLineEdit(EXPORT_DIR)
        er.addWidget(field_label('导出目录'), 0)
        er.addWidget(self.b_export_dir, 1)
        b = QPushButton('导出数据集 CSV')
        b.clicked.connect(lambda: self.do_export(self._batch_result, ['dataset'], self.b_export_dir.text()))
        er.addWidget(b)
        rl.addWidget(exp_row)
        exp_row2 = QWidget()
        er2 = hlay((0, 0, 0, 0), 8)
        self.b_params_btn = QPushButton('下载实际参数 CSV')
        self.b_params_btn.setEnabled(False)
        self.b_params_btn.setToolTip('逐样本实际 Te/Ne/浓度/R/网格/温度/展宽开关（仅批量成功后可用）')
        self.b_params_btn.clicked.connect(lambda: self.do_export(self._batch_result, ['parameters'], self.b_export_dir.text()))
        self.b_tpl_btn = QPushButton('下载模板 CSV')
        self.b_tpl_btn.setEnabled(False)
        self.b_tpl_btn.setToolTip('可再次导入的模板 CSV（仅批量成功后可用）')
        self.b_tpl_btn.clicked.connect(lambda: self.do_export(self._batch_result, ['template'], self.b_export_dir.text()))
        er2.addWidget(self.b_params_btn)
        er2.addWidget(self.b_tpl_btn)
        er2.addStretch(1)
        rl.addWidget(exp_row2)
        self._batch_mode_changed(self.b_mode.currentIndex())
        return page

    # ---------------------------------------------------------------- 扫描
    def _build_scan(self) -> QWidget:
        page = QWidget()
        lay = hlay((14, 4, 14, 6), 12)
        page.setLayout(lay)
        panel_frame = QFrame()
        panel_frame.setObjectName('Card')
        pl = vlay((14, 12, 14, 12), 9)
        panel_frame.setLayout(pl)
        panel_frame.setFixedWidth(350)
        lay.addWidget(panel_frame)

        self.sc_axis = QComboBox()
        self.sc_axis.addItems(['Te [eV]', 'Ne 指数 (10^x)', '分辨率 R'])
        self.sc_axis.currentIndexChanged.connect(self._scan_axis_changed)
        self.sc_start = QLineEdit('0.5')
        self.sc_end = QLineEdit('5.0')
        self.sc_frames = QLineEdit('10')
        pl.addWidget(field('扫描轴', self.sc_axis))
        row = QWidget()
        rr = hlay((0, 0, 0, 0), 8)
        row.setLayout(rr)
        rr.addWidget(field_label('起 → 止'), 0)
        rr.addWidget(self.sc_start, 1)
        rr.addWidget(self.sc_end, 1)
        pl.addWidget(row)
        pl.addWidget(field('帧数', self.sc_frames))
        run_btn = QPushButton('▶  开始扫描')
        run_btn.setObjectName('Primary')
        run_btn.setCursor(Qt.PointingHandCursor)
        run_btn.clicked.connect(self.start_scan)
        pl.addWidget(run_btn)
        pl.addSpacing(6)
        play_row = QWidget()
        prl = hlay((0, 0, 0, 0), 8)
        play_row.setLayout(prl)
        self.sc_prev = QPushButton('⏮')
        self.sc_play = QPushButton('▶')
        self.sc_next = QPushButton('⏭')
        for b in (self.sc_prev, self.sc_play, self.sc_next):
            b.setCursor(Qt.PointingHandCursor)
        self.sc_prev.clicked.connect(self.prev_frame)
        self.sc_play.clicked.connect(self.toggle_play)
        self.sc_next.clicked.connect(self.next_frame)
        prl.addWidget(self.sc_prev)
        prl.addWidget(self.sc_play)
        prl.addWidget(self.sc_next)
        prl.addStretch(1)
        pl.addWidget(play_row)
        self.sc_frame_label = QLabel('无扫描结果')
        self.sc_frame_label.setObjectName('MetaChips')
        pl.addWidget(self.sc_frame_label)
        pl.addStretch(1)

        right = QWidget()
        rl = vlay((0, 0, 0, 0), 6)
        right.setLayout(rl)
        lay.addWidget(right, 1)
        self.sc_legend = QLabel('')
        self.sc_legend.setObjectName('Legend')
        rl.addWidget(self.sc_legend)
        chart_frame = QFrame()
        chart_frame.setObjectName('Card')
        cf = vlay((2, 2, 2, 2), 0)
        chart_frame.setLayout(cf)
        self.sc_chart = SpectrumChart(chart_palette(self._pal()))
        cf.addWidget(self.sc_chart)
        rl.addWidget(chart_frame, 1)
        self.sc_meta = QLabel('')
        self.sc_meta.setObjectName('MetaChips')
        self.sc_meta.setTextFormat(Qt.RichText)
        self.sc_meta.setWordWrap(True)
        rl.addWidget(self.sc_meta)
        exp_row = QWidget()
        er = hlay((0, 0, 0, 0), 8)
        exp_row.setLayout(er)
        self.sc_export_dir = QLineEdit(EXPORT_DIR)
        er.addWidget(field_label('导出目录'), 0)
        er.addWidget(self.sc_export_dir, 1)
        png_btn = QPushButton('导出当前帧 PNG')
        png_btn.clicked.connect(lambda: self.do_export(self._scan_result, ['png'], self.sc_export_dir.text(),
                                                       frame=self._frame_idx))
        gif_btn = QPushButton('导出 GIF')
        gif_btn.clicked.connect(lambda: self.do_export(self._scan_result, ['gif'], self.sc_export_dir.text()))
        er.addWidget(png_btn)
        er.addWidget(gif_btn)
        rl.addWidget(exp_row)
        return page

    # ---------------------------------------------------------------- 任务记录
    def _build_jobs(self) -> QWidget:
        page = QWidget()
        lay = hlay((14, 4, 14, 6), 12)
        page.setLayout(lay)
        panel_frame = QFrame()
        panel_frame.setObjectName('Card')
        pl = vlay((14, 12, 14, 12), 9)
        panel_frame.setLayout(pl)
        panel_frame.setFixedWidth(560)
        lay.addWidget(panel_frame)

        self.j_path = QLineEdit()
        self.j_path.setPlaceholderText('历史 CSV 路径（wavelength,intensity 或 NIST 格式）')
        pl.addWidget(self.j_path)
        row = QWidget()
        rr = hlay((0, 0, 0, 0), 8)
        row.setLayout(rr)
        open_btn = QPushButton('离线打开')
        open_btn.clicked.connect(self.open_history)
        refresh_btn = QPushButton('刷新任务')
        refresh_btn.clicked.connect(self.refresh_jobs)
        view_btn = QPushButton('查看结果')
        view_btn.clicked.connect(self.view_selected_job)
        resume_btn = QPushButton('↻ 续跑')
        resume_btn.clicked.connect(self.resume_selected_job)
        rr.addWidget(open_btn)
        rr.addWidget(refresh_btn)
        rr.addWidget(view_btn)
        rr.addWidget(resume_btn)
        pl.addWidget(row)
        self.j_table = QTableWidget(0, 7)
        self.j_table.setHorizontalHeaderLabels(['创建', '类型', '状态', '进度', '耗时', '摘要', 'ID'])
        self.j_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.j_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.j_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.j_table.setAlternatingRowColors(True)
        self.j_table.verticalHeader().setVisible(False)
        self.j_table.cellClicked.connect(self._job_row_clicked)
        pl.addWidget(self.j_table, 1)

        right = QWidget()
        rl = vlay((0, 0, 0, 0), 6)
        right.setLayout(rl)
        lay.addWidget(right, 1)
        lbl = QLabel('任务事件')
        lbl.setObjectName('PanelTitle')
        rl.addWidget(lbl)
        self.j_detail = QPlainTextEdit()
        self.j_detail.setObjectName('LogView')
        self.j_detail.setReadOnly(True)
        self.j_detail.setMaximumBlockCount(800)
        rl.addWidget(self.j_detail, 1)
        return page

    # ---------------------------------------------------------------- 设置
    def _build_settings(self) -> QWidget:
        page = QWidget()
        lay = hlay((14, 4, 14, 6), 12)
        page.setLayout(lay)
        panel_frame = QFrame()
        panel_frame.setObjectName('Card')
        pl = vlay((14, 12, 14, 12), 9)
        panel_frame.setLayout(pl)
        panel_frame.setFixedWidth(520)
        lay.addWidget(panel_frame)

        self.st = {}
        for key, label in (('connect_timeout', '连接超时 [s]'), ('read_timeout', '读取超时 [s]'),
                           ('page_load', '页面加载 [s]'), ('static_deadline', 'static 期限 [s]'),
                           ('dynamic_deadline', 'dynamic 期限 [s]')):
            w = QLineEdit()
            self.st[key] = w
            pl.addWidget(field(label, w))
        for key, label in (('output_dir', '输出目录'), ('source', '源库路径'),
                           ('python', 'Python 解释器'), ('chrome', 'Chrome 路径'),
                           ('driver', 'ChromeDriver 路径')):
            w = QLineEdit()
            self.st[key] = w
            pl.addWidget(field(label, w))
        self.st_proxy = QLineEdit()
        self.st_proxy.setPlaceholderText('留空=直连；例如 http://127.0.0.1:7890（NIST 被干扰时可用）')
        pl.addWidget(field('网络代理', self.st_proxy))
        self.st['tls_verify'] = QCheckBox('TLS 证书校验（默认开启，关闭需自担风险）')
        pl.addWidget(self.st['tls_verify'])
        row = QWidget()
        rr = hlay((0, 0, 0, 0), 8)
        row.setLayout(rr)
        save = QPushButton('保存设置')
        save.setObjectName('Primary')
        save.clicked.connect(self.save_settings)
        reset = QPushButton('恢复默认')
        reset.clicked.connect(self.reset_settings)
        rr.addWidget(save)
        rr.addWidget(reset)
        rr.addStretch(1)
        pl.addWidget(row)
        pl.addStretch(1)

        right = QWidget()
        rl = vlay((0, 0, 0, 0), 6)
        right.setLayout(rl)
        lay.addWidget(right, 1)
        self.st_info = QLabel('')
        self.st_info.setObjectName('MetaChips')
        self.st_info.setTextFormat(Qt.RichText)
        self.st_info.setWordWrap(True)
        self.st_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        rl.addWidget(self.st_info)
        rl.addStretch(1)
        return page

    # ================================================================== 启动
    def _startup(self) -> None:
        self._setup_brand_icon()
        self.preset_h()
        self.load_settings_form()
        self.refresh_engine()
        self.refresh_jobs()
        self.log('SimLIBS · SPECTRUM WORKBENCH FOR SCNU 就绪 · 本地/服务器/客户端三路径 · '
                 '本地默认未展宽线谱（勾选"离线展宽"应用 R/热/额外宽度） · '
                 '图表：左键框选放大 / 中键或 Shift 平移 / 右键复位')

    def _mode_changed(self, idx: int) -> None:
        """v3：本地/服务器/客户端三路径，按模式启用参数并刷新补全与状态。"""
        local, client = idx == 0, idx == 2
        if local:
            self.s_scale.setCurrentIndex(0)      # 本地仅相对光子（web 同规则）
        self.s_scale.setEnabled(not local)
        self.s_broaden.setEnabled(local)
        self._sync_local_rows()
        for wdg in (self.s_conv, self.s_grid, self.s_minrel):
            wdg.setEnabled(client)
        self._refresh_element_completions()
        self.refresh_engine()

    def _sync_local_rows(self) -> None:
        """离线展宽关闭（或非本地模式）时，宽度/温度参数不可用（web 同语义）。"""
        on = self.s_mode.currentIndex() == 0 and self.s_broaden.isChecked()
        self.s_local_gauss.setEnabled(on)
        self.s_local_lorentz.setEnabled(on)
        self.s_temp_mode.setEnabled(on)
        self.s_temp_k.setEnabled(on and self.s_temp_mode.currentIndex() == 1)

    def go(self, pid: str) -> None:
        titles = dict(PAGES)
        old_widget = self.stack.currentWidget()
        new_widget = self.pages[pid]
        switching = old_widget is not new_widget
        self.stack.setCurrentWidget(new_widget)
        self.page_title.setText(titles[pid])
        for p, btn in self._nav_buttons.items():
            btn.setChecked(p == pid)
        if not switching or self.fade_ms <= 0:
            return
        # 位图交叉过渡（旧页淡出上移 / 新页滑入）+ 内容错峰入场
        fade_between(self.stack, old_widget, duration=320)
        stagger_entrance(new_widget, duration=200, stagger_ms=40)

    def _go_single(self) -> None:
        self.go('single')

    def _go(self, pid: str) -> None:
        self.go(pid)

    # ================================================================== 主题
    def _apply_theme(self) -> None:
        self._current_palette = self._build_palette()
        self.theme_name = f"{self.theme_pref['preset']}-{('light' if not self._effective_dark() else 'dark')}"
        app = QApplication.instance()
        apply_fusion_palette(app, self._pal())
        app.setStyleSheet(build_qss(self._pal()))
        for chart in (self.s_chart, self.sc_chart):
            chart.set_palette(chart_palette(self._pal()))
        self.task_progress.set_palette(self._pal())
        if self._series_spec:
            self._repaint_series_spec()
        if hasattr(self, '_last_engine'):
            self._update_engine(self._last_engine)
        self._update_theme_buttons()
        self._save_theme_pref()

    def _update_theme_buttons(self) -> None:
        mode = self.theme_pref['mode']
        icon_file = {'dark': 'moon.svg', 'light': 'sun.svg', 'system': 'monitor.svg'}.get(mode, 'moon.svg')
        self.theme_mode_btn.setIcon(
            svg_icon(CLI_ROOT / 'assets' / icon_file, self._pal()['muted'], size=20))
        self.theme_mode_btn.setIconSize(QSize(20, 20))
        if mode == 'system':
            tip = f'跟随系统 · 当前{"夜间" if self._effective_dark() else "日间"}'
        else:
            tip = '夜间' if mode == 'dark' else '日间'
        self.theme_mode_btn.setToolTip(tip + '，点击选择日间/夜间/跟随系统')
        name = THEME_PRESETS[self.theme_pref['preset']]['name']
        self.theme_catalog_btn.setToolTip(f'页面主题颜色：{name}')

    def open_theme_catalog(self) -> None:
        dlg = ThemeCatalogDialog(self, selected=self.theme_pref['preset'])
        if dlg.exec() == ThemeCatalogDialog.Accepted and dlg.selected:
            self.theme_pref['preset'] = dlg.selected
            self._apply_theme()
            self.toast(f'页面主题已切换：{THEME_PRESETS[dlg.selected]["name"]}', timeout=2000)

    def show_theme_mode_menu(self) -> None:
        menu = QMenu(self)
        menu.setObjectName('ThemeMenu')
        icons = {'light': 'sun.svg', 'dark': 'moon.svg', 'system': 'monitor.svg'}
        for mode_id, label in (('light', '日间'), ('dark', '夜间'), ('system', '跟随系统')):
            act = menu.addAction(
                svg_icon(CLI_ROOT / 'assets' / icons[mode_id], self._pal()['text'], size=18), label)
            act.setCheckable(True)
            act.setChecked(self.theme_pref['mode'] == mode_id)
            act.triggered.connect(lambda _=False, m=mode_id: self._set_theme_mode(m))
        menu.exec(self.theme_mode_btn.mapToGlobal(
            QPoint(0, self.theme_mode_btn.height() + 4)))

    def _set_theme_mode(self, mode: str) -> None:
        self.theme_pref['mode'] = mode
        self._apply_theme()
        self.toast('主题模式：' + {'light': '日间', 'dark': '夜间', 'system': '跟随系统'}[mode],
                   timeout=2000)

    def _setup_brand_icon(self) -> None:
        """窗口/应用图标 = popcat.gif（缺失时回退 graduation.jpg）。"""
        for name in ('popcat.gif', 'graduation.jpg'):
            file = CLI_ROOT / 'assets' / name
            if not file.is_file():
                continue
            icon = QIcon(str(file))
            self.setWindowIcon(icon)
            QApplication.instance().setWindowIcon(icon)
            break

    def _repaint_series_spec(self) -> None:
        p = self._pal()
        spec = []
        for s in self._series_spec:
            key = s.get('color_key')
            spec.append({**s, 'color': p.get(key, s.get('color', p['accent']))})
        # 主题切换后按新配色重绘当前页图表（保留视窗）
        chart = self.s_chart if self.stack.currentWidget() is self.pages['single'] else \
            self.sc_chart if self.stack.currentWidget() is self.pages['scan'] else None
        if chart is not None:
            chart.set_series(spec, reset_view=False)

    # ================================================================== 工具
    def toast(self, message: str, kind: str = 'info', timeout: int = 4500) -> None:
        self.toasts.show(message, kind, timeout)

    def log(self, message: str, level: str = 'info') -> None:
        color = self._pal().get(
            {'info': 'muted', 'ok': 'good', 'warn': 'warn', 'error': 'bad'}.get(level, 'muted'))
        ts = datetime.now().strftime('%H:%M:%S')
        self.task_log.appendPlainText(f'[{ts}] {message}')
        self.task_log.setStyleSheet('')  # 保持 QSS

    def run_bg(self, fn, on_done=None) -> None:
        task = BackgroundTask(fn, self)
        self._threads.append(task)
        if on_done is not None:
            task.done.connect(on_done)
        task.failed.connect(lambda msg: self.toast(f'出错了：{msg}', 'error', 6000))
        task.finished.connect(lambda: self._threads.remove(task) if task in self._threads else None)
        task.start()

    @staticmethod
    def parse_float(raw: str, name: str) -> float:
        try:
            v = float(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f'{name} 不是合法数字：{raw!r}') from None
        if not math.isfinite(v):
            raise ValueError(f'{name} 必须是有限数值')
        return v

    @staticmethod
    def parse_int(raw: str, name: str) -> int:
        f = MainWindow.parse_float(raw, name)
        if f != int(f):
            raise ValueError(f'{name} 必须是整数')
        return int(f)

    # ================================================================== 配比
    def comp_add_row(self, el: str = '', pct: str = '') -> None:
        row = len(self._comp_rows)
        el_in = QLineEdit(el)
        el_in.setPlaceholderText('元素')
        el_in.setFixedWidth(84)
        el_in.setCompleter(self._element_completer())
        el_in.setToolTip('输入首字母自动补全元素；fe 等大小写会在失焦时自动规范为 Fe')

        def canonicalize() -> None:
            fixed = self._canonical_element(el_in.text())
            if fixed != el_in.text():
                el_in.setText(fixed)

        el_in.editingFinished.connect(canonicalize)
        pct_in = QLineEdit(pct)
        pct_in.setPlaceholderText('%')
        del_btn = QPushButton('✕')
        del_btn.setFixedWidth(34)
        rec = {'el': el_in, 'pct': pct_in}
        self._comp_rows.append(rec)
        el_in.textChanged.connect(self.comp_update_sum)
        pct_in.textChanged.connect(self.comp_update_sum)
        del_btn.clicked.connect(lambda: self.comp_del_row(rec))
        self.comp_grid.addWidget(el_in, row, 0)
        self.comp_grid.addWidget(pct_in, row, 1)
        self.comp_grid.addWidget(del_btn, row, 2)
        self.comp_update_sum()

    def comp_del_row(self, rec: dict) -> None:
        if rec in self._comp_rows:
            self._comp_rows.remove(rec)
        for w in (rec['el'], rec['pct']):
            w.setParent(None)
            w.deleteLater()
        self.comp_regrid()

    def comp_regrid(self) -> None:
        while self.comp_grid.count():
            item = self.comp_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for i, rec in enumerate(self._comp_rows):
            self.comp_grid.addWidget(rec['el'], i, 0)
            self.comp_grid.addWidget(rec['pct'], i, 1)
            del_btn = QPushButton('✕')
            del_btn.setFixedWidth(34)
            del_btn.clicked.connect(lambda _=False, r=rec: self.comp_del_row(r))
            self.comp_grid.addWidget(del_btn, i, 2)
            rec['_del'] = del_btn
        self.comp_update_sum()

    def comp_values(self) -> list[tuple[str, float]]:
        out = []
        for rec in self._comp_rows:
            el = rec['el'].text().strip()
            pct_raw = rec['pct'].text().strip()
            if not el and not pct_raw:
                continue
            out.append((el, self.parse_float(pct_raw, f'配比 {el or "?"}')))
        return out

    def comp_update_sum(self, *_):
        try:
            vals = self.comp_values()
            total = sum(p for _, p in vals)
            ok = bool(vals) and abs(total - 100.0) <= 1e-6
        except ValueError as exc:
            self.sum_label.setText(f'✗ {exc}')
            self.sum_label.setProperty('class', 'bad')
            self._repolish(self.sum_label)
            return
        p = self._pal()
        if ok:
            self.sum_label.setText('✓ 100%')
        else:
            self.sum_label.setText(f'✗ 总和 {total:.6g}%（须为 100%）')
        self.sum_label.setStyleSheet(f'color: {p["good"] if ok else p["bad"]}; font-size: 12px;')

    def comp_normalize(self) -> None:
        try:
            vals = self.comp_values()
        except ValueError as exc:
            self.toast(str(exc), 'warning')
            return
        if not vals:
            self.toast('配比为空', 'warning')
            return
        total = sum(p for _, p in vals)
        if total <= 0:
            self.toast('总和必须为正数才能归一化', 'warning')
            return
        before = ' '.join(f'{el}{p:g}' for el, p in vals)
        for rec, (el, pct) in zip(self._comp_rows, vals):
            rec['pct'].setText(f'{pct / total * 100:.6g}')
        after = ' '.join(f'{el}{pct / total * 100:g}' for el, pct in vals)
        self.log(f'[norm] 归一化：{before} → {after}')
        self.toast(f'已归一化（主动操作，共 {len(vals)} 项）', 'success', 2500)

    @staticmethod
    def _repolish(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _current_mode(self) -> str:
        return ('local', 'server', 'client')[self.s_mode.currentIndex()]

    def _available_elements(self) -> list[str]:
        """补全候选：本地模式只列离线谱线库真正可用的元素，在线模式给完整周期表。"""
        if self._current_mode() == 'local':
            try:
                st = self.backend.engine_status('local')
                elements = (st.get('local') or {}).get('elements') or []
                if elements:
                    return [str(e) for e in elements]
            except Exception:
                pass
            return []
        from simlibs_ui.models import ELEMENTS
        return sorted(ELEMENTS)

    def _refresh_element_completions(self) -> None:
        """模式切换后刷新所有配比输入框的补全候选（本地模式只列库内可用元素）。"""
        available = self._available_elements()
        if getattr(self, '_element_model', None) is None:
            return
        self._element_model.setStringList(available)
        if self._current_mode() == 'local':
            try:
                local = (getattr(self, '_last_engine', None) or {}).get('local') or {}
                if local:
                    self.local_capability_label.setText(
                        f"本地谱线库：{local.get('csv_count', '?')} CSV · "
                        f"{len(local.get('elements') or [])} 元素可用")
            except Exception:
                pass
        else:
            self.local_capability_label.setText('')

    def _element_completer(self) -> QCompleter:
        if getattr(self, '_element_model', None) is None:
            from PySide6.QtCore import QStringListModel
            self._element_model = QStringListModel(self._available_elements())
        completer = QCompleter(self._element_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchStartsWith)
        completer.popup().setStyleSheet(
            f'QListView {{ background: {self._pal()["card2"]};'
            f' color: {self._pal()["text"]};'
            f' selection-background-color: {self._pal()["hover"]}; }}')
        return completer

    @staticmethod
    def _canonical_element(text: str) -> str:
        """fe → Fe（唯一大小写不敏感匹配时自动规范化）。"""
        from simlibs_ui.models import ELEMENTS
        txt = text.strip()
        if not txt:
            return txt
        matches = [e for e in ELEMENTS if e.lower() == txt.lower()]
        return matches[0] if len(matches) == 1 else txt

    def _make_slider_row(self, label: str, key: str, safe_field):
        line_edit = {'s_te': self.s_te, 's_ne': self.s_ne, 's_r': self.s_r}[key]
        to_text, from_text = self._slider_specs[key]
        def guarded_to_text(pos):
            try:
                return to_text(pos)
            except (ValueError, OverflowError, ZeroDivisionError):
                return line_edit.text()
        def guarded_from_text(s):
            try:
                return from_text(s)
            except (ValueError, OverflowError, ZeroDivisionError):
                return None
        row = self.slider_field(label, line_edit, guarded_to_text, guarded_from_text)
        return row

    def slider_field(self, label: str, line_edit: QLineEdit,
                     to_text, from_text) -> QWidget:
        """数值输入 + 滑块双向同步（滑块拖动改输入框，输入框编辑后滑块跟随）。"""
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 1000)
        slider.setCursor(Qt.PointingHandCursor)

        def slider_to_edit(pos: int) -> None:
            line_edit.blockSignals(True)
            line_edit.setText(to_text(pos))
            line_edit.blockSignals(False)

        def edit_to_slider() -> None:
            try:
                pos = from_text(line_edit.text())
            except (ValueError, ZeroDivisionError):
                return
            if pos is None:
                return
            slider.blockSignals(True)
            slider.setValue(int(max(0, min(1000, pos))))
            slider.blockSignals(False)

        slider.valueChanged.connect(slider_to_edit)
        line_edit.editingFinished.connect(edit_to_slider)
        edit_to_slider()
        box = QWidget()
        lay = hlay((0, 0, 0, 0), 8)
        lbl = field_label(label)
        lbl.setMinimumWidth(96)
        lay.addWidget(lbl)
        line_edit.setFixedWidth(92)
        lay.addWidget(line_edit)
        lay.addWidget(slider, 1)
        box.setLayout(lay)
        return box

    # ================================================================== 预设
    def preset_h(self) -> None:
        """默认参数：Fe 100% · local 模式 · 200–700nm · R3000 · 电荷 2（与 Web 默认一致）。"""
        self.fill_single(1.0, 1e17, 3000, 200, 700, 2, [('Fe', 100.0)])

    def preset_wfm(self) -> None:
        self.fill_single(1.0, 1e17, 3000, 200, 700, 2,
                         [('W', 50.0), ('Fe', 25.0), ('Mo', 25.0)])

    def fill_single(self, te, ne, r, low, up, charge, comp) -> None:
        self.s_te.setText(str(te))
        self.s_ne.setText(f'{ne:.3e}'.replace('e+', 'e') if ne >= 1e4 else f'{ne:g}')
        self.s_r.setText(str(r))
        self.s_low.setText(str(low))
        self.s_up.setText(str(up))
        self.s_charge.setText(str(charge))
        for rec in list(self._comp_rows):
            self.comp_del_row(rec)
        for el, pct in comp:
            self.comp_add_row(el, f'{pct:g}')
        self.show_placeholder()

    def show_placeholder(self) -> None:
        """运行前的本地示意图（明确标注，不冒充真实数据）。"""
        try:
            low, up = self.parse_float(self.s_low.text(), 'λ'), self.parse_float(self.s_up.text(), 'λ')
            if not (0 < low < up):
                raise ValueError
        except ValueError:
            low, up = 650.0, 660.0
        try:
            comp = [el for el, _ in self.comp_values()] or ['H']
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
        p = self._pal()
        self._set_chart(self.s_chart, [{'label': '示意', 'xs': xs, 'ys': ys,
                                        'color': p['muted'], 'dotted': True, 'color_key': 'muted'}])
        self.s_legend.setText('示意预览 · 运行后替换为真实光谱')

    def _set_chart(self, chart: SpectrumChart, spec: list[dict]) -> None:
        chart.set_series([{k: v for k, v in s.items() if k != 'color_key'} for s in spec])
        if chart is self.s_chart:
            self._single_series_spec = spec
        else:
            self._scan_series_spec = spec

    # ================================================================== 参数
    def _single_params_dict(self) -> dict:
        def f(sel, name):
            return self.parse_float(sel.text(), name)
        mode = ('local', 'server', 'client')[self.s_mode.currentIndex()]
        charge = self.parse_int(self.s_charge.text(), '最大离子电荷')
        if not 0 <= charge <= 2:
            raise ValueError('最大离子电荷须为 0–2（本地谱线库与 NIST v2 均只支持 I/II）')
        resample = self.s_resample.isChecked()
        broaden = self.s_broaden.isChecked() if mode == 'local' else True
        d = {
            'te': f(self.s_te, 'Te'), 'ne': f(self.s_ne, 'Ne'),
            'resolution': self.parse_int(self.s_r.text(), '分辨率 R'),
            'low_w': f(self.s_low, 'λ 下界'), 'up_w': f(self.s_up, 'λ 上界'),
            'max_ion_charge': charge,
            'mode': mode, 'mode_version': 2,
            'headless': self.s_headless.isChecked(),
            'resample': resample,
            'intensity_scale': 'photon' if mode == 'local'
                else ('photon', 'energy')[self.s_scale.currentIndex()],
            'broadening': 'local' if mode in ('local', 'client') else 'nist',
            'local_broadening_enabled': broaden,
        }
        if resample:
            d['resample_step'] = f(self.s_step, '重采样步长')
        if mode == 'local':
            d['broaden_convention'] = 'physics'   # 离线本地固定 FWHM=λ/R
            if broaden:
                d['local_gaussian_nm'] = f(self.s_local_gauss, '额外高斯宽度')
                d['local_lorentz_nm'] = f(self.s_local_lorentz, '洛伦兹 FWHM')
                d['local_temperature_mode'] = ('linked', 'manual')[self.s_temp_mode.currentIndex() == 1]
                d['local_temperature_K'] = 0.0 if d['local_temperature_mode'] == 'linked' \
                    else f(self.s_temp_k, '重粒子温度')
            else:
                d['local_gaussian_nm'] = 0.0
                d['local_lorentz_nm'] = 0.0
                d['local_temperature_mode'] = 'linked'
                d['local_temperature_K'] = 0.0
        elif mode == 'client':
            d['broaden_convention'] = 'physics' if self.s_conv.currentIndex() == 1 else 'nist'
            d['broaden_grid_step'] = f(self.s_grid, '展宽网格步长')
            d['broaden_min_rel_int'] = f(self.s_minrel, '选线阈值')
        return d

    # ================================================================== 单次
    def start_single(self) -> None:
        from backend_api import CommonParams, CompositionItem, SingleRequest, validate_composition
        try:
            params = CommonParams.from_api(self._single_params_dict())
            params.check_points()
            comp = [CompositionItem(el, pct) for el, pct in self.comp_values()]
            validate_composition(comp)
        except Exception as exc:
            self.toast(str(exc), 'warning', 6000)
            return
        req = SingleRequest(params=params, composition=comp, title=self.s_title.text().strip())
        try:
            jid = self.backend.start_single(req)
        except Exception as exc:
            self.toast(str(exc), 'error', 6000)
            return
        launcher = lambda: self.backend.start_single(req)
        self.watch(jid, f'单次模拟 · {params.summary()}', launcher=launcher)

    @staticmethod
    def _aggregate_elements(ions: list[dict]) -> list[dict]:
        """同元素各真实离子贡献求和（排除总谱/Exp/Residual 由调用方过滤）；颜色按元素稳定。"""
        import re
        from collections import OrderedDict
        groups: "OrderedDict[str, list[dict]]" = OrderedDict()
        for ion in ions or []:
            label = str(ion.get('label', ''))
            m = re.match(r'^([A-Z][a-z]?)\s', label + ' ')
            el = m.group(1) if m else label
            groups.setdefault(el, []).append(ion)
        out = []
        for i, (el, items) in enumerate(groups.items()):
            xs = items[0]['xs']
            total = [0.0] * len(xs)
            for it in items:
                for j, v in enumerate(it['ys']):
                    total[j] += float(v)
            out.append({'label': el, 'xs': xs, 'ys': total})
        return out

    def paint_single(self) -> None:
        result = self._single_result
        if not result:
            return
        view = self.s_view.currentIndex()   # 0 插值 1 原始 2 元素贡献
        p = self._pal()
        series = result.get('series') or {}
        if not series and result.get('xs'):   # MOCK 引擎返回顶层 xs/ys
            series = {'interpolated': {'label': 'spectrum', 'xs': result['xs'], 'ys': result['ys']}}
        spec = []
        main = series.get('interpolated') or series.get('raw')
        if view != 1 and main:
            spec.append({'label': '主线', 'xs': main['xs'], 'ys': main['ys'],
                         'color': p['accent'], 'color_key': 'accent'})
        if view == 2:
            # 元素贡献：同元素各离子求和，颜色按元素稳定（总谱/Exp/Residual 已由后端排除）
            for i, el in enumerate(self._aggregate_elements(series.get('ions') or [])):
                key = ION_KEYS[i % len(ION_KEYS)]
                spec.append({'label': str(el.get('label')), 'xs': el['xs'], 'ys': el['ys'],
                             'color': p[key], 'color_key': key})
        else:
            for i, ion in enumerate(series.get('ions') or []):
                if view == 1:
                    break
                key = ION_KEYS[i % len(ION_KEYS)]
                spec.append({'label': str(ion.get('label')), 'xs': ion['xs'], 'ys': ion['ys'],
                             'color': p[key], 'color_key': key})
        if view == 1 and series.get('raw'):
            spec.append({'label': 'raw', 'xs': series['raw']['xs'], 'ys': series['raw']['ys'],
                         'color': p['raw'], 'dotted': True, 'color_key': 'raw'})
        self._series_spec = spec
        # web 约定：实际科学数据不做 morph/reveal 插值动画
        self.s_chart.set_series([{k: v for k, v in s.items() if k != 'color_key'} for s in spec],
                                animate=False)
        self.s_legend.setText(self._legend_text(spec, (result.get('meta') or {}).get('intensity_scale')))

    def _legend_text(self, spec: list[dict], scale: str | None) -> str:
        p = self._pal()
        name = {'photon': 'Photon flux', 'energy': 'Energy flux'}.get(scale or '', '尺度 unknown')
        parts = [f'<span style="color:{s["color"]}">●</span> {s["label"]}' for s in spec]
        return ' · '.join(parts) + f'　<i>{name} (a.u.)</i>'

    def show_single(self, result: dict) -> None:
        self._single_result = result
        self.paint_single()
        meta = result.get('meta') or {}
        bits = [f'<b>{meta.get("source", "")}</b>']
        if meta.get('points'):
            bits.append(str(meta['points']))
        if meta.get('sha256'):
            bits.append(f'SHA {meta["sha256"]}')
        if meta.get('ne_actual') is not None:
            try:
                bits.append(f'实际 Ne={float(meta["ne_actual"]):.3g}')
            except (TypeError, ValueError):
                bits.append(f'实际 Ne={meta["ne_actual"]}')
        if meta.get('intensity_scale'):
            name = {'photon': 'Photon', 'energy': 'Energy'}.get(meta.get('intensity_scale'), '尺度 unknown')
            bits.append(f'{name} flux (a.u.)')
        if meta.get('mode') or meta.get('mode_version'):
            bits.append(f"{meta.get('mode', '')} v{meta.get('mode_version', '')}".strip())
        if meta.get('requested_resolution') is not None:
            bits.append(f'请求R={meta["requested_resolution"]}')
        if meta.get('initial_server_resolution') is not None:
            bits.append(f'服务器初始R={meta["initial_server_resolution"]}')
        for key, label in (('computation_location', '计算'), ('broadening', '展宽'),
                           ('actual_resolution', '实际R')):
            if meta.get(key) is not None:
                bits.append(f'{label}={meta[key]}')
        if meta.get('local_broadening_enabled') is False:
            bits.append(f'<span style="color:{self._pal()["warn"]}">未展宽 · R未应用</span>')
        txt = ' · '.join(bits)
        self.s_meta.setText(txt)
        if meta.get('resolution_warning'):
            self.s_meta.setText(txt + f'<br><span style="color:{self._pal()["bad"]}">⚠ '
                                      f'{meta["resolution_warning"]}</span>')

    # ================================================================== 批量
    def import_batch_csv(self) -> None:
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

        path = self.b_csv.text().strip().strip('"')
        if not path:
            self.toast('请先填写组成 CSV 路径', 'warning')
            return
        try:
            df = pd.read_csv(path, encoding='utf-8-sig')
        except Exception as exc:
            self.toast(f'无法读取 CSV：{exc}', 'error', 6000)
            return
        df = df.loc[:, [c for c in df.columns if not str(c).startswith('Unnamed:')]]
        name_col = next((c for c in df.columns
                         if str(c).strip().lower() in ('name', 'samples', 'sample')), None)
        el_map = {c: el_of(c) for c in df.columns if c != name_col and el_of(c)}
        if not el_map:
            self.toast('CSV 中没有可识别的元素列（如 H、He、Fe 或 *_at%）', 'error', 6000)
            return
        normalize = self.b_norm_import.isChecked()
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
        self.b_comp_table.setRowCount(0)
        for r in rows:
            i = self.b_comp_table.rowCount()
            self.b_comp_table.insertRow(i)
            self.b_comp_table.setItem(i, 0, QTableWidgetItem(r['name']))
            self.b_comp_table.setItem(i, 1, QTableWidgetItem(' '.join(f'{it.el}{it.pct:g}' for it in r['items'])))
            self.b_comp_table.setItem(i, 2, QTableWidgetItem(f"{r['total']:.6g}%"))
        if errors:
            self.toast(f'{len(rows)} 行导入，{len(errors)} 行未通过校验（可勾选"导入时归一化"）\n{errors[0]}',
                       'warning', 8000)
        else:
            self.toast(f'已导入 {len(rows)} 行组成', 'success', 2500)

    def batch_use_current(self) -> None:
        from backend_api import CompositionItem, validate_composition
        try:
            vals = self.comp_values()
            if not vals:
                raise ValueError('当前配比为空')
            items = [CompositionItem(el, pct) for el, pct in vals]
            validate_composition(items)
        except Exception as exc:
            self.toast(str(exc), 'warning', 5000)
            return
        self._batch_pool = [{'name': 'current', 'items': items, 'total': 100.0}]
        self.b_comp_table.setRowCount(0)
        self.b_comp_table.insertRow(0)
        self.b_comp_table.setItem(0, 0, QTableWidgetItem('current'))
        self.b_comp_table.setItem(0, 1, QTableWidgetItem(' '.join(f'{el}{p:g}' for el, p in vals)))
        self.b_comp_table.setItem(0, 2, QTableWidgetItem('100%'))
        self.toast('已用单次模拟页当前配比作为候选池（1 行）', 'success', 2500)

    def _batch_mode_changed(self, idx: int) -> None:
        """批量三路径按模式启停参数：local 用离线展宽/温度，client 用网格/阈值，server 无展宽参数。"""
        local, client = idx == 0, idx == 2
        if local:
            self.b_scale.setCurrentIndex(0)      # 本地仅相对光子（web 同规则）
        self.b_scale.setEnabled(not local)
        self.b_broaden.setEnabled(local)
        self._sync_batch_local_rows()
        for wdg in (self.b_grid, self.b_minrel, self.b_conv):
            wdg.setEnabled(client)
        self._sync_batch_generation_ui()

    def _sync_batch_local_rows(self) -> None:
        """离线展宽关闭（或非本地模式）时，宽度/温度参数不可用（web 同语义）。"""
        on = self.b_mode.currentIndex() == 0 and self.b_broaden.isChecked()
        self.b_gauss.setEnabled(on)
        self.b_lorentz.setEnabled(on)
        self.b_temp_mode.setEnabled(on)
        self.b_temp_k.setEnabled(on and self.b_temp_mode.currentIndex() == 1)

    def _sync_batch_generation_ui(self) -> None:
        """生成方式三选：固定=组成池+均匀范围；随机=逐元素规则；模板=CSV。"""
        gen = self.b_generation.currentIndex()   # 0 固定 1 随机 2 模板
        fixed, rand, tpl = gen == 0, gen == 1, gen == 2
        self.b_rand_te.setEnabled(rand)
        self.b_rand_ne.setEnabled(rand)
        ne_on = rand and self.b_rand_ne.isChecked()
        self.b_ne_lo.setEnabled(ne_on)
        self.b_ne_hi.setEnabled(ne_on)
        self._ne_bounds_row.setEnabled(ne_on)
        self.b_rand_table.setEnabled(rand)
        self.b_rand_from_pool.setEnabled(rand)
        rand_te_on = rand and self.b_rand_te.isChecked()
        self._row_te.setEnabled(fixed or rand_te_on)
        self._te_label.setText('随机 Te 边界 [eV]' if rand_te_on else 'Te 范围 [eV]')
        self._row_ne.setEnabled(fixed)
        for wdg in self._pool_widgets:
            wdg.setEnabled(fixed)
        for wdg in self._template_widgets:
            wdg.setEnabled(tpl)
        if rand and self.b_rand_table.rowCount() == 0:
            self._fill_rand_table_from_sources(quiet=True)

    def batch_random_from_pool(self) -> None:
        if not self._fill_rand_table_from_sources():
            return
        self.toast('已生成逐元素浓度规则（可编辑固定值/随机边界）', 'success', 2500)

    def _fill_rand_table_from_sources(self, quiet: bool = False) -> bool:
        if self._batch_pool:
            items = [(it.el, it.pct) for it in self._batch_pool[0]['items']]
            source = '组成池'
        else:
            try:
                items = self.comp_values()
            except ValueError:
                items = []
            source = '当前配比'
        if not items:
            if not quiet:
                self.toast('先导入组成 CSV 或使用当前配比，再生成随机规则', 'warning')
            return False
        table = self.b_rand_table
        table.setRowCount(0)
        for el, pct in items:
            row = table.rowCount()
            table.insertRow(row)
            el_item = QTableWidgetItem(el)
            el_item.setFlags(el_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, el_item)
            table.setItem(row, 1, QTableWidgetItem(f'{pct:g}'))
            chk = QCheckBox()
            wrap = QWidget()
            wl = hlay((0, 0, 0, 0), 0)
            wl.addWidget(chk)
            wl.setAlignment(chk, Qt.AlignCenter)
            wrap.setLayout(wl)
            table.setCellWidget(row, 2, wrap)
            table.setItem(row, 3, QTableWidgetItem('0'))
            table.setItem(row, 4, QTableWidgetItem('100'))
        if not quiet:
            self.log(f'[batch] 已从{source}生成 {len(items)} 条随机浓度规则')
        return True

    def _generation_rules(self) -> dict:
        """从随机规则表构造 generation 请求体（kind=random，web generationPayload 同校验）。"""
        concentrations = []
        lo_sum = hi_sum = 0.0
        table = self.b_rand_table
        for row in range(table.rowCount()):
            el = (table.item(row, 0).text() or '').strip()
            if not el:
                raise ValueError('随机规则表存在空元素行')
            enabled = bool(table.cellWidget(row, 2) and
                           table.cellWidget(row, 2).findChild(QCheckBox) and
                           table.cellWidget(row, 2).findChild(QCheckBox).isChecked())
            if enabled:
                lo = self.parse_float(table.item(row, 3).text(), f'{el} 浓度下界')
                hi = self.parse_float(table.item(row, 4).text(), f'{el} 浓度上界')
                if not (0 <= lo <= hi <= 100):
                    raise ValueError(f'{el} 浓度边界须满足 0 ≤ 下界 ≤ 上界 ≤ 100')
                concentrations.append({'el': el, 'enabled': True, 'min': lo, 'max': hi})
                lo_sum += lo
                hi_sum += hi
            else:
                fixed = self.parse_float(table.item(row, 1).text(), f'{el} 固定浓度')
                if not (0 <= fixed <= 100):
                    raise ValueError(f'{el} 固定浓度须在 0–100%')
                concentrations.append({'el': el, 'enabled': False, 'fixed': fixed})
                lo_sum += fixed
                hi_sum += fixed
        if not concentrations:
            raise ValueError('随机浓度规则为空：先从组成池/当前配比生成规则')
        if lo_sum > 100 + 1e-9 or hi_sum < 100 - 1e-9:
            raise ValueError('浓度边界不能容纳 100%：请检查固定值和上下界')
        te: dict = {'enabled': self.b_rand_te.isChecked()}
        if te['enabled']:
            te['min'] = self.parse_float(self.b_temin.text(), '随机 Te 下界')
            te['max'] = self.parse_float(self.b_temax.text(), '随机 Te 上界')
        ne: dict = {'enabled': self.b_rand_ne.isChecked()}
        if ne['enabled']:
            ne['min'] = self.parse_float(self.b_ne_lo.text(), '随机实际 Ne 下界')
            ne['max'] = self.parse_float(self.b_ne_hi.text(), '随机实际 Ne 上界')
        for rule, label in ((te, 'Te'), (ne, '实际 Ne')):
            if rule['enabled'] and rule['min'] > rule['max']:
                raise ValueError(f'随机{label}下界不能大于上界')
        if self.b_mode.currentIndex() == 0:   # 本地模式：正含量元素须在离线谱线库内
            try:
                st = self.backend.engine_status('local')
                available = {str(e) for e in (st.get('local') or {}).get('elements') or []}
            except Exception:
                available = set()
            if available:
                for c in concentrations:
                    minimum = c['min'] if c['enabled'] else c['fixed']
                    if minimum > 0 and c['el'] not in available:
                        raise ValueError(f'{c["el"]} 缺少可用本地谱线；不会向 NIST 回退')
        return {'kind': 'random', 'te': te, 'ne': ne, 'concentrations': concentrations}

    def _batch_params_dict(self) -> dict:
        def f(sel, name):
            return self.parse_float(sel.text(), name)
        mode = ('local', 'server', 'client')[self.b_mode.currentIndex()]
        charge = self.parse_int(self.b_charge.text(), '最大离子电荷')
        if not 0 <= charge <= 2:
            raise ValueError('最大离子电荷须为 0–2（本地谱线库与 NIST v2 均只支持 I/II）')
        resample = self.b_resample.isChecked()
        broaden = self.b_broaden.isChecked() if mode == 'local' else True
        d = {
            'te': f(self.b_te, 'Te'), 'ne': f(self.b_ne, 'Ne'),
            'resolution': self.parse_int(self.b_r.text(), '分辨率 R'),
            'low_w': f(self.b_low, 'λ 下界'), 'up_w': f(self.b_up, 'λ 上界'),
            'max_ion_charge': charge,
            'mode': mode, 'mode_version': 2,
            'headless': self.b_headless.isChecked(),
            'resample': resample,
            'intensity_scale': 'photon' if mode == 'local'
                else ('photon', 'energy')[self.b_scale.currentIndex()],
            'broadening': 'local' if mode in ('local', 'client') else 'nist',
            'local_broadening_enabled': broaden,
        }
        if resample:
            d['resample_step'] = f(self.b_step, '插值目标步长')
        if mode == 'local':
            d['broaden_convention'] = 'physics'
            if broaden:
                d['local_gaussian_nm'] = f(self.b_gauss, '额外高斯宽度')
                d['local_lorentz_nm'] = f(self.b_lorentz, '洛伦兹 FWHM')
                d['local_temperature_mode'] = ('linked', 'manual')[self.b_temp_mode.currentIndex() == 1]
                d['local_temperature_K'] = 0.0 if d['local_temperature_mode'] == 'linked' \
                    else f(self.b_temp_k, '重粒子温度')
            else:
                d['local_gaussian_nm'] = 0.0
                d['local_lorentz_nm'] = 0.0
                d['local_temperature_mode'] = 'linked'
                d['local_temperature_K'] = 0.0
        elif mode == 'client':
            d['broaden_convention'] = 'physics' if self.b_conv.currentIndex() == 1 else 'nist'
            d['broaden_grid_step'] = f(self.b_grid, '展宽网格步长')
            d['broaden_min_rel_int'] = f(self.b_minrel, '选线阈值')
        return d

    def _batch_base_parameters(self):
        from backend_api import CommonParams
        from simlibs_ui.models import Parameters
        cp = CommonParams.from_api(self._batch_params_dict())
        return Parameters(
            Te=cp.te, Ne=cp.ne, resolution=cp.resolution, low_w=cp.low_w, upper_w=cp.up_w,
            max_ion_charge=cp.max_ion_charge, webscraping=cp.mode, mode_version=cp.mode_version,
            headless=cp.headless, resample=cp.resample, step=cp.resample_step,
            intensity_scale=cp.intensity_scale, broadening=cp.broadening,
            broaden_convention=cp.broaden_convention, broaden_grid_step=cp.broaden_grid_step,
            broaden_center_decimals=cp.broaden_center_decimals,
            broaden_min_rel_int=cp.broaden_min_rel_int,
            local_gaussian_nm=cp.local_gaussian_nm, local_lorentz_nm=cp.local_lorentz_nm,
            local_temperature_K=cp.local_temperature_K,
            local_temperature_mode=cp.local_temperature_mode,
            local_broadening_enabled=cp.local_broadening_enabled)

    def validate_template(self) -> None:
        """校验模板 CSV：行数/计划数/参数覆盖，结果显示在模板卡内。"""
        from simlibs_ui.batch_template import parse_template
        try:
            text = self._template_text()
            if text is None:
                self.b_tpl_info.setText('未填写模板路径')
                return
            plan = parse_template(text, self._batch_base_parameters(), self._repeats())
            els = sorted({el for e in plan['entries'] for el in e['parameters']['elements']})
            self.b_tpl_info.setText(
                f"✓ {plan['row_count']} 行 × {self._repeats()} 重复 = {plan['sample_count']} 条 · "
                f"元素 {' '.join(els)}")
        except Exception as exc:
            self.b_tpl_info.setText(f'✗ {exc}')
        self._repolish(self.b_tpl_info)

    def _template_text(self) -> str | None:
        path = self.b_tpl_path.text().strip().strip('"')
        if not path:
            return None
        file = Path(path)
        if not file.is_file():
            raise ValueError(f'模板文件不存在：{file}')
        text = file.read_text(encoding='utf-8-sig')
        if not text.strip():
            raise ValueError('模板 CSV 为空')
        return text

    def _repeats(self) -> int:
        return self.parse_int(self.b_repeats.text(), '每行重复次数')

    def start_batch(self) -> None:
        from backend_api import BatchRequest
        try:
            gen = self.b_generation.currentIndex()   # 0 固定 1 随机 2 模板
            params_dict = self._batch_params_dict()
            raw = {
                'params': params_dict,
                'batch_size': self.parse_int(self.pk_size.text(), '每包样本数'),
                'seed': self.parse_int(self.b_seed.text(), '随机种子'),
                'te_range': [self.parse_float(self.b_temin.text(), 'Te min'),
                             self.parse_float(self.b_temax.text(), 'Te max')],
                'ne_range': [self.parse_float(self.b_nemin.text(), 'Ne 指数 min'),
                             self.parse_float(self.b_nemax.text(), 'Ne 指数 max')],
            }
            if gen == 2:
                template_text = self._template_text()
                if template_text is None:
                    raise ValueError('生成方式为 CSV 模板：请先填写模板路径')
                raw['template_csv'] = template_text
                raw['repeats'] = self._repeats()
                raw['name_column'] = 'name'
            elif gen == 1:
                raw['n_samples'] = self.parse_int(self.b_n.text(), '样本总数')
                raw['generation'] = self._generation_rules()
            else:
                if not self._batch_pool:
                    raise ValueError('组成候选池为空：导入组成 CSV、模板 CSV 或使用当前配比')
                raw['n_samples'] = self.parse_int(self.b_n.text(), '样本总数')
                raw['compositions'] = [
                    {'name': r['name'],
                     'items': [{'el': it.el, 'pct': it.pct} for it in r['items']]}
                    for r in self._batch_pool]
            req = BatchRequest.from_api(raw)
        except Exception as exc:
            self.toast(str(exc), 'warning', 7000)
            return
        try:
            jid = self.backend.start_batch(req)
        except Exception as exc:
            self.toast(str(exc), 'error', 7000)
            return
        n = req.n_samples
        gen_label = ('固定', '随机', '模板')[gen]
        launcher = lambda: self.backend.start_batch(req)
        self.watch(jid, f'批量模拟({gen_label}) · {n} 样本 · 每包 {req.batch_size} · '
                        f'{req.params.mode}', launcher=launcher)

    def _update_pack_estimate(self, *_):
        try:
            n = int(float(self.b_n.text()))
            bs = int(float(self.pk_size.text()))
            assert n >= 1 and bs >= 1
        except (ValueError, AssertionError):
            self.pk_count.setText('预计 —')
            return
        packages = (n + bs - 1) // bs
        last = n - (packages - 1) * bs
        self.pk_count.setText(f'预计 {packages} 包 · 末包 {last} 条')

    def show_batch(self, result: dict) -> None:
        self._batch_result = result
        p = self._pal()
        table = self.b_samples
        table.setRowCount(0)
        for s in result.get('samples', []):
            i = table.rowCount()
            table.insertRow(i)
            comp = ' '.join(f"{c['el']}{c['pct']:g}" for c in s.get('composition', []))
            table.setItem(i, 0, QTableWidgetItem(s.get('name', '')))
            table.setItem(i, 1, QTableWidgetItem(f"{s.get('te', 0):g}"))
            table.setItem(i, 2, QTableWidgetItem(f"{s.get('ne', 0):.3g}"))
            table.setItem(i, 3, QTableWidgetItem(comp))
        summary = result.get('summary') or {}
        scale = result.get('intensity_scale')
        scale_txt = {'photon': 'Photon flux', 'energy': 'Energy flux'}.get(scale, '尺度 unknown')
        is_partial = bool(summary.get('partial'))
        partial = (' · <span style="color:%s">partial（部分样本未完成）</span>' % p['warn']) \
            if is_partial else ''
        self.b_meta.setText(
            f'<span style="color:{p["good"]}">批量完成</span> · 请求 {summary.get("total", 0)} · '
            f'完成 {summary.get("completed", 0)}{partial} · {scale_txt} (a.u.)')
        self.b_wide.setText(str((result.get('wide') or {}).get('note', '')))
        self.b_params_btn.setEnabled(bool(result.get('actual_parameters_available')) and not is_partial)
        self.b_tpl_btn.setEnabled(bool(result.get('template_csv_available')) and not is_partial)
        # 训练包状态
        package = result.get('training_package') or {}
        if package.get('available'):
            self.pk_btn.setEnabled(True)
            self.pk_btn.setToolTip(f"训练包已生成 · {package.get('packages', '?')} 包"
                                   f" · {package.get('sample_count', '?')} 样本")
        else:
            self.pk_btn.setEnabled(False)
            self.pk_btn.setToolTip(str(package.get('reason', '此任务没有完整训练包；重新运行批量模拟后可下载')))

    def download_training(self) -> None:
        result = self._batch_result
        if not result:
            self.toast('先完成一次批量模拟', 'warning')
            return
        package = result.get('training_package') or {}
        if not package.get('available'):
            self.toast(str(package.get('reason', '此任务没有完整训练包；重新运行批量模拟后可下载')),
                       'warning', 6000)
            return
        out_dir = Path(self.b_export_dir.text().strip().strip('"') or EXPORT_DIR)
        self.status_chip.label.setText('● 下载训练包…')

        def work():
            payload = self.backend.export(result['job_id'], 'training')
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / (payload.filename or f"{result['job_id']}_training.zip")
            path.write_bytes(payload.payload)
            return str(path)
        self.run_bg(work, on_done=self._training_done)

    def _training_done(self, path: str) -> None:
        self.status_chip.label.setText('● 完成')
        self.log(f'[training] {path}', 'ok')
        self.toast('训练数据包已下载：\n' + path, 'success', 8000)


    # ================================================================== 扫描
    def _scan_axis_changed(self, idx: int) -> None:
        defaults = {0: ('0.5', '5.0'), 1: ('-1', '1'), 2: ('500', '5000')}
        s, e = defaults.get(idx, ('', ''))
        self.sc_start.setText(s)
        self.sc_end.setText(e)

    def start_scan(self) -> None:
        from backend_api import CommonParams, CompositionItem, ScanRequest, validate_composition
        try:
            params = CommonParams.from_api(self._single_params_dict())
            params.check_points()
            axis = ['te', 'ne', 'r'][self.sc_axis.currentIndex()]
            if axis == 'r':
                start, end = self.parse_int(self.sc_start.text(), 'R 起点'), self.parse_int(self.sc_end.text(), 'R 终点')
            else:
                start = self.parse_float(self.sc_start.text(), '起点')
                end = self.parse_float(self.sc_end.text(), '终点')
            frames = self.parse_int(self.sc_frames.text(), '帧数')
            if frames < 2:
                raise ValueError('帧数至少为 2')
            comp = [CompositionItem(el, pct) for el, pct in self.comp_values()]
            validate_composition(comp)
            req = ScanRequest(params=params, axis=axis, start=start, end=end, frames=frames,
                              composition=comp)
        except Exception as exc:
            self.toast(str(exc), 'warning', 6000)
            return
        try:
            jid = self.backend.start_scan(req)
        except Exception as exc:
            self.toast(str(exc), 'error', 6000)
            return
        launcher = lambda: self.backend.start_scan(req)
        self.watch(jid, f'扫描动画 · {req.axis} {req.start:g}→{req.end:g} · {req.frames} 帧', launcher=launcher)

    def show_scan(self, result: dict) -> None:
        self._scan_result = result
        self._frame_idx = 0
        self._scan_job_id = result.get('job_id')
        self._scan_cache = {}
        self._scan_fetching = set()
        p = self._pal()
        self.sc_meta.setText(
            f"扫描轴 {result.get('axis', '')}{result.get('unit', '')} · {result.get('params_summary', '')}"
            f" · {result.get('intensity_units', 'a.u.')}"
            + ('' if not result.get('lazy_frames') else ' · 按帧加载'))
        self.render_frame(animate=True)
        self.set_playing(len(result.get('frames') or []) > 1)

    def render_frame(self, animate: bool = False) -> None:
        result = self._scan_result
        if not result:
            return
        frames = result.get('frames') or []
        if not frames:
            return
        idx = max(0, min(self._frame_idx, len(frames) - 1))
        frame = frames[idx]
        series = frame.get('series')
        if not series and frame.get('xs'):   # MOCK 引擎的帧直接是 xs/ys
            series = {'interpolated': {'label': 'frame', 'xs': frame['xs'], 'ys': frame['ys']}}
        if not series and result.get('lazy_frames'):
            # 懒帧：按帧加载全量（最多缓存 3 帧），播放等待当前帧完成
            cached = self._scan_cache.get(idx)
            if cached is None:
                if idx in self._scan_fetching:
                    return
                self._scan_fetching.add(idx)
                self.sc_frame_label.setText(f'帧 {idx + 1}/{len(frames)} · 加载中…')
                jid = self._scan_job_id
                self.run_bg(lambda: self.backend.get_result(jid, frame=idx),
                            on_done=lambda data, i=idx: self._frame_loaded(i, data))
                return
            series = cached
        self._paint_frame(series, result, idx, frame, animate)

    def _frame_loaded(self, idx: int, data: dict) -> None:
        self._scan_fetching.discard(idx)
        series = data.get('series')
        if not series and data.get('xs'):    # 兼容顶层 xs/ys
            series = {'interpolated': {'label': 'frame', 'xs': data['xs'], 'ys': data['ys']}}
        self._scan_cache[idx] = series or {}
        while len(self._scan_cache) > 3:     # 最多缓存 3 个完整帧
            oldest = next(k for k in self._scan_cache if k != self._frame_idx)
            self._scan_cache.pop(oldest)
        if self._scan_result and self._frame_idx == idx:
            self.render_frame()

    def _paint_frame(self, series: dict, result: dict, idx: int, frame: dict,
                     animate: bool = False) -> None:
        total = len(result.get('frames') or [])
        p = self._pal()
        spec = []
        main = (series or {}).get('interpolated') or (series or {}).get('raw')
        if main:
            spec.append({'label': '主线', 'xs': main['xs'], 'ys': main['ys'],
                         'color': p['accent'], 'color_key': 'accent'})
        for i, ion in enumerate((series or {}).get('ions') or []):
            key = ION_KEYS[i % len(ION_KEYS)]
            spec.append({'label': str(ion.get('label')), 'xs': ion['xs'], 'ys': ion['ys'],
                         'color': p[key], 'color_key': key})
        self._series_spec = spec
        self.sc_chart.set_series([{k: v for k, v in s.items() if k != 'color_key'} for s in spec],
                                 animate=animate and self.fade_ms > 0)
        self.sc_legend.setText(self._legend_text(spec, result.get('intensity_scale')))
        unit = str(result.get('unit', ''))
        axis = str(result.get('axis', '')).upper()
        state = '（自动播放中）' if self._playing else ''
        unbroadened = (frame.get('meta') or result.get('meta') or {}) \
            .get('local_broadening_enabled') is False
        tag = ' · 未展宽 · R未应用' if unbroadened else ''
        self.sc_frame_label.setText(
            f'帧 {idx + 1}/{total} · {axis}={frame.get("value"):g}{unit}{state}{tag}')

    def set_playing(self, playing: bool) -> None:
        self._playing = playing
        if playing:
            self.play_timer.start()
        else:
            self.play_timer.stop()
        self.sc_play.setText('⏸' if playing else '▶')

    def toggle_play(self) -> None:
        if not self._scan_result:
            self.toast('还没有扫描结果：先运行一次扫描', 'warning')
            return
        self.set_playing(not self._playing)

    def prev_frame(self) -> None:
        if self._scan_result:
            self.set_playing(False)
            self._frame_idx = max(0, self._frame_idx - 1)
            self.render_frame()

    def next_frame(self) -> None:
        if self._scan_result:
            self.set_playing(False)
            n = len(self._scan_result.get('frames') or [])
            self._frame_idx = min(n - 1, self._frame_idx + 1)
            self.render_frame()

    def advance_frame(self) -> None:
        if not self._scan_result:
            self.set_playing(False)
            return
        n = len(self._scan_result.get('frames') or [])
        if n < 2:
            self.set_playing(False)
            return
        self._frame_idx = (self._frame_idx + 1) % n
        self.render_frame()

    # ================================================================== 任务
    def watch(self, job_id: str, summary: str, launcher=None) -> None:
        self._last_launch = (launcher, summary, 0)
        self.current_job = job_id
        p = self._pal()
        self.status_chip.label.setText('● 运行中')
        self.status_chip.setProperty('class', '')
        self._repolish(self.status_chip)
        self.task_status.setText(f'● 运行中  {summary}')
        self.task_progress.setValue(0)
        self.task_progress.start_shimmer()
        self.log(f'[worker] 已提交任务 {job_id[:8]}… · {summary}')
        self.refresh_jobs()
        try:
            queue = self.backend.subscribe(job_id)
        except Exception as exc:
            self.toast(f'订阅任务事件失败：{exc}', 'error', 6000)
            return
        bridge = JobEventBridge(self)
        bridge.event.connect(self._on_event)
        pump = EventPump(queue, bridge, self)
        self._pumps.append(pump)
        pump.finished.connect(lambda: self._pumps.remove(pump) if pump in self._pumps else None)
        pump.start()

    def _on_event(self, ev) -> None:
        p = self._pal()
        if getattr(ev, 'message', ''):
            self.log(ev.message, getattr(ev, 'level', 'info'))
            if getattr(ev, 'level', '') == 'error':
                self._last_error_msg = ev.message
        if getattr(ev, 'progress', None) is not None:
            self.task_progress.set_value_smooth(float(ev.progress))
            if getattr(ev, 'status', None) is None and self.current_job:
                self.task_status.setText(f'● 运行中  {ev.progress:.0f}%')
        if getattr(ev, 'final', False):
            self._finalize(getattr(ev, 'status', 'failed'))

    def _finalize(self, status: str) -> None:
        jid, self.current_job = self.current_job, None
        launcher, summary_last, retries = (self._last_launch or (None, '', 0))
        p = self._pal()
        self.task_progress.stop_shimmer()
        if self.fade_ms > 0:
            pulse(self.status_chip, duration=360)
        if status == 'completed':
            self._last_launch = (launcher, summary_last, 0) if launcher else None
            self.task_progress.set_value_smooth(100, duration=420)
            self.status_chip.label.setText('● 完成')
            self.log('[done] 任务完成 · 读取结果与来源证据…', 'ok')
            self.run_bg(lambda: self._fetch_result(jid), on_done=self._route_result)
        elif status == 'cancelled':
            self.status_chip.label.setText('● 已取消')
            self.log('[ui] 已取消 · 保留上一次成功结果', 'warn')
            self.toast('任务已取消（保留上一次成功结果）', 'warning', 4000)
        else:
            self.status_chip.label.setText('● 失败')
            if self._maybe_retry_network(summary_last):
                return
            self.toast('任务失败，详情见任务日志', 'error', 6000)
        self.refresh_jobs()

    @staticmethod
    def _is_network_error(msg: str) -> bool:
        msg = str(msg)
        return any(k in msg for k in ('SSLError', 'SSL:', 'ConnectionError', 'MaxRetryError',
                                      'ReadTimeout', 'ConnectTimeout', 'ProtocolError'))

    def _maybe_retry_network(self, summary: str) -> bool:
        """NIST 间歇性 TLS 干扰：失败自动重新提交（最多 2 次）。"""
        launcher, _summary, retries = (self._last_launch or (None, '', 0))
        err = getattr(self, '_last_error_msg', '')
        if (not launcher) or retries >= 2 or not self._is_network_error(err):
            return False
        self._last_launch = (launcher, _summary, retries + 1)
        self.log(f'[retry] NIST 网络波动（{type(err).__name__}），2.5 秒后自动重试 '
                 f'{retries + 1}/2：{summary}', 'warn')
        self.toast(f'NIST 网络波动，2.5 秒后自动重试（{retries + 1}/2）', 'warning', 4000)
        self.status_chip.label.setText('● 重试中')
        QTimer.singleShot(2500, lambda: self._relaunch(launcher, summary))
        return True

    def _relaunch(self, launcher, summary: str) -> None:
        try:
            jid = launcher()
        except Exception as exc:
            self.toast(f'重试提交失败：{exc}', 'error', 6000)
            return
        self.watch(jid, summary + '（自动重试）', launcher=launcher)

    def _fetch_result(self, job_id: str) -> dict:
        result = self.backend.get_result(job_id) or {}
        result['job_id'] = job_id
        return result

    def _route_result(self, result: dict) -> None:
        kind = result.get('kind')
        if kind == 'single':
            self.show_single(result)
            self.go('single')
        elif kind == 'scan':
            self.show_scan(result)
            self.go('scan')
        elif kind == 'batch':
            self.show_batch(result)
            self.go('batch')
        self.toast('结果已就绪（来源证据已保存 manifest）', 'success', 3000)

    def refresh_jobs(self, *_):
        try:
            jobs = self.backend.list_jobs()
        except Exception:
            return
        self._jobs_rows = {}
        self.j_table.setRowCount(0)
        for j in jobs:
            i = self.j_table.rowCount()
            self.j_table.insertRow(i)
            status = j.get('status', '?')
            p = self._pal()
            styled = {'completed': ('✓ 完成', p['good']), 'running': ('● 运行', p['warn']),
                      'queued': ('◌ 排队', p['muted']), 'failed': ('✗ 失败', p['bad']),
                      'cancelled': ('⊘ 取消', p['warn'])}.get(status, (status, p['muted']))
            vals = [j.get('created', ''), j.get('kind', ''), styled[0],
                    f"{j.get('progress') or 0:.0f}%", j.get('duration', '-'),
                    str(j.get('summary', ''))[:52], str(j.get('job_id', ''))[:8]]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if col == 2:
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor(styled[1]))
                self.j_table.setItem(i, col, item)
            self._jobs_rows[i] = j.get('job_id')

    def _job_row_clicked(self, row: int, _col: int) -> None:
        jid = self._jobs_rows.get(row)
        if jid:
            self.show_job_detail(jid)

    def show_job_detail(self, job_id: str) -> None:
        try:
            detail = self.backend.get_job(job_id)
        except Exception as exc:
            self.toast(f'读取任务详情失败：{exc}', 'error', 5000)
            return
        self.j_detail.clear()
        self.j_detail.appendPlainText(f"任务 {job_id} · {detail.get('kind')} · {detail.get('status')}")
        for ev in detail.get('events', []):
            self.j_detail.appendPlainText(f"[{ev.get('ts')}] {ev.get('message')}")

    def view_selected_job(self) -> None:
        row = self.j_table.currentRow()
        jid = self._jobs_rows.get(row)
        if not jid:
            self.toast('先在表格中选择一个任务', 'warning')
            return
        try:
            self._route_result(self._fetch_result(jid))
        except Exception as exc:
            self.toast(f'暂无结果：{exc}', 'warning', 5000)

    def resume_selected_job(self) -> None:
        """失败/中断的批量任务从 checkpoint 续跑（校验计划/算法/库哈希，由后端完成）。"""
        row = self.j_table.currentRow()
        jid = self._jobs_rows.get(row)
        if not jid:
            self.toast('先在表格中选择一个任务', 'warning')
            return
        try:
            detail = self.backend.get_job(jid)
        except Exception as exc:
            self.toast(f'读取任务失败：{exc}', 'error', 5000)
            return
        if not detail.get('resumable'):
            self.toast(str(detail.get('resume_reason') or '该任务不可续跑'), 'warning', 6000)
            return
        try:
            new_jid = self.backend.resume(jid)
        except Exception as exc:
            self.toast(f'续跑失败：{exc}', 'error', 7000)
            return
        self.log(f'[resume] 已从 {jid[:8]}… 的 checkpoint 创建续跑任务 {new_jid[:8]}…', 'ok')
        launcher = lambda: self.backend.resume(jid)
        self.watch(new_jid, f"续跑 {jid[:8]}… · 已完成{detail.get('completed_samples', '?')}"
                            f"/{detail.get('total_samples', '?')} 条", launcher=launcher)

    def open_history(self) -> None:
        path = self.j_path.text().strip().strip('"')
        if not path:
            self.toast('请先填写历史 CSV 路径', 'warning')
            return
        self.run_bg(lambda: load_history(path), on_done=self._history_loaded)

    def _history_loaded(self, loaded: dict) -> None:
        meta = loaded['meta']
        p = self._pal()
        spec = [{'label': s['label'], 'xs': s['xs'], 'ys': s['ys'], 'color': p['info'],
                 'color_key': 'info'} for s in loaded['series']]
        self._series_spec = spec
        self.s_chart.set_series([{k: v for k, v in s.items() if k != 'color_key'} for s in spec])
        self.go('single')
        self.s_meta.setText(
            f"<b>{meta['source']}</b> · {meta.get('points', '')} · SHA {meta.get('sha256', '')} · "
            f"<span style='color:{p['warn']}'>{meta.get('params', '')}</span>")
        self.s_legend.setText(self._legend_text(spec, None))
        self.log(f"[history] 已离线载入 {meta.get('path')}", 'ok')

    # ================================================================== 导出
    def do_export(self, result: dict | None, kinds: list[str], out_dir: str,
                  frame: int | None = None) -> None:
        target = (result or {}).get('job_id') or self._current_completed_job()
        if not target:
            self.toast('没有可导出的成功任务', 'warning')
            return
        out_dir = out_dir.strip().strip('"') or EXPORT_DIR

        def work():
            paths = []
            for kind in kinds:
                payload = self.backend.export(target, kind, frame=frame)
                ext = {'text/csv': 'csv', 'application/json': 'json', 'image/png': 'png',
                       'image/gif': 'gif'}.get(payload.media_type.split(';')[0], 'bin')
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                path = Path(out_dir) / (payload.filename or f'{target}_{kind}.{ext}')
                data = payload.payload
                if isinstance(data, str):
                    path.write_text(data, encoding='utf-8')
                else:
                    path.write_bytes(data)
                paths.append(str(path))
            return paths
        self.status_chip.label.setText('● 导出中…')
        self.run_bg(work, on_done=self._export_done)

    def _export_done(self, paths: list[str]) -> None:
        self.status_chip.label.setText('● 完成')
        for pth in paths:
            self.log(f'[export] {pth}', 'ok')
        self.toast('已导出：\n' + '\n'.join(paths), 'success', 6000)

    def _current_completed_job(self) -> str | None:
        try:
            for j in reversed(self.backend.list_jobs()):
                if j.get('status') == 'completed':
                    return j.get('job_id')
        except Exception:
            pass
        return None

    def cancel_job(self) -> None:
        jid = self.current_job
        if not jid:
            self.toast('当前没有运行中的任务', 'warning')
            return
        if self.backend.cancel(jid):
            self.log('[ui] 已发送协作取消标记（0.8 秒宽限后清理任务进程树）', 'warn')

    # ================================================================== 设置
    def load_settings_form(self) -> None:
        try:
            s = self.backend.get_settings()
        except Exception:
            return
        mapping = {'connect_timeout': 'connect_timeout', 'read_timeout': 'read_timeout',
                   'page_load': 'page_load', 'static_deadline': 'static_deadline',
                   'dynamic_deadline': 'dynamic_deadline', 'output_dir': 'output_dir',
                   'source': 'source', 'python': 'python', 'chrome': 'chrome', 'driver': 'driver'}
        for key, their in mapping.items():
            self.st[key].setText('' if s.get(their) is None else str(s.get(their)))
        self.st['tls_verify'].setChecked(bool(s.get('tls_verify', True)))
        if hasattr(self.backend, 'get_proxy'):
            self.st_proxy.setText(self.backend.get_proxy())
        p = self._pal()
        if hasattr(self.backend, 'settings_path'):
            self.st_info.setText(
                f'设置文件：{self.backend.settings_path()}<br>'
                '修改解释器/Chrome/输出目录后保存；TLS 校验默认开启（关闭需自担风险）。')
        else:
            self.st_info.setText('MOCK 引擎使用固定演示配置，不可修改。')

    def save_settings(self) -> None:
        def num(key, name):
            raw = self.st[key].text().strip()
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f'{name} 不是合法数字：{raw!r}') from None
        try:
            self.backend.save_settings({
                'connect_timeout': num('connect_timeout', '连接超时'),
                'read_timeout': num('read_timeout', '读取超时'),
                'page_load': num('page_load', '页面加载'),
                'static_deadline': num('static_deadline', 'static 期限'),
                'dynamic_deadline': num('dynamic_deadline', 'dynamic 期限'),
                'output_dir': self.st['output_dir'].text().strip(),
                'source': self.st['source'].text().strip(),
                'python': self.st['python'].text().strip(),
                'chrome': self.st['chrome'].text().strip(),
                'driver': self.st['driver'].text().strip(),
                'tls_verify': self.st['tls_verify'].isChecked(),
            })
            if hasattr(self.backend, 'set_proxy'):
                self.backend.set_proxy(self.st_proxy.text())
        except Exception as exc:
            self.toast(f'保存失败：{exc}', 'error', 8000)
            return
        self.toast('设置已保存（代理对新任务生效）', 'success', 2500)
        self.log('[settings] 设置已保存', 'ok')
        self.refresh_engine()

    def reset_settings(self) -> None:
        if hasattr(self.backend, 'settings_path'):
            try:
                self.backend.settings_path().unlink(missing_ok=True)
            except Exception:
                pass
            self.backend._inst._settings = self.backend._load_settings(self.backend._inst, fallback=True)
        self.load_settings_form()
        self.toast('已恢复默认设置', 'success', 2500)

    # ================================================================== 引擎状态
    def refresh_engine(self, *_args) -> None:
        mode = self._current_mode() if getattr(self, 's_mode', None) else 'local'

        def probe():
            try:
                return self.backend.engine_status(mode)
            except TypeError:      # MOCK 旧签名
                return self.backend.engine_status()
        self.run_bg(probe, on_done=self._update_engine)

    def _update_engine(self, st: dict) -> None:
        self._last_engine = st
        self.engine_card.update_status(st)
        p = self._pal()
        chip = self.nist_chip
        if st.get('local') is not None:
            local = st.get('local') or {}
            ready = bool(local.get('ready'))
            chip.setProperty('class', 'good' if ready else 'bad')
            self._repolish(chip)
            chip.label.setText(('● 本地库就绪  ' if ready else '● 本地库不可用  ')
                               + f"{local.get('csv_count', 0)} CSV · "
                                 f"{len(local.get('elements') or [])} 元素")
            self._refresh_element_completions()
            return
        ok = bool(st.get('nist_ok'))
        chip.setProperty('class', 'good' if ok else 'bad')
        self._repolish(chip)
        label = str(st.get('nist', '')).split('·')[-1].strip()
        chip.label.setText(('● NIST 可达  ' if ok else '● NIST 不可达  ') + label)

    # ================================================================== 关闭
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.current_job:
            self.backend.cancel(self.current_job)
        event.accept()


def main() -> None:
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    apply_dark_titlebar(window)
    sys.exit(app.exec() if hasattr(app, 'exec') else app.exec_())
