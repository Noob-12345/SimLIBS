"""用真实 STARK-B 表验证宽度约定、温度范围和缓存；测试不联网。"""
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch

from simLIBS import stark_b


HTML = (Path(__file__).parent/'fixtures'/'starkb_si_ii_6347.html').read_text(encoding='utf-8')


class StarkBTests(unittest.TestCase):
    def table(self, html=HTML):
        return stark_b.parse_table(html, element='Si', charge=1, dataset_id='223', method='SCP')[0]

    def test_real_table_electron_fwhm_and_published_fit(self):
        row = self.table()
        self.assertEqual(row['lower_label'], '3s2.4s 2S 1/2')
        self.assertEqual(row['upper_label'], '3s2.4p 2Po 3/2')
        self.assertEqual(len(row['samples']), 4)
        # 表中 10000K 的 1.93 Angstrom 是电子 FWHM；当前代码 W=FWHM/2。
        out = stark_b.evaluate_width(row, temperature_k=10000, ne=1e17, wavelength_nm=634.7)
        self.assertAlmostEqual(out['stark_width_nm'], .0965)
        self.assertEqual(out['stark_reference_ne_cm3'], 1e17)
        self.assertEqual(out['stark_temperature_method'], 'tabulated')
        self.assertIn('PhysRevA.16.1617', out['stark_source'])
        self.assertEqual(out['stark_method'], 'SCP')
        self.assertIsNone(out['stark_isolated_limit_cm3'])
        fit = stark_b.evaluate_width(row, temperature_k=15000, ne=1e16, wavelength_nm=635.)
        x = math.log10(15000)
        expected = 10**(5.18838-1.99203*x+.1914*x*x)*.1*.1*(635/634.7)**2/2
        self.assertAlmostEqual(fit['stark_width_nm'], expected)
        self.assertEqual(fit['stark_temperature_method'], 'published log10 fit')

    def test_no_extrapolated_temperature_or_high_density(self):
        for temperature, ne, reason in [(4999, 1e17, 'temperature'), (40001, 1e17, 'temperature'),
                                         (10000, 1.01e17, 'density')]:
            with self.subTest(), self.assertRaisesRegex(stark_b.StarkBUnavailable, reason):
                stark_b.evaluate_width(self.table(), temperature_k=temperature, ne=ne, wavelength_nm=634.7)

    def test_missing_fit_is_not_replaced_by_an_invented_law(self):
        row = self.table()
        row['fit'] = None
        with self.assertRaisesRegex(stark_b.StarkBUnavailable, 'fit'):
            stark_b.evaluate_width(row, temperature_k=15000, ne=1e17, wavelength_nm=634.7)

    def test_invalid_impact_flag_and_isolated_limit_are_rejected(self):
        row = self.table()
        for sample in row['samples']:
            sample['flag'] = '*'
        with self.assertRaisesRegex(stark_b.StarkBUnavailable, 'impact'):
            stark_b.evaluate_width(row, temperature_k=10000, ne=1e17, wavelength_nm=634.7)
        row = self.table()
        row['c_angstrom_cm3'] = 1.93e16
        with self.assertRaisesRegex(stark_b.StarkBUnavailable, 'isolated'):
            stark_b.evaluate_width(row, temperature_k=10000, ne=1e17, wavelength_nm=634.7)

    def test_isolated_limit_uses_same_density_reference_as_C(self):
        row = self.table()
        row['c_angstrom_cm3'] = 1.93e18  # 原表 W=1.93A，故 Ne 上限始终为 1e18。
        out = stark_b.evaluate_width(row, temperature_k=10000, ne=1e16, wavelength_nm=634.7)
        self.assertAlmostEqual(out['stark_isolated_limit_cm3'], 1e18)

    def test_temperature_boundary_roundoff_is_only_machine_precision(self):
        for t in (math.nextafter(5000., 0.), math.nextafter(40000., math.inf)):
            out = stark_b.evaluate_width(self.table(), temperature_k=t, ne=1e17, wavelength_nm=634.7)
            self.assertEqual(out['stark_temperature_method'], 'tabulated')

    def test_malformed_service_response_does_not_become_empty_coverage(self):
        for html in ('<h1>Error</h1>', HTML.replace('w (Å)', 'unrecognised-width')):
            with self.subTest(), self.assertRaises(ValueError):
                self.table(html)

    def test_cache_reuses_snapshot_offline_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = stark_b.SourceCache(folder, allow_network=True)
            count = []
            def fetch():
                count.append(1)
                return {'html': HTML}
            document = cache.get('test-si', fetch)
            self.assertEqual(len(count), 1)
            offline = stark_b.SourceCache(folder, allow_network=False)
            self.assertEqual(offline.get('test-si', lambda: self.fail('network used')), document)
            self.assertIn('retrieved_utc', document)
            self.assertIn('sha256', document)
            with self.assertRaisesRegex(stark_b.StarkDataAccessError, 'cache'):
                offline.get('absent', fetch)
            file = next(Path(folder).glob('*.json'))
            file.write_text(file.read_text(encoding='utf-8').replace('6347', '6348'), encoding='utf-8')
            with self.assertRaisesRegex(stark_b.StarkDataAccessError, 'integrity'):
                offline.get('test-si', fetch)

    def test_exact_density_uses_standard_table_form(self):
        replies = [
            '<table id="ion-datasets"><a href="/index.php/data/ion/35">Si II</a></table>',
            '<select id="dataset"><option value="223">Si II, electron, method : SCP</option></select>',
            '<select id="density"><option value="1e17">1e17</option></select>',
            '<select id="transition"><option value="all">All</option></select>',
            '<select id="temperature"><option value="all">All</option></select>', HTML,
        ]
        with patch.object(stark_b.StarkBClient, '_request', side_effect=replies) as request:
            result = stark_b.StarkBClient(None)._fetch('Si', 1, 1e17)
        calls = [c.kwargs.get('data', {}) for c in request.call_args_list]
        self.assertEqual(calls[-1]['queryType'], 'density')
        self.assertEqual(calls[-1]['temperature'], 'all')
        self.assertEqual(result['datasets'][0]['html'], HTML)

    def test_query_density_keeps_precision_beyond_printed_table(self):
        rounded = HTML.replace('1.000e+17', '9.877e+16')
        payload = dict(datasets=[dict(id='223', method='SCP', url='STARK-B', html=rounded)])
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(stark_b.StarkBClient, '_fetch', return_value=payload):
            rows, _ = stark_b.StarkBClient(stark_b.SourceCache(folder)).species('Si', 1, 9.87654321e16)
        self.assertEqual(rows[0]['samples'][0]['ne'], 9.87654321e16)
        self.assertEqual(rows[0]['samples'][0]['printed_ne_cm3'], 9.877e16)

    def test_read_only_request_retries_transient_connection_error(self):
        from unittest.mock import Mock
        response = Mock(text=HTML)
        response.raise_for_status.return_value = None
        session = Mock()
        session.request.side_effect = [stark_b.requests.ConnectionError('temporary disconnect'), response]
        self.assertEqual(stark_b.StarkBClient._request(session, 'POST', 'https://stark-b.obspm.fr'), HTML)
        self.assertEqual(session.request.call_count, 2)


if __name__ == '__main__':
    unittest.main()
