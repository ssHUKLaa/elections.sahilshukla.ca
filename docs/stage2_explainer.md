# Stage 2, in plain language

Stage 2 turns source rows into model-ready identities while refusing to guess when the evidence is ambiguous. Its output is `data/processed/stage2.sqlite`, rebuilt by `pipeline/build_stage2.py` from immutable Stage 1 inputs.

## Poll and candidate matching

Every NYT question is classified as a target race poll, national signal, other-office context, non-target stage, or unresolved race. Target races are resolved from office, state, district or seat, election date, and stage. Louisiana's November House `primary` label maps to the registry's open-primary stage.

Candidate options are resolved in this order:

1. a manually reviewed source candidate ID;
2. one exact normalized name within the mapped race; or
3. one unique first-and-last-name match within that race.

The match never uses party alone. Independents remain independent candidates. If a candidate-like answer does not resolve uniquely, the complete question is quarantined. Noncandidate answers and all original option rows remain stored.

In the current source snapshot, 2,236 option rows map to stable candidate IDs and 1,677 rows are retained as noncandidate responses. Another 973 candidate rows are quarantined, mostly because early or hypothetical matchups contain people absent from the current ballot registry. Four single-candidate questions are excluded because they contain no candidate contrast. This leaves 666 immediately eligible questions: 159 in 78 House races, 279 in 24 Senate races, and 228 in 27 governor races. Future ballot updates can release quarantined questions without changing their raw history.

NYT assigns source IDs and candidate-name fields to response buckets such as `Don't know`, `Someone else`, and `Would not vote`. Stage 1 classifies `party=NONE` rows as noncandidate responses before examining those fields, and Stage 2 has a regression gate for that rule. Alaska's Dan J. Sullivan and Dan S. Sullivan are mapped by two explicitly reviewed source IDs rather than an ambiguous name match.

## Historical polls

The builder normalizes 14,976 historical polling questions and 31,534 answer options. Senate, House, governor, generic-ballot, and presidential-approval series use one question table and one complete option-vector table. Historical `created_at` values retain an explicit timezone/publication warning and are not silently promoted to verified publication times.

## Official results and reconciliation

The pipeline normalizes 12,873 candidate result rows from the FEC workbooks for 2010–2022 and the House Clerk's official 2024 election publication. Those official rows supply every federal baseline. The structured FiveThirtyEight result archive supplies an independent comparison and governor history.

The aggregate federal comparison currently contains 2,571 exact matches and 471 differences no larger than 0.1%. There are 669 larger mismatches and 64 records missing on one side. These remain recorded for investigation; they cannot replace an official value. Differences commonly reflect blank or exhausted ballots, ranked-choice rounds, fusion-party reporting, specials, and differing treatment of write-ins.

Governor rows retain their upstream state-result links. They remain marked as pending final official reconciliation because the United States has no single federal governor-result authority equivalent to the FEC or House Clerk.

## Fundamentals

All 506 races receive a fundamentals record:

- all 435 House races use the latest official result for the same state and district label;
- Class II Senate races use the same seat's 2020 result, while the Florida and Ohio Class III specials use 2022;
- all 36 governor races use the latest structured statewide governor result with its source link; and
- 250 current ballot entries match the prior official or structured winner by a conservative normalized-name rule.

When a same-seat Senate result is structurally uncontested, the model keeps that race's winner identity but uses the nearest contested statewide Senate shares with a 1.25 uncertainty multiplier. Georgia's 2020 runoff uses the structured result archive because the normalized FEC rows do not contain that runoff. Both exceptions are explicit in the fundamentals evidence fields and validator.

The House value is a fallback result, not a claim that old votes have been reallocated to verified 2026 boundaries. If the latest House election lacked a Democratic or Republican nominee, its party shares come from the latest same-district election where both appeared; the latest winner identity is retained. Every House race carries widened uncertainty: 1.5 for ordinary same-label comparisons and 2.0 for Missouri while its 2026 plan remains unresolved. A future precinct crosswalk can replace these fallbacks race by race.

## Production environment

The acquisition schedule now targets the Ubuntu ARM Oracle OCI host. Hardened systemd service and timer templates live in `ops/systemd/`. They run the daily live pull and weekly historical refresh from `/opt/us2026forecast` using the repository virtual environment.

## What Stage 3 may assume

Stage 3 may use stable race and candidate keys, official federal result baselines, governor source links, ballot-rule metadata, explicit uncertainty multipliers, and only poll questions marked `model_eligible=1`. It must continue to generate forecasts for races without eligible polls and must treat the House fallback as noisier than a validated 2026-boundary lean.
