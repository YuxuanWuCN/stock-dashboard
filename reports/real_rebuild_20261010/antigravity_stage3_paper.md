# Antigravity Stage 3 Paper Handoff

Status: paper draft generated; supervisor review pending. No commit was made by the implementer.

## Scope

- Generated `paper_draft_zh.md` from the final machine-readable M4 JSON artifacts.
- Kept the date-matched placebo limitation explicit: when the control pool is insufficient, the result is marked `invalid_insufficient_control` and is diagnostic only, not valid matched inference.
- Reported serial-dependence-robust inference with Newey-West HAC and moving-block sensitivity. IID bootstrap values are labelled comparison-only.
- No quantitative rerun, raw-data overwrite, or fabricated provenance/performance claim.

## Commands and Results

1. `.venv\\Scripts\\python.exe -m pytest tests\\test_p4_real_quant.py -q`
   - Result: `38 passed in 4.48s`.
2. `.venv\\Scripts\\python.exe scripts\\p4_paper_builder.py`
   - Result: success; output size 39,826 bytes.
3. Determinism check: generated the paper twice from the same JSON inputs and compared SHA-256.
   - Result: identical hashes: `53697C4DEF46AAEC565E717A8CAEBF39D49A927293297EE6235FF3AC9B0DC4E2`.
4. `tools\\run_quality.ps1 small`
   - Result: PASS. Existing heavy environmental failures remain recorded by the quality gate and are unrelated to P4-specific tests.

## Limitations and Pending Review

- Date-matched placebo is censored on dates where the pool has fewer observations than the target; it must not be read as a valid matched test.
- Overlapping holding windows induce strong serial dependence; formal interpretation uses HAC and block sensitivities, not IID bootstrap p-values.
- The CSMAR label remains repository metadata rather than an independently verified acquisition certificate.
- Heavy/final submission and commit remain pending supervisor approval.
