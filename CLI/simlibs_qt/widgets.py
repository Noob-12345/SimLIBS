"""Qt 通用组件：Toast 通知、shimmer 进度条、chip、引擎状态卡、页面过渡与入场动画。"""
from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation, QRectF,
                            QTimer, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QPainter, QLinearGradient, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QProgressBar, QStackedWidget, QVBoxLayout, QWidget)

from .theme_qt import DARK, LIGHT


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
