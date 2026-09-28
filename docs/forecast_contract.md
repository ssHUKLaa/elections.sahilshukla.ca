# 2026 nowcast data contract (draft 0.2)

This is the implementation contract for the [project plan](../PLAN_2026.md). Version 0.2 changes the target from eventual Election Day results to the result **if voting occurred at the information cutoff**. Stage 0–5 model artifacts produced before this change are legacy election-day forecasts and must not be labeled nowcasts. See the [retargeting plan](nowcast_remediation.md).

## Scope and unit of analysis

- One `race_id` identifies one office, jurisdiction, seat, election date, election type, and stage. A state can have multiple Senate races, and a seat can have a primary, general election, and runoff.
- Core universe: 435 voting House seats; 2026 regular and special U.S. Senate races; 2026 governor races in the 50 states. Nonvoting delegates and territorial governors are separate extensions.
- The primary share target is the **candidate vote-share vector if the listed election stage were held at `as_of_utc`**, including all qualified candidates who may plausibly win. Shares sum to one within each stage. For a possible runoff, apply the jurisdiction's subsequent counting or selection rule to that hypothetical vote; the winner is computed from all required stages. “Other/write-in” can be a residual category only when it cannot hide a plausible winning candidate.
- Every probability is conditional on the information available at `as_of_utc`. The nowcast includes uncertainty about support, turnout, polling, candidates, and counting rules **at that date**. It does not simulate campaign movement between `as_of_utc` and the scheduled Election Day. Any future-election projection would be a separately labeled product.
- Candidate win probability is the fraction of posterior predictive draws in which that candidate wins under the jurisdiction's counting rule. A two-party Democratic share is optional and defined only when both major parties have candidates; it is never the primary target.
- House and Senate seat distributions use joint draws across races. An independent winner remains independent in race output. Senate caucus alignment is a separately sourced scenario for chamber control.

## Identity and provenance

`race_id` is a stable project key. The current [race universe](../data/reference/races_2026.json) contains no candidate assertions; the separate [ballot registry](../data/reference/ballot_registry_2026.json) attaches candidates and source status. Reviewed state files override the exact-revision Wikipedia aggregation. `candidate_id` is a stable project person key, distinct from a source's candidate ID; `ballot_entry_id` connects a candidate to a particular race, ballot label, stage, and effective period. Names alone are not sufficient for future identity resolution. Source IDs are stored with their source name and snapshot hash.

Every race and ballot entry has a source URL, `verified_at_utc`, effective date where known, and verification status (`official`, `provisional`, `unresolved`). Registration or a poll appearance does **not** establish ballot qualification. Candidate withdrawal, replacement, and changed ballot labels create new versions, never silent edits. Keep endorsing party, ballot party, and expected Senate caucus in distinct fields. Caucus assumptions require a dated source or a clearly labeled conditional scenario.

Every poll keeps `source`, `poll_id`, `question_id`, `race_id`, field start/end, publication time if available, retrieval time, pollster, sponsor, mode, sample population, sample size, and all question options. Each option keeps its source candidate ID, printed answer, reported percentage, party label, and mapping status. Generic ballot, approval, primary, special, runoff, and general polls are separate observation types. “Don't know,” “someone else,” “would not vote,” and unnamed “other” are responses, not ballot candidates.

An as-of forecast may use a poll only after its publication time. If only `created_at` is available, its meaning must be verified before using it as a publication proxy. Preserve raw downloaded bytes with URL, retrieval UTC, size, SHA-256, and schema. The first [NYT snapshot](../pipeline/snapshot_nyt_polls.py) covers the six user-supplied URLs. Local raw snapshots live under ignored `data/raw/`.

## Election rules and publication

Each race records the counting rule and whether the November result is final or can advance to another selection stage. [Louisiana's 2026 House rule](https://www.sos.la.gov/elections-voting/types-of-elections) is a November 3 open primary: a candidate with a majority wins then; otherwise the top two proceed to a December 12 general election. Alaska and Maine federal races use ranked choice; Georgia uses a majority threshold and possible runoff; and [Vermont governor](https://sos.vermont.gov/vsara/learn/elections/majority-election) requires a popular majority or a General Assembly choice among the top three. Remaining general-election races use the plurality branch. Do not infer ranked-choice transfers or a contingent legislative choice from first-choice shares alone. Those branches need their own validated modules or explicit conditional scenarios.

For each published run, record `as_of_utc`, `model_version`, `data_snapshot_hashes`, `race_universe_version`, random seed, and candidate/ballot verification date. Publish candidate means, predictive intervals, and win probabilities only for races whose ballot mapping and counting rule passed validation. Show a clearly labeled scenario or data-status notice elsewhere. Do not make a 50/50 D–R placeholder for an unverified ballot.

House control counts voting House seats only. Senate control adds forecast seats to continuing seats, then applies caucus and vice-president assumptions dated to that run. Report conditional probabilities separately when an independent's caucus choice is unresolved.

## Validation gates

1. The race registry contains 435 voting House IDs and no Census `ZZ` or nonvoting `98` geography rows. Louisiana's six House IDs retain the open-primary and possible runoff branch. Any provisional governor or special Senate entry remains visibly provisional until an official ballot or election notice verifies it.
2. Every poll question's options map to exactly one race and either a verified ballot candidate or a noncandidate response category. Ambiguous or historical candidate sets are quarantined; they never enter the live fit silently.
3. Candidate shares are in `[0, 1]` and sum to one per race and draw. Candidate win probabilities sum to one when the rule produces one winner. Each House/Senate draw preserves its seat total.
4. Snapshot replay is idempotent. Source/schema changes stop the update and keep the last valid forecast labeled with its original `as_of_utc`.
