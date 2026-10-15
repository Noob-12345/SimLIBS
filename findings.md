# Self-absorption paper findings

## Verified metadata
- Paper: A numerical procedure for understanding the self-absorption effects in laser induced breakdown spectroscopy.
- Authors: Lekha Mary John and K. K. Anoop.
- RSC Advances (2023), 13, 29613-29624; DOI 10.1039/D3RA06226K.
- Local PDF has 12 pages and states CC-BY 4.0.

## Pre-implementation source (historical comparison)
- simLIBS/self_absorption.py computes beta(tau) = -expm1(-tau)/tau, beta(0)=1.
- Tau is supplied explicitly as scalar or array; no opacity derivation from populations or line parameters.
- Existing computed/broadened total and ion channels share pointwise beta.
- simulation.py maps raw-node tau onto interpolation and ion axes; saves references and diagnostics.

## Verified paper equations (PDF pages 3-4, printed 29615-29616)
- Eq. (4): intrinsic Stark FWHM approximately 2 W (Ne / 1e16), using the Stark-B electron-impact width parameter W.
- Eq. (6): SA = I(lambda0)/I0(lambda0) = (1-exp(-k(lambda0) l))/(k(lambda0) l); center optical depth is tau0=q/FWHM.
- Eq. (7): q = Ns*gk*lambda0^4*Aki*l*exp(-Ei/(kB*T)) / (4*pi^2*c*Us(T)). Ns is the number density of the relevant species, not electron density. Ei is the lower-level energy.
- Eq. (8): FWHM_abs/FWHM_thin = SA^alpha, alpha=-0.54.
- SA is a line-center peak ratio. It must not be confused with integrated line area.
- A high-resolution crop confirms Eq. (5) has unusual squared-FWHM notation in the numerator and denominator. Treat this as a possible typesetting/notation issue, not evidence of the authors' implementation. A reproduction must explicitly define peak height versus integrated area and use a consistent Lorentz normalization.
- The paper uses homogeneous LTE plus a semi-empirical width relation; it is not a full space/time radiative-transfer solver.
- Figure 2 (PDF page 6, printed 29618) visually labels FWHM=0.143 nm without SA and 0.179 nm with SA. This is a reported ~25.2% width increase, not just amplitude scaling.
- Full text contains no executable source listing or algorithm pseudocode clarifying the peak-height versus line-area normalization.
- Concentration and path-length scans use fixed T/Ne examples; the temperature scan in section 3.1 recomputes Ne via Saha and charge balance with a fixed total elemental density ~1e18 cm^-3. Do not summarize the paper as always holding Ne fixed.
- Eq. (7) uses SI Ns, wavelength and path length; Eq. (4) uses Ne referenced to 1e16 cm^-3 and width in nm. Unit conversion is essential.

## Comparison conclusions
- Current beta(tau) and paper SA(tau0) have the same scalar algebraic form.
- Current code does not derive tau from Te/Ne, species density, line data, or optical path length and has no Stark-B widths or Eq. (8) width update.
- Scalar tau only rescales the current spectrum; wavelength-dependent tau can change apparent shape but has no automatic line-by-line opacity model or specified FWHM relation.
- Paper starts from individual transitions; current code acts on the existing broadened total/channels using common beta per wavelength.
- A constant shared beta adds the same ln(beta) to Boltzmann-plot ordinates, so it cannot by itself reproduce line-selective slope distortion. This is an inference from the equations, not a separate experimental finding.
- Paper section 3.4 / Table 2 uses a simulated 50/50 Mg-Ca alloy; including SA-affected resonance lines gives 36.42% Mg / 63.58% Ca, while omitting resonance lines gives 49.33% / 50.67%. This comparison is limited to that simulated example.

## Reproduction cautions
- SA in Eq. (6) is a line-center peak ratio. When using an area-normalized Lorentz profile, changing its area and width independently requires enforcing the desired center ratio; blindly scaling area by SA and width by SA^-0.54 would not preserve that definition.
- Eq. (6) uses a linewidth symbol without the before/after suffix distinguished in Eq. (8); a reproduction should explicitly define which width is used rather than claim the unpublished source code is known.
- Do not substitute instrumental lambda/R for a Stark width in Eq. (6).
- Do not infer a universal monotonic temperature trend for all arbitrary conditions; populations, ionization and widths change together, and the paper's reported scans have specific constraints.

## Verified illustration
- Created output/analysis/self_absorption_paper_comparison.png and visually checked it.
- Illustration uses actual current attenuate_spectrum with scalar tau=1 and a peak-normalized Lorentz reference of FWHM=0.020 nm.
- SA=0.6321205588; current FWHM=0.020 nm; Eq. (8) illustration FWHM=0.0256211159 nm (factor 1.2810558).
- The red curve illustrates only a peak-ratio-preserving linewidth change; it is not digitized paper data or a reproduction of the paper's full spectrum.

## Current implemented model (2026-10-15)
- Both original core and Vue advanced use identical shared paper line engine and snapshot. Default31 transitions (Mg13/Ca14/Zn4),1696 real bound NIST states across I/II/III.
- Three-stage Saha; explicit q SI conversion; tau from unabsorbed Stark width; SA stable expm1; FWHM SA^-.54; area SA^.46 preserves the center peak ratio.
- Defaults: original core energy/no instrument/charge-balance density; Vue photon/optional instrument/number density from Ncol/(100L).
- Parent independently verified30 core tests,38 Vue tests, frontend typecheck/build, true worker and actual3 exports, packaged wheel installation and source/data hash identity.
- Chinese report and real example assets are under simLIBS-2.0.3/SELF_ABSORPTION_REPORT.md and docs/self_absorption_results/. No EXE/NSIS rebuild in the Rust-less environment; source-only delivery boundary is explicit.

## Source access
- Local PDF is complete and readable. Publisher articlehtml fetch returned HTTP 403; use local PDF as the primary source and do not retry the same URL.
- Search verified DOI/title/authors on the publisher landing page. PMC full-text open returned a browser challenge; no attempt was made to bypass it. All detailed equation/figure claims come from the local PDF.
