# Senate forecast component audit — September 21, 2026 snapshot

`python pipeline/audit_senate_components.py --draws 20000` replays the frozen Stage 1 and Stage 2 inputs with paired Stage 3 draws and outcome seeds. The [full numeric report](../artifacts/senate_component_audit.json) includes every Senate race. Each row below removes one component from the **recalibrated Stage 4 model**. These are diagnostics, not replacement forecasts; their effects are not additive.

The accepted 75,000-draw Stage 5 run now gives **38.1%** Democratic Senate control **conditional on every other-party winner caucusing with Democrats**. The audit replay gives **37.9%**. Before correcting the verified prior-winner name matches for Dan S. Sullivan and Susan Collins, the accepted run gave **37.6%**. The candidate slate, counting rules, 34 Democratic-caucus and 31 Republican-caucus seats not up, and Republican vice-presidential tie break are unchanged.

| One change from the replay baseline | Conditional D control | Change | Expected D winners in 35 races |
| --- | ---: | ---: | ---: |
| Recalibrated model | 37.9% | — | 15.38 |
| Remove the fitted Senate poll-bias correction | **65.2%** | **+27.3 points** | 17.09 |
| Remove race polls entirely | 49.7% | +11.8 points | 16.24 |
| Remove the generic ballot | 41.2% | +3.4 points | 15.59 |
| Remove the fitted Senate local lean | 40.1% | +2.2 points | 15.55 |
| Remove approval-based national fundamentals | 36.3% | −1.6 points | 14.99 |
| Remove the Senate shared race-poll error allowance | 30.7% | −7.2 points | 14.85 |
| Remove both national and local updates, retaining Stage 3 priors and race polls | 28.3% | −9.6 points | 13.87 |

The fitted directional poll correction remains the largest reason this forecast is more Republican than the unadjusted polls. The multi-cycle rebuild did **not** provide evidence for setting that correction to zero: its independent 2024 race-level error was lower than both zero correction and the previous single-cycle model. [The recalibration report](senate_poll_bias_recalibration.md) explains the training and holdout checks.

The no-correction run sets mean poll corrections to zero while keeping their fitted error variances. Its 65.2% conditional control figure is not a calibrated alternative. Removing shared race-poll error lets corrected polls count more strongly, which moves this forecast further toward Republicans. The national inputs point toward Democrats: approval-based fundamentals are D+8.73, the generic ballot is D+6.76, and their combined national House two-party estimate is D+7.89.

This audit holds poll selection, candidate mapping, the unvalidated 30-day live race-poll half-life, and other model components fixed. The new Senate D/R correction passes a held-out 2024 race-level check and the 2020/2024 major-party interval gate. Other-party candidate shares still have poor interval coverage. For multiparty races, a D/R margin excludes independents and cannot be read as a winner probability; the JSON report preserves D, R, and other-party win probabilities separately.
