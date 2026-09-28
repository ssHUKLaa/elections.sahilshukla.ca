# National fundamentals signal ablation — preliminary (23 September 2026)

The reproducible script is `python modeling/test_national_signals.py`; machine-readable cycle results are in `artifacts/national_signal_ablation.json`. This analysis did **not** change the production forecast.

## Data and design

- Target and cutoff: national Democratic two-party House margin at the eventual election, and separately the generic-ballot reading 43 days before Election Day. The latter is a **proxy** for held-today national preference, not observed vote intention itself.
- Overlap: 11 elections, 1996–2016, from the frozen [FiveThirtyEight historical generic trendline](https://github.com/fivethirtyeight/data/tree/master/congress-generic-ballot), [Brookings House vote totals](https://www.brookings.edu/articles/vital-statistics-on-congress/), and dated [American Presidency Project approval polls](https://www.presidency.ucsb.edu/statistics/data/presidential-job-approval-all-data). The source files and checksums are already in `data/reference/`.
- Rolling test: start after five training elections; predict 2006, 2008, 2010, 2012, 2014, and 2016 using only earlier elections. The generic-only eventual-vote model adds the training mean of `outcome - generic` to the current generic reading. The approval variant fits that residual to president-party-signed net approval using ridge regression, with training-only standardization and fixed alpha 2.
- Current-generic proxy test: predict the cutoff-date generic reading from the previous House vote alone, then add signed presidential approval. Both use the same ridge procedure. The extra feature is evaluated on identical held-out cycles.
- The 2020 check uses 17 raw, dated likely/registered-voter generic polls in the 30 days before the cutoff, with poll creation dates no later than the cutoff. It is reported separately because a raw unweighted average is not methodologically comparable to the 1996–2016 reconstructed trendline.

## Results

| Held-out 2006–2016 election target | MAE, margin points | RMSE, margin points |
| --- | ---: | ---: |
| Raw generic reading | 3.09 | 3.21 |
| Generic plus learned historical correction | **1.54** | 2.75 |
| Generic plus correction informed by approval | 1.73 | **2.66** |

The approval version reduces absolute error in **one of six** held-out elections. Its small RMSE gain is driven by improving the largest miss, 2008; it worsens the other five absolute errors. This does not establish that approval has no value, but it provides no stable evidence for treating an approval-based prior as independent of a well-observed generic ballot.

| Held-out 2006–2016 current generic target | MAE, margin points | RMSE, margin points |
| --- | ---: | ---: |
| Previous House vote only | 5.87 | 6.80 |
| Previous House vote plus approval | **4.95** | **5.88** |

Approval improves current-generic absolute error in **five of six** cycles. This supports using approval in a structural estimate where generic polling is absent or thin. It does not establish the amount of independent information approval contributes *after* the generic reading is observed.

With ridge alpha 0.5, 2, and 8, adding approval after the generic reading has MAE 1.78, 1.73, and 1.64, all worse than the 1.54 generic-only correction. For the current-generic proxy, approval improves MAE at all three settings: 6.11→4.98, 5.87→4.95, and 5.37→4.86. These settings are sensitivity checks, not a new tuning search.

The separate 2020 raw-poll check has a D+8.67 generic reading and eventual D+3.09 House margin. The historical generic-only correction predicts D+5.40; adding approval predicts D+5.67. Both are too Democratic, and the approval addition slightly worsens this one election. The structural prior using only previous House vote predicts the contemporaneous generic reading at D+0.98; adding approval moves it to D+1.68, still far below the raw poll reading. The 2020 poll mix and trendline differ, so this is a stress check rather than a comparable seventh observation.

## Limits and decision

The historical FiveThirtyEight trendline was reconstructed in 2020; its daily values might use retrospective model settings or future information. We have **not verified strict as-of validity**. The raw 2020 poll mean is unweighted and has no pollster adjustment. Six rolling cycles cannot identify a stable national approval coefficient or error covariance. Both the election-outcome score and the contemporaneous-generic proxy fall short of validating held-today vote directly. The [Algara et al. replication archive](https://doi.org/10.7910/DVN/9ZWATQ) is cited in the paper but the Harvard Dataverse endpoint returned HTTP 403 from this environment; its raw historical poll series has therefore not been inspected or used.

**Decision:** retain the current model as an internal baseline, but do not claim that the present independent approval-plus-generic weighting is empirically calibrated. The test points toward approval as a prior for sparse generic data and suggests that a dense generic ballot should dominate the current national estimate. Before changing weights, acquire a strictly dated historical generic poll archive, fit their joint error/covariance with approval on cycle-blocked snapshots, and benchmark the change against the current model. Do not use these six cycles to set an ad hoc 2026 correction.
