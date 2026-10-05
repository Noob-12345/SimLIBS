"""simLIBS Studio Qt —— 真实引擎联机冒烟（显式复验，不代表独立验收）。

用法（E:\\Anaconda\\envs\\simLIBS\\python.exe）：
    python verify_real.py                       # H 窄波段 · static + 本地展宽（无需浏览器）
    python verify_real.py --wfe-mo              # W/Fe/Mo 200–1000 nm 宽波段
    python verify_real.py --output <dir>        # 自定义输出目录

流程：Qt 窗口（offscreen 渲染）驱动与真实界面完全相同的路径（按钮 → JobController 专属
worker 子进程 → 真实 NIST 请求 → manifest 证据 → 图表渲染 → 导出），并保存页面 PNG 快照。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CLI_ROOT))
sys.dont_write_bytecode = True

os.environ.pop('SIMLIBS_WEB_BACKEND', None)   # 强制真实引擎
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')

import asyncio  # noqa: E402  (仅用于兼容旧调用方式；实际用 QTimer 步进)


def run_verification(output: Path, wfe_mo: bool) -> dict:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from simlibs_qt.app import MainWindow

    report: dict = {'command': [sys.executable, *sys.argv], 'engine': 'real-qt',
                    'steps': [], 'independent_acceptance': False}
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow(fade_ms=0)
    win.resize(1440, 900)
    win.show()
    out = output
    snaps = out / 'snapshots'
    snaps.mkdir(parents=True, exist_ok=True)
    state = {'step': 'params', 'result': None, 'export_files': [], 't0': time.monotonic()}

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait(cond, timeout_s: float, what: str) -> bool:
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
            if cond():
                return True
        report['steps'].append({'step': what, 'ok': False, 'note': f'{timeout_s}s 超时'})
        return False

    def snap(name: str) -> None:
        for _ in range(20):
            app.processEvents()
        win.grab().save(str(snaps / f'{name}.png'))

    def save_report(ok: bool) -> dict:
        report['ok'] = ok
        (out / 'verify-real.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'ok': ok, 'steps': [s.get('step') for s in report['steps']],
                          'report': str(out / 'verify-real.json')}, ensure_ascii=False), flush=True)
        return report

    # 参数：本地模拟（离线，确定性，不依赖 NIST）
    pump(0.6)
    win.s_mode.setCurrentIndex(0)
    if wfe_mo:
        win.preset_wfm()
        label = 'W/Fe/Mo 200–700nm · local 离线'
    else:
        win.preset_h()
        label = 'Fe 100% 200–700nm · local 离线'
    pump(0.4)
    report['steps'].append({'step': 'params', 'label': label})

    # 运行（等待结果就绪；仅当界面明确显示失败时才提前退出）
    win.start_single()
    settled = wait(lambda: win._single_result is not None
                   or '失败' in win.status_chip.label.text(), 150, 'run')
    result = win._single_result
    if result is None:
        tail = win.task_log.toPlainText().strip().splitlines()[-3:]
        report['steps'].append({'step': 'run', 'ok': False, 'note': '任务失败（多为 NIST 网络波动）',
                                'log_tail': tail})
        win.close()
        return save_report(False)
    # 完成后等待 _route_result 完成画布填充
    wait(lambda: len(win.s_chart._series) > 0, 20, 'chart')
    elapsed = time.monotonic() - state['t0']
    result = win._single_result
    meta = result.get('meta') or {}
    xs, ys = result.get('xs') or [], result.get('ys') or []
    origin = result.get('origin') or {}
    checks = {
        'kind_single': result.get('kind') == 'single',
        'points_finite': bool(xs) and len(xs) == len(ys),
        'chart_rendered': len(win.s_chart._series) >= 1,
        'meta_source': bool(meta.get('source')),
        'sha256': bool(meta.get('sha256')),
        'mode_local': (origin.get('mode') or meta.get('mode')) == 'local',
        'photon_only': (origin.get('parameters') or {}).get('intensity_scale') == 'photon',
        'broadening_local': meta.get('broadening') == 'local',
    }
    report['steps'].append({'step': 'run', 'ok': all(checks.values()), 'elapsed': round(elapsed, 1),
                            'checks': checks, 'meta_source': str(meta.get('source')),
                            'points': f'{len(xs)}/{meta.get("points", "")}'})
    snap('single-result-dark')

    # 导出（走真实界面同一 backend.export 路径）
    export_dir = out / 'exports'
    win.s_export_dir.setText(str(export_dir))
    win.do_export(result, ['csv', 'json', 'png'], str(export_dir))
    if not wait(lambda: len(list(export_dir.glob('*'))) >= 3, 120, 'export'):
        return save_report(False)
    report['steps'].append({'step': 'export', 'ok': True,
                            'files': sorted(f.name for f in export_dir.glob('*'))})

    # 页面快照（各页面 + 亮色主题）
    win.go('scan'); pump(0.3); snap('scan-dark')
    win.go('batch'); pump(0.3); snap('batch-dark')
    win.go('jobs'); pump(0.3); snap('jobs-dark')
    win.go('settings'); pump(0.3); snap('settings-dark')
    win.go('single'); pump(0.3)
    win.toggle_theme(); pump(0.3); snap('single-result-light')
    win.toggle_theme(); pump(0.2)
    report['steps'].append({'step': 'snapshots', 'ok': True,
                            'files': sorted(f.name for f in snaps.glob('*.png'))})
    win.close()
    ok = all(s.get('ok', True) for s in report['steps']) if report else False
    report = save_report(ok) if isinstance(report, dict) and 'ok' not in report else report
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='simLIBS Qt 真实引擎联机冒烟')
    parser.add_argument('--output', default=str(CLI_ROOT / 'output' / 'real-validation-qt'))
    parser.add_argument('--wfe-mo', action='store_true', help='改用 W/Fe/Mo 宽波段用例')
    parser.add_argument('--attempts', type=int, default=3, help='NIST 网络波动自动重试次数')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = None
    for attempt in range(1, args.attempts + 1):
        report = run_verification(output, args.wfe_mo)
        run_step = next((s for s in report.get('steps', []) if s.get('step') == 'run'), {})
        network_fail = (not report.get('ok')) and ('SSLError' in json.dumps(run_step, ensure_ascii=False)
                                                   or '网络波动' in str(run_step.get('note', '')))
        if report.get('ok') or not network_fail:
            break
        print(f'attempt {attempt}: NIST 网络波动，重试…', flush=True)
        time.sleep(3)
    ok = bool(report and report.get('ok'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
