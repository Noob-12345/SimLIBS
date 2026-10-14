"""从已保存的完整批量光谱生成两行光谱/元素标签训练包（仅由 worker 调用）。"""
import csv
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

import numpy as np
import pandas as pd

from .models import MAX_CELLS, composition, integer, intensity_scale_from_origin
from .storage import read_manifest, write_json

REFERENCE_ELEMENTS = 'Si Al Fe Ca K Na Mg Cr Cu Mn Zn Ti Ni Mo C Li Pb Y Eu Lu Er Ho Yb La Tm Tb Sm Pr'.split()


def build_training_package(directory, manifest, cancelled=lambda: False):
    directory = Path(directory).resolve()
    size = integer(manifest['spec']['batch_size'], '每 batch 光谱数', 1)
    samples = manifest.get('samples') or []
    if size > 5000 or manifest.get('partial') or not samples or len(samples) != manifest['requested'] or manifest.get('error'):
        raise ValueError('训练包需要完整成功的批量结果和有效 batch_size')
    origins = [read_manifest(path).get('origin') or {} for path in samples]
    extras = sorted({el for origin in origins for el in (origin.get('parameters') or {}).get('elements', [])}
                    - set(REFERENCE_ELEMENTS))
    elements = REFERENCE_ELEMENTS + extras
    metadata = {'schema': 1, 'format': 'alternating wavelength/intensity rows; paired atomic-percent labels',
                'spectra_header': False, 'contents_header': True, 'view': 'interpolated',
                'label_order': elements, 'sample_count': len(samples), 'batch_size': size,
                'parameters': manifest['parameters'], 'spec': manifest['spec'], 'origin': manifest['origin'],
                'packages': [], 'samples': []}
    grid, cells = None, 0

    def check_cancel():
        if cancelled():
            raise InterruptedError('训练数据打包已取消')

    with tempfile.TemporaryDirectory(prefix='.training-', dir=directory) as temporary:
        staging = Path(temporary)
        for key in ('actual_parameters','template_csv'):
            source=manifest.get(key)
            if source:
                check_cancel();path=Path(source);shutil.copyfile(path,staging/path.name)
                metadata[key]={'filename':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        for start in range(0, len(samples), size):
            check_cancel()
            ordinal = start // size + 1
            suffix = '' if ordinal == 1 else f'_{ordinal}'
            spectra_name, contents_name = f'Random_spectra{suffix}.csv', f'Random_contents{suffix}.csv'
            stop = min(start + size, len(samples))
            with (staging / spectra_name).open('w', newline='', encoding='utf-8') as spectra_stream, \
                 (staging / contents_name).open('w', newline='', encoding='utf-8') as contents_stream:
                spectra_writer, contents_writer = csv.writer(spectra_stream), csv.writer(contents_stream)
                contents_writer.writerow(elements)
                for index in range(start, stop):
                    check_cancel()
                    source = read_manifest(samples[index])
                    frame = pd.read_csv(source['files']['interpolated'], encoding='utf-8-sig', float_precision='round_trip')
                    wavelengths = frame['wavelength'].to_numpy(dtype=float)
                    intensities = frame['intensity'].to_numpy(dtype=float)
                    if not len(wavelengths) or not np.isfinite(wavelengths).all() or not np.isfinite(intensities).all():
                        raise ValueError('训练光谱为空或含非有限值')
                    if np.any(np.diff(wavelengths) <= 0):
                        raise ValueError('训练光谱波长必须严格递增')
                    if grid is None:
                        grid = wavelengths.copy()
                    elif not np.array_equal(grid, wavelengths):
                        raise ValueError('训练光谱网格不一致，不能生成配对训练包')
                    cells += len(wavelengths)
                    if cells > MAX_CELLS:
                        raise ValueError('训练包超过 5000000 个光谱单元')
                    origin = origins[index]
                    actual = origin.get('parameters') or {}
                    labels, percentages = composition(actual.get('elements', []), actual.get('percentages', []))
                    label_values = dict(zip(labels, percentages))
                    spectra_writer.writerow(wavelengths)
                    spectra_writer.writerow(intensities)
                    contents_writer.writerow([label_values.get(el, 0.0) for el in elements])
                    metadata['samples'].append({'index': index + 1, 'package': ordinal,
                                                'spectra_rows': [(index-start)*2+1, (index-start)*2+2],
                                                'contents_row': index-start+2, 'source_manifest': samples[index],
                                                'origin': origin, 'intensity_scale': intensity_scale_from_origin(origin)})
            metadata['packages'].append({'index': ordinal, 'sample_count': stop-start,
                                         'sample_start': start+1, 'sample_end': stop,
                                         'spectra': spectra_name, 'contents': contents_name,
                                         'sha256': {name: hashlib.sha256((staging/name).read_bytes()).hexdigest()
                                                    for name in (spectra_name, contents_name)}})
        metadata['grid'] = {'points': len(grid), 'low_w': float(grid[0]), 'upper_w': float(grid[-1]),
                            'sha256': hashlib.sha256(grid.tobytes()).hexdigest()}
        write_json(staging / 'package-manifest.json', metadata)
        write_json(staging / 'source-manifest.json', manifest)
        archive = staging / 'training.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for source in sorted(staging.iterdir()):
                if source == archive:
                    continue
                check_cancel()
                with source.open('rb') as input_stream, output.open(source.name, 'w') as member:
                    while chunk := input_stream.read(1024*1024):
                        check_cancel()
                        member.write(chunk)
        check_cancel()
        target = directory / 'training'
        if target.exists() or target.is_symlink():
            raise FileExistsError(f'训练产物目录已存在，不覆盖：{target}')
        # Windows 同卷移动会保留私有 staging DACL。先在正常输出目录中新建
        # 文件并复制内容，使其继承输出权限，再原子发布整个完整目录。
        publication = directory / ('.training-publish-' + uuid.uuid4().hex)
        publication.mkdir()
        try:
            for source in staging.iterdir():
                check_cancel()
                with source.open('rb') as input_stream, (publication / source.name).open('xb') as output_stream:
                    while chunk := input_stream.read(1024*1024):
                        check_cancel()
                        output_stream.write(chunk)
            check_cancel()
            # Readers/antivirus may briefly hold a Windows directory handle.
            # Retry the same atomic rename, preserving no-overwrite publication.
            import os
            import time
            for attempt in range(11):
                check_cancel()
                try:
                    publication.rename(target)
                    break
                except PermissionError as exc:
                    if os.name != 'nt' or getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 10:
                        raise
                    time.sleep(.025 * (attempt + 1))
        finally:
            if publication.exists():
                assert publication.resolve().is_relative_to(directory)
                shutil.rmtree(publication)
    return {'available': True, 'archive': str(target/'training.zip'),
            'manifest': str(target/'package-manifest.json'), 'batch_size': size,
            'packages': len(metadata['packages']), 'sample_counts': [p['sample_count'] for p in metadata['packages']],
            'points': len(grid), 'label_order': elements, 'source': manifest['origin']['label']}
