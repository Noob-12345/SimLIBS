"""批量光谱 → 神经网络训练 batch 打包。

格式与命名完全参照 Cross_attention/Dataset（datagen.py + SimspecGen/Gen.py 的约定）：
- `<prefix>_spectra[_N].csv`：每条光谱占两行（第一行=强度、第二行=波长），无表头无索引；
- `<prefix>_contents[_N].csv`：每条光谱一行浓度，固定元素列（未使用元素填 0），新建文件写表头；
- batch 满了自动换下一个编号（_2、_3…），目录里未写满的旧批次优先续写（与
  Gen.get_random_batch_target 语义一致）。
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

META_COLS = ('name', 'Te[eV]', 'Ne[cm^-3]')


def _is_wavelength(col: str) -> bool:
    try:
        v = float(str(col))
        return math.isfinite(v) and v > 0
    except (TypeError, ValueError):
        return False


def element_columns(df: pd.DataFrame) -> list[str]:
    """数据集宽表中的元素浓度列（非波长、非元信息），保持出现顺序。"""
    return [c for c in df.columns
            if c not in META_COLS and not _is_wavelength(str(c))]


def _find_target(out_dir: Path, prefix: str, batch_size: int) -> tuple[int, int]:
    """返回 (批号, 已有条数)：优先续写未满批次；否则下一个未用编号。"""
    number = 1
    while True:
        suffix = '' if number == 1 else f'_{number}'
        spectra = out_dir / f'{prefix}_spectra{suffix}.csv'
        if not spectra.is_file():
            return number, 0
        with spectra.open(encoding='utf-8') as fh:
            rows = sum(1 for _ in fh)
        existing = rows // 2
        if rows < 2 * batch_size:
            return number, existing
        number += 1


def _sample_rows(df: pd.DataFrame) -> tuple[list[list[float]], list[list[float]], list[dict]]:
    wl_cols = [c for c in df.columns if _is_wavelength(str(c))]
    if not wl_cols:
        raise ValueError('数据集中没有波长列，无法生成 spectra')
    el_cols = element_columns(df)
    if not el_cols:
        raise ValueError('数据集中没有元素浓度列，无法生成 contents')
    intensities, wavelengths, metas = [], [], []
    for _, row in df.iterrows():
        intensity = [float(row[c]) for c in wl_cols]
        wavelength = [float(c) for c in wl_cols]
        if not all(math.isfinite(v) for v in intensity + wavelength):
            raise ValueError('数据集包含非有限数值，拒绝打包')
        intensities.append(intensity)
        wavelengths.append(wavelength)
        metas.append({c: (float(row[c]) if c in el_cols and pd.notna(row[c]) else 0.0)
                      for c in el_cols})
    return intensities, wavelengths, metas


def pack_dataset(dataset_csv: str | Path, out_dir: str | Path, batch_size: int = 32,
                 prefix: str = 'Random') -> list[str]:
    """把批量数据集宽表按 batch_size 打包成训练用 CSV 对，返回写出/续写的文件路径。"""
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError('每包样本数必须是正整数')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(Path(dataset_csv), encoding='utf-8-sig')
    if df.empty:
        raise ValueError('数据集为空，无法打包')
    intensities, wavelengths, metas = _sample_rows(df)

    written: list[str] = []
    idx, total = 0, len(intensities)
    while idx < total:
        number, existing = _find_target(out, prefix, batch_size)
        take = min(batch_size - existing, total - idx)
        suffix = '' if number == 1 else f'_{number}'
        spectra_path = out / f'{prefix}_spectra{suffix}.csv'
        contents_path = out / f'{prefix}_contents{suffix}.csv'
        appending = existing > 0 and spectra_path.is_file() and contents_path.is_file()
        if appending:   # 沿用已有表头的固定浓度列
            cols = list(pd.read_csv(contents_path, nrows=0).columns)
        else:
            cols = list(metas[0].keys())
            appending = False
        rows = []
        for k in range(take):
            rows.append(intensities[idx + k])
            rows.append(wavelengths[idx + k])
        pd.DataFrame(rows).to_csv(spectra_path, mode='a' if appending else 'w',
                                  header=False, index=False)
        meta_df = pd.DataFrame([{c: m.get(c, 0.0) for c in cols} for m in metas[idx:idx + take]])
        meta_df.to_csv(contents_path, mode='a' if appending else 'w',
                       header=not appending, index=False)
        written.extend([str(spectra_path), str(contents_path)])
        idx += take
    return written
