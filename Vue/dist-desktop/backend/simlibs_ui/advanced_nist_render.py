"""Advanced no-Stark rendering using the original per-ion line renderer."""
from types import SimpleNamespace
import numpy as np
import pandas as pd

from .storage import valid_ion_column
from .models import MAX_CELLS


def render_plain(bands, lines_engine, *, low, high, step, resolution, instrument, factor):
    table = pd.concat([table for table, _ in bands], ignore_index=True).fillna(0.)
    columns = [column for column in table if valid_ion_column(column)]
    if not columns or not (table[columns].to_numpy() > 0).any():
        raise ValueError('当前波段未找到非零 NIST 谱线，请调整波长范围')
    grid = lines_engine.wavelength_grid(low, high, step)
    if len(grid)*(len(columns)+2)*2 > MAX_CELLS or len(grid)*len(table) > 50_000_000:
        raise ValueError('高级输出超过计算/内存上限，请加大步长或缩小波段')
    scaled = table.copy()
    scaled[columns] *= factor
    ion = pd.DataFrame({'Wavelength (nm)': grid})
    # Each mixed-request ion retains its fetched weight; never rerun pure elements.
    for column in columns:
        ion[column] = lines_engine.render_sticks(scaled[['wavelength', column]], grid, resolution,
                            instrument_broadening=instrument)['intensity'].to_numpy()
    ion['Sum(calc)'] = ion[columns].sum(axis=1)
    main = pd.DataFrame({'wavelength': grid, 'intensity': ion['Sum(calc)']})
    if not np.isfinite(ion.to_numpy()).all():
        raise ValueError('高级展宽产生非有限值')
    metadata = {'model_version': 'nist-lines-instrument-1' if instrument else 'nist-lines-sticks-1',
                'self_absorption': False, 'stark_broadening': False, 'instrument_broadening': instrument,
                'line_count': int((scaled[columns].to_numpy() > 0).sum()),
                'output_points': len(grid), 'output_step_nm': float(grid[1]-grid[0]),
                'assumptions': ['NIST mixed-request ion areas; shared grid; no atomic population or Stark coefficients.',
                                'No-broadening output is area/centroid conserving grid projection, not a physical line width.']}
    result = SimpleNamespace(spectrum=main, thin_spectrum=main.copy(), ion_spectrum=ion,
            thin_ion_spectrum=ion.copy(), line_diagnostics=pd.DataFrame(), metadata=metadata)
    return result, scaled
