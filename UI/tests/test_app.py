from dataclasses import replace
import tempfile
import tkinter as tk
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import pandas as pd
from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings
from simlibs_ui.storage import save_result, read_manifest

try:
    from simlibs_ui.app import Application
except ImportError:
    Application = None


class AppTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Application, '完整 Tk 应用尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = Application(self.root, replace(Settings(), output=self.temp.name))
        self.addCleanup(self.app.jobs.force_close)
        def destroy_root():
            try:
                self.app.pause_scan()
                self.root.update_idletasks()
                for timer in self.root.tk.call('after', 'info'):
                    self.root.after_cancel(timer)
                self.root.destroy()
            except tk.TclError:
                pass
        self.addCleanup(destroy_root)

    def test_three_pages_full_parameter_roundtrip(self):
        self.assertEqual(len(self.app.notebook.tabs()), 3)
        params = replace(Parameters(), Te=2.3, Ne=2.5e17, resolution=1800, low_w=600, upper_w=610,
                         max_ion_charge=2, webscraping='dynamic', headless=False, resample=True, step=.02,
                         elements=('Fe', 'H'), percentages=(30, 70))
        self.app.inputs.set_parameters(params)
        self.assertEqual(self.app.inputs.parameters(), params)

    def test_invalid_entry_rejected_before_worker_and_normalize_explicit(self):
        self.app.inputs.composition.set_rows(['H', 'He'], [80, 15])
        with patch.object(self.app.jobs, 'start') as start, patch('tkinter.messagebox.showerror'):
            self.app.run_single()
        start.assert_not_called()
        self.assertEqual(self.app.inputs.composition.rows()[1], [80, 15])
        with patch('tkinter.messagebox.showinfo'):
            self.app.inputs.composition.normalize()
        self.assertAlmostEqual(sum(self.app.inputs.composition.rows()[1]), 100)

    def test_source_warning_and_failure_retains_result(self):
        df = pd.DataFrame({'wavelength': [650., 655., 660.], 'intensity': [0., 2., 0.]})
        path = save_result(Path(self.temp.name) / 'history', {'raw': df},
                           {'kind': 'history', 'label': '已保存数据；参数未知', 'parameters': None, 'path': '历史.csv'})
        self.app.display_result(path)
        self.assertIn('已保存数据', self.app.result.origin.get())
        self.assertNotIn('ion', self.app.result.available_views)
        old = self.app.current_result
        self.app.jobs.state = 'FAILED'
        self.app.jobs.error = 'network failure'
        self.app.task_finished('FAILED')
        self.assertEqual(self.app.current_result, old)
        self.assertEqual(str(self.app.run_button['state']), 'normal')

    def test_scan_playback_pause_does_not_start_worker(self):
        df = pd.DataFrame({'wavelength': [650., 655., 660.], 'intensity': [0., 1., 0.]})
        frame = save_result(Path(self.temp.name) / 'frame', {'interpolated': df}, {'kind': 'simulation', 'parameters': {}})
        from simlibs_ui.storage import write_json
        path = Path(self.temp.name) / 'scan.json'
        write_json(path, {'kind': 'scan', 'frames': [frame, frame], 'values': [1, 2], 'completed_values': [1, 2],
                          'axis': 'Te', 'partial': False, 'origin': {'label': '真实扫描'}})
        self.app.display_result(path)
        with patch.object(self.app.jobs, 'start') as start:
            self.app.play_scan()
            self.root.update()
            self.app.pause_scan()
            index = self.app.frame_index
            self.root.update()
            self.assertEqual(index, self.app.frame_index)
        start.assert_not_called()

    def test_window_close_cleans_running_owned_tree(self):
        from tests.test_jobs import alive
        self.app.jobs.worker_module = 'tests.job_fixture'
        self.app.start('fixture', delay=20, child=True)
        limit = time.monotonic()+3
        while not (self.app.jobs.directory/'child.pid').exists() and time.monotonic() < limit:
            self.root.update()
            time.sleep(.01)
        child = int((self.app.jobs.directory/'child.pid').read_text())
        self.assertTrue(alive(child))
        start = time.monotonic()
        self.app.close()
        self.root.mainloop()
        self.assertLess(time.monotonic()-start, 5)
        self.assertEqual(self.app.jobs.state, 'CANCELLED')
        self.assertFalse(alive(child))
        self.assertIsNotNone(self.app.jobs.process.poll())

    def test_actions_visible_at_minimum_window_size(self):
        self.root.deiconify()
        self.root.geometry('950x680')
        self.app.notebook.select(self.app.batch)
        self.root.update()
        expected = {'新增行', '编辑行', '删除', '增加元素列', '逐行归一化', '校验'}
        found = []
        for frame in self.app.batch.winfo_children():
            for widget in frame.winfo_children():
                if widget.winfo_class() == 'TButton' and widget.cget('text') in expected:
                    found.append(widget)
        self.assertEqual(len(found), 6)
        for widget in found:
            with self.subTest(button=widget.cget('text')):
                self.assertTrue(widget.winfo_ismapped(), '批量操作不能被横向裁掉')
                self.assertLessEqual(widget.winfo_x()+widget.winfo_width(), widget.master.winfo_width())
        exports = {'打开历史 CSV', '内置历史样例', '导出 CSV', '导出 PNG', '来源 JSON', '完整结果目录', '导出 GIF'}
        for widget in self.app.actions:
            if widget.cget('text') in exports:
                with self.subTest(button=widget.cget('text')):
                    self.assertTrue(widget.winfo_ismapped(), '最小窗口下仍可访问导出')
        self.assertTrue(self.app.cancel_button.winfo_ismapped(), '取消按钮必须始终可见')
        self.assertTrue(self.app.progress.winfo_ismapped(), '任务状态栏必须始终可见')

    def test_result_controls_and_paging_usable_at_minimum_window_size(self):
        from simlibs_ui.storage import read_history
        frames, origin = read_history(Path(self.app.settings.source)/'docs'/'single_simulation.csv')
        path = save_result(Path(self.temp.name)/'pages', frames, origin)
        self.app.display_result(path)
        self.root.deiconify()
        self.root.geometry('950x680')
        self.root.update()
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (950, 680))

        def find_control(parent, text):
            for widget in parent.winfo_children():
                if widget.winfo_class() in ('TButton', 'TCheckbutton') and widget.cget('text') == text:
                    return widget
                found = find_control(widget, text)
                if found:
                    return found
            return None

        def assert_usable(widget):
            self.assertIsNotNone(widget)
            self.assertTrue(widget.winfo_ismapped(), f'{widget.cget("text")} 必须真实映射')
            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth(), '不能只露出按钮一角')
            self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())
            ancestor = widget.master
            while ancestor is not None:
                self.assertGreaterEqual(widget.winfo_rootx(), ancestor.winfo_rootx()-1)
                self.assertGreaterEqual(widget.winfo_rooty(), ancestor.winfo_rooty()-1)
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), ancestor.winfo_rootx()+ancestor.winfo_width()+1)
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), ancestor.winfo_rooty()+ancestor.winfo_height()+1)
                ancestor = ancestor.master

        color = find_control(self.app.result, '颜色')
        normalizer = find_control(self.app.result, '显示归一化')
        for widget in [color, normalizer, find_control(self.app.result, '标题更新')]:
            with self.subTest(control=widget.cget('text')):
                assert_usable(widget)
        with patch('tkinter.colorchooser.askcolor', return_value=(None, '#ef4444')):
            color.invoke()
        self.assertEqual(self.app.result.color, '#ef4444')
        normalizer.invoke()
        self.root.update()
        self.assertTrue(self.app.result.normalize.get())
        self.assertEqual(max(self.app.result.axes.lines[0].get_ydata()), 1)
        label = self.app.result.axes.yaxis.label.get_window_extent(self.app.result.canvas.get_renderer())
        self.assertGreaterEqual(label.y0, -1, '归一化轴标签不能在最小图中被裁掉')
        self.assertLessEqual(label.y1, self.app.result.figure.bbox.height+1)

        notebook = next(w for w in self.app.result.winfo_children() if w.winfo_class() == 'TNotebook')
        notebook.select(1)
        self.root.update()
        table_page = self.root.nametowidget(notebook.tabs()[1])
        previous = find_control(table_page, '上一页')
        following = find_control(table_page, '下一页')
        for widget in [previous, following]:
            with self.subTest(control=widget.cget('text')):
                assert_usable(widget)
        initial = float(self.app.result.table.item(self.app.result.table.get_children()[0], 'values')[0])
        following.invoke()
        self.root.update()
        self.assertEqual(self.app.result.page, 1)
        self.assertEqual(len(self.app.result.table.get_children()), 100)
        first = self.app.result.table.item(self.app.result.table.get_children()[0], 'values')[0]
        self.assertGreater(float(first), initial)
        previous.invoke()
        self.root.update()
        self.assertEqual(self.app.result.page, 0)
        for widget in [self.app.cancel_button, self.app.progress]:
            self.assertTrue(widget.winfo_ismapped())


if __name__ == '__main__':
    unittest.main()
