"""完整 tkinter 桌面 UI：参数、配比、批量、扫描、导入导出与异步任务。"""
import argparse
from dataclasses import asdict, replace
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .input_views import ParameterInputs, CompositionEditor, BatchInputs, ScanInputs, field
from .jobs import JobController
from .models import Parameters, BatchSpec, ScanSpec
from .result_view import ResultView
from .settings import Settings, PRESETS, UI_ROOT, save_config, load_config
from .storage import read_manifest, write_json


class Application:
    def __init__(self, root, settings=None):
        self.root = root
        self.settings = settings or Settings()
        self.jobs = JobController(self.settings)
        self.current_result = None
        self.current_manifest = None
        self.frame_manifest = None
        self.frame_index = 0
        self.playing = False
        self.play_timer = None
        self.closing = False
        self.pending_import = None
        self.task_kind = None
        self.actions = []
        root.title('simLIBS 光谱模拟工作台')
        width, height = min(1420, root.winfo_screenwidth()-70), min(940, root.winfo_screenheight()-90)
        root.geometry(f'{max(950, width)}x{max(680, height)}')
        root.minsize(950, 680)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 9))
        style.configure('Treeview', rowheight=24)
        top = ttk.Frame(root, padding=(10, 8))
        top.grid(row=0, column=0, sticky='ew')
        ttk.Label(top, text='simLIBS 光谱模拟', font=('Microsoft YaHei UI', 14, 'bold')).pack(side='left', padx=(0, 12))
        self.preset = tk.StringVar(value=next(iter(PRESETS)))
        presets = ttk.Combobox(top, textvariable=self.preset, values=list(PRESETS), state='readonly', width=26)
        presets.pack(side='left')
        presets.bind('<<ComboboxSelected>>', lambda event: self.apply_preset())
        for text, action in [('恢复默认', self.restore_defaults), ('保存配置', self.save_configuration),
                             ('导入配置', self.load_configuration), ('设置', self.settings_dialog)]:
            ttk.Button(top, text=text, command=action).pack(side='left', padx=3)
        body = ttk.Panedwindow(root, orient='horizontal')
        body.grid(row=1, column=0, sticky='nsew', padx=10)
        left = ttk.Frame(body, width=440)
        right = ttk.Frame(body)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        body.add(left, weight=0)
        body.add(right, weight=1)
        canvas = tk.Canvas(left, width=430, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.bind('<MouseWheel>', lambda event: canvas.yview_scroll(-int(event.delta/120), 'units'))
        self.inputs = ParameterInputs(inner)
        self.inputs.pack(fill='x', pady=(0, 6))
        self.notebook = ttk.Notebook(inner)
        self.notebook.pack(fill='both', expand=True)
        single = ttk.Frame(self.notebook, padding=5)
        self.inputs.composition = CompositionEditor(single)
        self.inputs.composition.pack(fill='x')
        self.add_action(single, '导入配比 CSV（取第 1 行）', lambda: self.import_compositions('single')).pack(fill='x', padx=5, pady=5)
        self.run_button = self.add_action(single, '生成单次真实光谱', self.run_single)
        self.run_button.pack(fill='x', padx=5, pady=6)
        self.batch = BatchInputs(self.notebook, lambda: self.import_compositions('batch'), self.batch_from_current)
        self.add_action(self.batch, '生成批量数据集', self.run_batch).pack(fill='x', pady=5)
        self.scan = ScanInputs(self.notebook)
        buttons = ttk.Frame(self.scan)
        buttons.grid(row=8, column=0, columnspan=2, sticky='ew', pady=5)
        ttk.Button(buttons, text='预览扫描值', command=self.preview_scan).pack(side='left')
        self.add_action(buttons, '生成扫描', self.run_scan).pack(side='left', padx=8)
        self.notebook.add(single, text='单次模拟')
        self.notebook.add(self.batch, text='批量 dataset')
        self.notebook.add(self.scan, text='参数扫描 / 动画')
        self.result = ResultView(right)
        self.result.grid(row=0, column=0, sticky='nsew')
        row = ttk.Frame(right)
        row.grid(row=1, column=0, sticky='ew', pady=5)
        for i, (text, action) in enumerate([('打开历史 CSV', self.open_history), ('内置历史样例', self.open_example),
                                           ('导出 CSV', self.export_csv), ('导出 PNG', lambda: self.export('png')),
                                           ('来源 JSON', lambda: self.export('json')), ('完整结果目录', self.export_directory),
                                           ('导出 GIF', lambda: self.export('gif'))]):
            self.add_action(row, text, action).grid(row=i//4, column=i%4, sticky='ew', padx=2, pady=1)
        for column in range(4):
            row.columnconfigure(column, weight=1)
        playback = ttk.Frame(right)
        playback.grid(row=2, column=0, sticky='ew', pady=3)
        for text, action in [('◀ 上一帧', lambda: self.step_frame(-1)), ('播放', self.play_scan), ('暂停', self.pause_scan), ('下一帧 ▶', lambda: self.step_frame(1))]:
            ttk.Button(playback, text=text, command=action).pack(side='left', padx=3)
        self.frame_label = tk.StringVar(value='扫描生成后可离线播放；批量结果可逐样本查看')
        ttk.Label(right, textvariable=self.frame_label).grid(row=3, column=0, sticky='w', padx=5)
        self.log = tk.Text(right, height=5, wrap='word', state='disabled', font=('Microsoft YaHei UI', 9), background='#f8fafc')
        self.log.grid(row=4, column=0, sticky='ew', pady=(2, 5))
        bottom = ttk.Frame(root, padding=(10, 8))
        bottom.grid(row=2, column=0, sticky='ew')
        self.status = tk.StringVar(value='就绪。新模拟需要 NIST 网络；打开历史 CSV 完全离线。')
        ttk.Label(bottom, textvariable=self.status).pack(side='left', fill='x', expand=True)
        self.progress = ttk.Progressbar(bottom, mode='determinate', length=160)
        self.progress.pack(side='left', padx=8)
        self.cancel_button = ttk.Button(bottom, text='取消当前任务', command=self.jobs.cancel, state='disabled')
        self.cancel_button.pack(side='right')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(80, self.poll)

    def add_action(self, parent, text, action):
        button = ttk.Button(parent, text=text, command=action)
        self.actions.append(button)
        return button

    def log_message(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', datetime.now().strftime('%H:%M:%S ') + text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def set_busy(self, busy):
        for button in self.actions:
            button.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        if not busy:
            self.progress.stop()
            self.progress.configure(mode='determinate')

    def start(self, kind, **payload):
        try:
            self.jobs.settings = self.settings
            self.jobs.start(kind, **payload)
            self.task_kind = kind
            self.set_busy(True)
            self.progress.configure(mode='indeterminate')
            self.progress.start(15)
            self.status.set('后台任务运行中；窗口仍可操作，支持取消。')
            self.log_message(f'启动 {kind}；任务目录 {self.jobs.directory}')
        except Exception as exc:
            messagebox.showerror('任务未启动', str(exc), parent=self.root)
            self.log_message(str(exc))

    def run_single(self):
        try:
            p = self.inputs.parameters()
            self.start('single', parameters=p.to_dict())
        except ValueError as exc:
            messagebox.showerror('参数错误（未启动 worker）', str(exc), parent=self.root)

    def batch_from_current(self):
        try:
            p = self.inputs.parameters()
            self.batch.set_data([dict(zip(p.elements, p.percentages), name='current')])
        except ValueError as exc:
            messagebox.showerror('配比错误', str(exc), parent=self.root)

    def run_batch(self):
        try:
            p = self.inputs.parameters()
            spec = self.batch.spec(p)
            data = self.batch.data()
            if p.webscraping == 'dynamic' and not p.resample:
                raise ValueError('动态批量请主动勾选统一重采样')
            self.start('batch', parameters=p.to_dict(), spec=asdict(spec), compositions=data.to_dict('records'))
        except ValueError as exc:
            messagebox.showerror('批量输入错误（未启动 worker）', str(exc), parent=self.root)

    def preview_scan(self):
        try:
            self.scan.spec(self.inputs.parameters())
        except ValueError as exc:
            messagebox.showerror('扫描参数错误', str(exc), parent=self.root)

    def run_scan(self):
        try:
            p = self.inputs.parameters()
            spec = self.scan.spec(p)
            self.start('scan', parameters=p.to_dict(), spec=asdict(spec))
        except ValueError as exc:
            messagebox.showerror('扫描参数错误（未启动 worker）', str(exc), parent=self.root)

    def apply_preset(self):
        self.inputs.set_parameters(PRESETS[self.preset.get()])
        self.log_message('预设只更改参数；尚未联网。')

    def restore_defaults(self):
        self.inputs.set_parameters(Parameters())
        self.settings = Settings()
        for k, v in asdict(BatchSpec()).items():
            self.batch.vars[k].set(v)
        self.scan.axis.set('Te')
        self.scan.vars['count'].set('2')
        self.scan.method.set('帧数')
        self.log_message('已恢复默认参数和设置，未发出网络请求。')

    def save_configuration(self):
        try:
            p = self.inputs.parameters()
            batch_spec = self.batch.spec(replace(p, resample=True))
            scan_spec = self.scan.spec(p)
            path = filedialog.asksaveasfilename(parent=self.root, title='保存配置 / 自定义预设', defaultextension='.json', filetypes=[('JSON', '*.json')])
            if path:
                save_config(path, self.settings, p, {'batch': asdict(batch_spec), 'scan': asdict(scan_spec), 'compositions': self.batch.records})
                self.log_message(f'配置已保存：{path}')
        except (ValueError, OSError) as exc:
            messagebox.showerror('保存配置失败', str(exc), parent=self.root)

    def load_configuration(self):
        path = filedialog.askopenfilename(parent=self.root, title='导入配置 / 自定义预设', filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            settings, p, extra = load_config(path)
            b = BatchSpec(**extra.get('batch', {})).validated(replace(p, resample=True))
            scan_data = extra.get('scan', {})
            ScanSpec(**scan_data).validated(p)
            self.settings = settings
            self.inputs.set_parameters(p)
            for k, v in asdict(b).items():
                self.batch.vars[k].set(v)
            if scan_data:
                self.scan.axis.set(scan_data['axis'])
                for k in self.scan.vars:
                    self.scan.vars[k].set(scan_data[k] if scan_data.get(k) is not None else '0.1')
                self.scan.method.set('步长' if scan_data.get('step') is not None else '帧数')
            if extra.get('compositions'):
                self.batch.set_data(extra['compositions'])
            self.log_message(f'配置已加载，未联网：{path}')
        except Exception as exc:
            messagebox.showerror('配置无效（可恢复默认）', str(exc), parent=self.root)

    def settings_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('运行环境 / 网络 / 输出设置')
        dialog.transient(self.root)
        dialog.columnconfigure(1, weight=1)
        labels = {'python': 'worker Python 3.10+', 'source': '源库根目录', 'driver': '匹配 ChromeDriver（可留空）',
                  'chrome': 'Chrome 路径（可留空自动定位）', 'output': '输出目录', 'connect_timeout': '连接超时 [s]',
                  'read_timeout': '读取超时 [s]', 'page_timeout': '页面加载超时 [s]', 'script_timeout': '脚本超时 [s]',
                  'static_deadline': 'static 单次总期限 [s]', 'dynamic_deadline': 'dynamic 单次总期限 [s]'}
        variables = {}
        for row, (key, label) in enumerate(labels.items()):
            variables[key] = tk.StringVar(value=str(getattr(self.settings, key)))
            field(dialog, row, label, variables[key], width=60)
            if key in ('python', 'source', 'driver', 'chrome', 'output'):
                def choose(k=key):
                    path = filedialog.askdirectory(parent=dialog) if k in ('source', 'output') else filedialog.askopenfilename(parent=dialog, filetypes=[('EXE', '*.exe'), ('全部', '*.*')])
                    if path:
                        variables[k].set(path)
                ttk.Button(dialog, text='浏览', command=choose).grid(row=row, column=2, padx=4)
        verify = tk.BooleanVar(value=self.settings.tls_verify)
        ttk.Checkbutton(dialog, text='TLS 证书校验（默认开启，失败不会自动关闭）', variable=verify).grid(row=11, column=0, columnspan=3, sticky='w', padx=5, pady=5)
        ttk.Label(dialog, text='留空驱动：后台 manager 获取匹配版本；不使用源库旧驱动。\nkeep_browser_open=False、detach_browser=False 固定，浏览器受任务管理。', foreground='#64748b').grid(row=12, column=0, columnspan=3, sticky='w', padx=5)
        def save():
            try:
                self.settings = Settings(**{k: v.get() for k, v in variables.items()}, tls_verify=verify.get()).validated()
                self.log_message('设置已更新；未启动联网或驱动下载。')
                dialog.destroy()
            except ValueError as exc:
                messagebox.showerror('设置错误', str(exc), parent=dialog)
        ttk.Button(dialog, text='应用设置', command=save).grid(row=13, column=0, columnspan=3, pady=10)

    def import_compositions(self, destination):
        path = filedialog.askopenfilename(parent=self.root, title='导入组成 CSV', filetypes=[('CSV', '*.csv')])
        if path:
            self.pending_import = destination
            self.start('compositions', path=path, name_column=self.batch.name_column.get())

    def open_history(self):
        path = filedialog.askopenfilename(parent=self.root, title='离线打开历史光谱（参数未知）', filetypes=[('CSV', '*.csv')])
        if path:
            self.start('history', path=path)

    def open_example(self):
        path = Path(self.settings.source) / 'docs' / 'single_simulation.csv'
        self.start('history', path=str(path))

    def display_result(self, path):
        manifest = read_manifest(path)
        self.pause_scan()
        self.current_result, self.current_manifest = path, manifest
        self.frame_index = 0
        self.show_frame()

    def show_frame(self):
        m = self.current_manifest
        if not m:
            return
        if m['kind'] == 'scan':
            paths = m['frames']
            path = paths[self.frame_index]
            self.frame_label.set(f'帧 {self.frame_index+1}/{len(paths)}；{m["axis"]}={m["completed_values"][self.frame_index]:.8g}')
        elif m['kind'] == 'batch':
            paths = m['samples']
            path = paths[self.frame_index]
            self.frame_label.set(f'样本 {self.frame_index+1}/{len(paths)}；完整 dataset 含 {m["completed"]} 行')
        else:
            path = self.current_result
            self.frame_label.set('单次光谱 / 已保存数据')
        self.frame_manifest = path
        self.result.set_result(read_manifest(path))

    def step_frame(self, direction):
        if not self.current_manifest:
            return
        key = 'frames' if self.current_manifest['kind'] == 'scan' else 'samples'
        paths = self.current_manifest.get(key, [])
        if paths:
            self.frame_index = (self.frame_index + direction) % len(paths)
            self.show_frame()

    def play_scan(self):
        if not self.current_manifest or self.current_manifest['kind'] != 'scan':
            return
        self.pause_scan()
        self.playing = True
        def advance():
            if self.playing and not self.closing:
                self.step_frame(1)
                self.play_timer = self.root.after(700, advance)
        self.play_timer = self.root.after(1, advance)

    def pause_scan(self):
        self.playing = False
        if self.play_timer is not None:
            self.root.after_cancel(self.play_timer)
            self.play_timer = None

    def export_csv(self):
        format = 'dataset' if self.current_manifest and self.current_manifest['kind'] == 'batch' else self.result.view.get()
        self.export(format)

    def export(self, format):
        if not self.current_result:
            messagebox.showinfo('无结果', '请先生成或导入数据', parent=self.root)
            return
        if format == 'gif' and self.current_manifest['kind'] != 'scan':
            messagebox.showinfo('GIF 导出', '请先生成完整参数扫描', parent=self.root)
            return
        suffix = {'png': '.png', 'gif': '.gif', 'json': '.json'}.get(format, '.csv')
        path = filedialog.asksaveasfilename(parent=self.root, title=f'导出 {format}', defaultextension=suffix,
                                          initialdir=self.settings.output, filetypes=[(format, '*' + suffix)])
        if path:
            source = self.current_result if format in ('gif', 'dataset', 'json') else self.frame_manifest
            self.start('export', manifest=source, target=path, format=format, view=self.result.view.get(),
                       title=self.result.title.get(), color=self.result.color, normalize=self.result.normalize.get())

    def export_directory(self):
        if not self.current_result:
            return
        base = filedialog.askdirectory(parent=self.root, title='选择父目录（自动创建新结果目录）')
        if base:
            path = Path(base) / ('simLIBS_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            self.start('export', manifest=self.current_result, target=str(path), format='directory')

    def task_finished(self, state):
        self.set_busy(False)
        if state == 'SUCCEEDED':
            result = self.jobs.last_result
            if result['kind'] == 'export':
                self.status.set('导出完成：' + result['target'])
            elif result['kind'] == 'compositions':
                self.batch.set_data(result['records'], result['columns'])
                if self.pending_import == 'single' and result['records']:
                    first = result['records'][0]
                    elements = [c for c in result['columns'] if c != 'name']
                    self.inputs.composition.set_rows(elements, [first[c] for c in elements])
                self.status.set('组成 CSV 已导入，生成前需校验总和与有限值。')
            else:
                self.display_result(self.jobs.result_path)
                self.status.set('已保存数据已载入（参数未知，未执行新模拟）' if self.task_kind == 'history' else '真实模拟完成；完整结果已保存在任务目录。')
            self.log_message(self.status.get())
        elif state == 'CANCELLED':
            self.status.set('已取消并清理本任务进程；保留上一成功结果。')
            self.log_message(self.status.get() + f' partial 检查目录：{self.jobs.directory}')
        else:
            self.status.set('任务失败；保留上一成功结果，可修改参数后重试。')
            self.log_message(self.jobs.error + f'；日志：{self.jobs.directory}')

    def poll(self):
        for message in self.jobs.poll():
            if message['event'] == 'progress':
                self.status.set(message.get('message', '后台处理中'))
                if 'total' in message:
                    self.progress.stop()
                    self.progress.configure(mode='determinate', maximum=message['total'], value=message['current'])
                self.log_message(message.get('message', ''))
            elif message['event'] == 'finished':
                self.task_finished(message['state'])
        if self.closing and not self.jobs.busy:
            self.jobs.force_close()
            self.root.destroy()
            return
        self.root.after(80, self.poll)

    def close(self):
        self.closing = True
        self.pause_scan()
        self.jobs.cancel()
        self.status.set('正在关闭并清理本任务所属进程…')


def diagnose(settings=None):
    settings = settings or Settings()
    result = {'python': sys.executable, 'python_version': sys.version, 'source': settings.source,
              'source_exists': (Path(settings.source)/'simLIBS'/'simulation.py').is_file(),
              'dependencies': {name: importlib.util.find_spec(name) is not None for name in
                               ['tkinter', 'matplotlib', 'pandas', 'numpy', 'scipy', 'requests', 'bs4', 'selenium', 'webdriver_manager', 'PIL']},
              'network_used': False, 'driver_downloaded': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['source_exists'] and all(result['dependencies'].values()) and sys.version_info >= (3, 10) else 1


def main():
    parser = argparse.ArgumentParser(description='simLIBS 本地桌面 UI')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    settings = replace(Settings(), output=str(Path(args.output).resolve())) if args.output else Settings()
    if args.diagnose:
        return diagnose(settings)
    root = tk.Tk()
    application = Application(root, settings)
    smoke = {'exit_code': 0}
    if args.smoke_test:
        configure_smoke(application, smoke)
    root.mainloop()
    return smoke['exit_code']


def configure_smoke(app, state):
    """真正创建并显示 Tk，后台导入历史、导出 CSV/PNG/JSON，记录心跳后自动关闭。"""
    import time
    output = Path(app.settings.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    ticks = []
    phase = {'number': 0, 'manifest': None, 'started': False}
    report = {'tk_window_created': True, 'pages': len(app.notebook.tabs()), 'new_simulation': False,
              'history_source': str(Path(app.settings.source) / 'docs' / 'single_simulation.csv')}
    def finish(error=None):
        state['exit_code'] = 1 if error else 0
        report.update(heartbeats=len(ticks), elapsed=time.monotonic()-started, error=error,
                      files=[str(output/name) for name in ('history.csv', 'history.png', 'history.json')])
        write_json(output / 'smoke.json', report)
        print(json.dumps(report, ensure_ascii=False))
        app.close()
    def tick():
        ticks.append(time.monotonic())
        if app.closing:
            return
        if time.monotonic() - started > 45:
            finish('smoke 超过 45 秒')
            return
        if not phase['started']:
            app.open_example()
            phase['started'] = True
        elif not app.jobs.busy:
            if app.jobs.state != 'SUCCEEDED':
                finish(app.jobs.error or app.jobs.state)
                return
            n = phase['number']
            if n == 0:
                phase['manifest'] = app.current_result
                report['origin'] = app.current_manifest['origin']
                app.root.lift()
                app.root.update_idletasks()
                try:
                    capture_window(app.root, output/'tk-smoke.png')
                except Exception as exc:
                    report['screenshot_error'] = str(exc)
                app.start('export', manifest=phase['manifest'], target=str(output/'history.csv'), format='raw')
            elif n == 1:
                app.start('export', manifest=phase['manifest'], target=str(output/'history.png'), format='png')
            elif n == 2:
                app.start('export', manifest=phase['manifest'], target=str(output/'history.json'), format='json')
            else:
                finish()
                return
            phase['number'] += 1
        app.root.after(50, tick)
    app.root.after(200, tick)


def capture_window(root, target):
    """只捕获本应用 HWND，避免别的前台窗口遮挡后误采桌面内容。"""
    from PIL import ImageGrab
    root.update()
    hwnd = root.winfo_id()
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        hwnd = int(user.GetAncestor(hwnd, 2) or hwnd)
    ImageGrab.grab(window=hwnd).save(target)
