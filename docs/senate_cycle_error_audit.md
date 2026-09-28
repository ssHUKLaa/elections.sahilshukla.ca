# Senate polling error shared across a cycle

`python pipeline/audit_senate_cycle_error.py` reproduces the [numeric report](../artifacts/senate_cycle_error_audit.json). It fixes the selected directional model form and fits its coefficients using only earlier-cycle polls for each whole-election check. The model form was selected on 2016–2022; only 2024 is untouched by that choice. The residual is the corrected D/R poll margin minus the eventual D/R vote margin, in approximate percentage points. A positive value means the corrected polls still overstated Democrats.

| Held-out cycle | Races | Mean residual | Race RMSE |
| --- | ---: | ---: | ---: |
| 2016 | 15 | D+0.38 | 7.86 |
| 2018 | 13 | D+5.46 | 8.79 |
| 2020 | 9 | D+5.50 | 7.19 |
| 2022 | 9 | D+3.29 | 7.20 |
| 2024 | 15 | D+0.62 | 5.20 |

Using the first four folds to estimate variation gives a **7.07-point within-cycle race error SD** and a **1.13-point extra shared-cycle SD** after subtracting the sampling variance of each cycle mean. Adding that estimated shared term changes the untouched 2024 joint predictive log density from **−47.18 to −47.33**, a slight worsening. One held-out cycle and four tuning cycles provide weak evidence about the correct covariance, so this exercise does not justify changing the live forecast's shared polling-error setting yet.

This audit addresses uncertainty around the cycle-wide error, not whether a correction trained on a RealClearPolling-derived archive should have the same mean for NYT polls in 2026. The historical target also combines survey error with movement between fieldwork and Election Day. The [race trace](senate_race_trace_2026.md) identifies that source-transfer question as the main unresolved issue for the headline forecast.
