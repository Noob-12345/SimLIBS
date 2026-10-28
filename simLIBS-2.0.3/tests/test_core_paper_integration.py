"""Core API: NIST line strengths, per-line absorption and dynamic bypass."""

import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from simLIBS import SimulatedLIBS, simulation
from simLIBS.nist_self_absorption import MissingStarkDataError
from stark_fixtures import provider_response, missing_provider


NIST_HTML = (Path(__file__).parent/'fixtures'/'nist_mg_280_290.html').read_text(encoding='utf-8')


def nist_response():
    response = Mock(text=NIST_HTML)
    response.raise_for_status.return_value = None
    return response


class CorePaperIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertIn("self_absorption_config", inspect.signature(SimulatedLIBS).parameters,
                      "core is not connected to self absorption")

    def make_core(self, **changes):
        args = dict(Te=1, Ne=1e17, elements=["Mg"], percentages=[100],
                    low_w=280, upper_w=290, max_ion_charge=2,
                    self_absorption=True, self_absorption_config={"path_length_m": 0.001,
                    "total_number_density_cm3": 1e16, "wavelength_step_nm": 0.001})
        args.update(changes)
        with patch.object(simulation.requests, "get", return_value=nist_response()) as fetch, \
                patch('simLIBS.nist_stark.resolve_online', side_effect=provider_response), \
                patch.object(simulation.webdriver, "Chrome", side_effect=AssertionError("static must not open Chrome")):
            result = SimulatedLIBS(**args)
            fetch.assert_called_once()
            return result

    def test_enabled_path_fetches_all_nist_lines_and_preserves_references(self):
        libs = self.make_core()
        self.assertEqual(libs.self_absorption_metadata["model_version"], "nist-lines-self-absorption-1")
        self.assertEqual(len(libs.self_absorption_diagnostics), 20)
        self.assertEqual(len(libs.line_table), 20)
        self.assertAlmostEqual(libs.self_absorption_diagnostics.thin_area.sum(),
                               libs.line_table.drop(columns='wavelength').sum().sum())
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
        self.assertEqual(len(libs.get_interpolated_spectrum()), 5001)
        np.testing.assert_allclose(libs.raw_spectrum.wavelength, libs.unabsorbed_raw_spectrum.wavelength)
        self.assertEqual(len(libs.self_absorption_diagnostics), 20)

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

    def test_dynamic_ignores_self_absorption_switch_and_configuration(self):
        def browser_result(instance):
            instance.ion_spectra = pd.DataFrame({
                "Wavelength (nm)": [200., 201., 202.],
                "Fe I": [1., 8., 2.], "Sum(calc)": [1., 8., 2.]})
            instance.raw_spectrum = pd.DataFrame({
                "wavelength": [200., 201., 202.], "intensity": [1., 8., 2.]})
            instance.interpolated_spectrum = instance.raw_spectrum.copy()

        outputs = []
        for enabled in (False, True):
            with self.subTest(self_absorption=enabled), \
                    patch.object(simulation.webdriver, "Chrome") as chrome, \
                    patch.object(simulation, "ChromeDriverManager"), \
                    patch.object(simulation, "Service"), \
                    patch.object(SimulatedLIBS, "retrieve_data_dynamic", autospec=True,
                                 side_effect=browser_result) as fetch, \
                    patch.object(SimulatedLIBS, "_render_paper_model",
                                 side_effect=AssertionError("paper model used")), \
                    patch.object(simulation.requests, "get",
                                 side_effect=AssertionError("static path used")):
                libs = SimulatedLIBS(elements=["Fe"], percentages=[100],
                    low_w=200, upper_w=202, webscraping="dynamic",
                    self_absorption=enabled, optical_depth=1,
                    self_absorption_config={"invalid_config_key": True})
                fetch.assert_called_once_with(libs)
                chrome.return_value.quit.assert_called_once()
                self.assertFalse(libs.self_absorption)
                self.assertIsNone(libs.self_absorption_config)
                self.assertIsNone(libs.self_absorption_metadata)
                self.assertIsNone(libs.unabsorbed_raw_spectrum)
                np.testing.assert_array_equal(libs.get_ion_spectra()["Fe I"], [1, 8, 2])
                libs.interpolate(resolution=.5)
                outputs.append(libs.get_interpolated_spectrum().copy())
        pd.testing.assert_frame_equal(*outputs)

    def test_missing_stark_data_reports_all_missing_nist_transitions(self):
        with patch.object(simulation.requests, 'get', return_value=nist_response()) as fetch, \
                patch('simLIBS.nist_stark.resolve_online', side_effect=missing_provider):
            with self.assertRaises(MissingStarkDataError) as raised:
                SimulatedLIBS(elements=['Mg'], percentages=[100], low_w=280, upper_w=290,
                              self_absorption=True)
        fetch.assert_called_once()
        self.assertEqual(len(raised.exception.missing_lines), 20)
        self.assertTrue((raised.exception.missing_lines.element == 'Mg').all())

    def test_dataset_forwards_paper_configuration(self):
        composition = pd.DataFrame({"Mg": [100.], "name": ["sample"]})
        with patch.object(simulation.requests, "get", return_value=nist_response()), \
                patch('simLIBS.nist_stark.resolve_online', side_effect=provider_response), \
                patch.object(simulation.time, 'sleep'):
            a = SimulatedLIBS.create_dataset(composition, size=2, Te_min=1, Te_max=1, Ne_min=1e17, Ne_max=1e17,
                self_absorption=True, self_absorption_config={"path_length_m": 0, "wavelength_step_nm": 100})
            b = SimulatedLIBS.create_dataset(composition, size=2, Te_min=1, Te_max=1, Ne_min=1e17, Ne_max=1e17,
                self_absorption=True, self_absorption_config={"path_length_m": .01, "wavelength_step_nm": 100})
        cols = [str(v) for v in np.linspace(200, 1000, 9)]
        self.assertFalse(np.allclose(a[cols].to_numpy(dtype=float), b[cols].to_numpy(dtype=float)))
        self.assertTrue((b["name"] == "sample").all())


if __name__ == "__main__":
    unittest.main()
