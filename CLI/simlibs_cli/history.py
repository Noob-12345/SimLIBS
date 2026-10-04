"""离线导入历史光谱 CSV（不联网）。

接受两类格式（与 Tk 桌面版一致）：
- `wavelength,intensity` 简单两列；
- NIST CSV（`Wavelength (nm)` + `Sum(calc)` + 离子列），单离子省略 Sum(calc) 的
  情形沿用 simlibs_ui.storage.clean_spectrum 的补列规则。
历史数据明确标注"参数未知"，不会作为新模拟成功结果。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def load_history(path: str | Path, budget: int = 6000) -> dict:
    from sampling import sample_indices  # UI/web/sampling.py，保峰抽样
    from simlibs_ui.storage import clean_spectrum

    file = Path(path)
    if not file.is_file():
        raise ValueError(f'文件不存在：{file}')
    df = pd.read_csv(file, encoding='utf-8-sig')
    if df.empty:
        raise ValueError('CSV 为空')
    ions = False
    if {'wavelength', 'intensity'}.issubset(df.columns):
        frame = clean_spectrum(df[['wavelength', 'intensity']])
    elif 'Wavelength (nm)' in df.columns:
        frame = clean_spectrum(df, ion=True)
        ions = True
    else:
        raise ValueError('需要 wavelength/intensity 两列，或 NIST 格式（Wavelength (nm)…）')

    if ions:
        wl = frame['Wavelength (nm)']
        ion_cols = [c for c in frame.columns if c not in ('Wavelength (nm)', 'Sum(calc)')]
        columns = ion_cols + (['Sum(calc)'] if 'Sum(calc)' in frame.columns else [])
        idx = sample_indices(wl, frame[columns], budget)
        series = [dict(label=str(c), xs=wl.iloc[idx].tolist(), ys=frame[c].iloc[idx].tolist())
                  for c in columns]
        total = sum(len(s['xs']) for s in series)
    else:
        idx = sample_indices(frame['wavelength'], frame['intensity'], budget)
        series = [dict(label='intensity', xs=frame['wavelength'].iloc[idx].tolist(),
                       ys=frame['intensity'].iloc[idx].tolist())]
        total = len(frame)
    return {
        'series': series,
        'meta': {
            'source': f'历史 CSV · {file.name}',
            'path': str(file.resolve()),
            'sha256': file_sha256(file)[:12] + '…',
            'points': f'抽样 {sum(len(s["xs"]) for s in series):,}/{total:,} 点（保峰预算 {budget}）',
            'params': '参数未知（历史数据，非本次模拟）',
        },
    }
