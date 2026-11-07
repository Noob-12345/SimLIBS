"""Static line-table synthesis, with offline NIST response fixtures."""
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import requests

from simLIBS import SimulatedLIBS, simulation
from simLIBS.nist_lines import parse_sticks, render_sticks


def html(rows, columns=("Fe I", "Fe II")):
    labels = ','.join("{label:'%s'}" % col for col in ("Wavelength (nm)", *columns))
    data = ''.join(',[' + ','.join(str(v) for v in row) + ']' for row in rows)
    # Deliberately different Doppler data must never be used.
    return ("<script>var dataDopplerArray=[[{label:'Wavelength'},{label:'Sum'}],[500,999999]];"
            + 'var dataSticksArray=[[' + labels + ']' + data + '];</script>')


def response(body):
    result = Mock(text=body)
    result.raise_for_status.return_value = None
    return result


class StaticLineTests(unittest.TestCase):
    def make(self, **kwargs):
        params = dict(Te=1.0, Ne=1.23456789e17, elements=['Fe'], percentages=[100],
                      resolution=1000, low_w=495, upper_w=505, webscraping='static')
        params.update(kwargs)
        return SimulatedLIBS(**params)

    def test_static_uses_calculated_sticks_and_preserves_integrated_strength(self):
        with patch.object(simulation.requests, 'get', return_value=response(html([[500, 80, 20]]))) as get, \
                patch.object(simulation.webdriver, 'Chrome', side_effect=AssertionError('browser used')):
            libs = self.make()
        x = libs.raw_spectrum.wavelength.to_numpy()
        expected = 100/(0.5*math.sqrt(math.pi))*np.exp(-((x-500)/0.5)**2)
        np.testing.assert_allclose(libs.raw_spectrum.intensity, expected, atol=1e-12)
        self.assertAlmostEqual(float(np.trapezoid(libs.raw_spectrum.intensity, x)), 100, places=10)
        pd.testing.assert_frame_equal(libs.raw_spectrum, libs.get_interpolated_spectrum())
        query = parse_qs(urlparse(get.call_args.args[0]).query)
        self.assertEqual(query['min_rel_int'], ['0'])
        self.assertEqual(float(query['eden'][0]), 1.23456789e17)
        self.assertEqual(get.call_args.kwargs['timeout'], 90)

    def test_regridding_renders_lines_without_network_or_spline(self):
        with patch.object(simulation.requests, 'get', return_value=response(html([[500, 80, 20]]))):
            libs = self.make()
        raw = libs.raw_spectrum.copy()
        with patch.object(simulation.requests, 'get', side_effect=AssertionError('network used')), \
                patch.object(simulation, 'CubicSpline', side_effect=AssertionError('spline used')):
            libs.interpolate(resolution=.01)
            first = libs.get_interpolated_spectrum().copy()
            libs.interpolate(resolution=.01)
        self.assertEqual(len(first), 1001)
        self.assertEqual(first.wavelength.iloc[-1], 505)
        pd.testing.assert_frame_equal(first, libs.get_interpolated_spectrum())
        pd.testing.assert_frame_equal(raw, libs.raw_spectrum)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'spectrum.csv'
            libs.save_to_csv(path)
            np.testing.assert_allclose(pd.read_csv(path), first)

    def test_bands_merge_before_broadening_and_keep_distinct_coincident_rows(self):
        rows = [[699.5, 3, 0], [700, 5, 0], [700, 7, 0], [700.5, 11, 0]]
        with patch.object(simulation.requests, 'get', return_value=response(html(rows))) as get, \
                patch.object(simulation.time, 'sleep'):
            libs = self.make(low_w=200, upper_w=1000)
        self.assertEqual(len(libs.line_table), 4)
        self.assertEqual(get.call_count, 2)
        queries = [parse_qs(urlparse(call.args[0]).query) for call in get.call_args_list]
        self.assertEqual([(q['low_w'][0], q['upp_w'][0]) for q in queries], [('200', '702.0'), ('698.0', '1000')])
        x = libs.raw_spectrum.wavelength.to_numpy()
        expected = np.zeros_like(x)
        for center, strength, _ in rows:
            width = center/1000
            expected += strength/(width*np.sqrt(np.pi))*np.exp(-((x-center)/width)**2)
        np.testing.assert_allclose(libs.raw_spectrum.intensity, expected, atol=1e-12)

    def test_empty_band_is_zero_and_null_ion_values_are_zero(self):
        with patch.object(simulation.requests, 'get', return_value=response(html([]))):
            libs = self.make()
        self.assertTrue((libs.raw_spectrum.intensity == 0).all())
        table = parse_sticks(html([[500, 'null', 4]]))
        self.assertEqual(table['Fe I'].iloc[0], 0)
        self.assertGreater(render_sticks(table, np.linspace(499, 501, 1001), 1000).intensity.max(), 0)

    def test_parser_rejects_missing_or_invalid_calculated_lines(self):
        for body in ('var dataDopplerArray=[[1,2]];', html([[500, -1, 2]]),
                     html([[500, 'NaN', 2]]), html([[500, 3]], columns=('Rel. Int.',))):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_sticks(body)

    def test_transient_request_failure_retries_and_exhaustion_raises(self):
        with patch.object(simulation.requests, 'get', side_effect=[requests.Timeout(), response(html([[500, 1, 0]]))]) as get, \
                patch.object(simulation.time, 'sleep'):
            self.make()
            self.assertEqual(get.call_count, 2)
        with patch.object(simulation.requests, 'get', return_value=response('bad response')) as get, \
                patch.object(simulation.time, 'sleep'), self.assertRaisesRegex(ValueError, 'dataSticksArray'):
            self.make()
        self.assertEqual(get.call_count, 3)

    def test_static_rejects_invalid_grid_and_resolution_before_request(self):
        with patch.object(simulation.requests, 'get', side_effect=AssertionError('network used')):
            for changes in ({'resolution': 0}, {'low_w': 500, 'upper_w': 500}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.make(**changes)

    def test_dynamic_still_recalculates_and_reads_browser_csv(self):
        driver = Mock()
        driver.window_handles = ['main', 'csv']
        driver.page_source = '<pre>Wavelength (nm),Fe I,Sum(calc)\n499,2,2\n500,7,7\n501,3,3</pre>'
        resolution_input, recalculate, csv_button = Mock(), Mock(), Mock()
        with patch.object(simulation.webdriver, 'Chrome', return_value=driver), \
                patch.object(simulation, 'ChromeDriverManager') as manager, \
                patch.object(simulation, 'Service'), \
                patch.object(simulation, 'WebDriverWait') as wait, \
                patch.object(simulation.requests, 'get', side_effect=AssertionError('static path used')), \
                patch.object(simulation, 'render_sticks', side_effect=AssertionError('local broadening used')):
            manager.return_value.install.return_value = 'test-driver'
            wait.return_value.until.side_effect = [resolution_input, recalculate, csv_button]
            libs = self.make(webscraping='dynamic')
        recalculate.click.assert_called_once()
        csv_button.click.assert_called_once()
        driver.quit.assert_called_once()
        np.testing.assert_array_equal(libs.get_interpolated_spectrum().intensity, [2, 7, 3])
        np.testing.assert_array_equal(libs.get_ion_spectra()['Fe I'], [2, 7, 3])
        query = parse_qs(urlparse(driver.get.call_args.args[0]).query)
        self.assertEqual(query['min_rel_int'], ['0.001'])
        self.assertIsNone(libs.line_table)


if __name__ == '__main__':
    unittest.main()
