"""Original SimulatedLIBS API connected to the offline paper model."""

import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from simLIBS import SimulatedLIBS, simulation


class CorePaperIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIn("self_absorption_config", inspect.signature(SimulatedLIBS).parameters,
                      "original core is not connected to the paper model")

    def make_core(self, **changes):
        args = dict(Te=1, Ne=1e17, elements=["Mg"], percentages=[100],
                    low_w=285.012, upper_w=285.412, max_ion_charge=2,
                    self_absorption=True, self_absorption_config={"path_length_m": 0.001,
                    "total_number_density_cm3": 1e16, "wavelength_step_nm": 0.001})
        args.update(changes)
        with patch.object(simulation.requests, "get", side_effect=AssertionError("paper path must stay offline")), \
                patch.object(simulation.webdriver, "Chrome", side_effect=AssertionError("paper path must not open Chrome")):
            return SimulatedLIBS(**args)

    def test_enabled_path_is_offline_and_preserves_three_references(self):
        libs = self.make_core()
        self.assertEqual(libs.self_absorption_metadata["model_version"], "john-anoop-2023-lines-1")
        self.assertEqual(len(libs.self_absorption_diagnostics), 13)
        self.assertTrue((libs.self_absorption_diagnostics.absorbed_fwhm_nm >=
                         libs.self_absorption_diagnostics.thin_fwhm_nm).all())
        self.assertGreater(libs.self_absorption_diagnostics.SA.nunique(), 1)
        self.assertIsNotNone(libs.unabsorbed_raw_spectrum)
        self.assertIsNotNone(libs.unabsorbed_interpolated_spectrum)
        self.assertIsNotNone(libs.unabsorbed_ion_spectra)
        ion = libs.get_ion_spectra()
        np.testing.assert_allclose(ion["Sum(calc)"], libs.get_interpolated_spectrum().intensity)

    def test_zero_path_identity_and_regridding_recalculate_profiles(self):
        libs = self.make_core(self_absorption_config={"path_length_m": 0, "wavelength_step_nm": .001})
        pd.testing.assert_frame_equal(libs.raw_spectrum, libs.unabsorbed_raw_spectrum)
        before = libs.get_interpolated_spectrum().copy()
        libs.interpolate(resolution=.001)
        pd.testing.assert_frame_equal(libs.get_interpolated_spectrum(), before)
        libs.interpolate(resolution=.002)
        self.assertEqual(len(libs.get_interpolated_spectrum()), 201)
        np.testing.assert_allclose(libs.raw_spectrum.wavelength, libs.unabsorbed_raw_spectrum.wavelength)
        self.assertEqual(len(libs.self_absorption_diagnostics), 13)

    def test_legacy_manual_tau_is_rejected_when_enabling_paper_model(self):
        with self.assertRaisesRegex(ValueError, "optical_depth"):
            self.make_core(optical_depth=1)

    def test_disabled_path_preserves_original_nist_results(self):
        def fixture(instance):
            instance.raw_spectrum = pd.DataFrame({"wavelength": [200., 201., 202.], "intensity": [1., 8., 2.]})
        with patch.object(SimulatedLIBS, "retrieve_data_static", fixture) as fetch:
            libs = SimulatedLIBS(elements=["Fe"], percentages=[100], low_w=200, upper_w=202)
        self.assertFalse(libs.self_absorption)
        np.testing.assert_array_equal(libs.raw_spectrum.intensity, [1, 8, 2])
        self.assertIsNone(libs.unabsorbed_raw_spectrum)

    def test_config_is_snapshotted_and_csv_contains_current_model_output(self):
        config = {"path_length_m": .001, "wavelength_step_nm": .001}
        libs = self.make_core(self_absorption_config=config)
        config["path_length_m"] = 100
        libs.interpolate(resolution=.002)
        self.assertEqual(libs.self_absorption_metadata["parameters"]["path_length_m"], .001)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"paper.csv"; libs.save_to_csv(str(path))
            frame = pd.read_csv(path)
        np.testing.assert_allclose(frame.intensity, libs.interpolated_spectrum.intensity)

    def test_missing_stark_data_never_falls_back_to_nist(self):
        with self.assertRaisesRegex(ValueError, "Stark"):
            self.make_core(elements=["Fe"])

    def test_dataset_forwards_paper_configuration(self):
        composition = pd.DataFrame({"Mg": [100.], "name": ["sample"]})
        with patch.object(simulation.requests, "get", side_effect=AssertionError("network used")):
            a = SimulatedLIBS.create_dataset(composition, size=2, Te_min=1, Te_max=1, Ne_min=1e17, Ne_max=1e17,
                self_absorption=True, self_absorption_config={"path_length_m": 0, "wavelength_step_nm": 100})
            b = SimulatedLIBS.create_dataset(composition, size=2, Te_min=1, Te_max=1, Ne_min=1e17, Ne_max=1e17,
                self_absorption=True, self_absorption_config={"path_length_m": .01, "wavelength_step_nm": 100})
        cols = [str(v) for v in np.linspace(200, 1000, 9)]
        self.assertFalse(np.allclose(a[cols].to_numpy(dtype=float), b[cols].to_numpy(dtype=float)))
        self.assertTrue((b["name"] == "sample").all())


if __name__ == "__main__":
    unittest.main()
