# Paper self-absorption implementation

Date: 2026-10-15 (Asia/Shanghai)

## Goal
Replace the original simLIBS core's prescribed-opacity processing with a line-by-line implementation of the supplied paper; also connect Vue's advanced backend to the same engine, and deliver a Chinese Markdown principle/implementation report with verified examples.

## Phases
1. [complete] Inspect code and identify data/model gaps; prior paper comparison preserved in findings.md.
2. [complete] Prepare independently verified Table 1 lines and NIST I/II/III level snapshots (one data file).
3. [complete] TDD: finite-bound-level Saha/Boltzmann, SI opacity, Stark width, SA peak/width-consistent line synthesis (12 tests passing).
4. [complete] Integrate new path in SimulatedLIBS and Vue advanced, regridding, dataset and exports; migrate old tests in steps of at most three business files.
5. [complete] Package data, create runnable example/plots and Chinese Markdown report, independent review and final verification. 30 core +38 Vue tests, frontend build, true worker and wheel install passed. EXE/NSIS rebuild explicitly outside verified delivery because Cargo/Rust is absent.

## Decisions
- Built-in 31 Table 1 transitions for Mg/Ca/Zn plus custom data support; missing Stark/atomic data must raise, never fall back to global attenuation.
- Use real bound levels for I/II/III partition functions; no invented III states.
- Use pre-absorption Stark width in Eq. (6), then Eq. (8) once. Explicitly document the paper's width-notation ambiguity.
- Treat Eq. (2) as integrated line weight and enforce Eq. (6)'s peak ratio when rebuilding an area-normalized Lorentz profile: area_abs = area_thin * SA**(1-0.54).
- Instrument Gaussian is an optional separate convolution after the intrinsic line model, not an opacity width.

## Source
D:/LIBS/Research-Proposal/Matrix_effect/Self-aborption/d3ra06226k.pdf

## Errors
- Publisher articlehtml URL returned HTTP 403. Continue with complete local PDF; use a different source path only if metadata verification is needed.
- PMC full-text page returned a browser challenge. No bypass attempted; local PDF remains the complete primary source.
- Poppler is available; no PDF dependency installation needed.
