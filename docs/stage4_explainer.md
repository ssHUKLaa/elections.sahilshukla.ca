# Stage 4: candidate-vector polling update

**Target notice:** This stage's historical error fit and holdout scores use eventual Election Day results from an earlier cutoff. They do not validate the [election-held-today nowcast target](nowcast_remediation.md) adopted on 23 September 2026.

## Purpose

Stage 4 asks whether mapped race polls improve the results-only Stage 3 forecast at a comparable historical cutoff. It admits race polling only after a frozen 2020 holdout improves a proper winner score and retains adequate overall interval coverage. It also includes a fitted postwar national House vote model and current generic ballot in the 2026 forecast.

The artifact remains internal. It estimates first-stage candidate shares and plurality winners, but it does not yet model ranked-choice transfers, runoffs, Senate caucus choices, or chamber control.

## Current inputs

Stage 2 marks 666 current questions as model eligible. Questions from the same source poll and race are dependent, so Stage 4 retains one question with the most mapped candidates from each poll-race cluster. This leaves 603 question-race observations covering:

| Office | Poll-updated races | Stage 3 prior only |
| --- | ---: | ---: |
| House | 78 | 357 |
| Senate | 24 | 11 |
| Governor | 27 | 9 |

Every used race records its exact poll IDs, question keys, pollsters, latest end date, and mean noncandidate response. Unmapped or quarantined options do not enter the likelihood. All 506 races receive the same sampled national-environment update, including races without a mapped race poll.

## Candidate-vector likelihood

For a race with candidate shares `p = (p1, ..., pK)`, Stage 4 works in candidate log ratios against a reference candidate:

```text
z_k = log(p_k / p_K),  k = 1, ..., K-1
```

Each question supplies contrasts only between named candidates it actually includes:

```text
y_i,ab = log(poll_pct_a / poll_pct_b)
y_i,ab = H_ab z + bias_i,ab + error_i,ab
```

This handles D–R, R–I, R–I–D, same-party, and larger candidate sets without manufacturing a missing Democratic or Republican option. Noncandidate answers such as undecided remain in diagnostics and are not relabeled as candidates. Candidate percentages are interpreted conditionally on the named candidate responses in that question.

Stage 3 draws provide a logistic-normal prior. The Gaussian update is:

```text
V_post = inverse(V_prior^-1 + H' R^-1 H)
m_post = V_post (V_prior^-1 m_prior + H' R^-1 y)
```

The posterior mean and covariance are applied to the existing Stage 3 draws with an affine transform. This preserves the national, office, state, and race dependence already present in the joint simulation. A covariance inflation factor is selected on 2018 from `{1, 1.25, 1.5, 2, 2.5, 3}` using winner log score subject to coverage constraints; the accepted factor is **1.25**. The accepted Stage 3 distribution remains stored beside every candidate so the effect of subsequent signals is auditable.

## Generic ballot and presidential approval

The national update first replaces the Stage 3 aggregate House vote center with a fitted postwar estimate. The race draws retain their local differences. It then uses the generic ballot as one additional measurement of the national D/R environment before race polls are applied.

For regular Senate races with sufficient historical data, a later [local-lean fit](senate_local_lean_rebuild.md) replaces the race D/R mean using the previous same-seat result, earlier state presidential lean, and returning-candidate evidence. It was selected on held-out Senate cycles and retains the existing correlated uncertainty draws. Two-party special elections and races without a usable prior retain their earlier baseline.

The NYT generic-ballot questions are deduplicated by poll and population, then combined with the same 30-day half-life used for race polling. The source aggregation implies approximately **D+6.8**. Its uncertainty includes the observed miss between the comparable 43-day 2020 generic-ballot average and the official 2020 House popular vote.

The historical national model fits 39 election cycles using Brookings House results since 1946 and dated presidential approval from the American Presidency Project. It uses the prior House vote, presidential party, a midterm indicator, and party-signed net approval. A 24-year recency half life was selected on rolling pre-2018 validation. The September 21 NYT approval average of 37.7% approve and 59.4% disapprove gives a fitted **D+8.73** House vote estimate, with a 5.27-point rolling historical error. See [the full rebuild](national_environment_rebuild.md).

The current generic ballot implies D+6.76. Combining it with the fitted historical estimate yields **D+7.89**. Their forecast-error covariance is not identified by the available generic-ballot archive, so the current calculation treats them as conditionally independent and remains internal. The Stage 3 aggregate center was D+2.27; it no longer acts as another national observation.

| National-signal scenario | Implied Democratic two-party margin |
| --- | ---: |
| Historical fundamentals only | +8.73 |
| Fundamentals and raw generic ballot | +7.89 |
| Generic error doubled | +8.42 |
| Fundamentals error doubled | +7.25 |
| Fundamentals and dated FLIPR-adjusted generic ballot | +8.67 |

These national signals are included in the 2026 artifact but excluded from the 2020 race-level backtest. Their impact is therefore an explicit modeling assumption supported by sensitivity analysis, rather than a backtested Stage 4 improvement claim.

## Poll-error model

The historical model uses 2018 as its calibration cycle. It fits separate errors for:

```text
log(D/R)
log((D+R)/O)
```

Predictors are office, pollster, population, methodology, sponsored versus unsponsored status, partisan/internal labels, days before the election, and sample size. Categorical effects receive ridge partial pooling. The penalty is selected with grouped cross-validation so questions from one race remain in the same fold.

The selected penalties were 1,000 for `log(D/R)` and 100 for major-party versus other share. The calibration contains 601 D/R observations and 108 observations with measured other-party support. Same-party candidate contrast variance is estimated separately by office.

Questions from the same source poll and race are collapsed before fitting or forecasting. Across distinct polls, recency and sample size determine relative precision. Historical training selected a 120-day half-life from the fixed grid `{14, 30, 60, 120}` days. The current 2026 forecast uses an explicit 30-day half-life so recent race polls carry more weight. Historical backtest scores still use the selected 120-day value; the 30-day live setting has not been separately backtested.

The likelihood retains an empirical race-level shared-error floor by office and coordinate. As a result, ten polls cannot reduce forecast uncertainty as if they were ten independent random samples. Historical poll error also includes campaign movement between each poll and Election Day; a poll's reported sampling margin is not treated as total forecast error.

## Comparable-cutoff backtest

The current information cutoff is 43 days before the 3 November 2026 election. Stage 4 therefore evaluates only historical questions available at least 43 days before the 2020 election. Source-created timestamps have an unverified timezone, so the backtest compares calendar dates and records that limitation.

The frozen 2020 test contains 92 races with usable candidate contrasts:

| Metric | Results only | Polls only | Combined |
| --- | ---: | ---: | ---: |
| Winner log score | 0.5040 | 0.8681 | **0.4182** |
| Multiclass Brier | 0.3417 | 0.5121 | **0.2831** |
| Candidate-share MAE | 0.0434 | 0.1344 | **0.0349** |
| 80% interval coverage | 83.5% | 75.9% | 75.9% |
| 95% interval coverage | 91.3% | 91.2% | 91.4% |

Polling alone is worse than results alone overall. The combined update improves both proper winner scores and share error, showing that the polls add information when constrained by the results prior and historical error model.

Polls update only the candidates they name. The total simulated mass of omitted candidates is retained from the prior in each draw, so a D/R poll cannot accidentally turn an unpolled independent into the favorite through a singular candidate-log-ratio transform.

Office-level results remain noisier for the small Senate and governor subsets; Stage 6 carries those calibration checks forward.

## Signal evidence boundary

The 2020 holdout validates the race-poll update. The national fundamentals model has separate time-ordered evaluation through 2024. The combined national update lacks enough historical generic-ballot cycles to estimate its joint forecast-error covariance or validate the combined stage end to end.

## Outputs

- `artifacts/stage4/model_parameters.json`: fitted effects, uncertainty terms, signal decisions, and holdout results.
- `artifacts/stage4/forecast_2026.json`: candidate distributions, Stage 3 comparisons, poll provenance, and 75,000 joint draws summarized as seat PMFs.
- `modeling/stage4_poll_model.py`: calibration, likelihood, backtest, and forecast implementation.
- `pipeline/validate_stage4.py`: forecast invariants, poll coverage, prior-only equality, seat accounting, and deterministic replay.

## Reproduce on Ubuntu ARM

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-stage4.txt
.venv/bin/python modeling/stage4_poll_model.py --draws 50000 --seed 20260921
.venv/bin/python pipeline/validate_stage4.py --check-reproducibility
```

The implementation uses NumPy, SciPy, and scikit-learn and does not depend on Windows scheduling or x86-specific code.
