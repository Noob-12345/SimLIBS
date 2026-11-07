from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from PIL import Image
from simlibs_ui.models import Parameters, BatchSpec, ScanSpec
from simlibs_ui.settings import Settings
from simlibs_ui.storage import read_manifest, save_result

try:
    from simlibs_ui.operations import batch, scan, export_result
except ImportError:
    batch = None


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(batch, '批量和扫描尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.calls = []
        self.messages = []
        self.df = pd.DataFrame({'H': [100, 80], 'He': [0, 20], 'name': ['a', 'b']})

    def fake_simulate(self, p, s):
        self.calls.append(p)
        df = pd.DataFrame({'wavelength': [650., 655., 660.], 'intensity': [0., p.Te, 0.]})
        return {'raw': df, 'interpolated': df}, {'kind': 'simulation', 'parameters': p.to_dict()}

    def emit(self, event, **kwargs):
        self.messages.append((event, kwargs))

    def test_batch_schema_ranges_seed_and_real_parameter_forwarding(self):
        p = replace(Parameters(), resolution=1500, max_ion_charge=2)
        spec = BatchSpec(size=3, Te_min=1, Te_max=2, Ne_min=1e17, Ne_max=2e17, seed=42)
        path = batch(p, Settings(), spec, self.df, self.path / 'first', self.emit, lambda: False, self.fake_simulate)
        manifest = read_manifest(path)
        df = pd.read_csv(manifest['dataset'])
        self.assertEqual(list(df.columns[-5:]), ['H', 'He', 'name', 'Te[eV]', 'Ne[cm^-3]'])
        self.assertEqual(len(df), 3)
        first = [p.to_dict() for p in self.calls]
        self.assertTrue(all(1 <= p.Te <= 2 and 1e17 <= p.Ne <= 2e17 for p in self.calls))
        self.assertTrue(all(p.resolution == 1500 and p.max_ion_charge == 2 for p in self.calls))
        self.calls.clear()
        batch(p, Settings(), spec, self.df, self.path / 'second', self.emit, lambda: False, self.fake_simulate)
        self.assertEqual(first, [p.to_dict() for p in self.calls])

    def test_cancel_stops_next_request_and_marks_partial(self):
        path = batch(Parameters(), Settings(), BatchSpec(size=3), self.df, self.path,
                     self.emit, lambda: len(self.calls) >= 1, self.fake_simulate)
        manifest = read_manifest(path)
        self.assertTrue(manifest['partial'])
        self.assertEqual(manifest['completed'], 1)
        self.assertEqual(len(self.calls), 1)

    def test_failed_sample_keeps_partial_manifest(self):
        def fail(p, s):
            if self.calls:
                raise RuntimeError('mock transport failure')
            return self.fake_simulate(p, s)
        with self.assertRaisesRegex(RuntimeError, 'mock transport'):
            batch(Parameters(), Settings(), BatchSpec(size=2), self.df, self.path, self.emit, lambda: False, fail)
        self.assertTrue(read_manifest(self.path / 'manifest.json')['partial'])
        self.assertEqual(read_manifest(self.path / 'manifest.json')['completed'], 1)

    def test_batch_grid_mismatch_rejected(self):
        def different(p, s):
            frames, origin = self.fake_simulate(p, s)
            if len(self.calls) > 1:
                frames['interpolated'] = frames['interpolated'].iloc[:2]
            return frames, origin
        with self.assertRaisesRegex(ValueError, '网格'):
            batch(Parameters(), Settings(), BatchSpec(size=2), self.df, self.path, self.emit, lambda: False, different)

    def test_all_three_scans_and_different_grids(self):
        for axis, start, stop, field in [('Te', 1, 2, 'Te'), ('Ne', 1e17, 2e17, 'Ne'), ('R', 1000, 2000, 'resolution')]:
            self.calls.clear()
            def different(p, s):
                frames, origin = self.fake_simulate(p, s)
                if len(self.calls) == 2:
                    frames = {k: v.iloc[:2] for k, v in frames.items()}
                return frames, origin
            path = scan(Parameters(), Settings(), ScanSpec(axis=axis, start=start, stop=stop), self.path / axis,
                        self.emit, lambda: False, different)
            result = read_manifest(path)
            self.assertEqual(result['values'], [start, stop])
            self.assertEqual([getattr(p, field) for p in self.calls], [start, stop])
            self.assertEqual(len(result['frames']), 2)
            self.assertEqual(read_manifest(result['frames'][1])['counts']['raw'], 2)

    def test_full_csv_png_and_zero_gif(self):
        def zero(p, s):
            frames, origin = self.fake_simulate(p, s)
            for df in frames.values():
                df['intensity'] = 0
            return frames, origin
        path = scan(Parameters(), Settings(), ScanSpec(), self.path / 'scan', self.emit, lambda: False, zero)
        export_result(path, self.path / 'scan.gif', 'gif', normalize=True)
        with Image.open(self.path / 'scan.gif') as gif:
            self.assertEqual(gif.format, 'GIF')
            self.assertEqual(gif.n_frames, 2)
        first = read_manifest(path)['frames'][0]
        export_result(first, self.path / 'raw.csv', 'raw')
        export_result(first, self.path / 'plot.png', 'png')
        self.assertEqual(len(pd.read_csv(self.path / 'raw.csv')), 3)
        self.assertTrue((self.path / 'raw.csv.json').exists())
        with Image.open(self.path / 'plot.png') as png:
            self.assertEqual(png.format, 'PNG')

    def test_directory_export_relocates_frame_paths_and_refuses_overwrite(self):
        path = scan(Parameters(), Settings(), ScanSpec(), self.path/'scan', self.emit, lambda: False, self.fake_simulate)
        target = self.path/'导出目录'
        export_result(path, target, 'directory')
        copied = read_manifest(target/'manifest.json')
        for frame in copied['frames']:
            self.assertTrue(Path(frame).is_relative_to(target))
            for csv in read_manifest(frame)['files'].values():
                self.assertTrue(Path(csv).is_relative_to(target))
                self.assertTrue(Path(csv).exists())
        with self.assertRaises(ValueError):
            export_result(path, target, 'directory')


if __name__ == '__main__':
    unittest.main()
