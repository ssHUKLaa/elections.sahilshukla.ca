# Generic-first 2026 nowcast (version 0.5)

The 23 September 2026 NYT snapshot contains 219 eligible generic-ballot polls in the last 180 days, with an effective count of 76.45 after the existing quality, sample-size, and 30-day recency weights. Given that coverage and the [historical signal tests](joint_national_signal_test_2026.md), the live shared national D/R center now equals the quality-weighted generic-ballot reading. Presidential approval and previous House vote continue to produce a separately fitted structural diagnostic, but they no longer update that center as a second independent measurement. No hand-set approval coefficient or new national correction was introduced.

| Shared national House environment | Version 0.4 | Version 0.5 |
| --- | ---: | ---: |
| Fitted approval/previous-vote diagnostic | D+8.89 | D+8.89 |
| Quality-weighted generic ballot | D+7.10 | D+7.10 |
| **Live national center** | **D+7.85** | **D+7.10** |
| National D/R log-ratio standard deviation | 0.0687 | 0.0902 |

The old D+7.85 calculation remains in `artifacts/nowcast/model_parameters.json` under `approval_prior_plus_generic_legacy`; the Stage 3 structural prior plus generic is also retained as a sensitivity. The wider version 0.5 uncertainty is a direct consequence of removing the independent approval observation. Its size still comes from the provisional generic error calibration, which uses one 2020 terminal polling miss; it is **not** a validated held-today interval.

The full pipeline was rerun with `python pipeline/run_nowcast_refresh.py --skip-pull`, preserving the same `2026-09-23T17:21:36Z` NYT information cutoff, 75,000 simulation draws, and source snapshot. Stage 1, Stage 2, and Stage 5 validation passed. The change in control probabilities therefore reflects the national-signal rule, not fresh polls.

| Democratic control probability | Version 0.4 | Version 0.5 |
| --- | ---: | ---: |
| House | 80.94% | **73.53%** |
| Senate, all other-party winners caucus D | 60.11% | **57.13%** |
| Senate, other-party winners unaligned | 56.38% | **53.57%** |

The Senate figures remain conditional on independent/other-party caucus behavior; the model does not assign an unsupported overall scenario weight. The forecast remains internal while race-poll error, generic-ballot error, and held-today uncertainty are calibrated more fully. The version 0.5 validator explicitly requires the live national mean **and** standard deviation to match the generic signal, preventing accidental reintroduction of the old independent approval update.
