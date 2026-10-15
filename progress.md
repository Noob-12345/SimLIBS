# Research progress

- 2026-10-15: Read PDF and planning skills; identified the single 12-page local paper.
- Inspected current self_absorption.py and constructor/interpolation integration.
- Extracted PDF text with Poppler to tmp/pdfs/d3ra06226k-review/paper.txt.
- No simulation source files modified in this research task.
- Visually inspected full PDF pages 3, 4 and 5, including Eqs. (3)-(8) and Table 1.
- Confirmed shared attenuation formula and the two main gaps: opacity generation and explicit SA-related width scaling.
- Visually checked PDF page 6 / Figure 2 and a high-resolution Eq. (5) crop. Read sections 3.1-3.3 and the conclusion, distinguishing reported trends from universal guarantees.
- Read section 3.4 and Table 2; verified how line-selective SA affects the Boltzmann plot and reported simulated composition.
- Generated and visually verified a clearly labeled schematic comparing constant-tau processing and Eq. (8) linewidth scaling.
- Completed model/units/processing-order comparison. No simulation code or tests were edited; analysis notes and a schematic were created.

## Implementation requested after comparison
- User authorized replacing the original core model and delivering an MD report, then added Vue advanced backend integration to the same task.
- Independent data task completed Table 1's 31 transitions and 9 complete NIST I/II/III response snapshots; 1696 bound states will enter partition sums.
- Wrote 12 independent equation/shape/data/limit tests, observed expected failures, then implemented the generic paper engine; all 12 now pass.
- Vue code-role agent owns advanced adapter/tests, minimum advanced UI controls/defaults, resource allowlist and advanced-only API preflight changes. Root remains plan/reviewer for Vue.
- Copied the shared engine and identical data snapshot into Vue/backend/source/simLIBS for integration; later changes must be resynchronized and hash-checked.
- Original core now uses the offline paper model when enabled; manual optical_depth produces a migration error. TDD integration and equation suites total30 passing tests after review fixes.
- Vue code completed and froze9 files; parent independently reran38 tests, verified hashes, ran true worker+CSV/JSON/PNG exports (301 nodes/13 Mg lines), and visually checked PNG.
- Portable Node22.16.0 was SHA-verified under tmp/toolchains; npm ci and npm run build passed with the lockfile unchanged. No Cargo/Rust available; release EXE/NSIS intentionally remain the existing version.
- Built final wheel, confirmed bundled JSON, installed to independent target and ran the actual model; installed engine matches source SHA.
- Generated SELF_ABSORPTION_REPORT.md, runnable example, real figures and CSV/JSON; all14 local report links verified.
- Verification method corrections: core unittest must run in simLIBS-2.0.3 (root invocation cannot import local package); compile source bytes rather than utf-8-decoded strings to preserve legal UTF-8 BOM handling. Corrected runs passed.
