# Findings

## Current implementation
- SimulatedLIBS(static, self_absorption=True) retrieves NIST lines, level/statistical-weight/ionization data, then matches every participating nonzero transition to user or built-in Stark coefficients.
- Built-in paper_atomic_data.json contains 31 coefficients: Mg 13, Ca 14, Zn 4.
- resolve_stark raises MissingStarkDataError if any required transition lacks a match.
- Current config has no network provider, per-temperature Stark interpolation or automatic persistent coefficient cache.

## Confirmed user choice
- 2026-10-16: only sourced per-transition coefficients; accuracy takes priority. Do not implement an invented or approximate fallback for missing data.

## Authoritative sources inspected
- NIST ASD contents: https://www.nist.gov/pml/atomic-spectra-database-contents (radiative transitions and energy levels).
- STARK-B description: https://stark-b.obspm.fr/index.php/description . Uncoloured periodic-table entries have no data; width tables specify temperature, perturber density, electron FWHM in Angstrom and validity flags. Multiplet values may require documented wavelength-squared scaling to individual lines. Published temperature fits are only valid inside their tabulated interval.
- STARK-B introduction: https://stark-b.obspm.fr/index.php/introduction . Includes several sourced theoretical methods; MSE itself is an approximation, so source provenance must not be equated with exact measured truth.
- VAMDC protocol: https://vamdc-standards.readthedocs.io/en/latest/dataAccessProtocol/vamdctap.html . Standard HTTP TAP queries using LANG=VSS2, FORMAT=XSAMS.
- VAMDC tutorial: https://tutorial.vamdc.eu/self-study/end-user-self-study/python-scripting.html . Read-only automation is supported; query conservatively and cache results.

## Open items
- Obtain approval of the concrete implementation approach before source edits.
- For implementation, verify width-convention mapping, source-state identifiers, temperature interpolation and validity checks against original tables.
- Quantify line-level coverage for the actual input; element-level availability alone is insufficient.

## Live species coverage check
- Downloaded the STARK-B periodic table with PowerShell Invoke-WebRequest and normal certificate validation on 2026-10-16.
- In the existing sample script's rare-earth list, Pr, Sm, Tb, Ho, Er, Tm and Yb are explicitly class="unavailable"; La, Eu, Lu and Y are available at element level. Availability at element level does not establish all stages or transitions.
- Mg, Fe and Si are also available at element level.
- This proves STARK-B alone cannot satisfy arbitrary-input coverage with sourced coefficients. It does not prove the missing species have no data in all other literature.
- Python 3.7 urllib could not validate the server certificate using its configured trust store. Switched to PowerShell's normally verified HTTP client; did not disable certificate verification.
- Browser text extraction's periodic-table links target image/JS controls, so clicks do not expose species datasets.

## Live service proof
- HTTPS endpoint works: https://stark-b.obspm.fr/12.07/vamdc/tap/sync . A registry entry is marked inactive, but actual HTTPS GET queries returned HTTP 200; the live response is stronger evidence than registry status.
- Mg I 2850-2860 Angstrom query returned XSAMS data (136846 characters).
- Si II 6340-6380 Angstrom query returned one RadiativeTransition at database wavelength 6347.0 Angstrom with two bibliographic sources, reference density 1e17 cm^-3 and several temperature environments; raw snapshot saved as starkb_siII_6340_6380.xsams.
- The Si response includes multiple perturbers (electron and proton) and gammaL parameters. A provider must filter electron environments for compatibility with the present electron-impact model, and verify gammaL/FWHM/HWHM mapping before converting to the code's W convention.
- The API returns term/configuration state references; matching to the current numeric NIST payload may need additional metadata, especially for multiplets and averaged/theoretical wavelengths.
- Official table.js exposes read-only species lookup via POST module=stark_b, action=periodictable:datasets, element=Mg; actual response listed Mg I/II/III/IV/XI, demonstrating that element availability does not mean all stages.
