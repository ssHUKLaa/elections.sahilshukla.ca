# Stage 1, in plain language

Stage 1 builds the project's time machine. It downloads source data without changing it, proves exactly what was downloaded, and creates a database that can answer: **what polling data did we possess by a particular UTC time?** It does not decide which candidate a poll option belongs to or fit a forecast. Those are later stages.

## What was built

### Immutable live-poll snapshots

`pipeline/snapshot_nyt_polls.py` downloads all six authorized NYT files into a new timestamped directory. Each snapshot has a manifest containing the URL, retrieval time, HTTP metadata, byte size, row count, ordered columns, and SHA-256 checksum. A combined content hash identifies the full pull.

The expected headers are frozen in `data/reference/nyt_poll_schema_v1.json`. If NYT adds, removes, renames, or reorders a column, acquisition stops and leaves an `.incomplete` directory for investigation. Updating the contract requires a deliberate adapter version change.

### A lossless replay database

`pipeline/ingest_nyt_snapshot.py` validates the manifest and every file checksum before writing to SQLite. It stores:

- each source snapshot as a separate version;
- poll metadata;
- one question record for every question;
- every answer row in its original order, including independents, minor parties, undecided, “other,” and ranked-choice fields;
- presidential approval responses and the published approval-average rows; and
- the untouched source fields as canonical JSON alongside the useful indexed columns.

The adapter does not pivot a question into Democratic and Republican columns. A three-candidate R–I–D question remains three candidate options, and noncandidate answers remain separate responses.

Reingesting the same snapshot is a no-op. A later retrieval gets a distinct snapshot version, even if some or all source files have not changed.

### Conservative as-of replay

`pipeline/query_nyt_as_of.py` selects the last complete snapshot retrieved at or before a requested cutoff and exports its complete question vectors. The source's `created_at` value is preserved, but it is not used as publication time. Available documentation describes database creation rather than a guaranteed poll-publication timestamp and does not provide enough timezone semantics for leakage-safe replay.

Using snapshot retrieval time is conservative: a poll cannot enter a historical forecast until the project actually observed it in a completed pull. Frequent snapshots will make this bound more precise.

### Historical training inputs

The historical snapshot contains 17 sources:

- archived FiveThirtyEight Senate, House, governor, generic-ballot, and presidential-approval poll files;
- FEC certified federal election workbooks for every even-year cycle from 2010 through 2022, plus the House Clerk's official 2024 publication; and
- FiveThirtyEight's candidate-level House, Senate, governor, and race files as a convenient structured cross-check with row-level upstream source links.

The original FiveThirtyEight historical polling URLs now redirect to ABC News. The pipeline therefore uses Simon Willison's Git tracked archive of those published files, under its CC BY 4.0 license. Coverage differs by office: the Senate archive contains 2018, 2020, and 2022; the House archive spans 2017–2021; the governor archive spans 2018–2022; and the generic-ballot archive contains 2020 and 2022. This is enough to begin normalization, but Stage 2 must report the gaps and Stage 6 may require another licensed archive before strong multi-cycle backtesting claims.

The FEC workbooks are the certified authority for federal results. No federal agency publishes a single equivalent governor workbook. The aggregated governor archive is an acquisition aid whose rows cite many original sources; Stage 2 must reconcile the model's final governor totals against the cited state certification sources.

### Repeatable operation

`pipeline/run_stage1_pull.py` performs a live NYT snapshot and ingests it. Ubuntu systemd runs it daily; `--include-historical` adds the larger historical refresh for a weekly timer. `docs/stage1_operations.md` contains the exact commands and failure behavior.

## What the two observed pulls showed

| Measure | 01:57 UTC snapshot | 20:03 UTC snapshot |
| --- | ---: | ---: |
| Poll records | 3,637 | 3,648 |
| Questions | 5,134 | 5,150 |
| Answer options | 19,846 | 19,895 |
| Approval-average rows | 1,204 | 1,206 |

The combined content hash changed from `98f620...c8de` to `0df771...c1ec`. Senate question count stayed at 1,105; House increased from 1,382 to 1,389; governor from 1,130 to 1,131; other-office questions from 271 to 275; and approval questions from 1,246 to 1,250. This is a real source change, so the replay database correctly preserves both views.

## Stage boundary

Stage 1 identifies source records and preserves them. Stage 2 will map source race and candidate IDs to the project's race and ballot registries, quarantine ambiguous options, normalize historical sources, reconcile certified totals, and build the first fundamentals table. No poll row is ready for modeling merely because Stage 1 ingested it.
