# Stage 2 data-quality report

Source snapshot: `nyt:20260921T200327Z:21f40e0754570333`.

## Live poll mapping

| Office | Races with eligible polls | Eligible questions |
| --- | ---: | ---: |
| House | 78 | 159 |
| Senate | 24 | 279 |
| Governor | 27 | 228 |

Mapped candidate option rows: **2,236**. Quarantined option rows: **973**. A quarantined option makes its question ineligible; it is never silently dropped from an otherwise eligible vector.

Most quarantined rows are candidates appearing in hypothetical general-election combinations who are not in the current ballot registry. They remain available for review and future dated ballot scenarios.

## Historical inputs

Normalized historical poll questions: **14,976**.

Federal result cross-checks: **2,571 exact**, **471 within 0.1%**, **669 quarantined mismatches**, **64 missing on one side**.

The numerical federal baselines come directly from normalized FEC workbooks and the official 2024 House Clerk publication. The FiveThirtyEight archive is a cross-check: mismatched comparisons remain quarantined and do not replace the official values.

## Geography and baseline policy

Every one of the 506 races has a fundamentals record. All 435 House and 35 Senate records use an official prior federal result. Governor baselines use the latest comparable statewide result, retain upstream state-result links, and remain pending final official reconciliation. House results are never labeled as a validated 2026-boundary lean: same-number district results carry a 1.5 uncertainty multiplier and Missouri carries 2.0.

The companion JSON contains state, ballot-status, counting-rule, source-cycle, reconciliation, and top-unmapped-candidate detail.
