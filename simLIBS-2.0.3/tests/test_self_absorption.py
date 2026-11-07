"""Self-absorption math and original-core integration, using offline spectra."""

import importlib
import importlib.util
import inspect
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from simLIBS import SimulatedLIBS
from simLIBS import simulation


def load_static_fixture(instance):
    instance.raw_spectrum = pd.DataFrame(
        {"wavelength": [200.0, 201.0, 202.0], "intensity": [1.0, 8.0, 2.0]}
    )


def load_dynamic_fixture(instance):
    instance.ion_spectra = pd.DataFrame({
        "Wavelength (nm)": [200.0, 201.0, 202.0],
        "Fe I": [1.0, 3.0, 2.0], "Fe II": [0.0, 5.0, 0.0],
        "Sum(calc)": [1.0, 8.0, 2.0],
    })
    instance.raw_spectrum = instance.ion_spectra[
        ["Wavelength (nm)", "Sum(calc)"]
    ].rename(columns={"Wavelength (nm)": "wavelength", "Sum(calc)": "intensity"})
    instance.interpolated_spectrum = instance.raw_spectrum.copy()


class SlabModelTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("simLIBS.self_absorption"),
            "the core does not yet provide a self_absorption module",
        )
        self.model = importlib.import_module("simLIBS.self_absorption")

    def test_matches_analytic_uniform_slab_solution(self):
        tau = np.array([0.0, math.log(2.0), 1.0, 100.0])
        expected = [1.0, 0.5 / math.log(2.0), 1.0 - math.exp(-1.0), 0.01]
        np.testing.assert_allclose(self.model.slab_attenuation_factor(tau), expected, rtol=1e-14)

    def test_thin_limit_is_stable(self):
        tau = np.array([0.0, 1e-14, 1e-10])
        expected = 1.0 - tau / 2.0 + tau ** 2 / 6.0
        np.testing.assert_allclose(self.model.slab_attenuation_factor(tau), expected, atol=1e-16)

    def test_factors_are_bounded_and_decrease_with_opacity(self):
        factors = self.model.slab_attenuation_factor(np.logspace(-12, 12, 100))
        self.assertTrue(np.all((factors > 0) & (factors <= 1)))
        self.assertTrue(np.all(np.diff(factors) <= 0))

    def test_rejects_invalid_optical_depth(self):
        invalid = (None, True, [0, False], -1, float("nan"), float("inf"),
                   [0, -1], [[1, 2]], 1 + 2j, "invalid")
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.model.slab_attenuation_factor(value)

    def test_frame_processing_preserves_input_and_intensity_scale(self):
        frame = pd.DataFrame({"wavelength": [200.0, 201.0], "intensity": [2.0, 10.0]})
        original = frame.copy(deep=True)
        corrected = self.model.attenuate_spectrum(frame, [0.0, 1.0])
        pd.testing.assert_frame_equal(frame, original)
        np.testing.assert_allclose(corrected.intensity, [2, 10 * (1 - math.exp(-1))])
        scaled = frame.copy()
        scaled.intensity *= 3
        np.testing.assert_allclose(
            self.model.attenuate_spectrum(scaled, [0, 1]).intensity,
            corrected.intensity * 3,
        )

    def test_frame_processing_rejects_mismatched_depth_and_invalid_spectrum(self):
        frame = pd.DataFrame({"wavelength": [200.0, 201.0], "intensity": [2.0, 10.0]})
        with self.assertRaises(ValueError):
            self.model.attenuate_spectrum(frame, [1])
        for column, value in (("wavelength", 0), ("intensity", -1),
                              ("intensity", float("inf"))):
            invalid = frame.copy()
            invalid.loc[0, column] = value
            with self.subTest(column=column, value=value):
                with self.assertRaises(ValueError):
                    self.model.attenuate_spectrum(invalid, 1)

    def test_complex_spectral_values_are_rejected_without_discarding_imaginary_part(self):
        for column in ("wavelength", "intensity"):
            invalid = pd.DataFrame({"wavelength": [200.0, 201.0], "intensity": [2.0, 10.0]})
            invalid[column] = invalid[column].astype(complex) + 1j
            with self.subTest(column=column):
                with self.assertRaises(ValueError):
                    self.model.attenuate_spectrum(invalid, 1)

    def test_numpy_complex_values_in_object_columns_are_also_rejected(self):
        for column in ("wavelength", "intensity"):
            for dtype in (np.complex64, np.complex128):
                invalid = pd.DataFrame({"wavelength": [200.0, 201.0], "intensity": [2.0, 10.0]})
                invalid[column] = pd.Series([dtype(200 + 1j), dtype(201)], dtype=object)
                with self.subTest(column=column, dtype=dtype):
                    with self.assertRaises(ValueError):
                        self.model.attenuate_spectrum(invalid, 1)



if __name__ == "__main__":
    unittest.main()
