# Automatic sourced Stark data coverage

Date: 2026-10-16 (Asia/Shanghai)

## Goal
Let input elements use Stark broadening and self absorption without manually preparing per-transition coefficients. The user requires traceable per-line coefficients and prioritizes accuracy; synthetic fallback coefficients are excluded.

## Phases
1. [complete] Inspect current resolver and confirm the default coefficient set: Mg 13, Ca 14, Zn 4 transitions.
2. [complete] Verify authoritative data services, access protocol, matching rules, temperature/density validity and coverage limits. Live HTTPS TAP queries returned Mg and Si II XSAMS data; seven rare-earth sample elements are unavailable in STARK-B.
3. [complete] User explicitly renewed the request to expand coverage to most elements on 2026-10-18; proceed with sourced data, no synthetic fallback.
4. [complete] Batch 1 provider/cache: real Si II fixture, seven offline tests passing, live query retrieved 36 Si II transitions from SCP/MSE datasets.
5. [complete] Strict NIST identity enrichment and matching tests; connected resolver/config and preserved local priority and legacy direct calls.
6. [complete] Chinese README/coverage report/CLI complete; 86 tests pass, seven additional elements verified live and final CLI snapshot repeat/export verified. Independent review rechecked cache fix, 16 focused tests and live Al tables; no further reproducible important defects.

## Delivered scope and data boundary
- Source-backed automatic retrieval/cache and strict identity bridge are implemented. No element whitelist remains in the NIST Stark engine.
- Seven additional elements have actual main-entry validation; blanket majority coverage of the user's full 28-element mix or every 200-900nm transition is NOT established. Missing external data/validity/identities remain explicit errors and exported coverage rows, never invented fallback coefficients.

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
