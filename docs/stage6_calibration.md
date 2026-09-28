# Stage 6 calibration and public gate

**Stage 6 implementation and historical replay are complete. The version 0.20 prelaunch evidence gate passes 11 of 11 checks.** The `nowcast-2026-0.20` uses the NYT snapshot cut off at 2026-09-27 02:11:02 UTC and 75,000 aligned draws. The [gate report](../artifacts/calibration/stage6_public_gate.json) pins the data, source, model, and replay hashes. The passing Stage 6 review supports the published forecast with documented limitations; it does not establish nominal held-today probability calibration. The 2026 outcome is a postrelease evaluation, not a launch requirement.

## What is being estimated

The forecast asks who would win **if voting occurred at the information cutoff**. Certified November outcomes are useful diagnostics, but they include later opinion and turnout changes. They do not reveal the counterfactual vote at a cutoff 90, 30, or 7 days earlier. The historical polling archive was obtained after the elections; the replay excludes polls until fieldwork ends and the source creation date arrives, but it cannot rule out retrospective row revisions. See the [poll archive manifest](../data/reference/stage6_wayback_manifest.json) and [538 data description](https://github.com/fivethirtyeight/data/blob/master/polls/README.md).

## Results and geography

Stage 2 now has **3,597** exact or tolerant federal total reconciliations, **53** source-checked official candidate-row resolutions, and **eight** verified regular/special vote splits. The regular Senate replay covers **33 of 33 races in 2020, 34 of 34 in 2022, and 33 of 33 in 2024**; [the gap audit](../artifacts/calibration/stage6_historical_senate_gaps.json) lists no missing regular race. Special Senate elections are outside this historical replay. The 2024 House Clerk record is used to separate California's and Nebraska's regular and special Senate totals; Nebraska's Dan Osborn is classified as an independent from his official ballot label. The underlying sources are the [FEC federal election compilations](https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/) and [House Clerk statistics](https://clerk.house.gov/Members/ViewElectionInformation).

The joint replay counts **435 House seats in each cycle**. It has numeric vote shares for 434 seats in 2020 and 433 in both 2022 and 2024. The [House gap audit](../artifacts/calibration/stage6_historical_chamber_gaps.json) identifies the remaining unopposed races with no numeric vote total. Their certified winners enter the seat count as outcome-only observations; no vote shares are invented. The general fallback for a six-year House gap requires the prior winner to be on the new ballot. A new district with 90–95% usable old-map population receives extra prior uncertainty for the unknown remainder.

The [population crosswalk](../data/reference/stage6_house_population_crosswalk.json) uses 2020 Census block-group population centers to measure old-to-new district overlap. It covers all 435 target districts for 2020-to-2022 and 2022-to-2024. A block group can cross a boundary, and cartographic polygons are generalized, so this is a geographic prior rather than a vote retabulation. The [paired selection test](../artifacts/calibration/stage6_house_population_crosswalk_test.json) improves 2022 seven-day House winner log score from **0.206525 to 0.195616**. The previously inspected 2024 diagnostic changes from **0.160973 to 0.161699**, inside the prespecified 0.01 tolerance.

The [historical presidential map shifts](../data/reference/stage6_historical_house_map_shifts.json) use [The Downballot's district results](https://www.the-downballot.com/p/data). For each House transition, the shift is the change in Democratic-to-Republican presidential vote log odds from its selected old-map prior to the target map. Population-weighted priors use the same old-district population weights. The [paired diagnostic](../artifacts/calibration/stage6_historical_map_shift_audit.json) shows D/R log-odds RMSE falling from **0.2780 to 0.2660** in 2020, **0.2777 to 0.1872** in 2022, and **0.1568 to 0.1223** in 2024. These are terminal-result diagnostics on development cycles. The source percentages are rounded, and the shifts are not ballot-level retabulations.

## Dated polling and historical replay

The [national snapshots](../artifacts/calibration/stage6_national_snapshots.json) contain generic-ballot and presidential-approval polls at 90, 30, and 7 days in 2018, 2020, 2022, and 2024. The scored race replay uses historical 538 pollster-rating editions from 2019, 2021, and 2023; the 2026 live model gives the applicable [Silver Bulletin January 2026 rating](https://www.natesilver.net/p/pollster-ratings-silver-bulletin) precedence. Unrated pollsters get neutral weight and banned pollsters zero weight. Within-cycle historical rating revisions are unavailable.

The 2026 generic-ballot error variance includes the RMS of the 2020, 2022, and 2024 seven-day generic-to-final-House misses, **0.07966 D/R log odds**. The [pinned calculation](../data/reference/stage6_generic_error_calibration.json) does not apply a signed partisan correction. The current national center uses a stated **95% generic-ballot / 5% approval-conditioned** blend. Economic sentiment and war opinion are not model inputs.

The [candidate-level replay](../artifacts/calibration/stage6_repaired_race_replay.json) fits results on earlier cycles, uses a separate 2018 poll-error training archive, and screens Senate minor contenders. Seven-day Senate candidate-share 95% coverage against terminal results is **89.9% in 2020, 85.7% in 2022, and 93.5% in 2024**. The low 2022 coverage is material. It does not by itself identify an interval correction for the held-today target.

The [joint replay](../artifacts/calibration/stage6_joint_replay.json) aligns national, office, state, and race shocks; updates races with dated polls and pollster weights; and applies the jurisdiction's counting rule. Runoff and ranked-choice transfer fits use only earlier cycles. Georgia's 2020 regular Senate actual winner is the runoff winner. Final candidate rosters are still applied retrospectively at the early cutoffs.

The 2026-09-27 governor local-lean revision is recorded in [its expanding-cycle audit](../artifacts/calibration/governor_local_lean_audit.json) and [same-seed paired replay](../artifacts/calibration/governor_local_lean_paired_replay.json). The replay confirms exact House and Senate probability equality across paired runs and reports governor margin-interval coverage. The revised model improves later-cycle margin RMSE but has a slightly worse actual-winner log score and weaker coverage in the small cross-party incumbent subgroup. The previous governor open-seat adjustment is disabled. The owner accepted these limitations for publication. The version 0.20 public gate checks the corrected governor replay, model hashes, live forecast, and Missouri certified House candidates. The forecast artifact is marked public with these limitations documented.

| Seven-day replay | House D prediction, mean [95% interval] | Actual House D | Regular Senate D prediction, mean [95% interval] | Actual Senate D |
| --- | ---: | ---: | ---: | ---: |
| 2020 | 244.1 [226, 260] | 222 of 435 | 14.0 [10, 18] | 13 of 33 |
| 2022 | 219.5 [190, 250] | 213 of 435 | 14.7 [11, 19] | 15 of 34 |
| 2024 | 215.9 [180, 252] | 215 of 435 | 19.4 [16, 22] | 17 of 33 |

The 2020 House actual falls below its 95% terminal-result proxy interval. Its historical national-error estimate had only the near-zero 2018 generic-ballot miss available; the live 2026 model uses three later cycles and is wider. The 2022 and 2024 House and all three regular Senate terminal seat totals fall within their intervals. Three correlated elections cannot establish nominal chamber calibration. No partisan mean adjustment or Senate-specific interval multiplier was chosen to hide these proxy misses.

## Gate and remaining evidence

The [prelaunch gate](../artifacts/calibration/stage6_public_gate.json) passes the data and live validators, official House outcomes, population crosswalk test, dated national and pollster inputs, complete House and regular Senate coverage, and the live Missouri map check. Two additional reviews are now complete:

- **Governor approval:** [A paired 2020 replay](../artifacts/calibration/stage6_governor_approval_audit.json) found an average governor winner log score of 0.0402 with approval and 0.0410 without it across 11 races, five with approval values. The old feature affected 15 current governor races and moved one first-stage win probability by almost 8 points. The smoothed historical series ends in 2020. Morning Consult published a [2022 workbook](https://pro.morningconsult.com/instant-intel/democratic-governors-are-resisting-bidens-decline), while its [2024 historical file](https://pro.morningconsult.com/analyst-reports/us-governor-approval-outlook-october-2024) is listed as Pro+ access; complete dated later-cycle inputs are unavailable here. Version 0.18 disables the approval coefficient and all approval shifts in both live and replay forecasts. Morning Consult data remain an incumbent-identity cross-check.
- **2020 House miss:** The chronological seven-day forecast remains about 244 Democratic seats [226, 260] versus 222 actual. The [forensic audit](../artifacts/calibration/stage6_house_2020_audit.json) finds a 0.0816 D/R log-odds generic-to-final-House error against a 0.0081 national SD learned from 2018 alone. The 2026 generic-ballot SD is 0.0799, based on three later cycles. Applying that later-known scale to the 2020 replay only as a sensitivity check gives [202, 286], which contains 222. This cannot replace the original backtest or prove 2026 coverage. No signed partisan correction or post-hoc interval multiplier was added.

Earlier-cutoff election support is unobservable. The 2018 poll-error data and 2020-2024 cycles were inspected during development, so they are development evidence, not a pristine final holdout. The [prospective holdout protocol](stage6_future_holdout.md) and [frozen version 0.20 forecast](../artifacts/calibration/frozen_2026-09-27_v020/manifest.json) establish a postrelease evaluation against the 2026 outcome. This evaluation is not a prelaunch pass condition.

The [September 25 Supreme Court order](https://www.supremecourt.gov/docket/docketfiles/html/public/26A388.html) stays the lower-court orders requiring Missouri's 2025 map and leaves its 2022 map operative absent a further order. All eight Missouri presidential district shifts in the live model are zero, and Missouri now receives the same House prior uncertainty multiplier as other states. A future court order needs a new map check. All eight Missouri House candidate lists match the state-certified general-election list after documented display-name abbreviations.

The published forecast is a **conditional nowcast**, with Democratic House control **77.2%** and Democratic Senate control **57.1%** if other-party winners are unaligned or **69.9%** if all of them caucus with Democrats. The Senate values are separate caucus scenarios. The [joint chamber sensitivity](../artifacts/calibration/stage6_joint_chamber_audit.json) and [Senate input audit](../artifacts/calibration/stage6_live_senate_input_audit.json) provide current-draw and ballot/poll checks.

## Reproduction

After installing `requirements-stage6.txt` and restoring the pinned Stage 1, historical result, Census, and governor sources:

```bash
python pipeline/fetch_stage6_wayback_polls.py
python pipeline/fetch_stage6_historical_house_maps.py
python pipeline/build_stage2.py
python pipeline/validate_stage2.py
python pipeline/build_stage6_historical_house_map_shifts.py
python pipeline/test_stage6_house_population_crosswalk.py
python modeling/stage3_results_baseline.py --draws 50000
python pipeline/validate_stage3.py
python modeling/stage5_outcome_model.py --draws 75000
python pipeline/validate_stage5.py
python pipeline/run_stage6_calibration.py --draws 1000 --screen-senate-contenders --skip-supplemental --output artifacts/calibration/stage6_repaired_race_replay.json
python pipeline/run_stage6_joint_replay.py --cycles 2020 --leads 7 --draws 2000 --national-logratio-sd-floor 0.07994100533894001 --output artifacts/calibration/stage6_house_2020_forensic_floor.json
python pipeline/audit_stage6_governor_approval.py
python pipeline/audit_stage6_house_2020.py
python pipeline/freeze_stage6_holdout.py --output-dir artifacts/calibration/frozen_2026-09-27_v020
python pipeline/run_stage6_joint_replay.py --draws 2000 --no-governor-approval --paired-governor-output artifacts/calibration/governor_local_lean_paired_replay.json
python pipeline/build_stage6_public_gate.py
python pipeline/promote_stage6_forecast.py
```

The paired governor on/off reports were frozen under the previous model code before removal of the coefficient; the governor audit checks their hashes. The House forensic run uses later information only as a sensitivity, not as a chronological backtest. Source CSVs are checksum checked, and the published map-shift file contains derived differences rather than a copy of The Downballot's vote tables.
