# Stage 5 explainer: from vote shares to office winners

Stage 4 estimates each named candidate's share at the next voting stage. Stage 5 keeps those 75,000 joint draws and resolves the actual election rule in every draw. It assigns exactly one winner to each of 435 House races, 35 Senate races, and 36 governor races.

## What changed upstream

The smoke tests exposed several upstream problems: fusion lines could lose their major-party label, Senate transitions linked different seat classes, structural party absences entered the log-odds fit as near-zero vote shares, and a wide Gaussian minor-party coordinate inflated low median support into large arithmetic means.

Stage 3 version 1.4 fixes those paths. Senate history now follows the same seat six years apart; D/R persistence is estimated only from elections where both parties appeared; fusion labels retain a major-party nomination; and other-party support uses separate recurring and debut cases with arithmetic-mean calibration. On the 2024 holdout, winner log score is 0.2207 versus 0.2749 for the carry-forward baseline, candidate-share MAE is 0.0386 versus 0.0571, and nominal 95% coverage is 90.7%. Stage 4 also calibrates posterior covariance on 2018 and passes its independent 2020 gate.

## Election-rule modules

### Plurality

The candidate with the largest share wins. Exact ties use stable ballot-entry order so replay is deterministic. This module covers 477 races, including uncontested and same-party fields.

### Majority followed by a top-two runoff

If a candidate exceeds 50%, that candidate wins immediately. Otherwise the top two advance. The archive yielded 37 matched first-stage/runoff pairs. A model of runoff finalist log odds was fitted with ridge strength selected by leave-one-pair-out Brier score. It did not beat an uninformed forecast, so the accepted fallback gives either finalist a 50% conditional chance. It is more honest than presenting the weak fitted relationship as information. First-stage advancement and outright-majority probabilities still come from the full candidate draws.

Most two-candidate Georgia races cannot reach a runoff in this normalized candidate universe because one of the two necessarily exceeds 50%. Multi-candidate Louisiana races have explicit runoff probabilities and finalist-pair distributions.

### Ranked-choice voting

The archive contains seven races with published later rounds and ten usable elimination transitions. For each transition, vote gains among continuing candidates and exhausted votes identify a transfer profile by source and destination party group. Each historical elimination event receives equal evidentiary weight so a large electorate is not mistaken for millions of independent transfer observations. Weak Dirichlet priors regularize sparse cells, and a transfer profile is sampled for every simulation draw.

Within a draw, the module checks for a continuing-vote majority, eliminates the lowest candidate, transfers that candidate's votes, records exhaustion, and repeats. This resolves Alaska and Maine while retaining every candidate separately.

### Vermont governor

Under the [Vermont Constitution and Secretary of State guidance](https://sos.vermont.gov/vsara/learn/elections/majority-election), a candidate needs a majority; otherwise the General Assembly selects one of the top three. Vermont's archive says the Assembly has historically, though not always, chosen the plurality winner. The accepted default follows that convention. Each race record also stores conditional outcomes for an Assembly preferring the highest top-three D, R, or O candidate. These cases are sensitivities rather than weighted forecasts.

## Senate accounting

The [Senate's current lineup](https://www.dailypress.senate.gov/on-the-floor/senate-facts/) is 53 Republicans, 45 Democrats, and two independents who caucus with Democrats. The 2026 universe contains 22 Republican-caucus and 13 Democratic-caucus seats, leaving 31 R and 34 D caucus seats not up for election.

Candidate party and caucus are separate. An independent remains an independent winner on the race page. Chamber control is reported under three conditional cases: all O winners unaligned, all caucus with Democrats, and all caucus with Republicans. No overall Senate control probability is produced because the model has no defensible weights for those cases. With Republican Vice President JD Vance, Republicans organize a 50-50 chamber; the [Senate documents the vice president's tie-breaking role](https://www.senate.gov/legislative/TieVotes.htm).

## The two Alaska Sullivans

The Alaska Senate candidates are stored as two people with two candidate IDs:

- `PERSON-AK-DAN-S-SULLIVAN`: incumbent **Dan S. Sullivan**
- `PERSON-AK-DAN-J-SULLIVAN`: retired teacher **Daniel J. Sullivan Jr.**

Both advanced to the general election, as reported by [AP](https://apnews.com/article/f79df9852994692cf8bc555c6a7fdaf2) and [Roll Call](https://rollcall.com/2026/08/26/senate-ballot-in-alaska-will-feature-two-dan-sullivans/). The upstream shorthand “Dan J. Sullivan” remains traceable as `source_name`; Stage 5 displays the verified full name. No name-based deduplication is used.

## Current internal output

These are model diagnostics, not a publication recommendation:

- House mean elected seats: D 237.0, R 194.8, O 3.2.
- House control: D 81.8%, R 14.5%, neither 3.7%.
- Senate elected-seat means: D 15.37, R 19.50, O 0.13, before adding the 65 seats not up.
- Senate control if every O winner caucuses D: D 38.1%, R 61.9%.
- Senate control if every O winner caucuses R: D 36.7%, R 63.3%.
- With O winners unaligned: D control 36.7%, R control 61.9%, unresolved 1.4%.
- Governor winner means: D 19.81, R 15.96, O 0.23.

Stage 6 must test calibration across more cycles and lead times before these probabilities are suitable for a public site.
