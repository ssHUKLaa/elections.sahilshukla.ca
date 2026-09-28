# Stage 2 acceptance gate

**Status: PASSED on 23 September 2026, with conservative data limitations carried into the model.**

Run:

```bash
python pipeline/build_stage2.py
python pipeline/report_stage2_quality.py
python pipeline/validate_stage2.py
```

## Gate evidence

| Requirement | Result | Evidence |
| --- | --- | --- |
| Stable race keys | Pass | All 506 registry races occur exactly once in the Stage 2 database. |
| Stable candidate keys | Pass | All 1,413 ballot entries occur exactly once; no mapped source candidate ID resolves to multiple project candidates. |
| Full option vectors | Pass | All 19,895 option rows from the latest Stage 1 snapshot occur in Stage 2. |
| No silent candidate mismatch | Pass | 973 unresolved candidate rows are quarantined; any affected question is ineligible. The gate separately verifies 1,677 `party=NONE` response rows and the two Alaska Sullivan identities. |
| Reviewed prior winners | Pass | The exact official 2020 winning rows are matched to Dan S. Sullivan and Susan Collins through a hash-tracked reviewed alias file; Dan J. Sullivan remains unmatched. |
| Signals separated from races | Pass | Approval and generic-ballot questions are classified as signals rather than district races. |
| Historical polls normalized | Pass | 14,976 questions and 31,534 options use common normalized tables. |
| Federal result baselines | Pass | 12,873 FEC/House Clerk rows supply House baselines and same-seat Senate history. Georgia's missing normalized 2020 runoff uses the structured result archive with explicit evidence; structurally uncontested Senate results use a widened contested-statewide share fallback. |
| Result discrepancies controlled | Pass | 3,042 archive comparisons are exact or within 0.1%; larger discrepancies remain visible and cannot override official rows. |
| Governor provenance | Pass with limitation | Every governor baseline retains an upstream result source; final state-certification reconciliation remains required before public model launch. |
| Changed or unresolved districts | Pass with widened uncertainty | No old House result is labeled a validated 2026-boundary lean; all House fallbacks are widened and Missouri receives the largest multiplier. |
| Coverage report | Pass | JSON and Markdown reports cover office, state, ballot status, counting rule, mapping status, source cycle, and reconciliation status. |
| Ubuntu ARM operation | Pass | Daily and weekly systemd units replace the earlier Windows scheduling instructions. |

The gate permits Stage 3 to build a results-only baseline. It does not permit the model to consume quarantined polls, treat governor links as fully reconciled certifications, or describe the House fallback as a precinct-reallocated partisan lean.
