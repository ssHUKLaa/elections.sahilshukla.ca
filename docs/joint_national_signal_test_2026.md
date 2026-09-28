# Poll-level national signal test (23 September 2026)

Run `python modeling/joint_national_signal_test.py --restore`. It restores the frozen source only if the local copy is missing, checks SHA-256, and writes [the cycle-level report](../artifacts/joint_national_signal_test.json). The historical CSV is intentionally excluded from Git; its URL and hash are in `data/reference/national_signals/source_manifest.json`. No live model coefficient or probability changed.

## Source and eligibility

The [FiveThirtyEight pollster-ratings raw polls](https://github.com/fivethirtyeight/data/blob/master/pollster-ratings/README.md) identify national generic-ballot questions as `House-G-US` and record a median field date, sample size, D/R responses, poll ID, and election cycle. The frozen file contains 883 such rows in 1998–2022. It is the set FiveThirtyEight used for **pollster ratings**, not necessarily a complete census of all generic polls. Approval comes from the [American Presidency Project's dated tables](https://www.presidency.ucsb.edu/statistics/data/presidential-job-approval-all-data); actual House vote comes from [Brookings](https://www.brookings.edu/articles/vital-statistics-on-congress/).

For each cycle we use nonpartisan national D/R polls with a median field date in the 60 days before a cutoff 43 days before Election Day. The primary analysis omits polls fielded in the final seven days before that cutoff, to reduce publication-date uncertainty. Averages are two-party D/R margins weighted by a 30-day recency half-life and the square root of sample size (capped at 3,000). There are 13 covered cycles, 1998–2022; each cutoff average has 3–23 polls (median 8). The rolling evaluation predicts 2008–2022, always training on earlier cycles only.

Two questions are tested: (1) does approval improve prediction of the **contemporaneous generic reading** beyond previous House vote; and (2) does it improve prediction of eventual House vote **after** the generic reading is known? The latter is not a held-today target, but it tests whether approval contributes to the historical election-outcome signal conditional on generic polling. The comparison uses the same fixed ridge specification and training-only scaling as the preceding [trendline ablation](national_signal_ablation_2026.md).

## Main results: seven-day field-date buffer

| Eight rolling held-out cycles | Generic / previous-House baseline MAE | Adding approval MAE | Baseline RMSE | Adding approval RMSE |
| --- | ---: | ---: | ---: | ---: |
| Predict cutoff-date generic reading from previous House vote | 5.51 | **4.90** | 6.56 | **5.62** |
| Predict eventual House margin from generic reading | **2.81** | 2.88 | 3.51 | **3.35** |

Approval improved eventual-outcome absolute error in 3 of 8 cycles. Results vary modestly with the date buffer: at zero days its addition changes MAE from 2.77 to 2.63; at seven days, 2.81 to 2.88; at fourteen days, 3.74 to 3.83. The fourteen-day pool can be as small as one poll in a cycle, so this is mostly a sparse-poll stress test. Approval improves the contemporaneous-generic proxy at all three buffers.

The 2020 cutoff illustrates the date problem. The seven-day rule includes 12 poll IDs; all match the earlier FiveThirtyEight archive with `created_at` timestamps, and **six were entered after the cutoff**. The 12-poll average is D+7.5; requiring `created_at` by the cutoff leaves six polls and gives D+7.9. A post-cutoff database entry does not prove the poll was unpublished then, but it prevents us from proving its archived row was available at the cutoff. Earlier cycles have no such timestamp in this source. Accordingly this is a **field-date reconstruction**, not a strict as-of backtest.

## Interpretation and release decision

The poll-level data strengthen the qualitative finding: approval has value when estimating national opinion without generic polling, while its incremental value after a generic reading is present is unstable and small in this sample. They do **not** identify the covariance of approval-prior and generic-ballot measurement errors for a held-today nowcast. Both measures are compared with eventual election results, which introduce subsequent opinion movement and a shared outcome error. A correlation of their eventual-result errors would not be the covariance needed for the present Gaussian update.

Keep the current forecast internal and retain the existing coefficients until the national update is replaced with a jointly validated model. A release-grade next dataset needs both field and first-publication dates, enough election cycles, and contemporaneous independent measurements of national support. The published [Algara et al.](https://www.cambridge.org/core/journals/ps-political-science-and-politics/article/forecasting-partisan-collective-accountability-during-the-2024-us-presidential-and-congressional-elections/9D6C577734D4FDB6CEED4256C60EE4BD) replication archive remains a possible route if its raw survey observations become accessible; the Dataverse endpoint currently responds HTTP 403 from this environment. Adding an arbitrary covariance or approval weight from these eight held-out elections would overstate what the data establish.
