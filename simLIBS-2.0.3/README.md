# Simulated LIBS

[![PyPI version](https://img.shields.io/pypi/v/SimulatedLIBS?style=flat&logo=pypi)](https://pypi.org/project/SimulatedLIBS/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE.md)
![Tests](https://github.com/MKastek/SimulatedLIBS/actions/workflows/test.yml/badge.svg)
[![ZENADO DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.7260706.svg)](https://doi.org/10.5281/zenodo.7260706)

*SimulatedLIBS* provides Python class to simulate LIBS spectra with NIST LIBS Database interface.  
*SimulatedLIBS* also allows the creation of simulated data sets that can be used to train ML models.  
*SimulatedLIBS* was mentioned is [FOSS For Spectroscopy](https://bryanhanson.github.io/FOSS4Spectroscopy/) by Prof. Bryan A. Hanson, DePauw University.

Project created for **B.Eng. thesis**:  
Computer methods of the identification of the elements in optical spectra obtained by Laser Induced Breakdown Spectroscopy.

**Thesis supervisor**: Paweł Gąsior PhD  
e-mail: pawel.gasior@ifpilm.pl  
Institute of Plasma Physics and Laser Microfusion - IPPLM  


## Installation
```python
pip install SimulatedLIBS
```
## Import

```python
from simLIBS import SimulatedLIBS
```
## Example
Parameters:
- Te - electron temperature [eV]
- Ne - electron density [cm^-3]
- elements - list of elements
- percentages - list of elements concentrations
- resoulution
- wavelength range: low_w, upper_w
- maximal ion charge: max_ion_charge
- websraping: 'static' or 'dynamic'


### Static websraping
Static mode retrieves NIST's **calculated, unbroadened `dataSticksArray`**
and synthesizes the spectrum locally, using the same Gaussian kernel as
`Cross_attention/Dataset/datagen.py`. It does not use `dataDopplerArray`.
NIST still calculates line strengths from composition, Te and Ne.

- Requests use `min_rel_int=0`, 500 nm core bands and 2 nm internal overlap.
  Line tables are merged before broadening; no per-band normalization is applied.
- Each line has area equal to its calculated strength, with
  `I = strength / (width * sqrt(pi)) * exp(-((wavelength-center)/width)**2)`.
  Here `width = center / resolution` is the Gaussian **1/e half-width**,
  not FWHM. The profile is evaluated within six widths of the center.
- The default output grid is approximately 0.005 nm, including both endpoints.
  The point count is `round((upper_w-low_w)/step)+1` (at least two);
  `linspace` adjusts the actual step if the range is not evenly divisible.
- `libs.line_table` retains the merged calculated line table.
  `raw_spectrum` contains the locally synthesized initial spectrum.
- With `self_absorption=False`, static mode uses this NIST line-table path.
  With `self_absorption=True`, static mode applies per-transition self absorption
  to the same NIST line strengths (see below).
  Dynamic mode always uses the browser result and ignores the self-absorption
  switch and its configuration. The instance's `self_absorption` attribute
  records whether self-absorption is actually enabled.

```python
libs = SimulatedLIBS(Te=1.0,
                     Ne=10**17,
                     elements=['W','Fe','Mo'],
                     percentages=[50,25,25],
                     resolution=1000,
                     low_w=200,
                     upper_w=1000,
                     max_ion_charge=3,
                     webscraping='static')
```

### Static self-absorption / 静态逐线自吸收

`static + self_absorption=True` now requests NIST first. It preserves every
returned nonzero stick contribution, obtains transition energies and `g_upper*Aki`
from `lines`, and levels/statistical weights/ionization energies from
`levels`, `gValues`, and `ips`. JavaScript is parsed as data, never executed.
Coincident transitions share the NIST stick area according to their
`gA*exp(-E_upper/Te)` weights; their individual absorption is then calculated.

布居使用 NIST 页面提供的全部电离阶段和能级集合（含裸核阶段），不再限定
JSON 中的 I/II/III。总密度未指定时通过电荷守恒反推；组分按原子数百分比处理，
总和须为 100。线强始终保留 NIST `int_scale=2` 的光子权重，不作分段归一化。

**Stark coefficients are still required for every transition.** The built-in
JSON is only a coefficient lookup, not a line selection list. Its air-wavelength
records are matched using both level energies (0.002 eV tolerance) and `gA`
(3% tolerance); ambiguous matches raise an error. User coefficients take priority.
No default Stark value is invented and missing lines are never silently skipped.

```python
from simLIBS import SimulatedLIBS, MissingStarkDataError

try:
    libs = SimulatedLIBS(
        Te=1.0, Ne=1e17, elements=['Mg'], percentages=[100],
        low_w=280, upper_w=290, resolution=3000,
        webscraping='static', self_absorption=True,
        self_absorption_config={'path_length_m': 0.001},
    )
except MissingStarkDataError as error:
    # 导出全部缺失谱线；依据有出处的逐线数据填入 stark_width_nm 后重新运行。
    error.missing_lines.to_csv('missing_stark.csv', index=False)
```

Use `self_absorption_config={'stark_data': dataframe_or_list, ...}` to supply
coefficients. Each record needs `element`, zero-based `charge`,
`wavelength_nm` (**vacuum**, matched within 1e-6 nm), `stark_width_nm`
and optionally `stark_reference_ne_cm3` (default 1e16) and `source`.
Instead of wavelength, both `lower_eV` and `upper_eV` can identify a transition
(matched within 1e-6 eV). When both identifiers are given, both must match.
For unresolved lines, include the energies to distinguish transitions.
`stark_width_nm` is W in **FWHM = 2*W*Ne/Ne_ref**, not a measured FWHM itself.
Convert source FWHM values to this convention before supplying them.

Defaults: `path_length_m=0.01`, `wavelength_step_nm=0.005`,
`total_number_density_cm3=None`, `instrument_broadening=True`.
`NISTSelfAbsorptionConfig` is also accepted instead of a dictionary.

The center attenuation is `(1-exp(-tau))/tau`; intrinsic width is multiplied
by `SA**(-0.54)` and NIST line area by `SA**0.46`. Final profiles are Voigt
profiles with Gaussian sigma `wavelength/(R*sqrt(2))`, consistent with the
ordinary static Gaussian convention. Instrument width never enters opacity.
This is an independent-line empirical model, not coupled radiative transfer.
Stark coefficients are scaled by electron density; no temperature law is inferred.

`unabsorbed_raw_spectrum` is the same NIST/Stark/Voigt model with absorption
removed. Because it includes intrinsic Stark width, it is not identical to
the Gaussian-only `self_absorption=False` spectrum. Diagnostics retain each
transition's original NIST area, coefficient source, tau, SA, width and area.
`interpolate()` reuses cached transitions and coefficients without network access.
Large line-count × grid-size jobs raise a resource-limit error; increase the
sampling step or narrow the window instead of silently dropping lines.

The old offline model remains explicitly available as
`simLIBS.self_absorption.simulate_paper_spectrum`. Its `PaperSelfAbsorptionConfig`,
`line_data`, `atomic_data` and `intensity_scale` settings belong to that standalone
function, not the new `SimulatedLIBS` path. The old paper demo/report describe
that standalone model. `dynamic` still ignores all self-absorption settings.

Run the NIST example from this project directory:

```bash
python examples/nist_self_absorption_demo.py --output output/nist_self_absorption
```

The default vacuum window, 285.27–285.33 nm, contains one Mg transition with
an available built-in Stark coefficient. A broader window can require additional
coefficients: use `--low 280 --high 290` to export the missing-line CSV template,
then supply the completed file with `--stark-csv path/to/coefficients.csv`.


### Plot
```python
libs.plot(color='blue', title='W Fe Mo composition')
```
![](https://github.com/MKastek/SimulatedLIBS/blob/master/images/plot_static.png?raw=True)

### Save to file
```python
libs.save_to_csv('filename.csv')
```

### Interpolated spectrum
For static mode this returns the locally synthesized spectrum. To change
its sampling step, evaluate the retained lines on a new grid without
another network request or spline interpolation:
```python
libs.interpolate(resolution=0.01)  # sampling step [nm], NOT spectrometer R
```
The existing method name is retained for compatibility. Dynamic mode still
returns the browser CSV directly at initialization; an explicit call to
`interpolate()` on dynamic data retains the legacy cubic-spline behavior.
```python
libs.get_interpolated_spectrum()
```

### Raw spectrum
Static: the initially synthesized local spectrum. Dynamic: the total
spectrum retrieved from NIST's browser CSV.
```python
libs.get_raw_spectrum()
```
### Dynamic webscraping
Unchanged: Chrome opens the official NIST page, recalculates at the requested
resolution, and reads the exported total spectrum and ion components.
```python
libs = SimulatedLIBS(Te=1.0,
                     Ne=10**17,
                     elements=['W','Fe','Mo'],
                     percentages=[50,25,25],
                     resolution=1000,
                     low_w=200,
                     upper_w=1000,
                     max_ion_charge=3,
                     webscraping='dynamic')
```

### Plot
```python
libs.plot(color='blue', title='W Fe Mo composition')
```
![](https://github.com/MKastek/SimulatedLIBS/blob/master/images/plot_dynamic.png?raw=True)

### Ion spectra
After simulation with parameter websraping = dynamic, ion spectra are stored in ion_spectra (pd.DataFrame) and can be plotted.
```python
libs.plot_ion_spectra()
```
![](https://github.com/MKastek/SimulatedLIBS/blob/master/images/plot_ion_spectra.png?raw=True)
### Random dataset of samples
Based on .csv file with chemical composition of samples, one can generate dataset of simulated LIBS measurements
with different Te and Ne values.

Example of input_composition_df pd.DataFrame:

|W  |H  |He |name|
|---|---|---|----|
|50 |25 |25 |A   |
|30 |60 |10 |B   |
|40 |40 |20 |C   |

```python
SimulatedLIBS.create_dataset(input_composition_df,
                             size=100,
                             Te_min=1.0,
                             Te_max=2.0,
                             Ne_min=10**17,
                             Ne_max=10**18)
```

Example of output .csv file:

|    |   200.0 |   200.1 |   200.2 |   200.3 |   200.4 | ...   |   H |   W |   Te |       Ne |
|---:|--------:|--------:|--------:|--------:|--------:|----:|----:|----:|-----:|---------:|
|  0 |       0 |     0   |     0   |     0   |     0   | ...   |2 |   50 | 1.43 | 1.08e+17 |
|  1 |       0 |     0   |     0   |     0   |     0   | ...   |0 |   0 | 1.06 | 1.08e+17 |
|  2 |       0 |     0.1 |     0.1 |     0.1 |     0.1 | ...   |0 |  68 | 1.82 | 1.18e+17 |
|  3 |       0 |    54.5 |    56.7 |    54.4 |    48.4 | ...   |0 |   3 | 1.25 | 1.06e+17 |
|  4 |       0 |   121.7 |   143.1 |   140.5 |   115.3 | ...   |0 |  84 | 1.08 | 9.23e+17 |


### Animations
SimulatedLIBS can be helpful in creating LIBS animations mostly for educational purpose.

#### Resolution animation
Changes in resolution in range: 500-10000.
![](https://github.com/MKastek/SimulatedLIBS/blob/master/SimulatedLIBS/animations/saved-gifs/animated_resolution.gif?raw=True)
#### Electron temperature animation
Changes in electron temperature Te in range: 0.5-5 eV.
![](https://github.com/MKastek/SimulatedLIBS/blob/master/SimulatedLIBS/animations/saved-gifs/animated_temperature.gif?raw=True)
#### Electron density animation
Changes in electron density Ne in range: 0.7-1.3 e+17 [cm^-3].
![](https://github.com/MKastek/SimulatedLIBS/blob/master/SimulatedLIBS/animations/saved-gifs/animated_density.gif?raw=True)

## References
- M. Kastek, _et al._, _Analysis of hydrogen isotopes retention in thermonuclear reactors with LIBS supported by machine learning_. Spectrochimica Acta Part B Atomic Spectroscopy 199: 106576. DOI: [10.1016/j.sab.2022.106576](https://doi.org/10.1016/j.sab.2022.106576).


## Used in Research
- Chen Z, Chen Z, Jiang W, Guo L, Zhang Y. _Line intensity calculation of laser-induced breakdown spectroscopy during plasma expansion in nonlocal thermodynamic equilibrium._ Opt Lett. 2023 Jun 15;48(12):3227-3230. DOI: [10.1364/OL.488250](https://opg.optica.org/ol/abstract.cfm?uri=ol-48-12-3227).
