# NIST enrichment research

Scope: read-only inspection of simLIBS-2.0.3; official NIST sources only; identify Si II 6347/6371 air pair; exclude width semantics and production modifications. All artifacts must start nist_enrichment_research in this directory.

Plan
1. Inspect six-column Saha-LTE payload and query path. In progress.
2. Download official ASD form/help and real Si II exports with exact params. Pending.
3. Check air/vacuum, A/g, fine structure and multiplet caveats. Pending.
4. Deliver reproducible requests, parsed sample rows and conservative identity strategy. Pending.

Findings so far
- parse_atomic_payload reads lines=[vacuum nm,g_upper*Aki,upper cm^-1,Z,ion stage,lower cm^-1], converting energies using cmeV. Config/term/J not present in returned transitions.
- Official ASD help allows CSV/TSV; configuration/term/J/energies selectable; all-vacuum output available.
- Multiplet ordering includes classified lines only and shares configuration and term; J remains essential for component identity.

Inspection: existing fixture confirms exact six-column array. First form-inspection stdout hit Windows GBK for Angstrom symbol; fixed by UTF-8 stdout, no TLS or download failure.

Progress: actual NIST LIBS Si request returns Ritz 634.886 and 637.313 nm, gA=233600000 and 136000000; AST-isolated current parse_atomic_payload successfully parsed it, and both lines uniquely joined to enriched cm^-1 export with <=4 ULP arithmetic allowance, no wavelength proximity search. Export eV and payload eV are independently rounded/converted, so cm^-1 is preferred for join. Four extra official Mg II/Ca II/Na I/Fe II samples demonstrate cores, parity, parent terms, letter qualifiers, and E1/M2 duplicate state pairs. Multiplet order requested as TSV actually returned HTML; saved with honest .html suffix. One combined read/log command was rejected by automatic policy without a reason; equivalent narrowly-scoped read-only inspection succeeded. No production imports/writes.

TLS note: one official L3541 bibliography request returned SSLEOFError (unexpected EOF), not a certificate validation error. Retried boundedly with Connection: close and exact original link; normal TLS validation retained throughout. Errors remaining: []

COMPLETE: bounded research ended. Final findings, exact params, two unique NIST joins, five-species normalization evidence and SCP/source ambiguity policy saved. Verified recorded sample hashes, CSV equivalence, identity result [1,0].
