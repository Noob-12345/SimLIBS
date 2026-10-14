"""nist_recon 移植的单测：解析、实际 R 提取、面积守恒、约定映射、逐离子一致性。"""
import math
import unittest

import numpy as np

from simlibs_ui.nist_recon import (
    Band, actual_resolution, ion_columns, line_strengths,
    merge_core_sticks, parse_nist_matrix, render_ion_sticks, render_nist_sticks,
)

STICKS_HTML = """
<script>
var dataSticksArray=[[{label:'Wavelength (nm)'},{label:'H I'},{label:'H II'}],
[656.28,100.0,20.0],[656.47,30.0,0.0],[486.13,50.0,5.0]];
var resolution=3000;
</script>
"""
DOPPLER_HTML = "<script>var dataDopplerArray=[[{label:'Wavelength (nm)'},{label:'Sum(calc)'}],[650.0,1.0],[650.2,2.0]];</script>"


class ParseTests(unittest.TestCase):
    def test_parse_sticks(self):
        sticks = parse_nist_matrix(STICKS_HTML, "dataSticksArray")
        self.assertEqual(list(sticks.columns), ["wavelength", "H I", "H II"])
        self.assertEqual(len(sticks), 3)
        self.assertAlmostEqual(sticks["H I"][0], 100.0)

    def test_parse_missing_variable(self):
        with self.assertRaises(ValueError):
            parse_nist_matrix(DOPPLER_HTML, "dataSticksArray")

    def test_actual_resolution(self):
        self.assertEqual(actual_resolution(STICKS_HTML), 3000.0)
        with self.assertRaises(ValueError):
            actual_resolution("<p>none</p>")

    def test_line_strengths_rejects_doppler(self):
        table = parse_nist_matrix(DOPPLER_HTML, "dataDopplerArray")
        with self.assertRaises(ValueError):
            line_strengths(table)


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.sticks = parse_nist_matrix(STICKS_HTML, "dataSticksArray")

    def test_area_conservation(self):
        grid = np.linspace(480.0, 660.0, 180001)
        spectrum = render_nist_sticks(self.sticks, grid, 3000.0)
        integrate = np.trapezoid if hasattr(np, 'trapezoid') else np.trapz
        area = float(integrate(spectrum["intensity"], spectrum["wavelength"]))
        expected = float((self.sticks["H I"] + self.sticks["H II"]).sum())
        self.assertAlmostEqual(area, expected, delta=expected * 1e-9)

    def test_nist_convention_fwhm(self):
        # w = λ/R 为 1/e 半宽 → FWHM = 2√ln2 · λ/R（只用 656.28 单线测量）
        lam, r = 656.28, 3000.0
        grid = np.linspace(lam - 1.0, lam + 1.0, 200001)
        spectrum = render_nist_sticks(
            self.sticks[(self.sticks["wavelength"] > 656.2) & (self.sticks["wavelength"] < 656.4)],
            grid, r)
        peak = spectrum["intensity"].max()
        half = spectrum[spectrum["intensity"] >= peak / 2.0]["wavelength"]
        fwhm = half.max() - half.min()
        self.assertAlmostEqual(fwhm, 2 * math.sqrt(math.log(2)) * lam / r, delta=1e-3)

    def test_physics_convention_mapping(self):
        # 物理约定 FWHM=λ/R → 等效 NIST R' = R·2√ln2
        lam, r_phys = 656.28, 3000.0
        r_equiv = r_phys * 2 * math.sqrt(math.log(2))
        grid = np.linspace(lam - 1.0, lam + 1.0, 200001)
        spectrum = render_nist_sticks(
            self.sticks[(self.sticks["wavelength"] > 656.2) & (self.sticks["wavelength"] < 656.4)],
            grid, r_equiv)
        peak = spectrum["intensity"].max()
        half = spectrum[spectrum["intensity"] >= peak / 2.0]["wavelength"]
        self.assertAlmostEqual(half.max() - half.min(), lam / r_phys, delta=1e-3)

    def test_ion_render_sums_to_total(self):
        grid = np.linspace(480.0, 660.0, 9001)
        total = render_nist_sticks(self.sticks, grid, 3000.0)["intensity"].to_numpy()
        ions = render_ion_sticks(self.sticks, grid, 3000.0)
        self.assertEqual(ion_columns(self.sticks), ["H I", "H II"])
        self.assertIn("Sum(calc)", ions.columns)
        np.testing.assert_allclose(ions["Sum(calc)"].to_numpy(), total, rtol=1e-12)

    def test_merge_band_boundary(self):
        b1, b2 = Band(400.0, 500.0), Band(500.0, 700.0)
        merged = merge_core_sticks([self.sticks, self.sticks], [b1, b2])
        # 486.13 归第一核心波段，656 两条归第二波段；每条线只出现一次
        self.assertEqual(sorted(merged["wavelength"].tolist()), [486.13, 656.28, 656.47])


if __name__ == "__main__":
    unittest.main()
