"""Physical invariants and real NIST payload compatibility, without network."""
from copy import deepcopy
from pathlib import Path
import math
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.constants import c
from scipy.special import voigt_profile
from stark_fixtures import provider_response, missing_provider

from simLIBS.nist_lines import parse_sticks
from simLIBS.nist_self_absorption import (
    NISTSelfAbsorptionConfig, MissingStarkDataError, parse_atomic_payload,
    attach_nist_strengths, nist_populations, prepare_nist_absorption,
    render_nist_absorption, resolve_stark,
)


HTML = (Path(__file__).parent/'fixtures'/'nist_mg_280_290.html').read_text(encoding='utf-8')


class NISTAbsorptionTests(unittest.TestCase):
    def setUp(self):
        self.payload = parse_atomic_payload(HTML)
        self.table = parse_sticks(HTML)
        provider_patch = patch('simLIBS.nist_stark.resolve_online', side_effect=provider_response)
        self.provider = provider_patch.start()
        self.addCleanup(provider_patch.stop)

    def prepare(self, **changes):
        config = NISTSelfAbsorptionConfig(**changes)
        rows, info = prepare_nist_absorption([(self.table, self.payload)], te=1, ne=1e17,
                                            elements=['Mg'], percentages=[100], config=config)
        return rows, info, config

    def render(self, rows, info, config, resolution=3000):
        return render_nist_absorption(rows, info, te=1, ne=1e17, low=280, high=290,
                                     resolution=resolution, config=config)

    def test_real_payload_gA_levels_and_nist_population_agreement(self):
        line = self.payload['transitions'][0]
        self.assertEqual(line['gA_s'], 514000000)
        self.assertEqual(line['charge'], 1)
        self.assertAlmostEqual(line['upper_eV'], 35669.31/self.payload['cmeV'])
        pop = nist_populations(self.payload['atoms']['Mg'], 1, 1e17,
                               self.payload['cmeV'], self.payload['koeff'])
        # Values independently reported in the captured response, not rounded column labels.
        np.testing.assert_allclose(pop['fractions'][:2], [.0378600533803186, .953933118472367], rtol=1e-10)
        self.assertEqual(len(pop['fractions']), 13)  # up through bare Mg nucleus
        self.assertAlmostEqual(sum(pop['fractions']), 1)

    def test_unresolved_transitions_preserve_nist_area(self):
        first = dict(self.payload['transitions'][0])
        second = dict(first, gA_s=first['gA_s']*3)
        payload = dict(self.payload, transitions=[first, second])
        table = pd.DataFrame({'wavelength': [first['wavelength_nm']], 'Mg II': [80.]})
        rows = attach_nist_strengths(table, payload, 1)
        self.assertEqual(len(rows), 2)
        np.testing.assert_allclose([r['nist_strength'] for r in rows], [20, 60])

    def test_missing_metadata_and_malformed_arrays_raise(self):
        with self.assertRaisesRegex(ValueError, 'lacks transition'):
            attach_nist_strengths(self.table, dict(self.payload, transitions=[]), 1)
        for html in (HTML.replace('var lines =', 'var other ='),
                     HTML.replace('gValues[12][1] =', 'missing[12][1] ='),
                     HTML.replace('514000000', 'null')):
            with self.subTest(), self.assertRaises(ValueError):
                parse_atomic_payload(html)

    def test_database_missing_list_and_complete_response(self):
        lines = attach_nist_strengths(self.table, self.payload, 1)
        self.provider.side_effect = missing_provider
        with self.assertRaises(MissingStarkDataError) as raised:
            resolve_stark(lines, NISTSelfAbsorptionConfig(), te=1, ne=1e17, cmev=self.payload['cmeV'])
        self.assertEqual(len(raised.exception.missing_lines), len(lines))
        self.assertIn('upper_eV', raised.exception.missing_lines)
        self.provider.side_effect = provider_response
        resolved = resolve_stark(lines, NISTSelfAbsorptionConfig(), te=1, ne=1e17, cmev=self.payload['cmeV'])
        self.assertEqual(len(resolved), len(lines))
        self.assertTrue(all(r['stark_width_nm'] == .002 for r in resolved))
        self.assertTrue(all(r['stark_source'].startswith('STARK-B') for r in resolved))

    def test_opacity_formula_peak_width_area_and_instrument_order(self):
        rows, info, config = self.prepare(total_number_density_cm3=1e16)
        out = self.render(rows, info, config)
        other_r = self.render(rows, info, config, resolution=1000)
        d = out.line_diagnostics
        np.testing.assert_array_equal(d.tau_center, other_r.line_diagnostics.tau_center)
        np.testing.assert_allclose(d.absorbed_peak/d.thin_peak, d.SA)
        np.testing.assert_allclose(d.absorbed_area/d.thin_area, d.SA**.46)
        np.testing.assert_allclose(d.absorbed_fwhm_nm/d.thin_fwhm_nm, d.SA**(-.54))
        row = rows[0]
        expected_q = (row['species_density_cm3']*1e6*row['gA_s']*(row['wavelength_nm']*1e-9)**4*
                      config.path_length_m/(4*math.pi**2*c*math.exp(row['log_partition']))*
                      math.exp(-row['lower_eV']))
        self.assertAlmostEqual(d.tau_center.iloc[0], expected_q/(.04*1e-9))
        np.testing.assert_allclose(d.instrument_sigma_nm, d.wavelength_nm/(3000*math.sqrt(2)))
        # Independently reconstruct one line's exact Voigt contribution from diagnostics.
        single = self.render(rows[:1], info, config)
        line = single.line_diagnostics.iloc[0]
        expected = line.absorbed_area*voigt_profile(single.spectrum.wavelength-line.wavelength_nm,
                                                   line.instrument_sigma_nm, line.absorbed_fwhm_nm/2)
        np.testing.assert_allclose(single.spectrum.intensity, expected)

    def test_zero_path_and_density_have_exact_thin_limit(self):
        for change in ({'path_length_m': 0}, {'total_number_density_cm3': 0}):
            with self.subTest(change=change):
                rows, info, config = self.prepare(**change)
                out = self.render(rows, info, config)
                pd.testing.assert_frame_equal(out.spectrum, out.thin_spectrum)
                np.testing.assert_array_equal(out.line_diagnostics.SA, np.ones(len(rows)))
                # Density only determines opacity; NIST areas are never replaced/re-normalized.
                self.assertAlmostEqual(out.line_diagnostics.thin_area.sum(),
                                       self.table.drop(columns='wavelength').sum().sum())

    def test_band_split_preserves_lines_and_full_profiles(self):
        whole, info, config = self.prepare()
        bands = [(self.table.loc[self.table.wavelength < 285], self.payload),
                 (self.table.loc[self.table.wavelength >= 285], self.payload)]
        split, split_info = prepare_nist_absorption(bands, te=1, ne=1e17,
                         elements=['Mg'], percentages=[100], config=config)
        a, b = self.render(whole, info, config), self.render(split, split_info, config)
        self.assertEqual(len(split), len(whole))
        np.testing.assert_allclose(a.spectrum, b.spectrum, rtol=1e-14)
        bad = deepcopy(self.payload)
        bad['atoms']['Mg']['levels'][1][0] = 1
        with self.assertRaisesRegex(ValueError, 'Inconsistent NIST atomic'):
            prepare_nist_absorption([(self.table, self.payload), (self.table, bad)],
                te=1, ne=1e17, elements=['Mg'], percentages=[100], config=config)

    def test_path_and_density_strengthen_absorption(self):
        small = self.render(*self.prepare(path_length_m=.001, total_number_density_cm3=1e16))
        large = self.render(*self.prepare(path_length_m=.01, total_number_density_cm3=1e16))
        self.assertTrue((large.line_diagnostics.SA < small.line_diagnostics.SA).all())
        np.testing.assert_allclose(large.line_diagnostics.tau_center, 10*small.line_diagnostics.tau_center)
        self.assertTrue((large.line_diagnostics.absorbed_area < small.line_diagnostics.absorbed_area).all())


if __name__ == '__main__':
    unittest.main()
