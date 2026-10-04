"""simLIBS Studio Qt —— 设计令牌与 QSS（移植 UI/design/DESIGN.md 的 Plasma Dark / Light）。"""
from __future__ import annotations

from PySide6.QtGui import QColor

# Plasma Dark（黑红）：色值与设计稿逐一对齐
DARK = dict(
    bg='#0a0b0e', card='#131418', card2='#17181d', brd='#26282f', brd_hover='#3d3036',
    text='#f0ebed', muted='#a59da2', accent='#ef4444', accent2='#f97316',
    ion='#f59e0b', ion2='#a78bfa', good='#34d399', warn='#fbbf24', bad='#fb7185',
    info='#60a5fa', raw='#8a8589', input_bg='#0d0e12', hover='#1a1b21',
)
# Light：青色方案（设计稿 Light 变体）
LIGHT = dict(
    bg='#f4f3f1', card='#ffffff', card2='#faf9f7', brd='#d9d5d2', brd_hover='#9ecfd9',
    text='#1c1a19', muted='#6f6a67', accent='#0891b2', accent2='#0e7490',
    ion='#b45309', ion2='#7c3aed', good='#059669', warn='#b45309', bad='#e11d48',
    info='#2563eb', raw='#8a8589', input_bg='#ffffff', hover='#efece9',
)

ION_CYCLE = ('ion', 'ion2', 'info', 'good')


def chart_palette(p: dict) -> dict:
    """Qt 令牌 → 图表键名（与画布/图例共用）。"""
    return {
        'bg': p['card'], 'brd': p['brd'], 'text': p['text'], 'muted': p['muted'],
        'accent': p['accent'], 'accent2': p['accent2'], 'ion': p['ion'], 'ion2': p['ion2'],
        'good': p['good'], 'warn': p['warn'], 'bad': p['bad'], 'info': p['info'],
        'raw': p['raw'],
    }


def build_qss(p: dict) -> str:
    return f"""
* {{ font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif; font-size: 13px; color: {p['text']}; }}
QMainWindow, QWidget#Root {{ background: {p['bg']}; }}
QToolTip {{ background: {p['card2']}; color: {p['text']}; border: 1px solid {p['brd']}; padding: 4px; }}

/* ---------- 侧边栏 ---------- */
QWidget#Sidebar {{ background: {p['bg']}; border-right: 1px solid {p['brd']}; }}
QLabel#Brand {{ color: {p['accent']}; font-size: 17px; font-weight: 800; padding: 2px; }}
QLabel#Brand i {{ color: {p['accent2']}; font-style: italic; font-weight: 400; }}
QPushButton[nav="true"] {{
    background: transparent; border: none; border-left: 3px solid transparent;
    color: {p['muted']}; text-align: left; padding: 10px 14px; font-size: 14px; border-radius: 0;
}}
QPushButton[nav="true"]:hover {{ background: {p['card']}; color: {p['text']}; }}
QPushButton[nav="true"]:checked {{
    background: {p['card']}; color: {p['accent']}; border-left: 3px solid {p['accent']};
    font-weight: 600;
}}
QFrame#EngineCard {{
    background: {p['card']}; border: 1px solid {p['brd']}; border-radius: 10px;
}}
QLabel#EngineTitle {{ color: {p['text']}; font-weight: 700; }}
QLabel#EngineLine {{ color: {p['muted']}; font-size: 12px; }}
QLabel#EngineLine b, QLabel#EngineLine span{{ color: {p['text']}; }}

/* ---------- 顶栏 chip ---------- */
QFrame#Chip {{
    background: {p['card']}; border: 1px solid {p['brd']}; border-radius: 14px;
}}
QFrame#Chip QLabel {{ color: {p['muted']}; font-size: 12px; }}
QFrame#Chip.good {{ border-color: {p['good']}; }}
QFrame#Chip.good QLabel {{ color: {p['good']}; }}
QFrame#Chip.bad {{ border-color: {p['bad']}; }}
QFrame#Chip.bad QLabel {{ color: {p['bad']}; }}
QLabel#PageTitle {{ font-size: 18px; font-weight: 800; }}

/* ---------- 卡片/面板 ---------- */
QFrame#Card {{ background: {p['card']}; border: 1px solid {p['brd']}; border-radius: 14px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollCorner {{ background: transparent; }}
QLabel#PanelTitle {{ color: {p['muted']}; font-size: 12px; letter-spacing: 1px; }}
QLabel::disabled {{ color: {p['muted']}; }}

/* ---------- 表单 ---------- */
QLabel.field-label {{ color: {p['muted']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {p['input_bg']}; border: 1px solid {p['brd']}; border-radius: 8px;
    padding: 6px 9px; selection-background-color: {p['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {p['accent']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 5px solid transparent; border-right: 5px solid transparent;
    border-top: 6px solid {p['muted']}; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {p['card2']}; border: 1px solid {p['brd']}; border-radius: 8px;
    selection-background-color: {p['hover']}; selection-color: {p['text']};
    outline: 0; padding: 4px;
}}
QCheckBox {{ color: {p['muted']}; spacing: 7px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border: 1px solid {p['brd']}; border-radius: 5px; background: {p['input_bg']};
}}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QSwitchLabel[on="true"] {{ color: {p['good']}; }}
QSwitchLabel[on="false"] {{ color: {p['muted']}; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {p['card2']}; border: 1px solid {p['brd']}; border-radius: 8px;
    padding: 7px 14px; color: {p['text']};
}}
QPushButton:hover {{ border: 1px solid {p['brd_hover']}; background: {p['hover']}; }}
QPushButton:disabled {{ color: {p['muted']}; border-color: {p['brd']}; }}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p['accent']}, stop:1 {p['accent2']});
    border: none; color: #ffffff; font-weight: 700; padding: 9px 18px;
}}
QPushButton#Primary:hover {{ background: {p['accent2']}; }}
QPushButton#Primary:disabled {{ background: {p['brd']}; color: {p['muted']}; }}
QPushButton#Danger {{ background: transparent; border: 1px solid {p['bad']}; color: {p['bad']}; }}
QPushButton#Danger:hover {{ background: {p['bad']}; color: #ffffff; }}
QPushButton#Ghost {{ background: transparent; }}

/* ---------- 表格/日志 ---------- */
QTableWidget, QTableView {{
    background: {p['card']}; border: none; gridline-color: {p['brd']};
    selection-background-color: {p['hover']}; selection-color: {p['text']};
    alternate-background-color: {p['card2']};
}}
QHeaderView::section {{
    background: {p['card']}; color: {p['muted']}; border: none;
    border-bottom: 1px solid {p['brd']}; padding: 7px 8px; font-size: 12px;
}}
QTableCornerButton::section {{ background: {p['card']}; border: none; }}
QPlainTextEdit#LogView {{
    background: {p['card']}; border: 1px solid {p['brd']}; border-radius: 10px;
    font-family: "Consolas", "JetBrains Mono", monospace; font-size: 12px; color: {p['muted']};
}}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['brd']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['brd_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['brd']}; border-radius: 4px; min-width: 30px; }}

/* ---------- 任务栏 ---------- */
QFrame#Taskbar {{ background: {p['bg']}; border-top: 1px solid {p['brd']}; }}
QProgressBar#TaskProgress {{
    background: {p['input_bg']}; border: 1px solid {p['brd']}; border-radius: 8px;
    height: 16px; text-align: center; color: {p['text']}; font-size: 11px;
}}
QProgressBar#TaskProgress::chunk {{
    border-radius: 7px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p['accent']}, stop:1 {p['accent2']});
}}

/* ---------- Toast ---------- */
QFrame#Toast {{
    background: {p['card2']}; border: 1px solid {p['accent']}; border-radius: 12px;
}}
QFrame#Toast QLabel {{ color: {p['text']}; }}
QFrame#Toast.error {{ border-color: {p['bad']}; }}
QFrame#Toast.warning {{ border-color: {p['warn']}; }}
QFrame#Toast.success {{ border-color: {p['good']}; }}

/* ---------- 图例/元数据 ---------- */
QLabel#Legend, QLabel#MetaChips {{ color: {p['muted']}; font-size: 12px; }}
QLabel#MetaChips b {{ color: {p['text']}; }}
QLabel#WarnLine {{ color: {p['bad']}; font-size: 12px; }}
QLabel#SumLabel {{ font-size: 12px; }}
QLabel#SumLabel.ok {{ color: {p['good']}; }}
QLabel#SumLabel.bad {{ color: {p['bad']}; }}
"""


def apply_dark_titlebar(widget) -> None:
    """Windows 暗色标题栏（DWMWA_USE_IMMERSIVE_DARK_MODE）。"""
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # 20 = 20H1+，19 = 旧版回退
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def apply_fusion_palette(app, p: dict) -> None:
    """Fusion 风格 + 全局暗色调色板打底（滚动条/右键菜单/提示等不再漏出系统亮色）。"""
    from PySide6.QtWidgets import QStyleFactory
    from PySide6.QtGui import QPalette
    try:
        app.setStyle(QStyleFactory.create('Fusion'))
    except Exception:
        pass
    pal = QPalette()
    bg, card, text, muted = QColor(p['bg']), QColor(p['card']), QColor(p['text']), QColor(p['muted'])
    pal.setColor(QPalette.Window, bg)
    pal.setColor(QPalette.WindowText, text)
    pal.setColor(QPalette.Base, QColor(p['input_bg']))
    pal.setColor(QPalette.AlternateBase, card)
    pal.setColor(QPalette.ToolTipBase, card)
    pal.setColor(QPalette.ToolTipText, text)
    pal.setColor(QPalette.Text, text)
    pal.setColor(QPalette.Button, card)
    pal.setColor(QPalette.ButtonText, text)
    pal.setColor(QPalette.BrightText, QColor(p['bad']))
    pal.setColor(QPalette.Highlight, QColor(p['accent']))
    pal.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    pal.setColor(QPalette.PlaceholderText, QColor(p['muted']))
    for group in (QPalette.Disabled,):
        pal.setColor(group, QPalette.Text, muted)
        pal.setColor(group, QPalette.ButtonText, muted)
        pal.setColor(group, QPalette.WindowText, muted)
    app.setPalette(pal)


def qcolor(key: str, p: dict) -> QColor:
    return QColor(p[key])
