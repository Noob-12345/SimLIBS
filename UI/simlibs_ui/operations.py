"""create_dataset/animation 的有界 GUI 适配，每个样本调用真实单次适配层。"""
from dataclasses import replace
from pathlib import Path
import random
import shutil
import numpy as np
import pandas as pd
from .storage import save_result, read_manifest, validate_compositions, write_json, write_csv, atomic_write, now


def simulation_function(simulator):
    if simulator is not None:
        return simulator
    from .adapter import simulate
    return simulate


def batch(parameters, settings, spec, compositions, directory, emit, cancelled, simulator=None):
    p, s = parameters.validated(), settings.validated()
    spec = spec.validated(p)
    df = validate_compositions(compositions)
    if p.webscraping in ('dynamic','server') and p.broadening != 'local' and not p.resample:
        raise ValueError('动态批量需要主动勾选统一重采样，保证宽表网格一致')
    simulate = simulation_function(simulator)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(spec.seed)
    elements = [c for c in df if c != 'name']
    manifest = {'kind': 'batch', 'requested': spec.size, 'completed': 0, 'partial': True,
                'parameters': p.to_dict(), 'spec': spec.__dict__, 'samples': [], 'created_at': now(),
                'origin': {'kind': 'simulation', 'label': '真实 NIST 批量（按源库选择组成/均匀采样语义，顺序请求）'}}
    rows, grid = [], None
    columns = None
    def persist():
        manifest['completed'] = len(rows)
        if rows:
            path = directory / ('dataset.partial.csv' if manifest['partial'] else 'dataset.csv')
            result = pd.DataFrame(rows, columns=columns)
            write_csv(path, result)
            manifest['dataset'] = str(path)
            manifest['preview'] = result[elements + ['name', 'Te[eV]', 'Ne[cm^-3]']].head(100).to_dict('records')
        write_json(directory / 'manifest.json', manifest)
    try:
        for i in range(spec.size):
            if cancelled():
                break
            row = df.iloc[rng.randrange(len(df))]
            actual = replace(p, elements=tuple(elements), percentages=tuple(float(row[e]) for e in elements),
                             Te=rng.uniform(spec.Te_min, spec.Te_max), Ne=rng.uniform(spec.Ne_min, spec.Ne_max)).validated()
            emit('progress', message=f'批量样本 {i + 1}/{spec.size}：{row["name"]}', current=i, total=spec.size,
                 deadline=p.deadline(s))
            frames, origin = simulate(actual, s) if simulator is not None else simulate(actual,s,cancelled=cancelled,emit=emit)
            spectrum = frames['interpolated']
            current_grid = spectrum['wavelength'].to_numpy(dtype=float)
            if grid is None:
                grid = current_grid
                columns = [str(float(w)) for w in grid] + elements + ['name', 'Te[eV]', 'Ne[cm^-3]']
            elif len(grid) != len(current_grid) or not np.allclose(grid, current_grid, rtol=0, atol=1e-8):
                raise ValueError('批量光谱网格不一致；请选择统一重采样')
            origin['sample_name'] = str(row['name'])
            sample = save_result(directory / f'sample_{i + 1:04d}', frames, origin)
            manifest['samples'].append(sample)
            rows.append(spectrum['intensity'].tolist() + [float(row[e]) for e in elements] + [str(row['name']), actual.Te, actual.Ne])
            persist()
            emit('progress', message=f'已完成 {i + 1}/{spec.size}', current=i + 1, total=spec.size)
        manifest['partial'] = len(rows) != spec.size or cancelled()
        manifest['completed'] = len(rows)
        if not manifest['partial']:
            from .training import build_training_package
            persist()
            emit('progress', message='正在后台打包完整训练光谱与配对标签', deadline=600)
            manifest['training_package'] = build_training_package(directory, manifest, cancelled)
            if cancelled():
                manifest.pop('training_package', None)
                manifest['partial'] = True
        persist()
    except Exception as exc:
        manifest['partial'] = True
        manifest.pop('training_package', None)
        manifest['error'] = str(exc)
        persist()
        raise
    return str(directory / 'manifest.json')


def scan(parameters, settings, spec, directory, emit, cancelled, simulator=None):
    p, s = parameters.validated(), settings.validated()
    values = spec.validated(p)
    simulate = simulation_function(simulator)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'kind': 'scan', 'axis': spec.axis, 'values': values, 'completed_values': [], 'frames': [],
                'parameters': p.to_dict(), 'partial': True, 'created_at': now(),
                'origin': {'kind': 'simulation', 'label': '真实 NIST 参数扫描（各帧独立请求）'}}
    try:
        for i, value in enumerate(values):
            if cancelled():
                break
            actual = replace(p, **{('resolution' if spec.axis == 'R' else spec.axis): value}).validated()
            emit('progress', message=f'{spec.axis} = {value:.8g}，帧 {i + 1}/{len(values)}', current=i, total=len(values),
                 deadline=p.deadline(s))
            frames, origin = simulate(actual, s) if simulator is not None else simulate(actual,s,cancelled=cancelled,emit=emit)
            origin['scan_axis'], origin['scan_value'] = spec.axis, value
            manifest['frames'].append(save_result(directory / f'frame_{i + 1:04d}', frames, origin))
            manifest['completed_values'].append(value)
            write_json(directory / 'manifest.json', manifest)
            emit('progress', message=f'已完成帧 {i + 1}/{len(values)}', current=i + 1, total=len(values))
        manifest['partial'] = len(manifest['frames']) != len(values) or cancelled()
    except Exception as exc:
        manifest['error'] = str(exc)
        write_json(directory / 'manifest.json', manifest)
        raise
    write_json(directory / 'manifest.json', manifest)
    return str(directory / 'manifest.json')


def export_result(manifest_path, target, format, view='interpolated', title='Simulated LIBS', color='#2563eb', normalize=False, cancelled=lambda: False):
    manifest = read_manifest(manifest_path)
    target = Path(target).resolve()
    if format in ('raw', 'interpolated', 'ion'):
        source = manifest.get('files', {}).get(format)
        if not source:
            raise ValueError(f'当前数据没有 {format}；ion 需要 dynamic 获取')
        atomic_write(target, lambda path: shutil.copyfile(source, path))
        write_json(str(target) + '.json', manifest['origin'])
    elif format == 'json':
        write_json(target, manifest)
    elif format == 'dataset':
        if manifest.get('partial') or 'dataset' not in manifest:
            raise ValueError('批量不完整，不能作为成功数据集导出；partial 文件仅供检查')
        atomic_write(target, lambda path: shutil.copyfile(manifest['dataset'], path))
        write_json(str(target) + '.json', manifest)
    elif format == 'training':
        package = manifest.get('training_package') or {}
        if manifest.get('partial') or not package.get('available') or not Path(package.get('archive', '')).is_file():
            raise ValueError('此任务没有完整训练包；重新运行批量模拟后可下载')
        atomic_write(target, lambda path: shutil.copyfile(package['archive'], path))
    elif format == 'directory':
        if target.exists():
            raise ValueError('完整结果导出目录已存在，请选择新目录名')
        if cancelled():
            return
        shutil.copytree(Path(manifest_path).parent, target)
        # 清单使用绝对路径；复制后重定位全部任务内路径，离线可搬运。
        source_root = str(Path(manifest_path).parent.resolve())
        for path in target.rglob('*.json'):
            text = path.read_text(encoding='utf-8')
            text = text.replace(json_escape(source_root), json_escape(str(target)))
            path.write_text(text, encoding='utf-8')
    elif format == 'png':
        from .plotting import export_png
        export_png(manifest, target, view, title, color, normalize)
        write_json(str(target) + '.json', manifest.get('origin', {}))
    elif format == 'gif':
        from .plotting import export_gif
        if manifest.get('kind') != 'scan' or manifest.get('partial'):
            raise ValueError('GIF 需要完整扫描结果')
        export_gif(manifest, target, title, color, normalize, cancelled)
        if not cancelled():
            write_json(str(target) + '.json', manifest)
    else:
        raise ValueError(f'未知导出格式：{format}')


def json_escape(value):
    import json
    return json.dumps(value, ensure_ascii=False)[1:-1]
