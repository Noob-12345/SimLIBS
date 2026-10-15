"""Independent equation and spectrum checks for the paper's line model."""

import math
import unittest

import numpy as np
from scipy.constants import c, e, h, m_e

from simLIBS import self_absorption as model


MG_LINE = dict(element="Mg", charge=0, wavelength_nm=285.212, Aki_s=4.91e8,
               lower_eV=0.0, upper_eV=4.345, g_lower=1, g_upper=3,
               stark_width_nm=0.007, stark_reference_ne_cm3=1e16)
ATOMS = {"Mg": {"ionization_energies_eV": [7.646, 15.035], "levels": {
    "0": [dict(energy_eV=0, g=1, is_bound=True), dict(energy_eV=4.345, g=3, is_bound=True)],
    "1": [dict(energy_eV=0, g=2, is_bound=True), dict(energy_eV=4.433, g=4, is_bound=True)],
    "2": [dict(energy_eV=0, g=1, is_bound=True)],
}}}


class PaperModelTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(model, "simulate_paper_spectrum", None)),
                        "paper line-by-line model is not implemented yet")

    def config(self, **values):
        return model.PaperSelfAbsorptionConfig(**values)

    def run_line(self, **changes):
        values = dict(Te=1.0, Ne=1e17, elements=["Mg"], percentages=[100],
                      low_w=284.212, upper_w=286.212, resolution=1000, max_ion_charge=2)
        config = dict(path_length_m=0.001, total_number_density_cm3=1e16,
                      wavelength_step_nm=0.0002, line_data=[MG_LINE], atomic_data=ATOMS)
        config.update(changes.pop("config", {}))
        values.update(changes)
        return model.simulate_paper_spectrum(**values, config=self.config(**config))

    def test_equations_4_6_7_8_in_si_and_peak_normalization(self):
        cfg = self.config(path_length_m=0.01)
        row = model.paper_line_parameters(MG_LINE, Te=1, Ne=1e17,
                                         species_density_cm3=1e16, partition_function=2, config=cfg)
        wavelength = 285.212e-9
        q_m = 1e22 * 3 * wavelength**4 * 4.91e8 * 0.01 / (4 * math.pi**2 * c * 2)
        width_nm = 2 * 0.007 * (1e17 / 1e16)
        tau = q_m / (width_nm * 1e-9)
        sa = (1 - math.exp(-tau)) / tau
        self.assertAlmostEqual(row["q_m"] / q_m, 1, places=13)
        self.assertAlmostEqual(row["thin_fwhm_nm"], width_nm)
        self.assertAlmostEqual(row["tau_center"] / tau, 1, places=13)
        self.assertAlmostEqual(row["SA"] / sa, 1, places=13)
        self.assertAlmostEqual(row["absorbed_fwhm_nm"] / width_nm, sa**(-0.54))
        self.assertAlmostEqual(row["absorbed_peak"] / row["thin_peak"], sa)
        self.assertAlmostEqual(row["absorbed_area"] / row["thin_area"], sa**0.46)
        expected_area = h*c/wavelength / (4*math.pi) * 4.91e8 * 1e22 * 3/2 * math.exp(-4.345)
        self.assertAlmostEqual(row["thin_area"] / expected_area, 1, places=13)

    def test_finite_bound_partition_and_three_stage_saha(self):
        import copy
        atom = copy.deepcopy(ATOMS["Mg"])
        atom["levels"]["0"].append(dict(energy_eV=0, g=1e6, is_bound=False))
        result = model.saha_populations(atom, Te=1, Ne=1e17)
        partitions = np.array([1+3*math.exp(-4.345), 2+4*math.exp(-4.433), 1.0])
        prefactor = 2 * (2*math.pi*m_e*e/h**2)**1.5 / 1e23
        r1 = prefactor * partitions[1]/partitions[0] * math.exp(-7.646)
        r2 = prefactor * partitions[2]/partitions[1] * math.exp(-15.035)
        expected = np.array([1, r1, r1*r2]); expected /= expected.sum()
        np.testing.assert_allclose(result["partition_functions"], partitions, rtol=1e-13)
        np.testing.assert_allclose(result["fractions"], expected, rtol=1e-13)
        self.assertEqual(result["bound_level_counts"], [2, 2, 1])

    def test_missing_third_stage_is_not_invented(self):
        import copy
        atom = copy.deepcopy(ATOMS["Mg"]); del atom["levels"]["2"]
        with self.assertRaises(ValueError):
            model.saha_populations(atom, Te=1, Ne=1e17)

    def test_zero_path_is_exact_optically_thin_limit(self):
        result = self.run_line(config={"path_length_m": 0})
        np.testing.assert_array_equal(result.spectrum.intensity, result.thin_spectrum.intensity)
        self.assertEqual(result.line_diagnostics.iloc[0].SA, 1)
        self.assertEqual(result.line_diagnostics.iloc[0].tau_center, 0)

    def test_single_line_peak_and_measured_width_match_diagnostics(self):
        result = self.run_line()
        row = result.line_diagnostics.iloc[0]
        self.assertAlmostEqual(result.spectrum.intensity.max() / result.thin_spectrum.intensity.max(), row.SA, places=10)
        for frame, expected in ((result.spectrum, row.absorbed_fwhm_nm),
                                (result.thin_spectrum, row.thin_fwhm_nm)):
            x = frame.wavelength.to_numpy(); y = frame.intensity.to_numpy()
            center = int(y.argmax()); half = y[center]/2
            left = np.interp(half, y[:center+1], x[:center+1])
            right = np.interp(half, y[center:][::-1], x[center:][::-1])
            self.assertAlmostEqual((right-left)/expected, 1, places=4)

    def test_density_and_path_increase_tau_and_width(self):
        a = self.run_line()
        b = self.run_line(config={"path_length_m": 0.002})
        d = self.run_line(config={"total_number_density_cm3": 2e16})
        for result in (b, d):
            row = result.line_diagnostics.iloc[0]; base = a.line_diagnostics.iloc[0]
            self.assertAlmostEqual(row.tau_center/base.tau_center, 2)
            self.assertLess(row.SA, base.SA)
            self.assertGreater(row.absorbed_fwhm_nm, base.absorbed_fwhm_nm)

    def test_instrument_resolution_never_enters_opacity(self):
        a = self.run_line(resolution=1000, config={"instrument_broadening": True})
        b = self.run_line(resolution=2000, config={"instrument_broadening": True})
        np.testing.assert_array_equal(a.line_diagnostics.tau_center, b.line_diagnostics.tau_center)
        np.testing.assert_array_equal(a.line_diagnostics.absorbed_fwhm_nm, b.line_diagnostics.absorbed_fwhm_nm)
        self.assertFalse(np.allclose(a.spectrum.intensity, b.spectrum.intensity))

    def test_energy_and_photon_scale_differ_by_line_photon_energy(self):
        energy = self.run_line()
        photon = self.run_line(config={"intensity_scale": "photon"})
        expected = h*c/(MG_LINE["wavelength_nm"]*1e-9)
        np.testing.assert_allclose(energy.spectrum.intensity, photon.spectrum.intensity*expected, rtol=1e-13)

    def test_default_density_closes_electron_charge_balance(self):
        result = self.run_line(config={"total_number_density_cm3": None})
        self.assertAlmostEqual(result.metadata["charge_balance_ne_cm3"]/1e17, 1, places=13)
        self.assertEqual(result.metadata["density_mode"], "charge_balance")

    def test_real_builtin_data_and_components_are_traceable_and_additive(self):
        data = model.load_paper_data()
        self.assertEqual(len(data["lines"]), 31)
        for element in ("Mg", "Ca", "Zn"):
            for stage in ("0", "1", "2"):
                self.assertTrue(any(v["is_bound"] for v in data["elements"][element]["levels"][stage]))
        result = model.simulate_paper_spectrum(
            Te=1, Ne=1e17, elements=["Mg", "Ca"], percentages=[50, 50],
            low_w=275, upper_w=430, resolution=3000, max_ion_charge=2,
            config=self.config(wavelength_step_nm=0.01),
        )
        cols = [c for c in result.ion_spectrum if c not in ("Wavelength (nm)", "Sum(calc)")]
        np.testing.assert_allclose(result.ion_spectrum[cols].sum(axis=1), result.spectrum.intensity)
        self.assertEqual(len(result.line_diagnostics), 27)
        self.assertEqual(len(result.metadata["data_sha256"]), 64)

    def test_missing_stark_or_element_data_fails_instead_of_fallback(self):
        bad = dict(MG_LINE); del bad["stark_width_nm"]
        with self.assertRaises(ValueError):
            self.run_line(config={"line_data": [bad]})
        with self.assertRaises(ValueError):
            model.simulate_paper_spectrum(Te=1, Ne=1e17, elements=["Fe"], percentages=[100],
                                         low_w=248, upper_w=249, resolution=1000, max_ion_charge=2)

    def test_invalid_parameters_and_resource_limits(self):
        for values in ({"path_length_m": -1}, {"path_length_m": True},
                       {"wavelength_step_nm": 0}, {"instrument_broadening": 1},
                       {"intensity_scale": "unknown"}, {"total_number_density_cm3": float("inf")}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.config(**values)
        with self.assertRaises(ValueError):
            self.run_line(config={"wavelength_step_nm": 1e-12})

    def test_malformed_custom_rows_are_not_silently_dropped(self):
        for row in (None, {}, {"element": None}, {"element": "Mg"}):
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    self.run_line(config={"line_data": [MG_LINE, row]})

    def test_unrepresentable_grid_is_rejected(self):
        low = 285.0
        high = np.nextafter(low, math.inf)
        with self.assertRaises(ValueError):
            self.run_line(low_w=low, upper_w=high,
                          config={"wavelength_step_nm": (high-low)/4})

    def test_nonfinite_charge_balance_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_line(Te=1e100, config={"total_number_density_cm3": 1e308})


if __name__ == "__main__":
    unittest.main()
