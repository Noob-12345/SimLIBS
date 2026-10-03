"""显式联机复验，使用真实 Tk 和与 GUI 相同的所属 worker，结果逐项记录。"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
import time
import tkinter as tk
import numpy as np
import pandas as pd
from PIL import Image, ImageGrab
from simlibs_ui.app import Application, capture_window
from simlibs_ui.models import Parameters, BatchSpec, ScanSpec
from simlibs_ui.settings import Settings, UI_ROOT
from simlibs_ui.storage import read_manifest, write_json

sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='显式真实 NIST 自测；不代表独立验收')
    parser.add_argument('--output', default=str(UI_ROOT/'output'/'real-validation'))
    parser.add_argument('--static-only', action='store_true')
    parser.add_argument('--dynamic-only', action='store_true')
    parser.add_argument('--no-tls-verify', action='store_true', help='显式按源库原设置关闭 TLS 校验并记录（默认校验）')
    parser.add_argument('--driver', default='')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = replace(Settings(), output=str(output), tls_verify=not args.no_tls_verify, driver=args.driver)
    root = tk.Tk()
    app = Application(root, settings)
    report = {'command': [sys.executable, *sys.argv], 'settings': settings.to_dict(), 'steps': [], 'heartbeats': 0,
              'independent_acceptance': False}
    closed = False
    def heartbeat():
        if not closed:
            report['heartbeats'] += 1
            root.after(20, heartbeat)
    heartbeat()
    def persist():
        write_json(output/'real-validation.json', report)
    def task(label, kind, **payload):
        started, ticks = time.monotonic(), report['heartbeats']
        print(f'开始 {label}', flush=True)
        app.start(kind, **payload)
        while app.jobs.busy:
            root.update()
            time.sleep(.02)
        root.update()
        result = {'label': label, 'state': app.jobs.state, 'elapsed': time.monotonic()-started,
                  'heartbeats': report['heartbeats']-ticks, 'worker_pid': app.jobs.process.pid,
                  'worker_exited': app.jobs.process.poll() is not None, 'job_directory': str(app.jobs.directory)}
        if app.jobs.state == 'SUCCEEDED':
            result['manifest'] = app.jobs.result_path
        else:
            result['error'] = app.jobs.error
        report['steps'].append(result)
        persist()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return app.jobs.result_path if app.jobs.state == 'SUCCEEDED' else None

    def check_spectrum(path):
        manifest = read_manifest(path)
        summary = {}
        for view, csv in manifest['files'].items():
            df = pd.read_csv(csv)
            if df.empty or not np.isfinite(df.to_numpy(dtype=float)).all():
                raise AssertionError('真实谱为空或含非有限数据')
            summary[view] = {'shape': list(df.shape), 'max': float(df.iloc[:, 1:].to_numpy().max())}
        report['steps'][-1]['spectra'] = summary
        report['steps'][-1]['origin'] = manifest['origin']
        persist()

    try:
        single = task('H100 static 650–660 nm', 'single', parameters=Parameters().to_dict()) if not args.dynamic_only else None
        if single:
            check_spectrum(single)
            try:
                capture_window(root, output/'real-tk.png')
            except OSError as exc:
                report['screenshot_error'] = str(exc)
                persist()
            for format, filename in [('raw', 'H-raw.csv'), ('interpolated', 'H-interpolated.csv'), ('png', 'H.png'), ('json', 'H-origin.json')]:
                task('H 导出 '+format, 'export', manifest=single, target=str(output/filename), format=format)
        batch = task('size=2 真实批量', 'batch', parameters=Parameters().to_dict(), spec=asdict(BatchSpec()),
                     compositions=[{'H': 100., 'name': 'H-only'}]) if not args.dynamic_only else None
        if batch:
            m = read_manifest(batch)
            df = pd.read_csv(m['dataset'])
            assert len(df) == 2 and list(df.columns[-4:]) == ['H', 'name', 'Te[eV]', 'Ne[cm^-3]']
            report['steps'][-1]['dataset_shape'] = list(df.shape)
            persist()
            task('批量导出宽表', 'export', manifest=batch, target=str(output/'dataset-size2.csv'), format='dataset')
        for axis, start, stop in ([] if args.dynamic_only else [('Te', 1., 1.2), ('Ne', 1e17, 1.2e17), ('R', 1000, 1200)]):
            scan = task(axis+' 两帧真实扫描', 'scan', parameters=Parameters().to_dict(),
                        spec=asdict(ScanSpec(axis=axis, start=start, stop=stop, count=2)))
            if scan:
                m = read_manifest(scan)
                assert len(m['frames']) == 2 and not m['partial']
                for frame in m['frames']:
                    f = read_manifest(frame)
                    for csv in f['files'].values():
                        assert np.isfinite(pd.read_csv(csv).to_numpy(dtype=float)).all()
                gif_path = output/(axis+'.gif')
                gif = task(axis+' GIF 全帧导出', 'export', manifest=scan, target=str(gif_path), format='gif')
                if gif:
                    with Image.open(gif_path) as image:
                        assert image.n_frames == 2
                        report['steps'][-1]['gif_frames'] = image.n_frames
                    persist()
                task(axis+' 完整帧目录导出', 'export', manifest=scan, target=str(output/(axis+'-frames')), format='directory')
        if not args.static_only:
            dynamic = task('H 真实 dynamic / ion 尝试', 'single', parameters=replace(Parameters(), webscraping='dynamic').to_dict())
            if dynamic:
                check_spectrum(dynamic)
                assert 'ion' in read_manifest(dynamic)['files']
                task('完整 ion CSV 导出', 'export', manifest=dynamic, target=str(output/'H-ion.csv'), format='ion')
        baseline = json.loads((UI_ROOT/'.ai-workflow'/'20261002-simlibs-ui'/'source-baseline.json').read_text(encoding='utf-8-sig'))
        report['source_hashes_unchanged'] = all(hashlib.sha256(Path(item['Path']).read_bytes()).hexdigest().upper() == item['Hash'] for item in baseline)
        assert report['source_hashes_unchanged']
        report['all_requested_steps_succeeded'] = all(step['state'] == 'SUCCEEDED' for step in report['steps'])
        persist()
    finally:
        closed = True
        app.close()
        while app.jobs.busy:
            root.update()
            time.sleep(.02)
        try:
            root.update()
        except tk.TclError:
            pass
        app.jobs.force_close()
        try:
            root.destroy()
        except tk.TclError:
            pass
    return 0 if report.get('all_requested_steps_succeeded') else 1


if __name__ == '__main__':
    raise SystemExit(main())
