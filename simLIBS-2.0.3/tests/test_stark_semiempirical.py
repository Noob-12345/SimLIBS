"""Independent equation, unit and domain checks for the 1980 MSE model."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import stark_semiempirical as mse
except ModuleNotFoundError:
    mse = None


class SemiempiricalTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(mse, 'The requested stark_semiempirical.py module is missing')

    def levels(self):
        return (mse.Level(3., 0, (mse.Perturber(2., 18.),)),
                mse.Level(3., 1, (mse.Perturber(2., 6.), mse.Perturber(2., 7.5))))

    def width(self, **overrides):
        lower, upper = self.levels()
        params = dict(wavelength_nm=500., temperature_k=10000., electron_density_cm3=1e17,
                      ion_charge=2, lower=lower, upper=upper)
        params.update(overrides)
        return mse.calculate_stark_width(**params)

    def test_independent_low_energy_benchmark(self):
        # Eq. (9): sums 5 and 6.5. Eq. (6): g_tilde = 0.9 - 1.1/3.
        # Weighted sum = 31.5*(0.9-1.1/3) + 11.5*0.2 = 19.1.
        # Independent SI evaluation of Eq. (7), with NO extra a0**2.
        out = self.width()
        self.assertAlmostEqual(out.weighted_sum_a0_sq, 19.1, places=12)
        self.assertAlmostEqual(out.fwhm_rad_s / 7.971838023651587e11, 1., places=12)
        self.assertAlmostEqual(out.fwhm_nm, 0.1058029807901368, places=13)
        self.assertEqual(len(out.contributions), 5)

    def test_density_and_wavelength_scaling_and_zero_density(self):
        base = self.width()
        self.assertAlmostEqual(self.width(electron_density_cm3=2e17).fwhm_nm, 2*base.fwhm_nm)
        self.assertAlmostEqual(self.width(wavelength_nm=1000.).fwhm_nm, 4*base.fwhm_nm)
        self.assertEqual(self.width(electron_density_cm3=0.).fwhm_nm, 0.)

    def test_units_and_hwhm(self):
        out = self.width()
        self.assertAlmostEqual(out.fwhm_angstrom, 10*out.fwhm_nm)
        self.assertAlmostEqual(out.hwhm_nm, out.fwhm_nm/2)
        converted = out.fwhm_rad_s*(500e-9)**2/(2*math.pi*299792458)*1e9
        self.assertAlmostEqual(converted, out.fwhm_nm, places=14)

    def test_low_temperature_inverse_square_root(self):
        # All channels remain at x<=2 only below about 30945 K.
        self.assertAlmostEqual(self.width(temperature_k=20000.).fwhm_nm, self.width().fwhm_nm/math.sqrt(2))

    def test_same_n_matrix_elements_and_sum(self):
        self.assertAlmostEqual(mse.same_n_matrix_element_sq(3., 0, 1, 2, phi=1.), 18.)
        self.assertAlmostEqual(mse.same_n_matrix_element_sq(3., 1, 0, 2, phi=1.), 6.)
        self.assertAlmostEqual(mse.same_n_matrix_element_sq(3., 1, 2, 2, phi=0.5), 1.875)
        self.assertAlmostEqual(mse.different_n_matrix_sum(3., 0, 2), 5.)
        self.assertAlmostEqual(mse.different_n_matrix_sum(3., 1, 2), 6.5)

    def test_effective_n_from_binding_energy(self):
        binding = 9*13.605693122994/9
        self.assertAlmostEqual(mse.effective_principal_quantum_number(binding, 2), 3.)

    def test_gaunt_table_knots_and_interpolation(self):
        for x, expected in [(0., .2), (2., .2), (3., .24), (5., .33),
                            (10., .56), (30., .98), (100., 1.33)]:
            with self.subTest(x=x):
                self.assertAlmostEqual(mse.tabulated_gaunt_factor(x), expected)
        self.assertAlmostEqual(mse.tabulated_gaunt_factor(math.sqrt(3*5)), (.24+.33)/2)
        with self.assertRaises(ValueError):
            mse.tabulated_gaunt_factor(100.01)

    def test_high_temperature_gbko_is_applied_to_each_contribution(self):
        # Every x is > 50 at this temperature for the synthetic levels.
        out = self.width(temperature_k=1e7)
        self.assertTrue(all(c.gaunt_regime == 'GBKO' for c in out.contributions))
        for c in out.contributions:
            expected = math.sqrt(3)/math.pi*(.5+math.log(
                2*3*8.617333262145e-5*1e7/(9*c.delta_e_ev)))
            self.assertAlmostEqual(c.gaunt_factor, expected, places=12)

    def test_high_temperature_boundary_and_modified_gaunt(self):
        self.assertAlmostEqual(mse.gaunt_factor(1., n_eff=3., ion_charge=2, same_n=True), .9-1.1/3)
        self.assertAlmostEqual(mse.gaunt_factor(1., n_eff=3., ion_charge=3, same_n=True), .9-1.1/4)
        self.assertNotEqual(mse.gaunt_factor(50., n_eff=3., ion_charge=2, same_n=True),
                            mse.gaunt_factor(50.00001, n_eff=3., ion_charge=2, same_n=True))

    def test_explicit_different_n_sum_and_complete_breakdown(self):
        lower, upper = self.levels()
        lower = mse.Level(lower.n_eff, lower.l, lower.same_n, different_n_sum_a0_sq=0.)
        out = self.width(lower=lower, upper=upper)
        self.assertAlmostEqual(out.weighted_sum_a0_sq, 18.1, places=12)
        self.assertTrue(math.isclose(sum(c.fwhm_rad_s for c in out.contributions),
                                     out.fwhm_rad_s, rel_tol=1e-14))

    def test_invalid_plasma_parameters(self):
        for kwargs in [dict(temperature_k=0), dict(temperature_k=float('nan')),
                       dict(electron_density_cm3=-1), dict(electron_density_cm3=float('inf')),
                       dict(wavelength_nm=-1), dict(ion_charge=1), dict(ion_charge=2.5),
                       dict(ion_charge=True)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.width(**kwargs)

    def test_missing_or_invalid_atomic_data(self):
        for factory in [lambda: mse.Level(3., 0, ()),
                        lambda: mse.Level(0., 0, (mse.Perturber(2., 1.),)),
                        lambda: mse.Level(3., -1, (mse.Perturber(2., 1.),)),
                        lambda: mse.Perturber(0., 1.), lambda: mse.Perturber(1., -1.),
                        lambda: mse.Perturber(float('nan'), 1.),
                        lambda: mse.same_n_matrix_element_sq(3., 0, 2, 2, phi=1.),
                        lambda: mse.same_n_matrix_element_sq(1., 0, 1, 2, phi=1.)]:
            with self.subTest(factory=factory), self.assertRaises(ValueError):
                factory()

    def test_numpy_integer_level_matches_python_float(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest('NumPy scalar compatibility only applies when NumPy is installed')
        normal = mse.Level(7., 0, (mse.Perturber(2., 18.),))
        compact = mse.Level(np.int8(7), np.int8(0), (mse.Perturber(np.float32(2.), np.int8(18)),))
        expected = self.width(temperature_k=100000., lower=normal, upper=normal)
        actual = self.width(temperature_k=100000., lower=compact, upper=compact)
        self.assertAlmostEqual(actual.fwhm_nm, expected.fwhm_nm, places=13)

    def test_zero_matrix_elements_do_not_evaluate_irrelevant_gaunt_factors(self):
        base = mse.Level(20., 0, (mse.Perturber(2., 18.),))
        zero = mse.Level(20., 0, (mse.Perturber(2., 18.), mse.Perturber(.025, 0.)))
        expected = self.width(lower=base, upper=base)
        actual = self.width(lower=zero, upper=zero)
        self.assertEqual(actual.fwhm_nm, expected.fwhm_nm)
        self.assertTrue(any(c.gaunt_regime == 'zero-matrix-element' for c in actual.contributions))

    def test_cli_json_round_trip(self):
        script = str(ROOT/'stark_semiempirical.py')
        example = subprocess.run([sys.executable, script, '--example'], check=True,
                                 text=True, capture_output=True)
        payload = json.loads(example.stdout)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'line.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            run = subprocess.run([sys.executable, script, '--input', str(path)], check=True,
                                 text=True, capture_output=True)
        out = json.loads(run.stdout)
        self.assertAlmostEqual(out['fwhm_nm'], self.width().fwhm_nm)
        self.assertEqual(out['ion_charge'], 2)
        self.assertIn('synthetic', payload['description'])
        bad = subprocess.run([sys.executable, script, '--input', 'missing-file.json'],
                             text=True, capture_output=True)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn('Traceback', bad.stderr)


if __name__ == '__main__':
    unittest.main()
