"""Official HTML fallback for species rejected by the VAMDC service.

Downloads every electron dataset at every *published* reference density.
No density interpolation is requested. Raw pages preserve all collider columns,
shifts, published fits, C and method labels. Importing this module is offline.
"""
import importlib.util
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import requests


BASE = "https://stark-b.obspm.fr"


def _parser():
    source = Path(__file__).resolve().parent / "simLIBS" / "stark_b.py"
    spec = importlib.util.spec_from_file_location("_stark_html_parser", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_payload(payload, *, element, charge, ne):
    if payload.get("format") != "starkb-html" or not payload.get("pages"):
        raise ValueError("Missing original STARK-B HTML tables")
    parser = _parser()
    rows = []
    seen = set()
    for page in payload["pages"]:
        if urlsplit(page["url"]).hostname != "stark-b.obspm.fr":
            raise ValueError("Unexpected STARK-B HTML source URL")
        identity = (page["dataset_id"], page["ne"])
        if identity in seen:
            raise ValueError("Duplicate STARK-B HTML dataset/density")
        seen.add(identity)
        reference_ne = float(page["ne"])
        if not math.isfinite(reference_ne) or reference_ne <= 0:
            raise ValueError("Invalid published HTML reference density")
        parsed = parser.parse_table(page["html"], element=element, charge=charge,
                                    dataset_id=page["dataset_id"], method=page["method"])
        method_label = page["method"]
        method_match = re.match(r"^\s*(SCP|MSE)(?:\s|,|$)", method_label)
        method = method_match.group(1) if method_match else "unreported"
        if not parsed:
            raise ValueError("Official HTML electron table is unexpectedly empty")
        transitions = page.get("transition_selector_html")
        temperatures = page.get("temperature_selector_html")
        if bool(transitions) != bool(temperatures):
            raise ValueError("Missing HTML completeness selector evidence")
        expected_temperatures = None
        if transitions:
            options = BeautifulSoup(transitions, "html.parser").select("#transition option")
            expected = {" ".join(o.get_text(" ", strip=True).split()) for o in options
                        if o.get("value") not in (None, "-1", "all")}
            actual = {r["lower_label"] + " -> " + r["upper_label"] for r in parsed}
            if not expected or actual != expected or len(parsed) != len(expected):
                raise ValueError("HTML transitions disagree with the published selector")
            expected_temperatures = {float(o["value"]) for o in
                BeautifulSoup(temperatures, "html.parser").select("#temperature option")
                if o.get("value") not in (None, "", "all", "-1")}
            if not expected_temperatures:
                raise ValueError("HTML temperature selector is empty")
        for row in parsed:
            row["method"] = method
            row["method_label"] = method_label
            wavelength = row["calculated_wavelength_angstrom"]
            if wavelength is None or not math.isfinite(wavelength) or wavelength <= 0:
                raise ValueError("HTML wavelength must be finite and positive")
            seen_temperatures = set()
            row["source_url"] = page["url"]
            row["source_format"] = "html"
            row["metadata"] = {"reference_ne_cm3": reference_ne}
            for sample in row["samples"]:
                temperature = sample["temperature_k"]
                if temperature is None or not math.isfinite(temperature) or temperature <= 0:
                    raise ValueError("HTML temperature must be finite and positive")
                if temperature in seen_temperatures:
                    raise ValueError("Duplicate HTML temperature sample")
                seen_temperatures.add(temperature)
                printed = sample["ne"]
                if printed is None or printed <= 0:
                    raise ValueError("Invalid density in STARK-B HTML table")
                rounding = .5 * 10 ** (math.floor(math.log10(printed)) - 3)
                if abs(printed - reference_ne) > rounding * (1 + 1e-12):
                    raise ValueError("HTML table density differs from published selector")
                sample["printed_ne_cm3"] = printed
                sample["ne"] = reference_ne
                width = sample["fwhm_angstrom"]
                if width is None or width <= 0:
                    sample["flag"] = "; ".join(filter(None, (sample["flag"], "nonpositive or missing source electron width")))
            if expected_temperatures is not None and seen_temperatures != expected_temperatures:
                raise ValueError("HTML temperatures disagree with the published selector")
            if reference_ne >= ne:
                rows.append(row)
    return rows


def fetch_species(element, charge, *, limiter):
    parser = _parser()
    pages = []
    with requests.Session() as session:
        def request(method, url, **kwargs):
            limiter.wait()
            print("STARK-B HTML requesting: " + url + " " + str(kwargs.get("data", "")), flush=True)
            response = session.request(method, url, timeout=(10, 60), **kwargs)
            response.raise_for_status()
            if len(response.content) > 20 * 1024 * 1024:
                raise ValueError("STARK-B HTML response exceeds 20 MiB")
            return response.text

        def post(action, **params):
            return request("POST", BASE + "/index.php",
                           data=dict(module="stark_b", action=action, **params))

        listing = post("periodictable:datasets", element=element)
        roman = parser._roman(charge + 1)
        links = [a for a in BeautifulSoup(listing, "html.parser").select("a[href]")
                 if a.get_text(" ", strip=True) == element + " " + roman]
        if len(links) != 1:
            raise ValueError("Missing or ambiguous official HTML species")
        url = BASE + links[0]["href"]
        ion = request("GET", url)
        options = BeautifulSoup(ion, "html.parser").select("#dataset option")
        for option in options:
            label = option.get_text(" ", strip=True)
            if option.get("value") == "-1" or "electron" not in label.lower():
                continue
            identifier = option["value"]
            method = label.split("method :")[-1].strip() if "method :" in label else "unreported"
            density_html = post("querypage:densities", datasetId=identifier)
            densities = [float(o["value"]) for o in BeautifulSoup(density_html, "html.parser").select("#density option")
                         if o.get("value") not in (None, "-1")]
            if not densities:
                raise ValueError("Official HTML dataset lacks published densities")
            for density in densities:
                transition_selector_html = post("querypage:transitions", density=f"{density:.12g}")
                temperature_selector_html = post("querypage:temperatures", transition="all")
                html = post("querypage:query", queryType="density", temperature="all", format="html")
                pages.append(dict(html=html, url=url, dataset_id=identifier, method=method, ne=density,
                                  transition_selector_html=transition_selector_html,
                                  temperature_selector_html=temperature_selector_html))
    payload = dict(format="starkb-html", element=element, charge=charge,
                   requested_ne_cm3=1e-300, status="ok", pages=pages)
    parse_payload(payload, element=element, charge=charge, ne=1e-300)
    return payload
