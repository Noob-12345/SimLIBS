"""simLIBS Studio CLI —— 终端界面入口。

用法：
    python run_cli.py                 # 真实引擎（需 NIST 网络）
    python run_cli.py --mock          # MOCK 演示引擎（合成谱，界面黄色 MOCK 徽章）
    python run_cli.py --diagnose      # 只检查解释器/依赖/源路径，不启动界面、不联网
"""
from __future__ import annotations

import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CLI_ROOT))


def diagnose() -> int:
    print('simLIBS Studio CLI · 诊断（不联网）')
    print(f'Python       : {sys.version}')
    print(f'解释器       : {sys.executable}')
    ok = True
    for mod in ('textual', 'rich', 'numpy', 'pandas', 'scipy', 'matplotlib',
                'requests', 'bs4', 'PIL'):
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


def main() -> int:
    if '--diagnose' in sys.argv[1:]:
        return diagnose()
    try:
        from simlibs_cli.app import main as run_app
        run_app()
        return 0
    except Exception:
        # 崩溃详情同时写入 CLI/last-crash.log，双击启动时窗口不闪退、错误可追溯
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
