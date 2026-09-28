# Governor fundamentals revision: implementation plan

## Implementation results (2026-09-27)

Refreshed as `nowcast-2026-0.20` and subsequently approved for publication with documented limitations. The training builder now requires Democratic and Republican candidates in both governor races, removing Alaska's ineligible 2014 and 2018 transitions; 234 transitions remain. The selected pre-2020 specification remains prior governor lean plus presidential state lean, with ridge penalty 1.0 and full-history coefficients -0.02151, 0.40479, and 0.36026. Later-cycle margin RMSE is 0.171 on 58 races; the prior-governor-only candidate's best tuning-selected penalty gives 0.190.

The audit now reports incumbent-running, open-seat, cross-party incumbent, local-signal disagreement, and strongly partisan subgroups for every tested specification. An incumbent term narrowly missed the pre-2020 overall selection score (0.1446 versus 0.1422 RMSE), although it improved later-cycle overall RMSE and the small cross-party incumbent subgroup. It was not substituted based on those later outcomes. The selected model's cross-party incumbent subgroup has 9 later races and RMSE 0.259, so forecasts in this class remain a known weakness.

Governor draw spread is now floored at expanding-cycle out-of-fold log-odds error. For races flagged as cross-party incumbent or conflicting local signals, the floor uses the larger subgroup error scale when at least five prior out-of-fold cases support it. The pooled 2020-2024 residual SD is 0.368; it is 0.569 for cross-party incumbents (9 cases) and 0.555 for disagreeing local signals (16 cases). This is applied before poll assimilation, so polls naturally have more influence when the fundamentals prior is less certain.

The paired historical replay was rerun in-process with sorted state draw order and identical seeds for old and revised methods. House and Senate race probabilities match exactly. Across 174 governor race-cutoffs, the old/new actual-winner log loss is 0.1731/0.1763. Revised vote-margin interval coverage is 81.0% for nominal 80% intervals and 94.8% for nominal 95% intervals. Cross-party incumbent coverage is 77.8%/88.9% over 27 race-cutoffs, representing only 9 distinct races. These terminal-result checks are imperfect proxies for held-today outcomes; the win-score regression and cross-party subgroup result keep this forecast provisional.

The current 2026 refresh uses the 2026-09-27 poll snapshot and 75,000 draws. It assigns Oklahoma's Cyndi Munson a 29.6% win probability and expected D/R shares of 43.2%/54.0%, with no Oklahoma-specific factor. In Vermont, expected D/R shares are 45.9%/48.8%; the wider cross-party-incumbent uncertainty produces a 45.1% Democratic win probability. Current House and Senate candidate probabilities are unchanged from version 0.19.

Artifacts:

- `artifacts/calibration/governor_local_lean_audit.json` - eligible rows, exclusions, model selection, subgroup scores, and uncertainty scales.
- `artifacts/calibration/governor_local_lean_forecast_comparison.json` - all 36 governor changes from version 0.19 to 0.20.
- `artifacts/calibration/governor_local_lean_paired_replay.json` - same-seed old/new winner scores and margin interval coverage.
- `artifacts/calibration/stage6_joint_replay.json` - revised joint replay.
- `artifacts/nowcast/` and `artifacts/nowcast_history/2026-09-27/` - refreshed forecast and daily snapshot.

The owner accepted version 0.20 for publication with the cross-party incumbent weakness and slight historical winner-score regression documented above. The corrected replay disables governor approval, the version 0.20 public gate passes 11 of 11 checks, and the live forecast is marked public. The prior forecast/replay backup from version 0.18 was retained locally during development and is excluded from deployment.

## Goal

Improve the 2026 governor nowcast's local baseline without a rule for Oklahoma or any other individual state. Keep the forecast target as **the result if voting occurred at the information cutoff**. The current Oklahoma forecast is a useful diagnostic: it has no usable governor polls, its baseline is R+8.95, and the fitted open-seat shift moves it to D+2.93. A revised model must be selected on historical evidence, not by whether it produces a preferred Oklahoma result.

This work changes governor fundamentals only. Preserve the House and Senate methods, the candidate-vector poll update, counting rules, and the website's forecast contract.

## Existing code and data

- `modeling/stage3_results_baseline.py`: historical governor races, transitions, current races, and the Stage 3 baseline.
- `modeling/fundamentals_features_2026.py`: current open-seat and candidate-experience fit. The governor open-seat coefficient is approximately -0.2555 in Democratic/Republican log odds. Its current application to Oklahoma is +0.2555 because the previous winner was a Republican who is not running.
- `modeling/senate_local_lean.py`: existing pattern for a state local-lean fit and expanding-cycle evaluation. `data/reference/local_lean/presidential_results.csv`, `data/reference/local_lean/senate_results.csv`, and the source manifest support it.
- `modeling/national_environment.py`: historical national House vote, needed to express governor outcomes and prior results relative to their election-year national environment.
- `modeling/stage4_poll_model.py`: inserts the current national signal and Senate local lean into candidate-share draws.
- `modeling/stage5_outcome_model.py`: applies additional fundamentals, polls, counting rules, and paired impact steps.
- `pipeline/run_stage6_joint_replay.py`: historical cutoff replay. `pipeline/run_nowcast_refresh.py --skip-pull` rebuilds current artifacts using the saved poll snapshot.

Before editing, save the current forecast, model parameters, fundamentals impact, and source hashes under a distinct comparison directory. Do not silently overwrite the dated baseline used for the before/after comparison.

## 1. Build an auditable governor training table

Add a dedicated governor local-lean module, following the source checks and report pattern in `modeling/senate_local_lean.py`. Use only historical general-election races with a Democratic and Republican candidate and a usable prior governor result. For target election year `t`, define all vote margins on a **two-party D-minus-R scale**:

- `target_lean = governor_margin_t - national_House_margin_t`;
- `prior_governor_lean = governor_margin_previous - national_House_margin_previous`;
- `presidential_lean = most_recent_presidential_state_margin_before_t - national_presidential_margin_that_year`;
- `open_seat_signed = +1` for a prior Democratic winner absent from the target ballot, `-1` for a prior Republican winner absent, and `0` otherwise;
- `other_prior_elected_winner_signed` with the existing historical identity rule, if retained as a candidate feature.

Use the previous governor election actually available before `t`, including states with nonstandard election years. Record the source election years and exclude any feature that would not have been known before the historical target election. Reuse reviewed candidate identity logic; do not treat a shared first and last name alone as proof of incumbency where the repository has an explicit alias or identity resolution. Preserve multi-candidate outcomes by aggregating D and R votes for the two-party margin, while keeping the existing candidate-vector model for the final forecast.

Emit a machine-readable training/audit report with row counts by cycle, missing-data exclusions, feature values, source hashes, and Oklahoma's 2026 input row. Check the 2022 Oklahoma governor result and 2024 presidential lean against the pinned sources.

## 2. Select the specification before looking at 2026 outputs

Compare at least these regularized specifications, with intercepts fitted from training data:

1. Existing prior-governor baseline and current separately fitted open-seat effect.
2. Previous governor lean only.
3. Presidential state lean only.
4. Previous governor lean plus presidential state lean.
5. Both leans plus open-seat signed indicator.
6. Both leans plus open-seat and candidate-experience indicators, if historical identity coverage supports them.

Use expanding-cycle backtests: fit only on earlier election cycles and predict the next whole cycle. Select the ridge penalty and specification using a prespecified training/tuning period; reserve later cycles, including 2020, 2022, and 2024 where available, as a reported check rather than selecting on their results. Compare mean absolute error, RMSE, signed bias, winner log score, and interval coverage where a full forecast is available. Report those metrics overall and for open seats, incumbent races, strongly partisan states, and states where the previous governor result differs sharply from presidential lean. Show sample sizes and paired changes, not just a winning model name.

The quick exploratory check that motivated this plan used 234 eligible governor transitions with presidential data. A prior-governor-plus-presidential-lean ridge fit had lower later-cycle margin RMSE than prior-governor lean alone (about 0.17 versus 0.19 on a 0-to-1 margin scale). That check is **not** the selection result: it used a simple standalone fit, did not replay polls, and did not evaluate winner probabilities or intervals. The new audit must reproduce or correct it.

Do not set a coefficient, cap, state category, or Oklahoma correction by hand. If the open-seat effect remains useful after adding presidential lean, fit it jointly in the chosen model and remove the old governor-only application so it is counted once. If it does not improve prespecified validation, omit it for governors and document that result. Keep the House and Senate coefficients as they are.

## 3. Integrate the selected governor prior

For eligible 2026 governor races, use the selected fit to produce a local two-party margin relative to the **drawn** national House environment. Convert the target margin to D/R log odds and shift Democratic and Republican candidate shares by equal and opposite half-shifts; renormalize the full candidate vector so independent candidates remain represented. Preserve the existing correlated national, office, state, and race residual draws around the new center. Do not turn the fitted local lean into a certainty: estimate out-of-cycle residual variation, account for coefficient uncertainty if practical, and check that unpolled governor intervals are not spuriously narrow.

Apply the candidate-vector polling update after this prior. Ensure a well-polled race can move substantially from its fundamentals and that an unpolled race is clearly marked as fundamentals-driven in diagnostics. For governor races lacking a required feature, use an explicitly tested fallback rather than silently substituting zero. Avoid applying the former governor open-seat coefficient again in `current_shifts()` or Stage 5. Keep multi-candidate and runoff handling intact.

Add per-race diagnostics to `model_parameters.json` or the fundamentals-impact artifact: previous governor result and year, presidential lean and year, fitted local lean, open-seat/experience contributions if selected, pre-poll D/R margin, poll count, post-poll margin, and uncertainty components. Update the paired impact report to show the governor baseline replacement separately from poll effects.

## 4. Validate before publishing a refreshed forecast

- Unit-check the margin and log-odds conversions, feature cutoff dates, candidate identity, missing-feature fallback, and that the governor open-seat effect is applied at most once.
- Replay historical governor cutoffs with the selected prior and the existing poll model. Compare against the prior implementation using identical cutoffs, poll snapshots, random seeds, and draws. The eventual certified result is an imperfect proxy for an election-held-today target; label it accordingly.
- Check winner and share calibration, especially unpolled races and partisan open seats. Inspect whether any interval coverage or log score materially deteriorates even if mean margin error improves.
- Run a current-forecast sensitivity comparison with the same saved NYT snapshot. Report all 36 governor races, their before/after D/R margins and winner probabilities, and a short explanation of the five largest changes. Explicitly include Oklahoma. Confirm House and Senate numerical outputs remain unchanged, aside from random-number ordering if implementation makes that unavoidable.
- Run `pipeline/validate_stage5.py` and the relevant Stage 6 replay/validation checks. Only after these pass, use `pipeline/run_nowcast_refresh.py --skip-pull` to generate the normal artifacts and archive the new dated nowcast. Update `docs/current_model_data_math_2026.md`, forecast version/notes, and any methodology text that still states the old governor coefficient is active.

## Decision rule and deliverables

Adopt the revised specification only if the prespecified historical evaluation supports it and no important governor subgroup or uncertainty check reveals a clear regression. If none beats the current method, retain the current forecast and publish the audit, explaining why Oklahoma remains an unresolved fundamentals-only outlier. **Do not require Oklahoma to flip Republican as an acceptance test.**

Deliver the fitted module, reproducible historical audit and machine-readable report, tests for the integration boundaries, before/after 2026 governor comparison, validated forecast artifacts if adopted, and updated methodology documentation. Record the model version and source/code hashes so daily site snapshots remain interpretable across the change.
