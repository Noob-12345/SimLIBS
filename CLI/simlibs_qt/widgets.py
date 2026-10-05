"""Qt 通用组件：Toast 通知、shimmer 进度条、chip、引擎状态卡、页面过渡与入场动画。"""
from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation, QRectF,
                            QTimer, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel, QProgressBar, QStackedWidget,
                               QVBoxLayout, QWidget)

from .theme_qt import DARK, LIGHT, THEME_PRESETS, palette_with_accent


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty('class', 'field-label')
    return lbl


def make_chip(text: str, chip_id: str = '') -> QFrame:
    chip = QFrame()
    chip.setObjectName('Chip')
    lay = QHBoxLayout(chip)
    lay.setContentsMargins(12, 4, 12, 4)
    lbl = QLabel(text)
    lay.addWidget(lbl)
    chip.label = lbl
    if chip_id:
        chip.setObjectName(chip_id)
    return chip


class Toast(QFrame):
    """右下角滑入的 toast 通知（带边框卡片），淡出后自动销毁。"""

    def __init__(self, host: QWidget, message: str, kind: str = 'info', timeout: int = 4500) -> None:
        super().__init__(host)
        self.setObjectName('Toast')
        self.kind = kind
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        icon = {'error': '✗', 'warning': '⚠', 'success': '✓', 'info': 'ℹ'}.get(kind, 'ℹ')
        icon_color = {'error': '#fb7185', 'warning': '#fbbf24', 'success': '#34d399',
                      'info': '#a59da2'}.get(kind, '#a59da2')
        lbl = QLabel(f'<span style="color:{icon_color};font-weight:700">{icon}</span>　{message}')
        lbl.setTextFormat(Qt.RichText)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(380)
        lay.addWidget(lbl)

        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(0.0)
        self.setGraphicsEffect(self._eff)
        self.adjustSize()

        # 滑入：从右侧淡入（最终纵坐标由 ToastHost.relayout 统一安排）
        self._anim_in = QPropertyAnimation(self._eff, b'opacity', self)
        self._anim_in.setDuration(200)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.start()
        self._slide: QPropertyAnimation | None = None
        self.show()
        self.raise_()
        QTimer.singleShot(timeout, self.fade_out)

    def slide_in(self, target: QPoint) -> None:
        start = QPoint(target.x() + 60, target.y())
        self.move(start)
        self._slide = QPropertyAnimation(self, b'pos', self)
        self._slide.setDuration(240)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.setStartValue(start)
        self._slide.setEndValue(target)
        self._slide.start()

    def glide_to(self, target: QPoint) -> None:
        """被推开的平滑移动。"""
        if self.pos() == target:
            return
        self._glide = QPropertyAnimation(self, b'pos', self)
        self._glide.setDuration(220)
        self._glide.setEasingCurve(QEasingCurve.OutCubic)
        self._glide.setStartValue(self.pos())
        self._glide.setEndValue(target)
        self._glide.start()

    def fade_out(self) -> None:
        anim = QPropertyAnimation(self._eff, b'opacity', self)
        anim.setDuration(220)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(self.deleteLater)
        anim.start()
        self._out_anim = anim   # 持有引用防回收


class ToastHost(QObject):
    """右下角 toast 堆叠管理：新提示出现时把旧的上推，消失时其余平滑回落，互不遮挡。"""

    GAP = 10
    MARGIN = 18

    def __init__(self, window) -> None:
        super().__init__(window)
        self._win = window
        self._active: list[Toast] = []

    def show(self, message: str, kind: str = 'info', timeout: int = 4500) -> None:
        toast = Toast(self._win, message, kind, timeout)
        toast.destroyed.connect(lambda *_: self._forget(toast))
        self._active.append(toast)
        self.relayout(animate_new=True)

    def _forget(self, toast: Toast) -> None:
        if toast in self._active:
            self._active.remove(toast)
        self.relayout()

    def relayout(self, animate_new: bool = False) -> None:
        y = self._win.height() - self.MARGIN
        for toast in reversed(self._active):          # 最新在最下
            if not toast.isVisible():
                continue
            y -= toast.height()
            target = QPoint(self._win.width() - toast.width() - self.MARGIN, y)
            if animate_new and toast is self._active[-1]:
                toast.slide_in(target)
            else:
                toast.glide_to(target)
            y -= self.GAP


class ShimmerProgress(QProgressBar):
    """红→橙渐变进度条，运行时叠加流光。"""

    def __init__(self, palette: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('TaskProgress')
        self.setRange(0, 100)
        self.setTextVisible(True)
        self.setFixedHeight(17)
        self._pal = dict(palette)
        self._phase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1400)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_phase)
        self._running = False

    def set_palette(self, palette: dict) -> None:
        self._pal = dict(palette)
        self.update()

    def set_value_smooth(self, v: float, duration: int = 260) -> None:
        """进度数值平滑增长（事件密集时合并到最近一次动画）。"""
        target = max(float(self.minimum()), min(float(self.maximum()), float(v)))
        if getattr(self, '_sv', None) is None:
            self._sv = QVariantAnimation(self)
            self._sv.valueChanged.connect(lambda x: QProgressBar.setValue(self, int(x)))
        self._sv.stop()
        self._sv.setDuration(duration)
        self._sv.setStartValue(float(self.value()))
        self._sv.setEndValue(target)
        self._sv.setEasingCurve(QEasingCurve.OutCubic)
        self._sv.start()

    def start_shimmer(self) -> None:
        self._running = True
        self._anim.start()

    def stop_shimmer(self) -> None:
        self._running = False
        self._anim.stop()
        self._phase = 0.0
        self.update()

    def _on_phase(self, v) -> None:
        self._phase = float(v)
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        super().paintEvent(ev)
        if not self._running:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        x = int((w + 120) * self._phase) - 120
        grad = QLinearGradient(x, 0, x + 120, 0)
        c = QColor(self._pal['text'])
        c.setAlpha(46)
        grad.setColorAt(0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.5, c)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        from PySide6.QtGui import QBrush
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 7, 7)


class TransitionOverlay(QWidget):
    """页面切换过渡：旧页淡出上移、新页自下方滑入淡入（320ms，OutCubic）。"""

    def __init__(self, host: QWidget, old_pix: QPixmap, new_pix: QPixmap, duration: int = 320) -> None:
        super().__init__(host)
        self._old, self._new = old_pix, new_pix
        self._t = 0.0
        self.setGeometry(host.rect())
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._step)
        anim.finished.connect(self.deleteLater)
        self._anim = anim
        self.show()
        self.raise_()
        anim.start()

    def _step(self, v) -> None:
        self._t = float(v)
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t = self._t
        p.setOpacity(1.0 - t)
        p.drawPixmap(0, int(-16 * t), self._old)
        p.setOpacity(t)
        p.drawPixmap(0, int(16 * (1 - t)), self._new)


def fade_between(stack: QStackedWidget, old_widget: QWidget, duration: int = 320) -> None:
    """QStackedWidget 切换后调用：用位图叠加层做交叉滑动过渡。"""
    if duration <= 0:
        return
    if getattr(stack, '_transitioning', False):
        return
    stack._transitioning = True
    old_pix = old_widget.grab()
    new_pix = stack.currentWidget().grab()

    def cleanup() -> None:
        stack._transitioning = False
    overlay = TransitionOverlay(stack, old_pix, new_pix, duration)
    overlay.destroyed.connect(lambda *_: cleanup())


def _has_chart(widget: QWidget) -> bool:
    from .chart import SpectrumChart
    if isinstance(widget, SpectrumChart):
        return True
    return widget.findChild(SpectrumChart) is not None


def stagger_entrance(page: QWidget, duration: int = 200, stagger_ms: int = 40) -> None:
    """页面内容错峰淡入：跳过含图表的锚点块（图表有自己的画入动画）。"""
    if duration <= 0:
        return
    targets = []
    lay = page.layout()
    if lay is None:
        return
    for i in range(lay.count()):
        item = lay.itemAt(i)
        w = item.widget() if item else None
        if w is None or not w.isVisible():
            continue
        if _has_chart(w):
            # 含图表的列：只对其不含图表的直接子块做入场
            inner = w.layout()
            if inner is not None:
                for j in range(inner.count()):
                    c = inner.itemAt(j).widget() if inner.itemAt(j) else None
                    if c is not None and c.isVisible() and not _has_chart(c):
                        targets.append(c)
        else:
            targets.append(w)
    for i, w in enumerate(targets):
        eff = QGraphicsOpacityEffect(w)
        eff.setOpacity(0.0)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b'opacity', w)
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda ww=w: ww.setGraphicsEffect(None))
        w._stagger_anim = anim
        QTimer.singleShot(i * stagger_ms, anim.start)


def pulse(widget: QWidget, duration: int = 340, dip: float = 0.45) -> None:
    """状态变化时的一次性呼吸脉冲（透明度先降后升）。"""
    if duration <= 0:
        return
    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)

    def step(v) -> None:
        eff.setOpacity(1.0 - dip * math.sin(float(v) * math.pi))

    def done() -> None:
        widget.setGraphicsEffect(None)
    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    widget._pulse_anim = anim
    anim.start()


class EngineCard(QFrame):
    """侧边栏底部引擎状态卡。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('EngineCard')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)
        self.title = QLabel('引擎状态')
        self.title.setObjectName('EngineTitle')
        self.lines = QLabel('正在检测…')
        self.lines.setObjectName('EngineLine')
        self.lines.setTextFormat(Qt.RichText)
        self.lines.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.lines)

    def update_status(self, st: dict) -> None:
        ok = bool(st.get('nist_ok'))
        p = DARK if self._is_dark() else LIGHT
        dot = f'<span style="color:{p["good"]}">●</span>' if ok else f'<span style="color:{p["bad"]}">●</span>'
        self.lines.setTextFormat(Qt.RichText)
        self.lines.setText(
            f'Python&nbsp;&nbsp;{st.get("python", "?")}<br>'
            f'NIST&nbsp;&nbsp;&nbsp;&nbsp;{dot} {st.get("nist", "?")}<br>'
            f'Chrome&nbsp;&nbsp;{st.get("chrome", "?")}<br>'
            f'运行中&nbsp;&nbsp;{st.get("jobs_running", 0)} 个任务')

    def _is_dark(self) -> bool:
        w = self.window()
        return getattr(w, 'theme_name', 'plasma-dark').endswith('dark')


class ThemePreviewCard(QFrame):
    """单张主题预览卡：日/夜两块迷你界面缩略（侧栏 + 卡片 + 按钮 + 谱线）。"""
    clicked = Signal(str)

    def __init__(self, preset_key: str, selected: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.preset_key = preset_key
        self.preset = THEME_PRESETS[preset_key]
        self.selected = selected
        self.setFixedSize(158, 128)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.preset_key)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        from .theme_qt import palette_with_accent
        half_w, half_h = (self.width() - 12) / 2, self.height() - 40
        for i, (base, accent_key) in enumerate(((LIGHT, 'light'), (DARK, 'dark'))):
            pal = palette_with_accent(base, self.preset[accent_key])
            ox = 4 + i * (half_w + 4)
            oy = 4
            # 面板底
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(pal['bg']))
            p.drawRoundedRect(QRectF(ox, oy, half_w, half_h), 6, 6)
            # 侧栏
            p.setBrush(QColor(pal['brd']))
            p.drawRoundedRect(QRectF(ox + 5, oy + 5, 16, half_h - 10), 3, 3)
            p.setBrush(QColor(self.preset[accent_key]))
            p.drawRoundedRect(QRectF(ox + 7, oy + 7, 12, 4), 2, 2)
            # 标题条 + 两张卡片
            p.setBrush(QColor(pal['brd']))
            p.drawRoundedRect(QRectF(ox + 26, oy + 6, half_w - 32, 6), 2, 2)
            for k in range(2):
                p.setBrush(QColor(pal['card']))
                p.drawRoundedRect(QRectF(ox + 26 + k * ((half_w - 34) / 2 + 2), oy + 16,
                                         (half_w - 38) / 2, 18), 3, 3)
            # 谱线折线
            from PySide6.QtGui import QPen, QPolygonF
            from PySide6.QtCore import QPointF
            pen = QPen(QColor(self.preset[accent_key]))
            pen.setWidthF(1.6)
            p.setPen(pen)
            xs = [0, 10, 15, 11, 20, 28, 35, 42, 60, 70, 76, 100]
            ys = [29, 28, 11, 28, 27, 2, 26, 28, 15, 28, 29, 29]
            scale_x = (half_w - 30) / 100
            poly = QPolygonF([QPointF(ox + 27 + x * scale_x, oy + half_h - 14 - y * 0.28)
                              for x, y in zip(xs, ys)])
            p.drawPolyline(poly)
        # 标签
        p.setPen(QColor('#f0ebed' if True else '#000'))
        p.drawText(QRectF(0, self.height() - 32, self.width(), 28),
                   Qt.AlignHCenter | Qt.AlignVCenter,
                   self.preset['name'] + ('  ✓' if self.selected else ''))
        if self.selected:
            pen = QPen(QColor(self.preset['light']))
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 8, 8)


class ThemeCatalogDialog(QDialog):
    """五种固定页面主题的预览选择。"""

    def __init__(self, parent=None, selected: str = 'violet') -> None:
        super().__init__(parent)
        self.setWindowTitle('选择页面主题颜色')
        self.selected = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        tip = QLabel('点击选择页面强调色（每张卡片左侧为日间、右侧为夜间预览）')
        tip.setObjectName('MetaChips')
        lay.addWidget(tip)
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setSpacing(10)
        self._cards = []
        for i, key in enumerate(THEME_PRESETS):
            card = ThemePreviewCard(key, selected=(key == selected))
            card.clicked.connect(self._pick)
            grid.addWidget(card, i // 3, i % 3)
            self._cards.append(card)
        lay.addWidget(row)
        self.setMinimumWidth(540)

    def _pick(self, key: str) -> None:
        self.selected = key
        for card in self._cards:
            card.set_selected(card.preset_key == key)
        self.accept()
