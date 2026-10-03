"""只选择原始行：保留所有通道峰谷及相邻点，再补最大间隙；不插值或舍入。"""
import heapq
import numpy as np
import pandas as pd
from simlibs_ui.storage import clean_spectrum

SINGLE_POINTS = 6000
SCAN_POINTS = 2000


def sample_indices(xs, ys, budget):
    x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    if y.ndim == 1:
        y = y[:, None]
    if len(x) == 0 or y.ndim != 2 or len(x) != len(y) or budget < 2:
        raise ValueError('显示采样输入无效')
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(np.diff(x) <= 0):
        raise ValueError('显示序列须有限且波长严格递增')
    if len(x) <= budget:
        return np.arange(len(x))
    selected = {0, len(x)-1}
    for column in y.T:
        changes = np.flatnonzero(np.diff(column) != 0)
        signs = np.sign(np.diff(column)[changes])
        turns = np.flatnonzero(signs[:-1] != signs[1:])
        for i in turns:
            for center in (int(changes[i]+1), int(changes[i+1])):
                selected.update(j for j in (center-1,center,center+1) if 0 <= j < len(x))
    if len(selected) > budget:
        raise ValueError(f'全部峰谷需要 {len(selected)} 个原始点，超过显示预算 {budget}；请缩小波段，避免丢失弱峰')
    ordered = sorted(selected)
    gaps = [(-(b-a),a,b) for a,b in zip(ordered,ordered[1:]) if b-a > 1]
    heapq.heapify(gaps)
    while len(selected) < budget and gaps:
        _, a, b = heapq.heappop(gaps)
        middle = (a+b)//2
        selected.add(middle)
        for lo,hi in ((a,middle),(middle,b)):
            if hi-lo > 1:
                heapq.heappush(gaps, (-(hi-lo),lo,hi))
    return np.array(sorted(selected),dtype=int)


def file_series(manifest, budget):
    result = {'ions': []}
    for name, path in (manifest.get('files') or {}).items():
        if name not in ('raw','interpolated','ion'):
            continue
        frame = clean_spectrum(pd.read_csv(path,encoding='utf-8-sig'), ion=name=='ion')
        if name == 'ion':
            columns = [c for c in frame if c not in ('Wavelength (nm)','Sum(calc)')]
            indices = sample_indices(frame['Wavelength (nm)'],frame[columns],budget)
            result['ions'] = [dict(label=c,xs=frame['Wavelength (nm)'].iloc[indices].tolist(),
                                  ys=frame[c].iloc[indices].tolist(),total_points=len(frame)) for c in columns]
        else:
            indices = sample_indices(frame['wavelength'],frame['intensity'],budget)
            result[name] = dict(label=name,xs=frame['wavelength'].iloc[indices].tolist(),
                                ys=frame['intensity'].iloc[indices].tolist(),total_points=len(frame))
    if not result.get('interpolated') and not result.get('raw'):
        raise ValueError('结果缺少完整光谱 CSV，不能用旧预览补造数据')
    return result
