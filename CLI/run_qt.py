"""simLIBS Studio Qt —— 原生桌面版入口（PySide6，无 HTML / 无终端 UI）。

用法：
    python run_qt.py                 # 真实引擎（需 NIST 网络）
    python run_qt.py --mock          # MOCK 演示引擎（合成谱）
    python run_qt.py --diagnose      # 只检查解释器/依赖/源路径，不启动界面
    python run_qt.py --screenshot    # offscreen 渲染各页面 PNG（自查用），不显示窗口
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CLI_ROOT))


def diagnose() -> int:
    print('simLIBS Studio Qt · 诊断（不联网）')
    print(f'Python       : {sys.version}')
    print(f'解释器       : {sys.executable}')
    ok = True
    for mod in ('PySide6', 'matplotlib', 'numpy', 'pandas', 'scipy', 'requests', 'bs4', 'PIL'):
        try:
            __import__(mod)
            print(f'依赖 {mod:<12}: OK')
        except ImportError as exc:
            ok = False
            print(f'依赖 {mod:<12}: 缺失（{exc}）')
    source = CLI_ROOT.parent / 'simLIBS-2.0.3'
    good = (source / 'simLIBS' / 'simulation.py').is_file()
    print(f'源库路径     : {source}  {"OK" if good else "缺失"}')
    ui = CLI_ROOT.parent / 'UI' / 'web' / 'real_backend.py'
    print(f'后端包装     : {ui}  {"OK" if ui.is_file() else "缺失"}')
    try:
        from simlibs_cli.backend import create_backend  # noqa: F401
        print('后端导入     : OK')
    except Exception as exc:
        ok = False
        print(f'后端导入     : 失败（{exc}）')
    print('结论         : 可以启动' if ok else '结论         : 先解决上方问题')
    return 0 if ok else 1


def screenshot_mode() -> int:
    """offscreen 渲染五个页面（深/浅主题）到 output/snapshots-qt/。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('SIMLIBS_WEB_BACKEND', 'mock')
    from PySide6.QtWidgets import QApplication
    from simlibs_qt.app import MainWindow
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(fade_ms=0)   # 截图模式禁用淡入动画，避免抓到过渡帧
    win.resize(1440, 900)
    win.show()
    out = CLI_ROOT / 'output' / 'snapshots-qt'
    out.mkdir(parents=True, exist_ok=True)

    def snap(name: str) -> None:
        app.processEvents()
        for _ in range(6):
            app.processEvents()
        win.grab().save(str(out / f'{name}.png'))
        print('saved', name)

    from PySide6.QtCore import QTimer
    loop_steps = []

    def step() -> bool:
        if not loop_steps:
            return False
        fn = loop_steps.pop(0)
        fn()
        return True

    timer = QTimer()
    timer.setInterval(220)

    def run_steps() -> None:
        if step():
            return
        timer.stop()
        app.quit()

    timer.timeout.connect(run_steps)

    def cycle_pages() -> None:
        for pid in ('batch', 'scan', 'jobs', 'settings'):
            loop_steps.append(lambda p=pid: (win.go(p), snap(f'{p}-dark')))
        loop_steps.append(lambda: (win.go('single'), snap('single-dark')))
        loop_steps.append(lambda: _scroll_single_to_bottom(win))
        loop_steps.append(lambda: snap('single-dark-scrolled'))
        loop_steps.append(lambda: win.toggle_theme())
        for pid in ('single', 'batch', 'scan'):
            loop_steps.append(lambda p=pid: (win.go(p), snap(f'{p}-light')))
        loop_steps.append(lambda: win.toggle_theme())

    def _scroll_single_to_bottom(w) -> None:
        from PySide6.QtWidgets import QScrollArea
        area = w.pages['single'].findChild(QScrollArea)
        if area:
            bar = area.verticalScrollBar()
            bar.setValue(bar.maximum())

    loop_steps.append(lambda: snap('single-dark'))
    loop_steps.append(cycle_pages)
    timer.start()
    app.exec()
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if '--diagnose' in argv:
        return diagnose()
    if '--screenshot' in argv:
        return screenshot_mode()
    try:
        from PySide6.QtCore import QPropertyAnimation
        from PySide6.QtWidgets import QApplication
        from simlibs_qt.app import MainWindow, apply_dark_titlebar
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName('simLIBS Studio')
        window = MainWindow()
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            window.setWindowOpacity(0.0)          # 开场淡入
        window.show()
        apply_dark_titlebar(window)
        if window.windowOpacity() == 0.0:
            fade = QPropertyAnimation(window, b'windowOpacity', window)
            fade.setDuration(240)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(__import__('PySide6.QtCore', fromlist=['QEasingCurve']).QEasingCurve.OutCubic)
            fade.start()
            window._intro_fade = fade
        return app.exec() if hasattr(app, 'exec') else app.exec_()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            (CLI_ROOT / 'last-crash.log').write_text(tb, encoding='utf-8')
        except OSError:
            pass
        print(tb, file=sys.stderr)
        try:
            input('\n[启动失败] 按回车键关闭窗口…（详情已保存 CLI/last-crash.log）')
        except EOFError:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
