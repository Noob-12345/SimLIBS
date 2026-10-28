"""Missing Stark coefficients retain lines, areas and usable diagnostics."""
from pathlib import Path
import math
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from scipy.integrate import trapezoid

from simLIBS import SimulatedLIBS, MissingStarkDataError, NISTSelfAbsorptionConfig
from simLIBS import nist_self_absorption as model
from stark_fixtures import partial_provider


HTML = (Path(__file__).parent / 'fixtures' / 'nist_mg_280_290.html').read_text(encoding='utf-8')


class MissingStarkTests(unittest.TestCase):
    def make(self, **changes):
        args = dict(Te=1., Ne=1e17, elements=['Mg'], percentages=[100.],
                    low_w=280., upper_w=290., resolution=3000,
                    stark_broadening=True, instrument_broadening=False,
                    self_absorption_config={'missing_stark': 'unbroadened'})
        args.update(changes)
        response = Mock(text=HTML)
        response.raise_for_status.return_value = None
        with patch('simLIBS.simulation.requests.get', return_value=response), \
                patch('simLIBS.nist_stark.resolve_online', side_effect=partial_provider):
            return SimulatedLIBS(**args)

    def test_partial_coverage_keeps_all_line_areas_and_reports_missing(self):
        libs = self.make()
        self.assertEqual(len(libs.missing_stark_lines), 18)
        self.assertEqual(len(libs.matched_stark_lines), 2)
        self.assertEqual(len(libs.self_absorption_diagnostics), 20)
        self.assertTrue(libs.missing_stark_lines.stark_width_nm.isna().all())
        self.assertTrue(libs.missing_stark_lines.stark_missing_reason.notna().all())
        self.assertTrue(libs.matched_stark_lines.stark_width_nm.gt(0).all())
        x = libs.raw_spectrum.wavelength.to_numpy()
        remaining = libs.raw_spectrum.intensity.to_numpy().copy()
        for row in libs.matched_stark_lines.itertuples():
            gamma = row.stark_width_nm * 1e17 / row.stark_reference_ne_cm3
            remaining -= row.nist_strength * gamma / (math.pi * ((x-row.wavelength_nm)**2+gamma**2))
        # Every unknown line is kept with its NIST area, independently of grid alignment.
        self.assertAlmostEqual(trapezoid(remaining, x), libs.missing_stark_lines.nist_strength.sum(), places=7)
        np.testing.assert_allclose(libs.raw_spectrum, libs.unabsorbed_raw_spectrum)
        counts = libs.self_absorption_metadata['stark_data']
        self.assertEqual((counts['missing_line_count'], counts['matched_line_count']), (18, 2))
        self.assertEqual(counts['stark_b_line_count'], 2)
        self.assertEqual(counts['source_mode'], 'STARK-B')
        self.assertNotIn('local_line_count', counts)
        self.assertNotIn('unavailable', counts['sources'])

    def test_all_missing_with_instrument_matches_analytic_gaussian(self):
        libs = self.make(low_w=281.05, upper_w=281.07, instrument_broadening=True)
        self.assertEqual(len(libs.missing_stark_lines), 2)
        self.assertTrue(libs.matched_stark_lines.empty)
        x = libs.raw_spectrum.wavelength.to_numpy()
        expected = np.zeros_like(x)
        for row in libs.missing_stark_lines.itertuples():
            width = row.wavelength_nm / 3000
            expected += row.nist_strength / (width*math.sqrt(math.pi)) * np.exp(-((x-row.wavelength_nm)/width)**2)
        np.testing.assert_allclose(libs.raw_spectrum.intensity, expected, rtol=2e-14)
        diagnostics = libs.self_absorption_diagnostics
        self.assertFalse(diagnostics.stark_broadening_applied.any())
        self.assertTrue(diagnostics.thin_fwhm_nm.isna().all())

    def test_all_missing_without_instrument_preserves_area_and_centroid(self):
        # These are discrete lines, not narrow Lorentzians with invented coefficients.
        libs = self.make(low_w=281.05, upper_w=281.07)
        x, y = libs.raw_spectrum.to_numpy().T
        rows = libs.missing_stark_lines
        self.assertTrue(np.isfinite(y).all())
        self.assertAlmostEqual(trapezoid(y, x), rows.nist_strength.sum())
        self.assertAlmostEqual(trapezoid(x*y, x), (rows.wavelength_nm*rows.nist_strength).sum())

    def test_self_absorption_only_corrects_lines_with_known_widths(self):
        libs = self.make(self_absorption=True)
        diagnostics = libs.self_absorption_diagnostics
        missing = diagnostics.loc[diagnostics.stark_missing]
        matched = diagnostics.loc[~diagnostics.stark_missing]
        self.assertTrue(missing.SA.eq(1).all())
        self.assertTrue(missing.tau_center.isna().all())
        self.assertFalse(missing.self_absorption_applied.any())
        np.testing.assert_array_equal(missing.thin_area, missing.absorbed_area)
        self.assertTrue(matched.self_absorption_applied.all())
        self.assertTrue(matched.SA.lt(1).all())
        self.assertEqual(libs.self_absorption_metadata['stark_data']['self_absorption_skipped_count'], 18)

    def test_regridding_keeps_missing_diagnostics_without_network(self):
        libs = self.make()
        missing = libs.missing_stark_lines.copy(deep=True)
        with patch('simLIBS.simulation.requests.get', side_effect=AssertionError('network used')), \
                patch.object(model, 'resolve_stark', side_effect=AssertionError('coefficients resolved again')):
            libs.interpolate(resolution=.01)
        pd.testing.assert_frame_equal(libs.missing_stark_lines, missing)
        self.assertEqual(len(libs.raw_spectrum), 1001)
        self.assertTrue(np.isfinite(libs.raw_spectrum.to_numpy()).all())

    def test_unbroadened_lines_do_not_require_dense_voigt_work(self):
        with patch.object(model, 'MAX_LINE_POINT_WORK', 1):
            libs = self.make(low_w=281.05, upper_w=281.07)
        self.assertEqual(len(libs.missing_stark_lines), 2)
        self.assertGreater(libs.raw_spectrum.intensity.max(), 0)

    def test_default_remains_strict_and_policy_is_validated(self):
        with self.assertRaises(MissingStarkDataError):
            self.make(self_absorption_config={})
        for value in ('skip', '', None, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'missing_stark'):
                NISTSelfAbsorptionConfig(missing_stark=value)


if __name__ == '__main__':
    unittest.main()
