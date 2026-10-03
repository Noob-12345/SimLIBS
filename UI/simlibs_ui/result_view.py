"""Matplotlib 与分页预览。完整数据读取和导出不在 Tk 主线程执行。"""
import tkinter as tk
from tkinter import ttk, colorchooser
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from .plotting import draw
from .models import intensity_scale_from_origin


class ResultView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.manifest = None
        self.available_views = []
        self.view = tk.StringVar(value='interpolated')
        self.title = tk.StringVar(value='Simulated LIBS')
        self.color = '#2563eb'
        self.normalize = tk.BooleanVar(value=False)
        self.origin = tk.StringVar(value='尚无光谱。可真实模拟，或离线打开已有 CSV。')
        self.info = tk.StringVar(value='ion 需要 dynamic；static 不生成离子分量。')
        self.page = 0
        self.origin_label = ttk.Label(self, textvariable=self.origin, foreground='#0f766e', wraplength=780)
        self.origin_label.pack(fill='x', padx=8, pady=5)
        controls = ttk.Frame(self)
        controls.pack(fill='x', padx=5)
        controls.columnconfigure(2, weight=1)
        ttk.Label(controls, text='结果视图').grid(row=0, column=0, sticky='w', padx=(0, 5))
        self.view_box = ttk.Combobox(controls, textvariable=self.view, values=[], state='disabled', width=12)
        self.view_box.grid(row=0, column=1, sticky='ew', padx=(0, 5))
        self.view_box.bind('<<ComboboxSelected>>', lambda event: self.redraw())
        ttk.Entry(controls, textvariable=self.title, width=18).grid(row=0, column=2, columnspan=2, sticky='ew')
        ttk.Button(controls, text='标题更新', command=self.redraw).grid(row=1, column=0, columnspan=2, sticky='w', pady=(4, 0))
        ttk.Button(controls, text='颜色', command=self.choose_color).grid(row=1, column=2, sticky='w', pady=(4, 0))
        ttk.Checkbutton(controls, text='显示归一化', variable=self.normalize, command=self.redraw).grid(row=1, column=3, sticky='w', pady=(4, 0), padx=(5, 0))
        self.info_label = ttk.Label(self, textvariable=self.info, foreground='#64748b', wraplength=780)
        self.info_label.pack(fill='x', padx=8, pady=4)
        self._wrap_width = None
        self.bind('<Configure>', self.resize_labels)
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True)
        plot, table = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(plot, text='光谱绘图')
        notebook.add(table, text='数据表（分页预览）')
        self.figure = Figure(figsize=(7, 4.5), dpi=100, layout='constrained')
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot)
        toolbar = NavigationToolbar2Tk(self.canvas, plot, pack_toolbar=False)
        toolbar.pack(side='bottom', fill='x')
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        self.table = ttk.Treeview(table, show='headings')
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.table.xview)
        self.table.configure(xscrollcommand=horizontal.set)
        buttons = ttk.Frame(table)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.table.grid(row=0, column=0, sticky='nsew')
        horizontal.grid(row=1, column=0, sticky='ew')
        buttons.grid(row=2, column=0, sticky='ew', pady=5)
        ttk.Button(buttons, text='上一页', command=lambda: self.change_page(-1)).pack(side='left')
        ttk.Button(buttons, text='下一页', command=lambda: self.change_page(1)).pack(side='left', padx=4)
        self.page_text = tk.StringVar()
        ttk.Label(buttons, textvariable=self.page_text).pack(side='left')
        self.axes.set(xlabel='Wavelength [nm]', ylabel='Intensity [a.u.]')
        self.canvas.draw_idle()

    def resize_labels(self, event):
        width = max(100, event.width-16)
        if width != self._wrap_width:
            self._wrap_width = width
            self.origin_label.configure(wraplength=width)
            self.info_label.configure(wraplength=width)

    def choose_color(self):
        color = colorchooser.askcolor(self.color, parent=self)[1]
        if color:
            self.color = color
            self.redraw()

    def set_result(self, manifest):
        self.manifest = manifest
        self.available_views = list(manifest.get('preview', {}))
        self.view_box.configure(values=self.available_views, state='readonly' if self.available_views else 'disabled')
        if self.view.get() not in self.available_views:
            self.view.set('interpolated' if 'interpolated' in self.available_views else self.available_views[0])
        origin = manifest.get('origin', {})
        label = origin.get('label', origin.get('kind', '未知来源'))
        if origin.get('kind') == 'history':
            label = '已保存数据 / 参数未知（未执行新模拟）\n来源：' + origin.get('path', '')
        elif origin.get('parameters'):
            p = origin['parameters']
            label += f'\nTe={p.get("Te")} eV，Ne={p.get("Ne")} cm⁻³，R={p.get("resolution")}；{p.get("webscraping", "")}；实际 Ne={origin.get("actual_Ne", "未知")}'
        self.origin.set(label)
        self.page = 0
        self.redraw()

    def redraw(self):
        if not self.manifest or self.view.get() not in self.available_views:
            return
        view = self.view.get()
        frame = pd.DataFrame(self.manifest['preview'][view])
        draw(self.axes, frame, view, self.title.get(), self.color, self.normalize.get(),intensity_scale_from_origin(self.manifest.get('origin')))
        if self.normalize.get():
            # 紧凑窗口中保持轴标签完整；仅缩短 UI 标签，全量导出仍用完整名称。
            self.axes.set_ylabel('Normalized I')
        self.canvas.draw_idle()
        count = self.manifest['counts'][view]
        text = f'{view} 完整 {count} 行；显示 {len(frame)} 行预览'
        if len(frame) < count:
            text += '（等距抽样，尖峰可能未显示；CSV/PNG 导出使用全量）'
        if 'ion' not in self.available_views:
            text += '；无 ion：需 dynamic 获取。'
        self.info.set(text)
        self.show_page()

    def show_page(self):
        view = self.view.get()
        records = self.manifest['preview'][view]
        columns = self.manifest['columns'][view]
        self.table.delete(*self.table.get_children())
        self.table['columns'] = columns
        for c in columns:
            self.table.heading(c, text=c)
            self.table.column(c, width=130, minwidth=80)
        self.page = max(0, min(self.page, (len(records)-1)//100))
        for row in records[self.page*100:(self.page+1)*100]:
            self.table.insert('', 'end', values=[f'{row[c]:.8g}' for c in columns])
        self.page_text.set(f'预览第 {self.page + 1}/{max(1, (len(records)+99)//100)} 页；每页 100 行')

    def change_page(self, amount):
        if self.manifest:
            self.page += amount
            self.show_page()
