"""simLIBS Studio CLI —— 设计令牌（移植 UI/design/DESIGN.md 的 Plasma Dark / Light）。"""
from __future__ import annotations

from textual.theme import Theme

# Plasma Dark（黑红）：色值与设计稿逐一对齐
DARK = dict(
    bg='#0a0b0e', card='#131418', brd='#26282f', brd_hover='#3d3036',
    text='#f0ebed', muted='#a59da2', accent='#ef4444', accent2='#f97316',
    ion='#f59e0b', ion2='#a78bfa', good='#34d399', warn='#fbbf24', bad='#fb7185',
    info='#60a5fa', raw='#8a8589', input_bg='#0d0e12',
)
# Light：青色方案（设计稿 Light 变体）
LIGHT = dict(
    bg='#f4f3f1', card='#ffffff', brd='#d9d5d2', brd_hover='#9ecfd9',
    text='#1c1a19', muted='#6f6a67', accent='#0891b2', accent2='#0e7490',
    ion='#b45309', ion2='#7c3aed', good='#059669', warn='#b45309', bad='#e11d48',
    info='#2563eb', raw='#8a8589', input_bg='#faf9f8',
)

ION_CYCLE = ('ion', 'ion2', 'info', 'good')  # 离子曲线配色循环（键名，经 palette 解析）


def canvas_palette(p: dict) -> dict:
    """theme.py 令牌 → 画布键名。"""
    return {
        'bg': p['bg'], 'card': p['card'], 'brd': p['brd'], 'brd-hover': p['brd_hover'],
        'text': p['text'], 'muted': p['muted'], 'accent': p['accent'], 'accent2': p['accent2'],
        'ion': p['ion'], 'ion2': p['ion2'], 'good': p['good'], 'warn': p['warn'],
        'bad': p['bad'], 'info': p['info'], 'raw': p['raw'],
    }


def make_theme(name: str, p: dict) -> Theme:
    return Theme(
        name=name, dark=name.endswith('dark'),
        primary=p['accent'], secondary=p['accent2'],
        success=p['good'], warning=p['warn'], error=p['bad'], accent=p['accent2'],
        foreground=p['text'], background=p['bg'], surface=p['card'], panel=p['card'],
        variables={
            'bg': p['bg'], 'card': p['card'], 'brd': p['brd'], 'brd-hover': p['brd_hover'],
            'muted': p['muted'], 'accent': p['accent'], 'accent2': p['accent2'],
            'ion': p['ion'], 'ion2': p['ion2'], 'good': p['good'], 'warn': p['warn'],
            'bad': p['bad'], 'info': p['info'], 'raw': p['raw'], 'input-bg': p['input_bg'],
        },
    )


PLASMA_DARK = make_theme('plasma-dark', DARK)
PLASMA_LIGHT = make_theme('plasma-light', LIGHT)
