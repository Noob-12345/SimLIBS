"""共用参数编辑与三个工作页输入，所有启动前校验在这里完成。"""
from dataclasses import asdict
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import pandas as pd
from .models import Parameters, BatchSpec, ScanSpec, composition, normalize as normalize_values
from .storage import validate_compositions


def field(parent, row, label, variable, width=18):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=5, pady=3)
    entry = ttk.Entry(parent, textvariable=variable, width=width)
    entry.grid(row=row, column=1, sticky='ew', padx=5, pady=3)
    return entry


class CompositionEditor(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.tree = ttk.Treeview(self, columns=('element', 'percent'), show='headings', height=5, selectmode='browse')
        self.tree.heading('element', text='元素符号')
        self.tree.heading('percent', text='原子数密度占比 [%]')
        self.tree.column('element', width=100)
        self.tree.column('percent', width=180)
        self.tree.pack(fill='x', padx=5, pady=4)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        row = ttk.Frame(self)
        row.pack(fill='x', padx=5)
        self.element, self.percent = tk.StringVar(value='H'), tk.StringVar(value='100')
        ttk.Entry(row, textvariable=self.element, width=8).pack(side='left')
        ttk.Entry(row, textvariable=self.percent, width=14).pack(side='left', padx=6)
        ttk.Button(row, text='新增', command=self.add).pack(side='left')
        ttk.Button(row, text='更新', command=self.update_row).pack(side='left', padx=3)
        row = ttk.Frame(self)
        row.pack(fill='x', padx=5, pady=4)
        ttk.Button(row, text='删除选中', command=self.delete).pack(side='left')
        ttk.Button(row, text='主动归一化 → 100%', command=self.normalize).pack(side='left', padx=5)
        self.total = tk.StringVar()
        ttk.Label(self, textvariable=self.total, foreground='#475569').pack(anchor='w', padx=5)
        self.set_rows(['H'], [100])

    def rows(self):
        elements, values = [], []
        for item in self.tree.get_children():
            element, value = self.tree.item(item, 'values')
            elements.append(element)
            try:
                values.append(float(value))
            except ValueError:
                values.append(value)
        return elements, values

    def set_rows(self, elements, percentages):
        self.tree.delete(*self.tree.get_children())
        for e, p in zip(elements, percentages):
            self.tree.insert('', 'end', values=(e, f'{p:.12g}' if isinstance(p, (int, float)) else p))
        self.refresh_total()

    def refresh_total(self):
        try:
            _, values = composition(*self.rows(), require_total=False)
            self.total.set(f'总和 {sum(values):.10g}%（提交要求 100%）')
        except ValueError as exc:
            self.total.set(str(exc))

    def select(self, event=None):
        items = self.tree.selection()
        if items:
            e, p = self.tree.item(items[0], 'values')
            self.element.set(e)
            self.percent.set(p)

    def checked_entry(self):
        e, p = composition([self.element.get()], [self.percent.get()], require_total=False)
        return e[0], p[0]

    def add(self):
        try:
            e, p = self.checked_entry()
            if e in self.rows()[0]:
                raise ValueError('元素已存在，请选中后更新')
            self.tree.insert('', 'end', values=(e, f'{p:.12g}'))
            self.refresh_total()
        except ValueError as exc:
            messagebox.showerror('配比输入错误', str(exc), parent=self)

    def update_row(self):
        try:
            items = self.tree.selection()
            if not items:
                raise ValueError('请先选中一行')
            e, p = self.checked_entry()
            others = [self.tree.item(i, 'values')[0] for i in self.tree.get_children() if i != items[0]]
            if e in others:
                raise ValueError('元素不能重复')
            self.tree.item(items[0], values=(e, f'{p:.12g}'))
            self.refresh_total()
        except ValueError as exc:
            messagebox.showerror('配比输入错误', str(exc), parent=self)

    def delete(self):
        self.tree.delete(*self.tree.selection())
        self.refresh_total()

    def normalize(self):
        try:
            e, old = composition(*self.rows(), require_total=False)
            new = normalize_values(old)
            self.set_rows(e, new)
            text = '\n'.join(f'{element}: {a:.10g}% → {b:.10g}%' for element, a, b in zip(e, old, new))
            messagebox.showinfo('主动归一化完成', text, parent=self)
        except ValueError as exc:
            messagebox.showerror('归一化失败', str(exc), parent=self)


class ParameterInputs(ttk.LabelFrame):
    def __init__(self, parent):
        super().__init__(parent, text='共同模拟参数（对当前工作页生效）', padding=5)
        self.columnconfigure(1, weight=1)
        self.vars = {}
        for row, (key, label) in enumerate([('Te', '电子温度 Te [eV]'), ('Ne', '电子密度 Ne [cm⁻³]'),
                                          ('resolution', '光谱分辨率 R（整数）'), ('low_w', '波长下界 [nm]'),
                                          ('upper_w', '波长上界 [nm]'), ('max_ion_charge', '最大离子电荷'), ('step', '重采样步长 [nm]')]):
            self.vars[key] = tk.StringVar()
            field(self, row, label, self.vars[key])
        self.vars['webscraping'] = tk.StringVar(value='static')
        ttk.Label(self, text='获取模式').grid(row=7, column=0, sticky='w', padx=5)
        ttk.Combobox(self, textvariable=self.vars['webscraping'], values=['static', 'dynamic'], state='readonly', width=17).grid(row=7, column=1, sticky='ew', padx=5)
        self.vars['headless'], self.vars['resample'] = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text='动态无头 Chrome（headless）', variable=self.vars['headless']).grid(row=8, column=0, columnspan=2, sticky='w')
        ttk.Checkbutton(self, text='主动重采样（使用上述步长）', variable=self.vars['resample']).grid(row=9, column=0, columnspan=2, sticky='w')
        ttk.Label(self, text='static 默认 0.005 nm；dynamic 默认 NIST 网格。\nR 控制谱线宽度，与重采样步长是不同参数。', foreground='#64748b').grid(row=10, column=0, columnspan=2, sticky='w', pady=4)
        self.composition = None
        self.set_parameters(Parameters())

    def set_parameters(self, p):
        self._intensity_scale=p.intensity_scale
        for key, value in asdict(p).items():
            if key in self.vars:
                self.vars[key].set(value)
        if self.composition:
            self.composition.set_rows(p.elements, p.percentages)

    def parameters(self):
        values = {k: v.get() for k, v in self.vars.items()}
        elements, percentages = self.composition.rows()
        return Parameters(elements=tuple(elements), percentages=tuple(percentages), intensity_scale=self._intensity_scale, **values).validated()


class BatchInputs(ttk.Frame):
    def __init__(self, parent, import_callback, current_callback):
        super().__init__(parent, padding=5)
        self.name_column = tk.StringVar(value='name')
        row = ttk.Frame(self)
        row.pack(fill='x')
        ttk.Label(row, text='名称列映射').pack(side='left')
        ttk.Entry(row, textvariable=self.name_column, width=9).pack(side='left', padx=4)
        ttk.Button(row, text='导入组成 CSV', command=import_callback).pack(side='left')
        ttk.Button(row, text='用当前配比', command=current_callback).pack(side='left', padx=3)
        self.records = []
        self.columns = []
        self.page = 0
        self.tree = ttk.Treeview(self, show='headings', height=5, selectmode='browse')
        self.tree.pack(fill='x', pady=5)
        xscroll = ttk.Scrollbar(self, orient='horizontal', command=self.tree.xview)
        xscroll.pack(fill='x')
        self.tree.configure(xscrollcommand=xscroll.set)
        self.tree.bind('<Double-1>', lambda event: self.edit_row())
        buttons = ttk.Frame(self)
        buttons.pack(fill='x', pady=3)
        for i, (text, command) in enumerate([('新增行', lambda: self.edit_row(True)), ('编辑行', self.edit_row), ('删除', self.delete_row),
                                             ('增加元素列', self.add_element), ('逐行归一化', self.normalize), ('校验', self.validate)]):
            ttk.Button(buttons, text=text, command=command).grid(row=i//3, column=i%3, sticky='ew', padx=1, pady=1)
        for column in range(3):
            buttons.columnconfigure(column, weight=1)
        pager = ttk.Frame(self)
        pager.pack(fill='x')
        ttk.Button(pager, text='上一页', command=lambda: self.change_page(-1)).pack(side='left')
        ttk.Button(pager, text='下一页', command=lambda: self.change_page(1)).pack(side='left')
        self.summary = tk.StringVar(value='尚未导入组成')
        ttk.Label(pager, textvariable=self.summary).pack(side='left', padx=4)
        grid = ttk.Frame(self)
        grid.pack(fill='x', pady=5)
        self.vars = {}
        for i, (key, label, value) in enumerate([('size', '样本数', 2), ('seed', '随机种子', 42), ('Te_min', 'Te 最小', 1),
                                               ('Te_max', 'Te 最大', 1), ('Ne_min', 'Ne 最小', 1e17), ('Ne_max', 'Ne 最大', 1e17)]):
            self.vars[key] = tk.StringVar(value=str(value))
            r, c = divmod(i, 2)
            ttk.Label(grid, text=label).grid(row=r, column=2*c, sticky='w', padx=2, pady=3)
            ttk.Entry(grid, textvariable=self.vars[key], width=11).grid(row=r, column=2*c+1, sticky='ew', padx=2)
        ttk.Label(self, text='逐行校验总和 100%；随机选择一行、均匀采样 Te/Ne。\n动态批量须主动重采样，结果包含组成、名称、Te/Ne。', foreground='#64748b').pack(anchor='w')

    def set_data(self, records, columns=None):
        self.records = [dict(row) for row in records]
        self.columns = list(columns or (list(records[0]) if records else ['H', 'name']))
        self.columns = [c for c in self.columns if c != 'name'] + ['name']
        self.page = 0
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.tree['columns'] = self.columns
        for c in self.columns:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=85, minwidth=60)
        for index in range(self.page * 100, min((self.page + 1) * 100, len(self.records))):
            row = self.records[index]
            self.tree.insert('', 'end', iid=str(index), values=[row.get(c, '') for c in self.columns])
        self.summary.set(f'{len(self.records)} 行；第 {self.page + 1} 页（100 行/页）')

    def change_page(self, amount):
        self.page = max(0, min(max(0, (len(self.records) - 1) // 100), self.page + amount))
        self.refresh()

    def edit_row(self, new=False):
        selected = self.tree.selection()
        if not new and not selected:
            return
        index = None if new else int(selected[0])
        record = {c: ('sample' if c == 'name' else 0) for c in self.columns} if new else self.records[index]
        dialog = tk.Toplevel(self)
        dialog.title('编辑组成（提交时严格校验）')
        dialog.transient(self.winfo_toplevel())
        variables = {}
        for row, c in enumerate(self.columns):
            variables[c] = tk.StringVar(value=str(record.get(c, '')))
            field(dialog, row, c, variables[c])
        def save():
            row = {c: v.get() for c, v in variables.items()}
            if index is None:
                self.records.append(row)
            else:
                self.records[index] = row
            self.refresh()
            dialog.destroy()
        ttk.Button(dialog, text='保存编辑', command=save).grid(row=len(variables), column=0, columnspan=2, pady=8)

    def delete_row(self):
        for index in sorted([int(i) for i in self.tree.selection()], reverse=True):
            del self.records[index]
        self.refresh()

    def add_element(self):
        element = simpledialog.askstring('增加元素列', '化学符号（例如 Fe）', parent=self)
        if element is None:
            return
        try:
            composition([element], [0], require_total=False)
            if element in self.columns:
                raise ValueError('元素列已存在')
            self.columns.insert(len(self.columns)-1, element)
            for row in self.records:
                row[element] = 0
            self.refresh()
        except ValueError as exc:
            messagebox.showerror('元素错误', str(exc), parent=self)

    def data(self):
        return validate_compositions(pd.DataFrame(self.records, columns=self.columns))

    def spec(self, params):
        return BatchSpec(**{k: v.get() for k, v in self.vars.items()}).validated(params)

    def validate(self):
        try:
            self.data()
            messagebox.showinfo('校验成功', f'{len(self.records)} 行全部满足元素与 100% 要求', parent=self)
        except ValueError as exc:
            messagebox.showerror('逐行校验失败', str(exc), parent=self)

    def normalize(self):
        try:
            if not self.records:
                raise ValueError('请先导入或新增组成行')
            elements = [c for c in self.columns if c != 'name']
            updated, changes = [], []
            for i, row in enumerate(self.records, 1):
                _, old = composition(elements, [row[c] for c in elements], require_total=False)
                new = normalize_values(old)
                updated.append(dict(zip(elements, new), name=row['name']))
                changes.append(f'第 {i} 行：{sum(old):.10g}% → 100%')
            self.records = updated
            self.refresh()
            messagebox.showinfo('主动逐行归一化完成', '\n'.join(changes[:25]), parent=self)
        except ValueError as exc:
            messagebox.showerror('归一化失败（未修改表）', str(exc), parent=self)


class ScanInputs(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=8)
        self.columnconfigure(1, weight=1)
        self.axis = tk.StringVar(value='Te')
        self.axis.trace_add('write', self.axis_changed)
        self.vars = {'start': tk.StringVar(value='1'), 'stop': tk.StringVar(value='2'),
                     'count': tk.StringVar(value='2'), 'step': tk.StringVar(value='0.1')}
        self.method = tk.StringVar(value='帧数')
        ttk.Label(self, text='扫描参数').grid(row=0, column=0, sticky='w')
        ttk.Combobox(self, textvariable=self.axis, values=['Te', 'Ne', 'R'], state='readonly', width=15).grid(row=0, column=1, sticky='ew')
        for row, (key, label) in enumerate([('start', '起点'), ('stop', '终点'), ('count', '帧数'), ('step', '步长')], 1):
            field(self, row, label, self.vars[key])
        ttk.Label(self, text='生成规则').grid(row=5, column=0, sticky='w')
        ttk.Combobox(self, textvariable=self.method, values=['帧数', '步长'], state='readonly', width=15).grid(row=5, column=1, sticky='ew')
        self.preview = tk.StringVar(value='点击“预览扫描值”确认请求数量')
        ttk.Label(self, textvariable=self.preview, wraplength=385, foreground='#475569').grid(row=6, column=0, columnspan=2, sticky='w', pady=5)
        ttk.Label(self, text='终点包含；步长模式最后一段允许短于步长。\nR 取整，重复值拒绝；最多 200 帧。\n只改变所选参数，其余使用共同参数/当前配比。', foreground='#64748b').grid(row=7, column=0, columnspan=2, sticky='w', pady=5)

    def axis_changed(self, *args):
        if not hasattr(self, 'vars'):
            return
        values = {'Te': ('1', '2', '0.1'), 'Ne': ('1e17', '2e17', '1e16'), 'R': ('1000', '2000', '100')}[self.axis.get()]
        for key, value in zip(('start', 'stop', 'step'), values):
            self.vars[key].set(value)

    def spec(self, params):
        value = ScanSpec(axis=self.axis.get(), start=self.vars['start'].get(), stop=self.vars['stop'].get(),
                         count=self.vars['count'].get(), step=self.vars['step'].get() if self.method.get() == '步长' else None)
        values = value.validated(params)
        self.preview.set(f'{len(values)} 帧 / {len(values)} 次 NIST 请求：\n' + ', '.join(f'{x:.8g}' for x in values[:20]) + (' …' if len(values) > 20 else ''))
        return value
