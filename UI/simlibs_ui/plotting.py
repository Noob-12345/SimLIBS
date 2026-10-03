"""共享绘图样式，重 PNG/GIF 导出在任务进程中进行，不依赖 ImageMagick。"""
import io
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import rcParams
from .storage import atomic_write, read_manifest
from .models import intensity_scale_from_origin

rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False


def draw(ax, frame, view='interpolated', title='Simulated LIBS', color='#2563eb', normalize=False, intensity_scale='unknown'):
    ax.clear()
    if view == 'ion':
        x = frame['Wavelength (nm)'].to_numpy()
        columns = [c for c in frame if c not in ('Wavelength (nm)', 'Sum(calc)')]
        maximum = float(frame[columns].to_numpy().max()) if columns else 0
        for column in columns:
            y = frame[column].to_numpy()
            ax.plot(x, y / maximum if normalize and maximum > 0 else y, label=column, linewidth=1)
    else:
        x, y = frame['wavelength'].to_numpy(), frame['intensity'].to_numpy()
        maximum = float(np.max(y))
        ax.plot(x, y / maximum if normalize and maximum > 0 else y, label=view, color=color, linewidth=1.4)
    label={'photon':'Photon flux [a.u.]','energy':'Energy flux [a.u.]'}.get(intensity_scale,'Intensity [a.u.; scale unknown]')
    ax.set(title=title, xlabel='Wavelength [nm]', ylabel='Normalized intensity' if normalize else label)
    ax.grid(alpha=.25)
    ax.legend(loc='upper right', fontsize=8)


def figure_for(manifest, view, title, color, normalize):
    files = manifest.get('files', {})
    if view not in files:
        view = 'raw' if 'raw' in files else next(iter(files))
    frame = pd.read_csv(files[view])
    figure = Figure(figsize=(9, 5), dpi=110, layout='constrained')
    FigureCanvasAgg(figure)
    draw(figure.add_subplot(111), frame, view, title, color, normalize,intensity_scale_from_origin(manifest.get('origin')))
    return figure


def export_png(manifest, target, view='interpolated', title='Simulated LIBS', color='#2563eb', normalize=False):
    figure = figure_for(manifest, view, title, color, normalize)
    atomic_write(target, lambda path: figure.savefig(path, format='png', dpi=150))
    figure.clear()


def export_gif(manifest, target, title='Simulated LIBS', color='#2563eb', normalize=False, cancelled=lambda: False):
    images = []
    try:
        for i, path in enumerate(manifest['frames']):
            if cancelled():
                return
            frame = read_manifest(path)
            caption = f'{title} | {manifest["axis"]}={manifest["completed_values"][i]:.8g} | {i + 1}/{len(manifest["frames"])}'
            figure = figure_for(frame, 'interpolated', caption, color, normalize)
            buffer = io.BytesIO()
            figure.savefig(buffer, format='png', dpi=90)
            buffer.seek(0)
            with Image.open(buffer) as png:
                images.append(png.convert('RGB').convert('P', palette=Image.Palette.ADAPTIVE))
            figure.clear()
            buffer.close()
        if images and not cancelled():
            atomic_write(target, lambda path: images[0].save(path, format='GIF', save_all=True, append_images=images[1:],
                                                           duration=700, loop=0, optimize=False, disposal=2))
    finally:
        for image in images:
            image.close()
