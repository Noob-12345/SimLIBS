# Findings
- Desktop UI confirmed by user.
- Source project is ../simLIBS-2.0.3; UI directory initially empty.
- Core simulation fetches data from NIST using requests or Selenium, rather than containing a fully offline plasma solver.
- Existing Python 3.10 simLIBS environment contains all current runtime dependencies, including tkinter.
- Herdr 0.9.3 session simlibs-ui running with three actual panes: w1:p1, w1:p2, w1:p3.
- User authorizes external Herdr orchestration. No source business files changed.
`n- Independent live core verification succeeded: H 100%, 650–660nm, raw 47 rows, interpolated 2000 rows, maximum intensity 1802. NIST requires composition sum 100%. See coordinator-notes.md.
