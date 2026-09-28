# Senate poll correction recalibration

**Legacy election-day target:** This calibration predicts the eventual result from a 43-day cutoff. The project target was clarified on 23 September 2026 as an election-held-today nowcast. The correction and the 38.1% artifact below are **not validated for that target**; see the [retargeting plan](nowcast_remediation.md).

**Snapshot:** September 21, 2026, 20:45:24 UTC. The accepted Stage 5 forecast remains internal.

## What changed

The Senate D/R polling correction no longer takes its directional mean from 2018 alone. [`modeling/senate_poll_bias.py`](../modeling/senate_poll_bias.py) uses a frozen [RealClearPolling-derived Senate archive](https://github.com/Jack-Whitcomb/All-US-Senate-polls-2006-2024) for the 2010–2024 cycles. The hash-verified source has **984 eligible polls in 112 matched regular Senate races** across eight cycles. Race matching requires a unique official-result race in the state and year; special or ambiguous races, questions lacking both major parties, duplicates, and polls after the historical cutoff are excluded. The model does not redistribute raw poll rows. [Source rights are recorded separately](data_rights.md).

For each election, the exercise reconstructs the forecast at **43 days before Election Day**. Each poll observes a D/R log ratio. The target is that ratio minus the eventual D/R vote log ratio, so the fitted correction includes both survey error and any change in voter preference between fieldwork and the election. Polls receive a 30-day recency weight within that historical as-of snapshot. Each race contributes equal total fitting weight within a cycle, and each cycle contributes equal total weight. This prevents a handful of heavily polled races or one year from deciding the national correction.

A ridge model may use a pooled intercept, pollster identity, likely-voter/registered-voter population, and sample size. Its specification and penalty were selected by rolling whole-cycle race-level RMSE on 2016, 2018, 2020, and 2022. Each fold trained only on earlier elections. The 2024 cycle was reserved for an independent check, then included in the final 2026 fit. For the Stage 4 2018 inflation calibration, the Senate correction trained only through 2016; for the 2020 holdout, it trained only through 2018; and for the 2024 holdout, only through 2022. The live 2026 model uses the final 2010–2024 fit.

## Held-out results

On the same 15 regular 2024 Senate races and 165 polls, approximately converted to D/R margin points:

| Correction | Race-level RMSE | Race-level MAE | Mean signed residual |
| --- | ---: | ---: | ---: |
| No correction | 7.11 | 5.63 | D+4.64 |
| Old 2018-only correction | 5.79 | 3.87 | D+1.48 |
| **New multi-cycle correction** | **5.20** | **3.42** | **D+0.62** |

These numbers come from the reproducible [comparison artifact](../artifacts/senate_poll_bias_comparison.json). A positive signed residual means the corrected polls still overstated Democrats relative to eventual results. The 2022 check, trained only through 2020, retains a D+3.52 mean residual and 7.31-point RMSE across nine races; the historical correction is not exact or guaranteed to repeat in 2026.

The full Stage 4 check now records candidate-share coverage by party group. Democratic and Republican 95% share intervals each covered **93.3%** of the 2020 Senate holdout; in 2024, coverage was **92.3% D** and **100% R**. These pass the explicit 90% major-party acceptance threshold. Other-party coverage was **55% in 2020** and **66.7% in 2024**, so the all-candidate 95% coverage remains below nominal. The 2024 full-model check uses poll fieldwork end dates as provisional availability dates because the archive lacks publication timestamps. That date approximation can admit a poll slightly too early near the cutoff.

## Effect on 2026

The original full 75,000-draw run after this recalibration put Democratic Senate control at **37.6% if every other-party winner caucuses with Democrats**, versus **39.5%** with the previous 2018-only correction. A later [verified prior-winner name-match repair](senate_race_trace_2026.md) raised the accepted figure to **38.1%**; the current paired no-correction diagnostic is **65.2%**, and it is not a calibrated alternative forecast. The multi-cycle evidence supports retaining a Republican-favouring Senate poll adjustment of roughly 3–4 D/R margin points for a typical current poll. It does not establish that its full size transfers to the live NYT source.

The weighted current-poll adjustments explain why control moved slightly further toward Republicans. In approximate D/R margin points, the old correction versus the new correction is **Iowa 3.22 → 3.64**, **Maine 3.30 → 4.36**, **Michigan 2.96 → 3.92**, and **Ohio 2.64 → 3.73**. Alaska moves in the other direction, **3.94 → 3.46**. These are averages over each state's accepted named D/R polls, not forecasts of the vote margin. The [comparison artifact](../artifacts/senate_poll_bias_comparison.json) records every state's values.

The [updated component audit](senate_component_audit.md) details national, local, polling, and shared-error effects. The 30-day live race-poll half-life and the minor-party share distribution remain separate issues requiring further validation. The new source repository has no explicit redistribution license; keep the raw archive internal until terms are verified before website publication.
