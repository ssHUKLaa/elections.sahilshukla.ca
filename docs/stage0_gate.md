# Stage 0 ballot and rule gate

Generated `2026-09-27T00:44:37.362437+00:00` from source-backed catalogs. This is a **coverage audit**, not a national certified candidate list.

| Check | Count |
| --- | ---: |
| Race universe | 506 |
| Races with candidate source entries | 506 |
| Races without candidate source entries | 0 |
| Candidate entries, including withdrawal/write-in records | 1414 |
| Races with counting rule pending | 0 |

## Ballot-source statuses

- `certified_list_ingested`: 112 races.
- `official_filing_list_reviewed`: 1 races.
- `official_list_reviewed`: 33 races.
- `official_list_unfinalized`: 15 races.
- `secondary_source_snapshot`: 345 races.

California, Texas, and Alabama lists are certified general-election sources. Washington's certified House entries were visually checked from a scanned PDF. Illinois is an active-candidate export that the state updates every 15 minutes and explicitly warns can change. Maryland lists active candidates; Maine has a general-election list with withdrawals tracked separately; North Carolina warns its list is not final. South Dakota and Montana were reviewed individually. Remaining races use exact-revision Wikipedia summary snapshots as the national aggregation layer. The [source cross-check](ballot_source_crosscheck.md) records differences. A source label only establishes what that version said; later corrections must create new snapshots.

## Uncovered candidate fields by office

- Senate: 0 races in 0 states: none.
- Governor: 0 races in 0 states: none.
- House: 0 races in 0 states: none.

## Election rules currently recorded

- `majority_then_legislative_selection`: 1 races.
- `majority_then_top_two_runoff`: 22 races.
- `plurality`: 477 races.
- `ranked_choice`: 6 races.

**Stage 0 gate: PASSED.** The planning inventory covers every race, candidate field, and counting rule. State-source verification, withdrawals, write-ins, fusion lines, and source changes remain recurring data-quality checks before any forecast run.
