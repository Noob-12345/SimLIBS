"""App 级 pilot 测试：页面导航、校验拦截、MOCK 引擎端到端、历史导入、导出。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

os.environ.setdefault('SIMLIBS_WEB_BACKEND', 'mock')  # App 级测试全部离线

from simlibs_cli.app import SimlibsCLI  # noqa: E402
from simlibs_cli.spectrum_canvas import SpectrumCanvas  # noqa: E402

EXAMPLE_CSV = Path(__file__).resolve().parents[2] / 'simLIBS-2.0.3' / 'docs' / 'single_simulation.csv'


def text_of(sel, app):
    return str(app.query_one(sel).render())


async def wait_result(app, attr, timeout_s=40):
    import asyncio
    for _ in range(int(timeout_s / 0.2)):
        await asyncio.sleep(0.2)
        if getattr(app, attr, None):
            return
    raise AssertionError(f'{attr} 超时未就绪')


class TestApp(unittest.IsolatedAsyncioTestCase):

    async def test_mount_and_navigation(self):
        app = SimlibsCLI()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            self.assertEqual(app.query_one('#pages').current, 'page-single')
            for pid in ('page-scan', 'page-batch', 'page-jobs', 'page-settings', 'page-single'):
                app.switch_page(pid)
                await pilot.pause()
            self.assertEqual(app.query_one('#pages').current, 'page-single')
            await pilot.press('f4')
            self.assertEqual(app.query_one('#pages').current, 'page-scan')
            await pilot.press(']')
            self.assertEqual(app.query_one('#pages').current, 'page-jobs')
            # 主题切换后画布配色更新
            await pilot.press('ctrl+t')
            self.assertEqual(app.theme, 'plasma-light')
            await pilot.press('ctrl+t')
            self.assertEqual(app.theme, 'plasma-dark')

    async def test_composition_sum_and_validation(self):
        app = SimlibsCLI()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(); await pilot.pause()

            async def wait_sum(marker, timeout_s=8):
                for _ in range(int(timeout_s / 0.2)):
                    await pilot.pause(0.2)
                    if marker in text_of('#s-comp-sum', app):
                        return
                raise AssertionError(f'配比校验条未出现 {marker!r}：{text_of("#s-comp-sum", app)}')

            await wait_sum('✓')
            # 破坏总和 → 拦截，不产生任务
            rows = list(app.query_one('#s-comp-rows').query('.comp-row'))
            inputs = [w for w in rows[0].children if hasattr(w, 'value')]
            inputs[1].value = '37'
            await wait_sum('✗')
            before = len(app.backend.list_jobs())
            app._start_single()
            await pilot.pause()
            self.assertEqual(len(app.backend.list_jobs()), before, '总和≠100% 必须在启动前拦截')
            # 非法 Te → 拦截
            app.query_one('#s-te').value = 'abc'
            app._start_single()
            await pilot.pause()
            self.assertEqual(len(app.backend.list_jobs()), before)
            # 预设恢复
            app._preset_h()
            await wait_sum('✓')

    async def test_mock_single_end_to_end(self):
        app = SimlibsCLI()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(); await pilot.pause(); await pilot.pause()
            app.query_one('#s-run').press()
            await wait_result(app, '_single_result')
            canvas = app.query_one('#canvas-single', SpectrumCanvas)
            self.assertEqual(len(canvas._series), 1, '画布应显示主谱')
            self.assertEqual(canvas.watermark, '')
            self.assertIn('MOCK', text_of('#s-meta', app))
            # 视图切换不崩溃
            app.query_one('#s-view').value = 'raw'
            await pilot.pause()
            # 任务表出现记录（≥1：可能含会话恢复的历史任务）
            app._refresh_jobs_table()
            await pilot.pause()
            self.assertGreaterEqual(app.query_one('#j-table').row_count, 1)

    async def test_mock_scan_with_playback(self):
        app = SimlibsCLI()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(); await pilot.pause(); await pilot.pause()
            app.switch_page('page-scan')
            await pilot.pause()
            app.query_one('#sc-run').press()
            await wait_result(app, '_scan_result')
            self.assertGreaterEqual(len(app._scan_result['frames']), 2)
            # 自动播放已开启：帧号会前进
            first = app._frame_idx
            await pilot.pause(1.0)
            self.assertNotEqual(app._frame_idx, first)
            app._set_playing(False)
            before = app._frame_idx
            app._next_frame()
            n = len(app._scan_result['frames'])
            self.assertEqual(app._frame_idx, min(before + 1, n - 1))
            self.assertIn('帧', text_of('#sc-frame', app))

    async def test_mock_batch(self):
        app = SimlibsCLI()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(); await pilot.pause(); await pilot.pause()
            app.switch_page('page-batch')
            await pilot.pause()
            app.query_one('#b-run').press()   # 候选池为空 → 拦截
            await pilot.pause()
            self.assertIsNone(app._batch_result)
            app.query_one('#b-use-current').press()
            for _ in range(25):
                await pilot.pause(0.2)
                if len(app._batch_pool) == 1:
                    break
            self.assertEqual(len(app._batch_pool), 1)
            app.query_one('#b-run').press()
            await wait_result(app, '_batch_result')
            self.assertIn('批量完成', text_of('#b-meta', app))

    async def test_history_import_and_export(self):
        import tempfile
        app = SimlibsCLI()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(); await pilot.pause(); await pilot.pause()
            app.switch_page('page-jobs')
            await pilot.pause()
            if EXAMPLE_CSV.is_file():
                app.query_one('#j-path').value = str(EXAMPLE_CSV)
                app._open_history()
                for _ in range(50):
                    await pilot.pause(0.2)
                    canvas = app.query_one('#canvas-single', SpectrumCanvas)
                    if canvas._series:
                        break
                self.assertTrue(canvas._series, '历史 CSV 应渲染到画布')
                self.assertIn('历史数据', canvas.watermark)
            # MOCK 单次 → 导出 CSV/JSON
            app.query_one('#s-run').press()
            await wait_result(app, '_single_result')
            with tempfile.TemporaryDirectory() as td:
                app.query_one('#s-export-dir').value = td
                app._do_export(app._single_result['job_id'], ['csv', 'json'], '#s-export-dir')
                for _ in range(100):
                    await pilot.pause(0.2)
                    files = list(Path(td).rglob('*'))
                    if len(files) >= 2:
                        break
                names = {f.suffix for f in files if f.is_file()}
                self.assertIn('.csv', names)
                self.assertIn('.json', names)


if __name__ == '__main__':
    unittest.main()
