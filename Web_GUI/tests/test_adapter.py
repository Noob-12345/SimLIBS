import importlib
from pathlib import Path
from dataclasses import replace
import tempfile
import sys
import unittest
from unittest.mock import patch, Mock
import numpy as np

from simlibs_ui.models import Parameters
from simlibs_ui.settings import Settings

try:
    from simlibs_ui.adapter import simulate, source_module, resolve_driver
except ImportError:
    simulate = None

HTML = b'<html><script>var dataDopplerArray=[\n[650,0],\n[655,2],\n[660,0]];\n    var dataSticksArray=[];</script></html>'
CSV = 'Wavelength (nm),H I,Sum(calc)\n650,0,0\n655,2,2\n660,0,0\n'


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(simulate, '真实适配层尚未实现')
        self.settings = Settings()
        self.module = source_module(self.settings.source)

    def test_static_real_constructor_parser_and_interpolate(self):
        response = Mock(content=HTML)
        with patch('requests.get', return_value=response) as get:
            frames, origin = simulate(Parameters(), self.settings)
        self.assertEqual(len(frames['raw']), 3)
        self.assertEqual(len(frames['interpolated']), 2000)
        self.assertTrue(np.isfinite(frames['interpolated'].to_numpy()).all())
        self.assertAlmostEqual(frames['raw']['intensity'].max(), 2)
        self.assertEqual(get.call_args.kwargs['timeout'], (10, 30))
        self.assertTrue(get.call_args.kwargs['verify'])
        self.assertIn('composition=H%3A100', get.call_args.args[0])
        self.assertEqual(origin['class'], 'simLIBS.simulation.SimulatedLIBS')
        self.assertEqual(origin['actual_Ne'], '1e17')
        self.assertEqual(len(origin['source_sha256']), 64)
        self.assertNotIn('ion', frames)

    def test_source_import_does_not_shadow_ui_module_paths(self):
        self.assertNotIn(str(Path(self.settings.source).resolve()), sys.path,
                         '源库仅临时添加到导入路径，不能遮蔽 UI/tests 名称空间')
        self.assertEqual(Path(self.module.__file__).resolve(), Path(self.settings.source)/'simLIBS'/'simulation.py')

    def test_invalid_parameters_zero_transport(self):
        with patch('requests.get') as get, self.assertRaises(ValueError):
            simulate(replace(Parameters(), Ne=0), self.settings)
        get.assert_not_called()

    def test_bad_response_and_duplicate_wavelength(self):
        for html in [b'<html>No NIST data</html>', HTML.replace(b'655,2', b'650,2')]:
            with patch('requests.get', return_value=Mock(content=html)), self.assertRaisesRegex(RuntimeError, 'NIST|重复'):
                simulate(Parameters(), self.settings)

    def test_custom_resampling_calls_real_interpolate(self):
        with patch('requests.get', return_value=Mock(content=HTML)):
            frames, _ = simulate(replace(Parameters(), resample=True, step=.1), self.settings)
        self.assertEqual(len(frames['interpolated']), 100)

    def test_wide_coarse_grid_bounded_during_real_constructor(self):
        original = self.module.SimulatedLIBS.interpolate
        steps = []
        def recorded(obj, resolution=.005):
            steps.append(resolution)
            self.assertLessEqual(int(np.ceil((obj.upper_w-obj.low_w)/resolution)), 200000,
                                 '原构造期间不能创建超限默认网格')
            return original(obj, resolution)
        p = replace(Parameters(), low_w=200, upper_w=5000, resample=True, step=1)
        with patch('requests.get', return_value=Mock(content=HTML)), patch.object(self.module.SimulatedLIBS, 'interpolate', recorded):
            frames, origin = simulate(p, self.settings)
        self.assertEqual(steps, [1.0], '用户步长在首次插值生效且不重复插值')
        self.assertEqual(len(frames['interpolated']), 4800)
        self.assertEqual(origin['parameters']['step'], 1.0)

    def test_dynamic_stable_controls_and_browser_quit(self):
        driver = Mock()
        driver.window_handles = ['main', 'csv']
        driver.page_source = '<html><pre>' + CSV + '</pre></html>'
        driver.find_element.return_value.is_displayed.return_value = True
        driver.find_element.return_value.is_enabled.return_value = True
        with patch('simlibs_ui.adapter.resolve_driver', return_value=('fake.exe', '154.0.8037.58')), \
             patch.object(self.module.webdriver, 'Chrome', return_value=driver) as chrome:
            frames, origin = simulate(replace(Parameters(), webscraping='dynamic'), self.settings)
        self.assertIn('--headless=new', chrome.call_args.kwargs['options'].arguments)
        self.assertNotIn('detach', chrome.call_args.kwargs['options'].experimental_options)
        self.assertEqual(driver.quit.call_count, 1)
        selectors = [c.args[1] for c in driver.find_element.call_args_list]
        self.assertIn('input#resolution, input[name="resolution"]', selectors)
        self.assertIn('button[name="recalc"]', selectors)
        self.assertIn('button[name="ViewDataCSV"], button[onclick*="viewDataCSV"]', selectors)
        self.assertEqual(list(frames['ion']), ['Wavelength (nm)', 'H I', 'Sum(calc)'])
        self.assertEqual(frames['raw'].to_dict('list'), frames['interpolated'].to_dict('list'))
        self.assertEqual(origin['driver_version'], '154.0.8037.58')

    def test_dynamic_error_always_quits(self):
        driver = Mock()
        driver.get.side_effect = RuntimeError('page timeout')
        with patch('simlibs_ui.adapter.resolve_driver', return_value=('fake.exe', '154')), \
             patch.object(self.module.webdriver, 'Chrome', return_value=driver), self.assertRaisesRegex(RuntimeError, 'page timeout'):
            simulate(replace(Parameters(), webscraping='dynamic'), self.settings)
        driver.quit.assert_called_once()

    def test_real_nist_single_ion_csv_without_sum_is_preserved(self):
        csv = (Path(__file__).parent/'fixtures'/'nist_H_singleion.csv').read_text(encoding='utf-8')
        driver = Mock()
        driver.window_handles = ['main', 'csv']
        driver.page_source = '<html><pre>' + csv + '</pre></html>'
        driver.find_element.return_value.is_displayed.return_value = True
        driver.find_element.return_value.is_enabled.return_value = True
        with patch('simlibs_ui.adapter.resolve_driver', return_value=('fake.exe', '154.0.8037.92')), \
             patch.object(self.module.webdriver, 'Chrome', return_value=driver):
            frames, origin = simulate(replace(Parameters(), webscraping='dynamic'), self.settings)
        self.assertEqual(list(frames['ion']), ['Wavelength (nm)', 'H I', 'Sum(calc)'])
        np.testing.assert_array_equal(frames['ion']['H I'], frames['ion']['Sum(calc)'])
        np.testing.assert_array_equal(frames['raw']['intensity'], frames['ion']['H I'])
        self.assertIn('sole H I', origin['ion_total'])
        driver.quit.assert_called_once()

    def test_dynamic_missing_or_nonfinite_scientific_cells_rejected(self):
        header = 'Wavelength (nm),H I,Sum(calc)\n650,0,0\n'
        for row in [',2,2', '   ,2,2', 'NaN,2,2', 'Inf,2,2', '655,2,', '655,2,NaN',
                    '655,2,Inf', '655,NaN,2', '655,nan,2', '655,Inf,2', '655,-Inf,2', '655,NA,2']:
            with self.subTest(row=row):
                driver = Mock()
                driver.window_handles = ['main', 'csv']
                driver.page_source = '<html><pre>' + header + row + '\n660,0,0\n</pre></html>'
                driver.find_element.return_value.is_displayed.return_value = True
                driver.find_element.return_value.is_enabled.return_value = True
                with patch('simlibs_ui.adapter.resolve_driver', return_value=('fake.exe', '154.0.8037.92')), \
                     patch.object(self.module.webdriver, 'Chrome', return_value=driver), self.assertRaises(RuntimeError):
                    simulate(replace(Parameters(), webscraping='dynamic'), self.settings)
                driver.quit.assert_called_once()

    def test_dynamic_legal_sparse_contributions_and_single_ion_preserved(self):
        for csv, expected in [
            ('Wavelength (nm),H I,He I,Sum(calc)\n650,0, ,0\n655,2,,2\n660,,3,3\n', [0, 2, 3]),
            ('Wavelength (nm),H I\n650,0\n655,2\n660, \n', [0, 2, 0])]:
            with self.subTest(csv=csv):
                driver = Mock()
                driver.window_handles = ['main', 'csv']
                driver.page_source = '<html><pre>' + csv + '</pre></html>'
                driver.find_element.return_value.is_displayed.return_value = True
                driver.find_element.return_value.is_enabled.return_value = True
                with patch('simlibs_ui.adapter.resolve_driver', return_value=('fake.exe', '154.0.8037.92')), \
                     patch.object(self.module.webdriver, 'Chrome', return_value=driver):
                    frames, origin = simulate(replace(Parameters(), webscraping='dynamic'), self.settings)
                self.assertEqual(frames['raw']['intensity'].tolist(), expected)
                self.assertTrue(np.isfinite(frames['ion'].to_numpy()).all())
                if 'He I' not in frames['ion']:
                    self.assertIn('copied sole H I', origin['ion_total'])
                driver.quit.assert_called_once()

    def test_driver_manager_matching_and_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chromedriver.exe'
            path.touch()
            with patch('simlibs_ui.adapter.chrome_version', return_value='154.0.8037.58'), \
                 patch('simlibs_ui.adapter.driver_version', return_value='154.0.8037.58'), \
                 patch('simlibs_ui.adapter.ChromeDriverManager') as manager:
                manager.return_value.install.return_value = str(path)
                actual, version = resolve_driver(self.settings)
            self.assertEqual(actual, str(path))
            self.assertEqual(version, '154.0.8037.58')
            self.assertEqual(manager.call_args.kwargs['driver_version'], '154.0.8037.58')
            with patch('simlibs_ui.adapter.chrome_version', return_value='154.0.8037.58'), \
                 patch('simlibs_ui.adapter.driver_version', return_value='152.0.0.0'), self.assertRaisesRegex(RuntimeError, '154.*152'):
                resolve_driver(replace(self.settings, driver=str(path)))


if __name__ == '__main__':
    unittest.main()
