import sys
import time
from typing import List

from bs4 import BeautifulSoup
import requests
import re
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import io
import random
import os
from scipy.interpolate import CubicSpline
from concurrent.futures import ThreadPoolExecutor
import math
from copy import deepcopy
from dataclasses import replace
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import urllib3

from .nist_self_absorption import (NISTSelfAbsorptionConfig, parse_atomic_payload,
                                   prepare_nist_absorption, render_nist_absorption)
from .nist_lines import bands_for, parse_sticks, render_sticks, wavelength_grid

urllib3.disable_warnings()


class CompositionError(Exception):
    pass


def validate_simulated_libs(
    Te: float,
    Ne: float,
    elements: List[str],
    percentages: List[float],
    low_w: int,
    upper_w: int,
    max_ion_charge: int,
):
    """
    Validates the input parameters for simLIBS.

    Raises:
        CompositionError: If the sum of percentages exceeds 100.
        ValueError: If any parameter has an invalid value (negative, wrong order).
    """
    if sum(percentages) > 100:
        raise CompositionError("Sum of element percentages cannot exceed 100%")
    if (
        any(value < 0 for value in [Te, Ne, max_ion_charge])
        or low_w > upper_w
        or len(elements) != len(percentages)
    ):
        raise ValueError(
            "Invalid parameters: negative values, wrong wavelength order, or element/percentage mismatch."
        )


class SimulatedLIBS(object):

    def __init__(
        self,
        Te: float = 1.0,
        Ne: float = 10**17,
        elements: list[str] = None,
        percentages: list[float] = None,
        resolution: int = 1000,
        low_w: int = 200,
        upper_w: int = 1000,
        max_ion_charge: int = 3,
        webscraping: str = "static",
        headless: bool = True,
        keep_browser_open: bool = False,
        detach_browser: bool = False,
        self_absorption: bool = False,
        optical_depth=None,
        self_absorption_config=None,
    ):
        """

        Parameters
        ----------
        Te : float
             Electron temperature Te [eV]
        Ne: float
            Electron density Ne [cm^-3]
        elements: list[str]
            List of elements
        percentages: list[percentages]
            List of element percentages
        resolution: int
            Resoultion of spectrometer
        low_w: int
            Lower wavelength [nm]
        upper_w: int
            Upper wavelength [nm]
        max_ion_charge: int
            Maximal ion charge
        webscraping : str
            Type of webscraping: 'static' or 'dynamic'
        headless : bool
            Run Chrome in headless mode when using dynamic scraping
        keep_browser_open : bool
            Keep browser session open after dynamic scraping (useful for debugging)
        detach_browser : bool
            Detach Chrome from driver so browser can stay open after script exits
        self_absorption : bool
             Apply per-line self absorption to the NIST line strengths in static mode
             (default False). Ignored in dynamic mode, including its configuration.
        optical_depth : deprecated
             Manual tau is no longer accepted when enabling the paper model.
        self_absorption_config : dict or NISTSelfAbsorptionConfig
             Physical/data settings, including path_length_m, optional total density,
             wavelength_step_nm, instrument_broadening and per-transition stark_data.
             NIST supplies transitions and levels; missing Stark coefficients raise
             MissingStarkDataError with a missing_lines DataFrame.

        """

        if type(self_absorption) is not bool:
            raise ValueError("self_absorption must be a boolean")
        self.self_absorption = webscraping == "static" and self_absorption
        if self.self_absorption and optical_depth is not None:
            raise ValueError("manual optical_depth has been replaced by the paper model; use self_absorption_config")
        self.optical_depth = None
        self.self_absorption_config = None
        self.self_absorption_metadata = None
        self._paper_request = None
        self._nist_bands = []
        self._absorption_lines = None
        self._absorption_metadata = None
        self.unabsorbed_raw_spectrum = None
        self.unabsorbed_interpolated_spectrum = None
        self.unabsorbed_ion_spectra = None
        self.self_absorption_diagnostics = None

        validate_simulated_libs(
            Te, Ne, elements, percentages, low_w, upper_w, max_ion_charge
        )

        self.Te = Te
        self._static_ne = Ne
        self.Ne = round(Ne, 3 - int(math.floor(math.log10(abs(Ne)))) - 1)
        self.Ne = re.sub(r"\+", "", str(self.Ne))

        self.elements = elements
        self.percentages = percentages
        self.resolution = resolution
        self.low_w = low_w
        self.upper_w = upper_w
        self.max_ion_charge = max_ion_charge

        self.raw_spectrum = pd.DataFrame({"wavelength": [], "intensity": []})
        self.interpolated_spectrum = pd.DataFrame({"wavelength": [], "intensity": []})
        self.webscraping = webscraping
        self.line_table = None

        if self.self_absorption:
            if isinstance(self_absorption_config, NISTSelfAbsorptionConfig):
                config = self_absorption_config
            elif self_absorption_config is None or isinstance(self_absorption_config, dict):
                try:
                    config = NISTSelfAbsorptionConfig(**(self_absorption_config or {}))
                except TypeError as error:
                    raise ValueError("invalid self_absorption_config: {}".format(error)) from None
            else:
                raise ValueError("self_absorption_config must be a dictionary or NISTSelfAbsorptionConfig; "
                                 "the offline PaperSelfAbsorptionConfig belongs to simulate_paper_spectrum")
            self.self_absorption_config = deepcopy(config)
            self._paper_request = dict(Te=Te, Ne=Ne, elements=tuple(elements), percentages=tuple(percentages),
                                       low_w=low_w, upper_w=upper_w, resolution=resolution, max_ion_charge=max_ion_charge)

        match webscraping:
            case "static":
                # 全部谱线的获取：自吸收开关不再改变谱线来源，始终先请求 NIST。
                self.retrieve_data_static()
                if self.self_absorption:
                    self._absorption_lines, self._absorption_metadata = prepare_nist_absorption(
                        self._nist_bands, te=Te, ne=Ne, elements=elements, percentages=percentages,
                        config=self.self_absorption_config)
                    self._render_paper_model()
                else:
                    self.interpolated_spectrum = self.raw_spectrum.copy(deep=True)
            case "dynamic":
                self.ion_spectra = None
                options = Options()
                options.add_argument("--disable-notifications")
                options.headless = headless
                if detach_browser:
                    options.add_experimental_option("detach", True)

                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                try:
                    self.retrieve_data_dynamic()
                finally:
                    if not keep_browser_open:
                        self.driver.quit()

    def _render_paper_model(self, step=None):
        """Retained internal name: render cached NIST transitions with self absorption."""
        config = self.self_absorption_config
        if step is not None:
            config = replace(config, wavelength_step_nm=step)
        request = self._paper_request
        result = render_nist_absorption(
            self._absorption_lines, self._absorption_metadata,
            te=request['Te'], ne=request['Ne'], low=request['low_w'], high=request['upper_w'],
            resolution=request['resolution'], config=config)
        self.raw_spectrum = result.spectrum.copy(deep=True)
        self.interpolated_spectrum = result.spectrum.copy(deep=True)
        self.ion_spectra = result.ion_spectrum.copy(deep=True)
        self.unabsorbed_raw_spectrum = result.thin_spectrum.copy(deep=True)
        self.unabsorbed_interpolated_spectrum = result.thin_spectrum.copy(deep=True)
        self.unabsorbed_ion_spectra = result.thin_ion_spectrum.copy(deep=True)
        self.self_absorption_diagnostics = result.line_diagnostics.copy(deep=True)
        self.self_absorption_metadata = deepcopy(result.metadata)

    def __repr__(self):
        return f"simLIBS(Te={self.Te:.2f} eV, Ne={self.Ne:.3e} cm^-3, elements={', '.join(self.elements)}, percentages={', '.join([str(p) for p in self.percentages])}, resolution={self.resolution}, low_w={self.low_w}, upper_w={self.upper_w}, max_ion_charge={self.max_ion_charge})"

    def __str__(self):
        return f"Te: {self.Te:.2f} eV, Ne: {self.Ne:.3e} cm^-3, elements: {', '.join(self.elements)}, percentages: {', '.join([str(p) for p in self.percentages])}"

    def get_site(self, low_w=None, upper_w=None, min_rel_int=None):
        """

        Returns
        -------

        """
        if min_rel_int is None:
            min_rel_int = 0 if self.webscraping == "static" else 0.001
        composition = ""
        spectrum = ""

        for i in range(len(self.elements)):
            if i > 0:
                composition += "3B"
                spectrum += "2C"
            composition += str(self.elements[i])
            composition += "%3A"
            composition += str(self.percentages[i])

            spectrum += str(self.elements[i])
            spectrum += "0-" + str(self.max_ion_charge)

            if i < len(self.elements) - 1:
                composition += "%"
                spectrum += "%"
        site = (
            "https://physics.nist.gov/cgi-bin/ASD/lines1.pl?composition={}"
            "&spectra={}"
            "&low_w={}&limits_type=0&upp_w={}"
            "&show_av=3&unit=1"
            "&resolution={}"
            "&temp={}"
            "&eden={}"
            "&maxcharge={}"
            "&min_rel_int={}"
            "&int_scale=2"
            "&libs=1"
        )
        site = site.format(
            composition,
            spectrum,
            self.low_w if low_w is None else low_w,
            self.upper_w if upper_w is None else upper_w,
            self.resolution,
            self.Te,
            format(self._static_ne, ".15g").replace("+", "%2B") if self.webscraping == "static" else self.Ne,
            self.max_ion_charge,
            min_rel_int,
        )

        return site

    def retrieve_data_dynamic(self):
        """

        Returns
        -------

        """
        site = self.get_site()
        self.driver.get(site)
        resolution_input = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located(
                (By.XPATH, "/html/body/div/div[1]/div[1]/form/div[3]/div/input")
            )
        )
        resolution_input.clear()
        resolution_input.send_keys(str(self.resolution))

        button_recalculate = WebDriverWait(self.driver, 2).until(
            EC.presence_of_element_located(
                (By.XPATH, "/html/body/div/div[1]/div[1]/form/button")
            )
        )
        button_recalculate.click()

        button_csv = WebDriverWait(self.driver, 2).until(
            EC.presence_of_element_located(
                (By.XPATH, "/html/body/div/div[2]/button[2]")
            )
        )
        button_csv.click()

        self.driver.switch_to.window((self.driver.window_handles[1]))

        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        self.ion_spectra = pd.read_csv(io.StringIO(soup.pre.text), sep=",").fillna(0)
        self.raw_spectrum["wavelength"] = self.ion_spectra["Wavelength (nm)"]
        self.raw_spectrum["intensity"] = self.ion_spectra["Sum(calc)"]

        self.interpolated_spectrum["wavelength"] = self.ion_spectra["Wavelength (nm)"]
        self.interpolated_spectrum["intensity"] = self.ion_spectra["Sum(calc)"]

    def retrieve_data_static(self):
        """Fetch calculated sticks in 500 nm bands, then broaden locally once."""
        grid = wavelength_grid(self.low_w, self.upper_w, 0.005)
        if not np.isfinite(self.resolution) or self.resolution <= 0:
            raise ValueError("Spectrometer resolution must be finite and positive")
        bands = list(bands_for(self.low_w, self.upper_w))
        tables = []
        self._nist_bands = []
        for index, (low, high, request_low, request_high) in enumerate(bands):
            site = self.get_site(request_low, request_high, min_rel_int=0)
            for attempt in range(3):
                try:
                    response = requests.get(site, timeout=90)
                    response.raise_for_status()
                    table = parse_sticks(response.text)
                    payload = parse_atomic_payload(response.text) if self.self_absorption else None
                    break
                except (requests.RequestException, ValueError):
                    if attempt == 2:
                        raise
                    time.sleep(1)
            wave = table["wavelength"]
            upper = wave <= high if index == len(bands)-1 else wave < high
            core_table = table.loc[(wave >= low) & upper].copy()
            tables.append(core_table)
            if payload is not None:
                self._nist_bands.append((core_table, payload))
            if index < len(bands)-1:
                time.sleep(3)
        # Assign overlap lines to one core band without rounding/deduplicating
        # distinct transitions at the same wavelength. Broaden after merging.
        self.line_table = pd.concat(tables, ignore_index=True).fillna(0.0)
        self.line_table = self.line_table.sort_values("wavelength").reset_index(drop=True)
        self.raw_spectrum = render_sticks(self.line_table, grid, self.resolution)

    def retrieve_spectrum_from_html(self, html_data: str):
        """Load calculated sticks from a supplied NIST HTML response."""
        self.line_table = parse_sticks(html_data)
        grid = wavelength_grid(self.low_w, self.upper_w, 0.005)
        self.raw_spectrum = render_sticks(self.line_table, grid, self.resolution)

    def interpolate(self, resolution: float = 0.005):
        """
        resolution here is the sampling step in nm, not spectrometer R.
        Static paths evaluate line profiles directly on the new grid;
        spectra without a line table retain the legacy CubicSpline behavior.
        """
        if self.self_absorption:
            self._render_paper_model(step=resolution)
            return
        if self.webscraping == "static" and self.line_table is not None:
            grid = wavelength_grid(self.low_w, self.upper_w, resolution)
            self.interpolated_spectrum = render_sticks(self.line_table, grid, self.resolution)
            return
        source = self.raw_spectrum
        cs = CubicSpline(
            source["wavelength"],
            source["intensity"],
            bc_type="natural",
        )
        x = np.arange(self.low_w, self.upper_w, resolution)
        y = np.clip(cs(x), 0, np.inf)

        interpolated = pd.DataFrame({"wavelength": np.round(x, 8), "intensity": np.round(y, 8)})
        self.interpolated_spectrum = interpolated

    def plot(
        self,
        color=(random.random(), random.random(), random.random()),
        title="Simulated LIBS",
    ):
        plt.plot(
            self.interpolated_spectrum["wavelength"],
            self.interpolated_spectrum["intensity"],
            label=str(self.elements) + str(self.percentages),
            color=color,
        )
        plt.grid()
        plt.title(title)
        plt.xlabel(r"$\lambda$ [nm]")
        plt.ylabel("Line Intensity [a.u.]")

    def plot_ion_spectra(self):
        self.ion_spectra.drop(["Sum(calc)"], axis=1).plot(
            x="Wavelength (nm)",
            xlabel=r"$\lambda$ [nm]",
            ylabel="Line Intensity [a.u.]",
            title="Ion spectra",
            grid=True,
        )

    def get_interpolated_spectrum(self):
        return self.interpolated_spectrum

    def get_raw_spectrum(self):
        return self.raw_spectrum

    def get_ion_spectra(self):

        if (self.self_absorption or self.webscraping == "dynamic") and self.ion_spectra is not None:
            return self.ion_spectra
        else:
            raise ValueError(
                "Data retrieval requires webscraping method set to 'dynamic' and successful data acquisition."
            )

    def save_to_csv(self, filepath: str):
        self.interpolated_spectrum.to_csv(path_or_buf=filepath, index=False)

    @staticmethod
    def worker(
        input_df: pd.DataFrame,
        Te_min: float,
        Te_max: float,
        Ne_min: float,
        Ne_max: float,
        webscraping: str,
        self_absorption: bool = False,
        optical_depth=None,
        self_absorption_config=None,
    ):
        seed = random.randrange(len(input_df))
        percentages = input_df.iloc[seed].values[:-1]
        elements = input_df.iloc[seed].keys().values[:-1]
        name = input_df.iloc[seed]["name"]
        Te = random.uniform(Te_min, Te_max)
        Ne = random.uniform(Ne_min, Ne_max)
        fun = SimulatedLIBS(
            Te=Te,
            Ne=Ne,
            elements=elements,
            percentages=percentages,
            webscraping=webscraping,
            self_absorption=self_absorption,
            optical_depth=optical_depth,
            self_absorption_config=self_absorption_config,
        ).get_interpolated_spectrum()

        return {
            "spectrum": fun,
            "composition": pd.DataFrame(
                {"elements": elements, "percentages": percentages}
            ),
            "name": name,
            "Te[eV]": Te,
            "Ne[cm^-3]": Ne,
        }

    @staticmethod
    def create_dataset(
        input_composition_df: pd.DataFrame,
        size: int = 10,
        Te_min: float = 1.0,
        Te_max: float = 2.0,
        Ne_min: float = 10**17,
        Ne_max: float = 10**18,
        webscraping: str = "static",
        self_absorption: bool = False,
        optical_depth=None,
        self_absorption_config=None,
    ) -> pd.DataFrame:
        """

        Parameters
        ----------
        input_composition_df: pd.DataFrame
            Input df with composition of elements to simulate
        size : int
            Output file size - number of simulated samples
        Te_min : float
            Minimal random electron temperature Te[eV]
        Te_max : float
            Maximal random electron temperature Te[eV]
        Ne_min : float
            Minimal random electron density Ne[cm^-3]
        Ne_max : float
            Maximal random electron density Ne[cm^-3]
        webscraping : str
            Webscraping type 'static' or 'dynamic'
        self_absorption : bool
             Apply self absorption to all NIST transitions in static samples; ignored in dynamic mode.
        optical_depth : deprecated
             Manual optical depth is rejected when self_absorption is enabled.
        self_absorption_config : dict or NISTSelfAbsorptionConfig
             Shared physical/Stark settings; NIST data and SA are computed for each sample.

        Returns
        -------

        """
        pool = ThreadPoolExecutor(size)
        spectra_pool = [
            pool.submit(
                SimulatedLIBS.worker,
                input_composition_df,
                Te_min,
                Te_max,
                Ne_min,
                Ne_max,
                webscraping,
                self_absorption,
                optical_depth,
                self_absorption_config,
            )
            for _ in range(size)
        ]
        columns = [
            str(wavelength)
            for wavelength in spectra_pool[0].result()["spectrum"]["wavelength"]
        ]
        for val in input_composition_df.columns.values:
            columns.append(str(val))
        columns.append("Te[eV]")
        columns.append("Ne[cm^-3]".format(Ne_min=Ne_min))
        output_df = pd.DataFrame(columns=columns)

        for spectra in spectra_pool:
            intensity = spectra.result()["spectrum"]["intensity"].values.tolist()
            percentages = spectra.result()["composition"]["percentages"].values.tolist()
            intensity.extend(percentages)
            intensity.append(spectra.result()["name"])
            intensity.append(spectra.result()["Te[eV]"])
            intensity.append(spectra.result()["Ne[cm^-3]".format(Ne_min=Ne_min)])
            output_df = pd.concat(
                [output_df, pd.DataFrame(data=[intensity], columns=columns)],
                ignore_index=True,
            )

        output_df.reset_index(drop=True)
        return output_df
