import math
import unittest
from unittest.mock import patch
from dataclasses import replace

try:
    from simlibs_ui.models import Parameters, composition, normalize, scan_values, BatchSpec, ScanSpec
except ImportError:
    Parameters = None


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Parameters, '参数契约尚未实现')

    def test_defaults_and_zero_removed_only_in_request(self):
        p = Parameters(elements=('H', 'He'), percentages=(100, 0)).validated()
        self.assertEqual(p.request_composition(), (['H'], [100.0]))
        self.assertEqual(p.points, 2000)

    def test_all_invalid_numbers_rejected(self):
        for field, values in {'Te': [0, -1, math.nan, math.inf], 'Ne': [0, -1, math.nan],
                              'resolution': [0, 1.5, math.inf], 'low_w': [0, 660],
                              'upper_w': [650, math.inf], 'max_ion_charge': [-1, 1.5],
                              'step': [0, -1, math.nan]}.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    replace(Parameters(), **{field: value}).validated()

    def test_bad_compositions_rejected(self):
        for elements, percentages in [((), ()), (('H', 'H'), (50, 50)), (('Xx',), (100,)),
                                       (('H',), (95,)), (('H',), (101,)), (('H', 'He'), (110, -10)),
                                       (('H',), (math.nan,)), (('H', 'He'), (100,))]:
            with self.subTest(elements=elements, percentages=percentages), self.assertRaises(ValueError):
                composition(elements, percentages)

    def test_explicit_normalization_and_tolerance(self):
        self.assertEqual(normalize([80, 15]), [80 / 95 * 100, 15 / 95 * 100])
        with self.assertRaises(ValueError):
            normalize([0, 0])
        p = Parameters(percentages=(99.9999999,)).validated()
        self.assertAlmostEqual(sum(p.percentages), 100, delta=1e-6)

    def test_scan_endpoints_and_resource_limits(self):
        self.assertEqual(scan_values('Te', 1, 2, count=2), [1.0, 2.0])
        self.assertEqual(scan_values('Te', 1, 1.3, step=.1), [1, 1.1, 1.2, 1.3])
        self.assertEqual(scan_values('R', 1000, 2000, count=3), [1000, 1500, 2000])
        for kwargs in [dict(start=2, stop=1, count=2), dict(start=1, stop=2, count=201),
                       dict(start=1, stop=2, step=0), dict(start=1, stop=2, count=1)]:
            with self.assertRaises(ValueError):
                scan_values('Te', **kwargs)
        with self.assertRaises(ValueError):
            replace(Parameters(), upper_w=2000).validated()
        with self.assertRaises(ValueError):
            BatchSpec(size=3000).validated(Parameters())
        with self.assertRaises(ValueError):
            ScanSpec(axis='bad').validated(Parameters())

    def test_resource_limit_uses_actual_default_grid(self):
        p = replace(Parameters(), step=10, resample=False)
        self.assertEqual(p.points, 2000)
        with self.assertRaises(ValueError):
            BatchSpec(size=3000).validated(p)
        with self.assertRaises(ValueError):
            BatchSpec().validated(replace(Parameters(), webscraping='dynamic', resample=False))

    def test_explicit_coarse_grid_allows_bounded_wide_range(self):
        p = replace(Parameters(), low_w=200, upper_w=5000, step=1, resample=True).validated()
        self.assertEqual(p.points, 4800)
        with self.assertRaises(ValueError):
            replace(p, step=.0001).validated()

    def test_finite_but_overflowing_totals_and_grids_rejected_cleanly(self):
        cases = [lambda: composition(['H', 'He'], [1e308, 1e308]),
                 lambda: normalize([1e308, 1e308]),
                 lambda: replace(Parameters(), upper_w=1e308).validated(),
                 lambda: replace(Parameters(), step=5e-324, resample=True).validated(),
                 lambda: replace(Parameters(), Te=10**400).validated(),
                 lambda: scan_values('Te', 1, 2, step=5e-324)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                case()

    def test_large_finite_count_scans_return_finite_ordered_endpoints(self):
        for axis in ('Te', 'Ne', 'R'):
            with self.subTest(axis=axis):
                spec = ScanSpec(axis=axis, start=1e308, stop=1.7e308, count=5)
                values = spec.validated(Parameters())
                self.assertEqual(len(values), 5)
                self.assertTrue(all(math.isfinite(v) for v in values))
                self.assertEqual(float(values[0]), 1e308)
                self.assertEqual(float(values[-1]), 1.7e308)
                self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
                self.assertTrue(all(1e308 <= v <= 1.7e308 for v in values))
                if axis == 'R':
                    self.assertTrue(all(type(v) is int for v in values))

    def test_step_scan_contains_exact_start_and_stop(self):
        start, stop = 1.12345678912345, 1.42345678912345
        values = scan_values('Te', start, stop, step=.1)
        self.assertEqual(values[0], start)
        self.assertEqual(values[-1], stop)
        self.assertTrue(all(start <= v <= stop for v in values))

    def test_scan_rejects_unrepresentable_distinct_frames(self):
        for axis in ('Te', 'Ne'):
            with self.subTest(axis=axis), self.assertRaises(ValueError):
                scan_values(axis, 1.0, math.nextafter(1.0, math.inf), count=5)

    def test_scan_spec_validates_each_derived_frame(self):
        for values in [[1., float('nan')], [1., float('inf')], [1., 0.], [1., 3.], [2., 1.]]:
            with self.subTest(values=values), patch('simlibs_ui.models.scan_values', return_value=values), self.assertRaises(ValueError):
                ScanSpec(start=1, stop=2, count=2).validated(Parameters())


if __name__ == '__main__':
    unittest.main()
