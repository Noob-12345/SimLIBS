import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd

try:
    from simlibs_ui.settings import Settings, PRESETS, save_config, load_config
    from simlibs_ui.storage import read_compositions, validate_compositions, read_history, write_json, save_result, read_manifest
except ImportError:
    Settings = None


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Settings, '存储和配置尚未实现')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '中文'
        self.path.mkdir()

    def test_config_roundtrip_and_invalid_configuration(self):
        from simlibs_ui.models import Parameters
        path = self.path / '配置.json'
        save_config(path, Settings(), Parameters(), {'batch': {'size': 2}})
        s, p, extra = load_config(path)
        self.assertEqual(p, Parameters())
        self.assertEqual(s, Settings())
        self.assertEqual(extra['batch']['size'], 2)
        data = json.loads(path.read_text(encoding='utf-8'))
        data['parameters']['Ne'] = 0
        write_json(path, data)
        with self.assertRaises(ValueError):
            load_config(path)
        self.assertIn('H 窄波段（已验证参数）', PRESETS)

    def test_composition_mapping_and_no_silent_normalize(self):
        path = self.path / '元素.csv'
        pd.DataFrame({'Unnamed: 0': [0], 'samples': ['旧样本'], 'H_at%': [80], 'He_at%': [15]}).to_csv(path, index=False)
        data = read_compositions(path, name_column='samples')
        self.assertEqual(list(data.columns), ['H', 'He', 'name'])
        self.assertEqual(data.iloc[0]['H'], 80)
        with self.assertRaisesRegex(ValueError, '第 1 行'):
            validate_compositions(data)
        for value in [float('nan'), -1, float('inf')]:
            with self.assertRaises(ValueError):
                validate_compositions(pd.DataFrame({'H': [value], 'name': ['坏样本']}))

    def test_history_and_full_export_preserve_origin(self):
        path = self.path / '历史.csv'
        pd.DataFrame({'Unnamed: 0': [0, 1, 2], 'wavelength': [650, 651, 652], 'intensity': [0, 4, 0]}).to_csv(path, index=False)
        frames, origin = read_history(path)
        self.assertEqual(list(frames['raw']), ['wavelength', 'intensity'])
        self.assertEqual(origin['kind'], 'history')
        self.assertIsNone(origin['parameters'])
        manifest_path = save_result(self.path / 'result', frames, origin, preview_limit=2)
        manifest = read_manifest(manifest_path)
        self.assertEqual(manifest['origin']['path'], str(path.resolve()))
        self.assertEqual(manifest['counts']['raw'], 3)
        self.assertLessEqual(len(manifest['preview']['raw']), 2)
        self.assertEqual(len(pd.read_csv(manifest['files']['raw'])), 3)
        self.assertNotIn('Unnamed: 0', pd.read_csv(manifest['files']['raw']).columns)

    def test_bad_history_and_corrupt_json(self):
        path = self.path / '坏.csv'
        for data in [dict(wavelength=[1, 1], intensity=[2, 3]),
                     dict(wavelength=[1, 2], intensity=[0, float('inf')]),
                     dict(wavelength=[], intensity=[])]:
            pd.DataFrame(data).to_csv(path, index=False)
            with self.assertRaises(ValueError):
                read_history(path)
        path.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_config(path)

    def test_ion_schema_failure_reports_actual_columns(self):
        from simlibs_ui.storage import clean_spectrum
        with self.assertRaisesRegex(ValueError, '实际列.*strange'):
            clean_spectrum(pd.DataFrame({'strange': [1]}), ion=True)

    def test_real_source_compositions_and_95_percent_history(self):
        from simlibs_ui.settings import DEFAULT_SOURCE
        source = Path(DEFAULT_SOURCE)
        data = validate_compositions(read_compositions(source/'data.csv'))
        self.assertEqual(list(data.columns), ['W', 'H', 'He', 'name'])
        self.assertEqual(len(data), 3)
        historic = read_compositions(source/'saved'/'contents.csv', name_column='samples')
        with self.assertRaisesRegex(ValueError, '100%'):
            validate_compositions(historic)

    def test_composition_import_limit_rejected(self):
        path = self.path/'大组成.csv'
        pd.DataFrame({'H': [100]*5001, 'name': ['H']*5001}).to_csv(path, index=False)
        with self.assertRaisesRegex(ValueError, '5000'):
            read_compositions(path)

    def test_sparse_ion_cells_only_allow_explicit_blank_contributions(self):
        from simlibs_ui.storage import clean_spectrum
        good = pd.DataFrame({'Wavelength (nm)': ['650', '655'], 'H I': ['  ', '2'], 'Sum(calc)': ['0', '2']}, dtype=object)
        result = clean_spectrum(good, ion=True)
        self.assertEqual(result['H I'].tolist(), [0, 2])
        for column in ['Wavelength (nm)', 'Sum(calc)', 'H I']:
            for bad in [float('nan'), float('inf'), 'NaN', 'Inf', 'NA']:
                frame = good.copy()
                frame.loc[0, column] = bad
                with self.subTest(column=column, value=bad), self.assertRaises(ValueError):
                    clean_spectrum(frame, ion=True)
        for column in ['Wavelength (nm)', 'Sum(calc)']:
            frame = good.copy()
            frame.loc[0, column] = ''
            with self.subTest(column=column), self.assertRaises(ValueError):
                clean_spectrum(frame, ion=True)
        with self.assertRaises(ValueError):
            clean_spectrum(good.rename(columns={'H I': 'unknown'}), ion=True)

    def test_history_nan_cannot_be_treated_as_sparse_ion_blank(self):
        path = self.path/'离子.csv'
        path.write_text('Wavelength (nm),H I,Sum(calc)\n650,0,0\n655,NaN,2\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            read_history(path)
        path.write_text('Wavelength (nm),H I,Sum(calc)\n650,,0\n655,2,2\n', encoding='utf-8')
        frames, _ = read_history(path)
        self.assertEqual(frames['ion']['H I'].tolist(), [0, 2])


if __name__ == '__main__':
    unittest.main()
