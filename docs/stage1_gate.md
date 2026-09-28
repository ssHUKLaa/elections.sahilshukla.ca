# Stage 1 acceptance gate

**Status: PASSED on 21 September 2026.**

Run `python pipeline/validate_stage1.py` from the repository root to repeat the automated gate.

## Gate evidence

| Requirement | Result | Evidence |
| --- | --- | --- |
| Two pulls can be replayed | Pass | Snapshots `20260921T015701Z` and `20260921T200327Z` both validate and ingest. |
| Replay is idempotent | Pass | Reingesting either identical snapshot returns `already_ingested` and does not add records. |
| Source changes create versions | Pass | The two full-pull content hashes differ and both versions remain queryable. |
| Full question vectors survive | Pass | For each snapshot, the normalized race-option count exactly equals the combined Senate, House, governor, and other source-row count. |
| Schema drift alerts | Pass | A synthetic added column raises a fatal schema-drift error; ordered headers are checked against contract version 1.0. |
| As-of cutoff works | Pass | A cutoff at each retrieval time selects the corresponding source version and exports that version's questions and options. |
| Checksums are enforced | Pass | Ingestion recomputes every NYT file checksum; the gate recomputes all 17 historical-source checksums. |
| Historical polls acquired | Pass | Five archived poll datasets have manifests, row counts, ordered columns, hashes, attribution, and license notes. |
| Official federal results acquired | Pass | Seven FEC certified workbooks cover 2010–2022. |
| Governor results acquired for reconciliation | Pass with recorded limitation | Candidate-level governor history and source links are present; state-certified reconciliation is explicitly assigned to Stage 2. |
| Rights and attribution travel with data | Pass | NYT permission, CC BY 4.0 attribution, FEC authority, and the election-results redistribution limitation are recorded in the source catalog and permission registry. |
| Scheduled operation defined | Pass | A one-command runner and daily/weekly Ubuntu systemd timers are documented. |

## Automated result

```text
status: passed
snapshots tested: 20260921T015701Z, 20260921T200327Z
idempotent replay: true
source change created new snapshot: true
full question vectors preserved: true
schema drift stops pipeline: true
as-of replay selects correct snapshot: true
historical sources verified: 17
```

Stage 2 may now depend on this acquisition layer. The historical coverage limitations remain model-design inputs, especially for House polling and independent-candidate backtests; passing this gate does not claim that those samples are sufficient for calibration.
