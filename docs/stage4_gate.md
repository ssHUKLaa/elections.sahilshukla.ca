# Stage 4 acceptance gate

**Status: passed for the internal forecast on 22 September 2026.** Run `python pipeline/validate_stage4.py` to check the current artifacts and their live source snapshot. The model parameters and forecast JSON carry the exact input, source-manifest, and code hashes.

## Evidence

- The original all-office 2020 holdout has 92 races with usable named-candidate poll contrasts at a fixed 43-day cutoff. The combined model's winner log score is **0.4180**, versus **0.5040** for results only; Brier score is **0.2831** versus **0.3417**. Its all-candidate 95% share coverage is **91.4%**.
- The Senate D/R mean poll correction now uses **984 polls in 112 regular races across 2010–2024**. Its specification was chosen by whole-cycle rolling checks through 2022. The untouched 2024 poll-error check has **5.20-point** race-level RMSE, compared with **5.79** for the previous 2018-only correction and **7.11** with no correction. See [the recalibration report](senate_poll_bias_recalibration.md).
- The full 2020 Senate holdout has **93.3% coverage for each major party** in 95% candidate-share intervals. The independent 2024 Senate holdout has **92.3% D** and **100% R** coverage. The validator requires both parties in both cycles to reach at least 90%.
- All 506 races receive the sampled national-environment update, and 129 receive mapped race polls. The live 2026 run uses **603** selected poll questions and **75,000** draws, with 35 Senate, 435 House, and 36 governor races. Candidate vectors preserve independents and same-party candidates.
- The combined national House D/R estimate is about **D+7.89**. Approval-based fundamentals and the generic ballot remain separately reported in the parameter artifact.

## Remaining limits

- Other-party candidate-share intervals have only **55% coverage in the 2020 Senate holdout** and **66.7% in the 2024 holdout**. The major-party gate does not validate independent-candidate shares or final outcomes in multiparty contests.
- The 2024 Senate archive lacks publication timestamps; its full-model as-of check treats the fieldwork end date as the earliest available date. A poll published later could be admitted a few days early near the cutoff.
- The live 30-day race-poll half-life and the generic-ballot/fundamentals error covariance still need multi-cycle selection or validation. The overall posterior covariance factor is selected on 2018 and remains a limitation.
- The additional historical Senate poll archive has no explicit redistribution license. The raw CSV is retained only for internal calibration and is excluded from the website artifacts.
- Stage 5 separately resolves ranked-choice transfers, runoffs, Senate caucus scenarios, and chamber control. The Stage 4 artifact is not a final-winner forecast for nonplurality races.

The Stage 4 forecast remains internal and must not be presented as a fully calibrated public election forecast.
