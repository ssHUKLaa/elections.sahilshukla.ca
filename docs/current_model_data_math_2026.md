# Data and mathematics of the current 2026 nowcast

This describes the **running `nowcast-2026-0.20` model** in `artifacts/nowcast/`, using the NYT snapshot with information cutoff **2026-09-27 02:11:02 UTC**. The question is what would happen if voting took place at that cutoff. The model simulates 75,000 joint outcomes for 435 House, 35 Senate, and 36 governor contests. This is an implementation inventory, not a claim that its probabilities have passed the nowcast calibration stage.

## Data entering the run

| Data | Role | Local record |
| --- | --- | --- |
| NYT 2026 Senate, House, governor, generic ballot and presidential approval feeds | Live race poll answers and dates; generic-ballot D/R; latest presidential approval average | `data/processed/stage1.sqlite`; frozen snapshot ID in `artifacts/nowcast/model_parameters.json` |
| Reviewed 2026 race/ballot registry and counting rules | Candidate identity, party, ballot status, office, district, runoff/RCV rules, reviewed name aliases | `data/reference/ballot_registry_2026.json`, `data/reference/nyt_alias_reviewed_2026.json`, Stage 2 `races`, `candidates`, `current_question_map`, `current_option_map` |
| Federal Election Commission and House Clerk certified results, with 538 results as a cross-check; state-linked governor results | Previous-race baseline and historical candidate-share transitions | Stage 2 `fec_candidate_results`, `clerk_2024_candidate_results`, `historical_results`, `result_reconciliation`; source list in `data/reference/stage1_source_catalog.json` |
| Archived 538 polls | Historical poll-error fit and terminal comparison | Stage 2 `historical_poll_questions`, `historical_poll_options` |
| Brookings House popular vote, 1946–2024; UCSB presidential approval history | Approval-conditioned national House-vote regression | `data/reference/national_environment/` and its source manifest |
| 538 presidential and Senate results; FEC presidential check | State presidential lean and Senate local-lean regression | `data/reference/local_lean/` and its source manifest |
| 2024 presidential vote by old and 2026 House districts | District-boundary shift | `data/reference/house_presidential_2026/` |
| Morning Consult 2025 Q4 governor table | Incumbent identity cross-check only; approval forecast effect disabled | `data/reference/governor_approval/` |
| Silver Bulletin January 2026 pollster ratings, with 538 fallback | Live poll precision weights using stable pollster IDs | `data/reference/pollster_ratings/` |

Stage 2 has 762 eligible live race questions. The final forecast uses **682 race poll observations** with at least two positive, mapped candidate answers: 161 House, 281 Senate, and 240 governor uses. They reach 83 House, 26 Senate, and 28 governor races. A question's other answers remain in the database; unmapped candidate names are quarantined instead of silently treated as another ballot entry. Polls are only eligible if both fieldwork end and publication/availability precede the cutoff. The current generic-ballot calculation uses 219 polls from its last 180 days.
The NYT `other.csv` office feed is outside this three-office forecast. The live presidential approval *polls* are stored, but the national approval input is the NYT derived approval *average*, used once.

The Stage 3 transition fit filters the much larger historical archive to regular, first-round, reconciled races from 2002 onward. Its actual eligible sample is **2,790 House, 181 Senate, and 302 governor races**, producing **2,320, 96, and 253** paired transitions, respectively. The separate Senate local-lean fit uses 361 historical regular races from its own 538-based series. These counts describe different fits and must not be added as if they were independent observations of the same coefficient.

## Fundamentals: candidate-share prior

### 1. Previous result and party-group transition

Let `D`, `R`, and `O` denote Democratic, Republican, and all other candidate vote shares. The baseline uses the latest comparable prior result: generally the same House district label, the prior Senate class six years earlier, or the previous statewide governor race. Official federal rows are preferred; results that fail reconciliation are withheld. A structurally absent major-party nominee can trigger an earlier contested-result fallback. Stage 2 records a source ID and `uncertainty_multiplier` for every race. The current multipliers are House **1.5** (all 435 races), Senate **1.0** (33) or **1.25** (2), and governor **1.25** (36). Missouri's operative 2022 map matches the model and receives the same House multiplier. These geography/evidence multipliers are policy values, not coefficients estimated in Stage 3.

Historical zero shares receive a 0.5-vote Jeffreys adjustment for log-ratio arithmetic, while true absence from a ballot remains a structural zero. The two group coordinates are

`u = log(D/R)`, and `v = log((D+R)/O)`.

For an identified office-specific transition, the fitted center is approximately

`u_next = u_previous + a_office`, and `v_next = v_previous + b_office`.

The current `a` values are House **0.00915**, Senate **0.00087**, governor **−0.01117**; `b` values are **0.21031**, **0.30861**, **0.05812** in the same order. The unit slopes preserve prior partisan lean and recurring other-party share instead of shrinking every race toward 50/50. A major party returning after absence gets a pooled historical reentry center. When `O` newly appears alongside D and R, its office-specific prior *mean share* is fitted from past debuts: House **2.51%**, Senate **4.12%**, governor **5.15%**. These are pre-poll centers, not caps.

Prediction errors are decomposed into **global election**, **office/election**, **state/election**, and **race** Gaussian draws in `u,v`. Historical residual variances and office normalizers set their scales. The selected Stage 3 predictive covariance multipliers are currently **1.0 for both coordinates**. The Stage 2 race multiplier acts on the race-specific draw. These shared draws make state and national errors correlated across races.

Within a party group, named candidates divide group vote by a softmax of `incumbent_log_utility × incumbent + Normal(0, within_group_sigma)`. Both numbers are fitted from historical same-party multicandidate groups. Listed write-ins use sampled historical write-in shares. The candidate-specific vote vector is then normalized to sum to one.

### 2. Shared national environment

Define a two-party margin `m = (D−R)/(D+R)` and log odds `g = log(D/R) = log((1+m)/(1−m))`.

The historical approval model has **39 House cycles from 1948–2024**. For each cycle it uses previous House two-party margin, the president's party, whether it is a midterm, and presidential net approval available 43 days before Election Day. A recency-weighted ridge regression, selected by rolling earlier-cycle error, predicts eventual House margin:

`m_House = α + β₁ m_previous + β₂(president_party × midterm) + β₃(president_party × net_approval) + β₄ president_party + error`.

The fitted coefficients for this run are `α=0.01456`, `β₁=0.50798`, `β₂=−0.06816`, `β₃=0.08210`, `β₄=0.00016`; selected historical half-life **24 years**, ridge penalty **0.001**, rolling error SD **0.05268** in margin units. The current inputs are 2024 House margin **R+2.58** and the NYT 2026-09-26 approval average **36.8% approve / 60.2% disapprove**. The resulting structural benchmark is **D+8.87**. It predicts historical eventual votes, so its interpretation as current support is provisional.

The generic ballot is the primary current observation. Select one eligible question per poll, preferring likely over registered voters, then weight its `log(D/R)` by

`w_j = 2^(−age_days/30) × sqrt(max(n_j,100)/600) × pollster_quality_j`.

The 219 recent generic polls give weighted `g_generic=0.14525`, or **D+7.25**. Its SD is **0.07994** in D/R log odds: poll dispersion divided by effective sample size plus the RMS of the 2020, 2022, and 2024 seven-day generic-ballot misses against final House vote (**0.07966**). The [pinned calibration](../data/reference/stage6_generic_error_calibration.json) enters variance only and does not subtract the historical signed mean from current polls. The current model blends means on log odds:

`g_national = 0.95 g_generic + 0.05 g_approval = 0.14688` (**D+7.33**).

The **95/5 weight is an explicit modeling choice**, not a fitted coefficient. With the correlation between the two errors unknown, the model uses the upper SD bound `0.95 SD_generic + 0.05 SD_approval = 0.08125`; adding approval does not create extra precision. The model shifts all candidate D/R log odds by the difference between this shared national draw and the original Stage 3 national draw while retaining local differences and correlated draws. Independents are not multiplied by the D/R shift; all candidate shares are renormalized.

### 3. Local lean and additional fundamentals

For 2026 regular Senate races with both D and R candidates and the required history, a 361-race ridge fit predicts the Senate margin **relative to the national House margin**:

`Senate_local_lean = 0.00531 + 0.4060 × previous_same_seat_Senate_lean + 0.4587 × most_recent_state_presidential_lean + 0.07399 × signed_recurring_candidate`.

The ridge penalty is **0.1**, selected by expanding-cycle RMSE. Senate lean is in two-party margin units; a `+1` recurring-candidate indicator means a returning Democrat and `−1` a returning Republican. The target race mean margin becomes the drawn national House margin plus this local lean, with its preexisting local residual retained. This applies to **28** current Senate races. It is not applied to R–I or other ballots missing D or R.

Additional D/R log-odds shifts are fitted to residuals after removing each historical cycle's mean. Only races with both D and R receive them:

| Feature | Applied shift | Current fitted values |
| --- | --- | --- |
| House district map | `log(D_2024/R_2024 on 2026 map) − log(D_2024/R_2024 on old map)` | Direct vote calculation; no fitted coefficient; 435 map rows, 136 nonzero applied shifts |
| Open seat | coefficient times signed party of prior winner if that winner is not running | House **-0.14310**, Senate **-0.13745**; governor term inactive |
| Other candidate with prior elected-office win | coefficient times signed experience indicator | House **+0.08780**, Senate **+0.14477**; governor term inactive |

Governors use a separate local-lean model selected by expanding-cycle RMSE through 2018. The selected 2026 specification is `Governor_local_lean = -0.02151 + 0.4048 * prior_governor_lean + 0.3603 * most_recent_state_presidential_lean`, with ridge penalty 1.0 fitted to 234 eligible historical transitions. A race enters this fit only if both the prior and target ballot included D and R candidates. The audit also evaluates open-seat, candidate-experience, and signed-incumbent terms; the incumbent specification narrowly missed the pre-2020 overall selection score, so it remains a comparison rather than a selected input. Selected-model terminal-margin RMSE is 0.171 over 58 later-cycle cases. The fitted lean is added to the drawn national House margin, and its local residual spread is floored at out-of-cycle log-odds error, with larger empirical floors for cross-party incumbents and races where prior governor and presidential leans disagree. This broadens the fundamentals prior before polls are applied, giving polls more leverage in those races. Terminal results remain an imperfect proxy for held-today support and include later campaign movement.

The same-seed held-cutoff governor replay compares both methods in-process. It also records two-party margin interval coverage. See the [governor local-lean audit](../artifacts/calibration/governor_local_lean_audit.json), [forecast comparison](../artifacts/calibration/governor_local_lean_forecast_comparison.json), the [paired replay](../artifacts/calibration/governor_local_lean_paired_replay.json), and the revised [joint replay](../artifacts/calibration/stage6_joint_replay.json). Historical terminal outcomes remain an imperfect proxy for held-today support, and governor probabilities remain provisional.

The governor approval effect remains disabled pending dated historical validation. The [Stage 6 approval audit](../artifacts/calibration/stage6_governor_approval_audit.json) records that decision. Office feature coefficients and ridge penalties are selected by leaving whole election cycles out. Each log-odds shift multiplies D shares by `exp(shift/2)` and R shares by `exp(-shift/2)`, then renormalizes the full candidate vector. The paired additions are shown in `artifacts/nowcast/fundamentals_impact_2026.md`.

### 4. Unusual ballot structures

For a new `O` candidate beside D and R, historical local transition residuals give **1.278×** the ordinary race-level SD for `u=log(D/R)` and **1.028×** for `v=log((D+R)/O)`; both are applied to the local race error. If only one major party plus `O` appears, the old D/R transition does not identify the major-versus-independent share. A separate fit from **103** historical ballots (100 House, 2 Senate, 1 governor) selects a pooled `log(major/O)` center **2.223** and residual SD **2.047**. These rules depend on ballot structure, not state identity.

After race polls are assembled, the model also checks for prior–poll conflict **only in those two unusual classes**. It maximizes the Gaussian marginal likelihood of poll contrasts over a prior covariance multiplier `s ≥ 1`. For Montana Senate, the current fit is **4.7569**; five races in all have a value above 1.0001. This is learned from that race's polls, not a Montana constant. The fitted multiplier and poll leverage are recorded on each forecast race. Its uncertainty is conditional on the fitted `s`; variation in `s` itself is not integrated into the intervals.

## Polling: observation and update

The unit is a mapped, named-candidate poll question. For a question naming candidates `i` and `j`, the observation is `y_ij = log(reported_pct_i / reported_pct_j)`. A Republican candidate is the preferred reference when present, otherwise a Democrat, then the highest reported candidate. This preserves a direct D/R comparison on D–R–I ballots. Candidate answers that are absent or reported as zero do not create a log-ratio observation. Undecided and noncandidate answers are measured diagnostically but do not receive an explicit allocation model; the inferred named-candidate vector ultimately sums to one.

Historical 2018 poll errors versus final race results fit partially pooled ridge terms for pollster, office, population, methodology, sponsor, partisan/internal status, time before election, and sample size. A Senate-specific historical bias model can replace the D/R bias fit, but **the current nowcast calls the updater with `apply_election_day_bias=False`**: it does not subtract a 43-day-to-final-result mean correction. The historical residual variances *are* still used, including a nonzero shared race-error floor. A D/R contrast uses the fitted D/R variance; major/other uses `other_variance + 0.25 × D/R_variance`; same-group candidate pairs have a separate fitted variance. These historical-to-final error estimates still contain some campaign movement, a calibration limitation for a held-today model.

Live pollster quality uses Silver Bulletin's January 2026 Predictive Plus-Minus when a stable ID matches: `quality = (5.390 / (5.390 + PredictivePlusMinus))²`. A Silver-banned poll gets zero. If Silver lacks that ID, 538's numeric grade gives `sqrt(grade/2.057)`; unrated polls get 1. This affects the effective weight, not a separate signed pollster shift. The current raw NYT numeric-grade field is blank, so the external rating tables supply ratings.

Each live race poll contrast has weight

`w_j = 2^(−age_days/30) × sqrt(max(sample_size,100)/600) × quality_j`.

The **30-day half-life** and sample-size scaling are current implementation choices. For each repeated candidate contrast, `y` is the weighted mean and its approximate variance is

`V = shared_race_error + max(total_error − shared_race_error, 0.01) / sum_j w_j`.

Thus adding polls reduces the independent part but not the shared floor. The current likelihood treats different aggregated contrasts as diagonal errors, even when contrasts from the same survey share a reference candidate; that covariance is a remaining modeling simplification.

Let `z` be the vector of candidate log shares relative to the last ballot candidate, `z_k=log(p_k/p_last)`. A Ledoit–Wolf covariance `P` is estimated from prior draws. With observation matrix `H`, poll vector `y`, diagonal error matrix `R`, and unusual-ballot scale `s` (otherwise 1), the Gaussian update is

`P_post = ((sP)^−1 + Hᵀ R^−1 H)^−1`,

`μ_post = P_post((sP)^−1 μ_prior + Hᵀ R^−1 y)`.

The model affinely transforms prior draws to this posterior mean/covariance and applies a softmax back to vote shares. If an independent is omitted by the polls, its prior mass is preserved and the observed candidates split the remainder. If a race has no usable poll, its candidate-share draws remain the fundamentals/national prior. The poll-leverage diagnostic is the diagonal of `H(sP)Hᵀ [H(sP)Hᵀ+R]^−1`; it varies by contrast and is not a literal fraction of vote share.

Finally, each share draw is processed under the race's plurality, top-two/runoff, ranked-choice, or Vermont legislative-selection rule. Candidate wins are counted jointly across the 75,000 draws. Senate control is shown under explicit scenarios for how any `O` winner caucuses; the Republican vice president breaks a 50–50 tie in the current accounting.

## What is fitted, chosen, and still absent

| Type | Current examples |
| --- | --- |
| Historically fitted | Stage 3 transition means and error components; national approval regression; Senate local lean; candidate/open-seat coefficients; historical polling residual and shared variances; within-party allocation; structural debut SD ratios |
| Estimated from current polls | Generic-ballot weighted mean; race contrast means; unusual-race prior-conflict scale |
| Chosen or fixed | 95/5 generic–approval blend; 30-day poll half-life; 180-day generic window; `sqrt(n/600)` sample-size factor; Stage 2 geography multipliers; Silver/538 quality mappings; no election-day mean bias correction; 75,000 draws |
| Not a live input | Economic sentiment, views of the war, campaign finance, a separate FLIPR likely-voter adjustment, or an independent use of the raw presidential approval polls alongside their derived average |

The [Stage 6 prelaunch review](stage6_calibration.md) is complete. Stage 3 prior errors and race-poll floors were learned largely from final election results; the generic-ballot floor uses three terminal-result proxy cycles and cannot isolate current support from later movement. The 5% approval-conditioned national blend and unusual-race conflict rule remain stated modeling choices with limited historical evidence. Public methodology should describe these limits and should not claim nominal held-today probability calibration.

## Code and exact run values

- `modeling/stage3_results_baseline.py` — group transitions, covariance, candidate allocation.
- `modeling/national_environment.py` and `modeling/senate_local_lean.py` — national benchmark and Senate local lean.
- `modeling/fundamentals_features_2026.py` and `modeling/structural_uncertainty_2026.py` — current additional fundamentals and unusual ballots.
- `modeling/pollster_quality.py` and `modeling/stage4_poll_model.py` — quality weights, poll likelihood, Gaussian update.
- `modeling/stage5_outcome_model.py` — nowcast assembly and counting rules.
- `artifacts/nowcast/model_parameters.json` — fitted values, input hashes, limitations; `artifacts/nowcast/forecast_2026.json` — race-level diagnostics and results.
