# Stage 3 acceptance gate

**Status: passed on 22 September 2026.**

## Evidence

- Coverage: 435 House, 35 Senate, and 36 governor races.
- Historical sample: 3,273 races and 2,669 comparable-result transitions.
- Senate history is linked only to the same seat six years earlier.
- Structural party absences are excluded from the corresponding persistence fit.
- D/R and other-party persistence coefficients are fixed at one; intercepts estimate average eligible historical changes.
- New other-party entries use office-specific historical debut shares, with arithmetic-mean calibration after simulation.
- 2024 holdout winner log score is 0.2207 versus 0.2749 for the carry-forward baseline.
- Candidate-share MAE is 0.0386 versus 0.0571.
- Coverage is 81.0% for nominal 80% intervals and 90.7% for nominal 95% intervals.
- Accounting and safe-state sanity checks pass.
- Optional deterministic replay must reproduce the artifact bytes.

Accepted artifact hashes:

```text
model_parameters.json  ff7a6749d7ba7a536ea64d68a3d8c4aa05b62c5574f3b628fe5ac110783a0a05
forecast_2026.json      aeb30720761a3961761ad36d7193f164940f2eda5342ec8630a177af8e0fe2dd
```

## Limitations carried into Stage 4

- Minor-party and independent breakthroughs remain less precisely estimated than the D/R split.
- House priors retain Stage 2's geography uncertainty multiplier.
- Current candidate qualification is provisional for entries sourced from secondary aggregations.
- Ranked-choice transfers, runoffs, seats not up, caucus choices, and chamber control are handled in Stage 5.
