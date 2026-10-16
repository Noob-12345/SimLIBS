# Automatic sourced Stark data coverage

Date: 2026-10-16 (Asia/Shanghai)

## Goal
Let input elements use Stark broadening and self absorption without manually preparing per-transition coefficients. The user requires traceable per-line coefficients and prioritizes accuracy; synthetic fallback coefficients are excluded.

## Phases
1. [complete] Inspect current resolver and confirm the default coefficient set: Mg 13, Ca 14, Zn 4 transitions.
2. [complete] Verify authoritative data services, access protocol, matching rules, temperature/density validity and coverage limits. Live HTTPS TAP queries returned Mg and Si II XSAMS data; seven rare-earth sample elements are unavailable in STARK-B.
3. [awaiting_user] Present a concrete modification proposal and obtain approval before coding, as required by the user's AGENTS.md.
4. [pending] If approved, implement in batches of at most three files with meaningful tests and update the report.

## Constraints
- Use only traceable per-transition coefficients; no global guessed width or approximate fallback for absent records.
- Never claim complete arbitrary-element/arbitrary-line coverage without evidence.
- Preserve existing deleted sample CSV files.
- Distinguish database theory/experiment provenance and data validity from numerical output.

## Proposed implementation batches
1. Add a STARK-B client and offline fixture-based provider tests, at most three files. Query each species conservatively, cache raw responses and preserve bibliographic/environment/method metadata. Verify the XSAMS gammaL convention against published tables before width conversion.
2. Extend the existing coefficient resolver/configuration and matching metadata, at most three files. Match species/stage and available level/term/configuration identifiers, handle air/vacuum and multiplet conventions explicitly, reject ambiguous assignments, and respect tabulated temperature/density validity. Keep user-provided records as highest priority.
3. Add a coverage preflight/export for the actual input transitions and update tests/docs/report in batches of at most three files. Distinguish not found, ambiguous, out of validity range and network failures. Do not label partially corrected outputs as complete self-absorption spectra.
4. Validate a sourced transition outside Mg/Ca/Zn (e.g. Si II), density/temperature conversion, matching ambiguity, no-data responses and existing model regressions. Produce a coverage audit for the current sample script's 28 elements / 200-900 nm / charge 0-2 when feasible; complete arbitrary-input coverage remains conditional on actual data availability.

## Errors
- Default Python is 3.7.0; planning-with-files session-catchup.py requires newer Python syntax and could not run. Existing root planning files were inspected manually.
- Python launcher `py` is unavailable. No environment changes made.
