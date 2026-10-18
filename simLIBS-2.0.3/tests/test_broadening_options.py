"""静态展宽组合的物理不变量、开关兼容性和离线集成测试。"""
import inspect
import importlib.util
import contextlib
import io
import json
import math
from pathlib import Path
import unittest
import sys
import tempfile
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid
from scipy.special import voigt_profile

from simLIBS import SimulatedLIBS, simulation
from simLIBS import nist_self_absorption as model
from simLIBS.nist_lines import render_sticks


HTML = (Path(__file__).parent/'fixtures'/'nist_mg_280_290.html').read_text(encoding='utf-8')
# 只供批量测试覆盖整段夹具使用；禁止作为实际模拟的物理系数。
TEST_STARK = [dict(row, stark_width_nm=.002, source='synthetic test fixture only')
              for row in model.parse_atomic_payload(HTML)['transitions']]


def response(body=HTML):
    """仅替换 HTTP 输入，谱线解析、系数匹配和线形合成均运行真实代码。"""
    result = Mock(text=body)
    result.raise_for_status.return_value = None
    return result


class IndependentBroadeningTests(unittest.TestCase):
    def setUp(self):
        for name in ('stark_broadening', 'instrument_broadening'):
            self.assertIn(name, inspect.signature(SimulatedLIBS).parameters,
                          '静态主入口尚未支持独立展宽选项: ' + name)

    def make(self, body=HTML, **changes):
        args = dict(Te=1., Ne=1e17, elements=['Mg'], percentages=[100.],
                    low_w=285.27, upper_w=285.33, resolution=3000, max_ion_charge=2,
                    webscraping='static', self_absorption=False,
                    stark_broadening=True, instrument_broadening=False,
                    self_absorption_config={'path_length_m': .001, 'wavelength_step_nm': .001})
        args.update(changes)
        with patch.object(simulation.requests, 'get', return_value=response(body)), \
                patch.object(simulation.webdriver, 'Chrome', side_effect=AssertionError('browser used')):
            return SimulatedLIBS(**args)

    def test_stark_without_absorption_matches_analytic_lorentz(self):
        libs = self.make()
        self.assertFalse(libs.self_absorption)
        self.assertTrue(libs.stark_broadening)
        self.assertFalse(libs.instrument_broadening)
        d = libs.self_absorption_diagnostics.iloc[0]
        width = 2*d.stark_width_nm*1e17/d.stark_reference_ne_cm3
        delta = libs.raw_spectrum.wavelength.to_numpy()-d.wavelength_nm
        expected = d.nist_strength*(width/2)/(math.pi*(delta**2+(width/2)**2))
        np.testing.assert_allclose(libs.raw_spectrum.intensity, expected, rtol=2e-14)
        self.assertEqual(d.tau_center, 0)
        self.assertEqual(d.SA, 1)
        self.assertEqual(d.absorbed_area, d.nist_strength)
        pd.testing.assert_frame_equal(libs.raw_spectrum, libs.unabsorbed_raw_spectrum)
        self.assertFalse(libs.self_absorption_metadata['self_absorption'])
        np.testing.assert_allclose(libs.get_ion_spectra()['Sum(calc)'], expected)

    def test_stark_and_instrument_without_absorption_match_voigt(self):
        libs = self.make(instrument_broadening=True)
        d = libs.self_absorption_diagnostics.iloc[0]
        sigma = d.wavelength_nm/(3000*math.sqrt(2))
        expected = d.nist_strength*voigt_profile(libs.raw_spectrum.wavelength-d.wavelength_nm,
                                                sigma, d.thin_fwhm_nm/2)
        np.testing.assert_allclose(libs.raw_spectrum.intensity, expected)
        self.assertEqual(d.instrument_sigma_nm, sigma)
        self.assertEqual(d.SA, 1)

    def test_stark_only_does_not_use_saha_or_absorption_density(self):
        with patch.object(model, 'nist_populations', side_effect=AssertionError('Saha used')):
            a = self.make(percentages=[50.], self_absorption_config={
                'path_length_m': 100., 'total_number_density_cm3': 0., 'wavelength_step_nm': .001})
            b = self.make(percentages=[50.], self_absorption_config={
                'path_length_m': 0., 'total_number_density_cm3': 1e30, 'wavelength_step_nm': .001})
        pd.testing.assert_frame_equal(a.raw_spectrum, b.raw_spectrum)
        self.assertNotIn('ion_populations', a.self_absorption_metadata)

    def test_stark_only_accepts_transition_payload_without_population_arrays(self):
        body = HTML.replace('levels[', 'unused_levels[').replace('gValues[', 'unused_gValues[')
        body = body.replace('ips[', 'unused_ips[').replace('var koeff', 'var unused_koeff')
        libs = self.make(body=body)
        self.assertEqual(len(libs.self_absorption_diagnostics), 1)
        self.assertTrue(np.isfinite(libs.raw_spectrum.to_numpy()).all())

    def test_stark_only_regrids_from_cache_and_snapshots_options(self):
        config = {'path_length_m': .001, 'wavelength_step_nm': .001,
                  'instrument_broadening': True}
        libs = self.make(self_absorption_config=config)
        config['instrument_broadening'] = True
        with patch.object(simulation.requests, 'get', side_effect=AssertionError('network used')), \
                patch.object(model, 'resolve_stark', side_effect=AssertionError('coefficients resolved again')):
            libs.interpolate(resolution=.002)
        self.assertEqual(len(libs.raw_spectrum), 31)
        self.assertFalse(libs.self_absorption_metadata['instrument_broadening'])
        pd.testing.assert_frame_equal(libs.raw_spectrum, libs.unabsorbed_raw_spectrum)

    def test_top_level_instrument_option_overrides_legacy_config_without_mutating_it(self):
        config = model.NISTSelfAbsorptionConfig(instrument_broadening=False, wavelength_step_nm=.001)
        libs = self.make(self_absorption=True, instrument_broadening=True,
                         self_absorption_config=config)
        self.assertFalse(config.instrument_broadening)
        self.assertTrue(libs.self_absorption_config.instrument_broadening)
        self.assertTrue((libs.self_absorption_diagnostics.instrument_sigma_nm > 0).all())
        self.assertTrue((libs.self_absorption_diagnostics.SA < 1).all())

    def test_unspecified_options_preserve_legacy_gaussian_and_absorption_defaults(self):
        ordinary = self.make(stark_broadening=None, instrument_broadening=None,
                             self_absorption_config={'invalid_but_ignored': True})
        self.assertFalse(ordinary.stark_broadening)
        self.assertTrue(ordinary.instrument_broadening)
        self.assertIsNone(ordinary.self_absorption_config)
        expected = render_sticks(ordinary.line_table, ordinary.raw_spectrum.wavelength.to_numpy(), 3000)
        pd.testing.assert_frame_equal(ordinary.raw_spectrum, expected)
        absorbed = self.make(self_absorption=True, stark_broadening=None,
                             instrument_broadening=None, self_absorption_config={
                                 'instrument_broadening': False, 'wavelength_step_nm': .001})
        self.assertTrue(absorbed.stark_broadening)
        self.assertFalse(absorbed.instrument_broadening)
        self.assertTrue((absorbed.self_absorption_diagnostics.SA < 1).all())

    def test_absorption_cannot_explicitly_disable_intrinsic_stark_width(self):
        with patch.object(simulation.requests, 'get', side_effect=AssertionError('network used')):
            with self.assertRaisesRegex(ValueError, 'Stark|stark'):
                SimulatedLIBS(elements=['Mg'], percentages=[100], self_absorption=True,
                              stark_broadening=False)

    def test_option_types_are_checked_before_request(self):
        for name in ('stark_broadening', 'instrument_broadening'):
            for value in (1, 'yes', np.bool_(True)):
                with self.subTest(name=name, value=value), \
                        patch.object(simulation.requests, 'get', side_effect=AssertionError('network used')):
                    with self.assertRaisesRegex(ValueError, name):
                        SimulatedLIBS(elements=['Mg'], percentages=[100], **{name: value})

    def test_disabling_both_keeps_line_area_and_regrids_without_atomic_data(self):
        body = "var dataSticksArray=[[{label:'Wavelength (nm)'},{label:'Mg I'}],[285.29642,5]];"
        libs = self.make(body=body, stark_broadening=False, instrument_broadening=False)
        with patch.object(simulation.requests, 'get', side_effect=AssertionError('network used')):
            libs.interpolate(resolution=.002)
        spectrum = libs.interpolated_spectrum
        self.assertAlmostEqual(trapezoid(spectrum.intensity, spectrum.wavelength), 5.)
        self.assertLessEqual(np.count_nonzero(spectrum.intensity), 2)
        self.assertIsNone(libs.self_absorption_config)

    def test_stark_only_still_reports_missing_coefficients(self):
        with self.assertRaises(model.MissingStarkDataError) as raised:
            self.make(low_w=280., upper_w=290., self_absorption_config={'stark_source': 'local'})
        self.assertEqual(len(raised.exception.missing_lines), 18)

    def test_dataset_forwards_both_options_and_uses_stark_sampling_grid(self):
        composition = pd.DataFrame({'Mg': [100.], 'name': ['sample']})
        with patch.object(simulation.requests, 'get', return_value=response()), \
                patch.object(simulation.time, 'sleep'), \
                patch.object(model, 'nist_populations', side_effect=AssertionError('Saha used')):
            dataset = SimulatedLIBS.create_dataset(
                composition, size=1, Te_min=1, Te_max=1, Ne_min=1e17, Ne_max=1e17,
                self_absorption=False, stark_broadening=True, instrument_broadening=False,
                self_absorption_config={'wavelength_step_nm': 100., 'stark_data': TEST_STARK})
        self.assertEqual(dataset.shape, (1, 13))  # 9 个波长点 + Mg/name/Te/Ne
        self.assertGreater(dataset['200.0'].iloc[0], 0)

    def test_dynamic_ignores_local_broadening_switches_and_config(self):
        def browser_result(instance):
            instance.ion_spectra = pd.DataFrame({'Wavelength (nm)': [280., 281.],
                                                'Mg I': [2., 4.], 'Sum(calc)': [2., 4.]})
            instance.raw_spectrum = pd.DataFrame({'wavelength': [280., 281.], 'intensity': [2., 4.]})
            instance.interpolated_spectrum = instance.raw_spectrum.copy()
        with patch.object(simulation.webdriver, 'Chrome'), \
                patch.object(simulation, 'ChromeDriverManager'), patch.object(simulation, 'Service'), \
                patch.object(SimulatedLIBS, 'retrieve_data_dynamic', side_effect=browser_result, autospec=True), \
                patch.object(simulation.requests, 'get', side_effect=AssertionError('static used')):
            libs = SimulatedLIBS(elements=['Mg'], percentages=[100], webscraping='dynamic',
                                 self_absorption=True, stark_broadening=False, instrument_broadening=False,
                                 self_absorption_config={'invalid_but_ignored': True})
        self.assertFalse(libs.self_absorption)
        self.assertFalse(libs.stark_broadening)
        np.testing.assert_array_equal(libs.get_ion_spectra()['Mg I'], [2., 4.])


class UnbroadenedGridTests(unittest.TestCase):
    def setUp(self):
        self.assertIn('instrument_broadening', inspect.signature(render_sticks).parameters,
                      '普通静态渲染尚未支持关闭仪器展宽')

    def test_discrete_projection_preserves_area_centroid_and_coincident_lines(self):
        grid = np.array([499., 499.7, 500.3, 501.])
        centers = np.array([499., 500., 500., 501.])
        strengths = np.array([2., 3., 5., 7.])
        table = pd.DataFrame({'wavelength': centers, 'Fe I': strengths})
        out = render_sticks(table, grid, 3000, instrument_broadening=False)
        self.assertTrue((out.intensity >= 0).all())
        self.assertAlmostEqual(trapezoid(out.intensity, grid), strengths.sum())
        self.assertAlmostEqual(trapezoid(out.intensity*grid, grid), np.dot(centers, strengths))

    def test_empty_table_and_outside_window_lines_do_not_make_artificial_edges(self):
        grid = np.array([499., 500., 501.])
        for centers in ([], [498., 502.]):
            table = pd.DataFrame({'wavelength': centers, 'Fe I': np.ones(len(centers))})
            out = render_sticks(table, grid, 3000, instrument_broadening=False)
            np.testing.assert_array_equal(out.intensity, np.zeros(3))


class ExampleCLITests(unittest.TestCase):
    def test_stark_only_cli_exports_thin_spectrum_and_effective_flags(self):
        path = Path(__file__).parents[1]/'examples/nist_self_absorption_demo.py'
        spec = importlib.util.spec_from_file_location('nist_demo_under_test', path)
        example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(example)
        with tempfile.TemporaryDirectory(prefix='simlibs-cli-') as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
            arguments = [str(path), '--stark-only', '--no-instrument-broadening', '--output', directory]
            with patch.object(sys, 'argv', arguments), \
                    patch.object(simulation.requests, 'get', return_value=response()), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    code = example.main()
                except SystemExit as error:
                    self.fail('示例 CLI 尚未支持独立展宽选项: ' + str(error))
            self.assertEqual(code, 0)
            metadata = json.loads((Path(directory)/'metadata.json').read_text(encoding='utf-8'))
            self.assertFalse(metadata['self_absorption'])
            self.assertFalse(metadata['instrument_broadening'])
            pd.testing.assert_frame_equal(pd.read_csv(Path(directory)/'stark_only.csv'),
                                          pd.read_csv(Path(directory)/'thin_voigt.csv'))


if __name__ == '__main__':
    unittest.main()
