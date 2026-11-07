"""Offline fallback contracts using the unedited official Si II HTML fixture."""
import copy
from pathlib import Path
import unittest

from stark_html_collect import parse_payload
from bs4 import BeautifulSoup


class HtmlCollectionTests(unittest.TestCase):
    def payload(self):
        html = (Path(__file__).parent / "fixtures/starkb_si_ii_6347.html").read_text(encoding="utf-8")
        return dict(format="starkb-html", pages=[dict(
            html=html, url="https://stark-b.obspm.fr/index.php/data/ion/14",
            dataset_id="official-fixture", method="SCP", ne=1e17)])

    def test_published_density_widths_and_source_are_retained(self):
        rows = parse_payload(self.payload(), element="Si", charge=1, ne=1e-300)
        self.assertEqual(len(rows), 1)
        self.assertEqual([s["fwhm_angstrom"] for s in rows[0]["samples"]], [2.74, 1.93, 1.44, 1.19])
        self.assertEqual(rows[0]["method"], "SCP")
        self.assertIn("1977", rows[0]["source"])
        self.assertTrue(all(s["ne"] == 1e17 for s in rows[0]["samples"]))
        self.assertEqual(parse_payload(self.payload(), element="Si", charge=1, ne=1e18), [])
        p = self.payload()
        p["pages"][0]["method"] = "SCP, Cowan code atomic data with specified ionization potentials"
        row = parse_payload(p, element="Si", charge=1, ne=1e-300)[0]
        self.assertEqual(row["method"], "SCP")
        self.assertIn("Cowan", row["method_label"])

    def test_duplicate_or_mismatched_density_or_foreign_source_is_rejected(self):
        for case in ("duplicate", "density", "source"):
            p = copy.deepcopy(self.payload())
            if case == "duplicate":
                p["pages"].append(copy.deepcopy(p["pages"][0]))
            elif case == "density":
                p["pages"][0]["ne"] = 1e18
            else:
                p["pages"][0]["url"] = "https://example.com/table"
            with self.subTest(case=case), self.assertRaises(ValueError):
                parse_payload(p, element="Si", charge=1, ne=1e-300)

    def test_empty_invalid_physical_values_and_conflicting_temperature_are_rejected(self):
        for case in ("empty", "temperature", "wavelength", "duplicate"):
            p = self.payload()
            soup = BeautifulSoup(p["pages"][0]["html"], "html.parser")
            body = soup.select_one("#shiftings table tbody")
            cells = body.select_one("tr").find_all("td")
            if case == "empty":
                body.clear()
            elif case == "temperature":
                cells[6].string = "0"
            elif case == "wavelength":
                for tr in body.select("tr"):
                    tr.find_all("td")[4].string = "0"
            else:
                body.append(copy.copy(body.select_one("tr")))
            p["pages"][0]["html"] = str(soup)
            with self.subTest(case=case), self.assertRaises(ValueError):
                parse_payload(p, element="Si", charge=1, ne=1e-300)

    def test_selector_completeness_rejects_missing_transitions_or_temperatures(self):
        p = self.payload()
        row = parse_payload(p, element="Si", charge=1, ne=1e-300)[0]
        p["pages"][0]["transition_selector_html"] = (
            '<select id="transition"><option value="1">' + row["lower_label"] + " -> " + row["upper_label"] +
            '</option></select>')
        p["pages"][0]["temperature_selector_html"] = '<select id="temperature">' + ''.join(
            f'<option value="{s["temperature_k"]}">{s["temperature_k"]}</option>' for s in row["samples"]) + '</select>'
        self.assertEqual(len(parse_payload(p, element="Si", charge=1, ne=1e-300)), 1)
        p["pages"][0]["temperature_selector_html"] = p["pages"][0]["temperature_selector_html"].replace(
            "</select>", '<option value="99999">99999</option></select>')
        with self.assertRaisesRegex(ValueError, "temperatures disagree"):
            parse_payload(p, element="Si", charge=1, ne=1e-300)


if __name__ == "__main__":
    unittest.main()
