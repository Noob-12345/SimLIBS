"""CSV/JSON 与小型预览清单；完整数据保存在任务专属文件中。"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
from contextlib import contextmanager
import re
import uuid
import numpy as np
import pandas as pd
from .models import composition, MAX_POINTS, ELEMENTS, MAX_CELLS


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path, writer):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        writer(temp)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, lambda tmp: tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8'))


def write_csv(path, df):
    atomic_write(path, lambda tmp: df.to_csv(tmp, index=False, encoding='utf-8-sig'))


def drop_index(df):
    return df.loc[:, [c for c in df.columns if str(c).strip() and not str(c).startswith('Unnamed:')]].copy()


def read_compositions(path, name_column='name'):
    df = drop_index(pd.read_csv(path, encoding='utf-8-sig', nrows=5001))
    if len(df) > 5000:
        raise ValueError('组成 CSV 最多 5000 行，请拆分文件')
    df.columns = [str(c).strip() for c in df.columns]
    name_column = name_column.strip()
    rename = {c: str(c).strip().removesuffix('_at%') for c in df.columns}
    if name_column not in df.columns:
        raise ValueError(f'缺少样本名称列 {name_column}；请设置名称列映射')
    rename[name_column] = 'name'
    df = df.rename(columns=rename)
    if df.columns.duplicated().any():
        raise ValueError('CSV 映射后有重复元素列')
    return df[[c for c in df if c != 'name'] + ['name']]


def validate_compositions(df):
    if df.empty or 'name' not in df or df.columns.duplicated().any():
        raise ValueError('组成表不能为空，必须有唯一 name 列')
    elements = [c for c in df if c != 'name']
    records = []
    errors = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        try:
            e, p = composition(elements, [row[c] for c in elements])
            if pd.isna(row['name']) or not str(row['name']).strip():
                raise ValueError('样本名称不能为空')
            records.append(dict(zip(e, p), name=str(row['name']).strip()))
        except ValueError as exc:
            errors.append(f'第 {i} 行：{exc}')
    if errors:
        raise ValueError('\n'.join(errors[:20]) + ('\n更多错误未列出' if len(errors) > 20 else ''))
    return pd.DataFrame(records, columns=elements + ['name'])


def valid_ion_column(column):
    """合法元素/离子列，可选丰度须为有限非负十进制数（含科学计数）。"""
    name = str(column).strip()
    match = re.fullmatch(r'([A-Z][a-z]?)\s+[IVXLCDM]+(?:\s*\(([^()]*)\))?', name)
    if not match:
        prefix = re.match(r'([A-Z][a-z]?)\s+[IVXLCDM]+(?:\s|\(|$)', name)
        if prefix and prefix.group(1) in ELEMENTS:
            raise ValueError(f'离子列名或丰度后缀格式无效：{name}')
        return False
    if match.group(1) not in ELEMENTS:
        return False
    abundance = match.group(2)
    if abundance is not None:
        abundance = abundance.strip()
        if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', abundance):
            raise ValueError(f'离子丰度须为有限非负数：{name}')
        number = float(abundance)
        if not np.isfinite(number) or number < 0:
            raise ValueError(f'离子丰度须为有限非负数：{name}')
    return True


def clean_spectrum(df, ion=False):
    df = drop_index(df)
    if ion:
        # 保留 CSV 原始词元后，只将合法离子列的真正空白单元视为无贡献。
        # np.nan/pd.NA/None 和字面 NaN/Inf 都不是空白，必须在后续数值检查拒绝。
        # 离子列名允许 NIST 的丰度后缀，如 "Fe I (4.4e-2)"（dynamic 页面表格常见）。
        ion_columns = {column for column in df.columns if valid_ion_column(column)}
        for column in df.columns:
            if column in ion_columns:
                blank = df[column].map(lambda value: isinstance(value, str) and not value.strip())
                if blank.any():
                    df.loc[blank, column] = '0'
        # 真实 NIST 当前单离子 CSV 省略 Sum(calc)，总谱就是唯一贡献列原值。
        if 'Wavelength (nm)' in df and 'Sum(calc)' not in df and len(df.columns) == 2:
            column = next(c for c in df if c != 'Wavelength (nm)')
            if column in ion_columns:
                df['Sum(calc)'] = df[column]
        if 'Wavelength (nm)' not in df or 'Sum(calc)' not in df or len(df.columns) < 3:
            raise ValueError(f'离子 CSV 需要 Wavelength (nm)、Sum(calc) 和离子分量列；实际列：{list(df.columns)}')
        wavelength = 'Wavelength (nm)'
    else:
        if not {'wavelength', 'intensity'}.issubset(df.columns):
            raise ValueError('光谱 CSV 需要 wavelength/intensity 列')
        df = df[['wavelength', 'intensity']]
        wavelength = 'wavelength'
    if df.empty or len(df) > MAX_POINTS:
        raise ValueError('光谱为空或超过 200000 点')
    if ion and df.size>MAX_CELLS:
        raise ValueError('离子通道超过5000000个单元，请缩小波段/离子阶数')
    try:
        df = df.apply(pd.to_numeric, errors='raise').astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError('光谱包含非数值数据') from exc
    if not np.isfinite(df.to_numpy()).all():
        raise ValueError('光谱包含 NaN 或无穷值')
    df = df.sort_values(wavelength).reset_index(drop=True)
    if df[wavelength].duplicated().any():
        raise ValueError('光谱含重复波长，不能插值')
    return df


def read_history(path):
    path = Path(path).resolve()
    df = drop_index(pd.read_csv(path, encoding='utf-8-sig', nrows=MAX_POINTS+1,
                               dtype=str, keep_default_na=False))
    if 'Wavelength (nm)' in df:
        ion = clean_spectrum(df, ion=True)
        raw = ion[['Wavelength (nm)', 'Sum(calc)']].rename(columns={'Wavelength (nm)': 'wavelength', 'Sum(calc)': 'intensity'})
        frames = {'raw': raw, 'interpolated': raw.copy(), 'ion': ion}
    else:
        frames = {'raw': clean_spectrum(df)}
    origin = {'kind': 'history', 'label': '已保存数据；参数未知（未执行新模拟）', 'path': str(path),
              'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'parameters': None, 'imported_at': now()}
    if 'Wavelength (nm)' in df and 'Sum(calc)' not in df:
        origin['ion_total'] = f'copied sole {next(c for c in df if c != "Wavelength (nm)")} contribution (NIST omitted Sum(calc))'
    return frames, origin


def save_result(directory, frames, origin, preview_limit=1500):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {'kind': 'spectrum', 'origin': origin, 'files': {}, 'counts': {}, 'preview': {}, 'columns': {}}
    for key, frame in frames.items():
        df = clean_spectrum(frame, ion=key in ('ion','ion_interpolated'))
        path = directory / f'{key}.csv'
        write_csv(path, df)
        manifest['files'][key] = str(path)
        manifest['counts'][key] = len(df)
        manifest['columns'][key] = list(df.columns)
        indices = np.unique(np.linspace(0, len(df) - 1, min(len(df), preview_limit)).astype(int))
        manifest['preview'][key] = df.iloc[indices].to_dict(orient='records')
    path = directory / 'manifest.json'
    write_json(path, manifest)
    return str(path)


def read_manifest(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
@contextmanager
def diagnostic_scope(directory):
    """Each dedicated worker sample/frame owns immutable transport diagnostics."""
    previous=os.environ.get('SIMLIBS_TASK_DIR')
    path=Path(directory).resolve();path.mkdir(parents=True,exist_ok=True)
    os.environ['SIMLIBS_TASK_DIR']=str(path)
    try:yield
    finally:
        if previous is None:os.environ.pop('SIMLIBS_TASK_DIR',None)
        else:os.environ['SIMLIBS_TASK_DIR']=previous
