# Stage 5 acceptance gate

**Status: passed on 22 September 2026.**

## Evidence

- All 506 races have exactly one eventual winner in every draw: 435 House, 35 Senate, and 36 governor.
- The rule registry resolves 477 plurality, 22 majority/runoff, six ranked-choice, and one legislative-selection race.
- Candidate win probabilities sum to one in every race; joint D/R/O seat distributions sum to one and conserve every seat.
- House and Senate control probabilities reproduce exactly from the stored joint seat-count PMFs.
- The Stage 5 first-stage shares and leader probabilities exactly equal the accepted Stage 4 artifact.
- The simulation uses 75,000 joint draws. Maximum candidate Monte Carlo standard error is 0.001826, below 0.2 percentage points.
- The runoff archive supplies 37 paired elections. The fitted relationship failed to beat chance, so the accepted conditional fallback has Brier score 0.2500 rather than using an overfit coefficient.
- Ranked-choice profiles use ten recorded elimination transitions from seven historical races, with Dirichlet uncertainty and explicit exhausted ballots.
- Vermont majority and top-three legislative behavior has a documented default and conditional sensitivities.
- Senate control begins from 34 D-caucus and 31 R-caucus seats not up, applies a Republican vice-presidential tie break, and leaves unweighted independent-caucus cases conditional.
- The validator asserts that Dan S. Sullivan and Daniel J. Sullivan Jr. retain distinct ballot and person IDs.
- Stage 3, Stage 4, and Stage 5 validators all pass on the same 75,000 draw dependency chain.

Run `python pipeline/validate_stage5.py` for the current artifact hashes and the check that its Stage 4 dependency hash matches. The Stage 5 artifact was regenerated after the multi-cycle Senate polling correction and the reviewed prior-winner name-match repair; its conditional Democratic Senate control probability is 38.1% when all other-party winners caucus with Democrats. **This gate checked the legacy eventual-election target, not the election-held-today nowcast target adopted on 23 September 2026.** See the [retargeting plan](nowcast_remediation.md).

## Limitations carried into Stage 6

- The runoff archive contains no out-of-sample predictive signal beyond 50/50 after the finalists are known. Candidate-specific runoff polling or more covariates may improve this later.
- Ranked-choice evidence is only ten elimination transitions. Alaska and Maine transfer behavior is partially pooled and sensitive to the prior.
- Vermont legislative selection is a conditional institutional decision, not a conventional voter probability.
- Senate overall control remains intentionally null until credible candidate-specific independent caucus assumptions or scenario weights are available.
- Other-party support now distinguishes recurring three-way contests from debut candidates and calibrates simulated arithmetic means. Candidate-specific independent assumptions still need scrutiny in Stage 6.
- The historical national fundamentals model has a separate later-cycle check; its combination with generic ballot remains provisional, as documented in Stage 4.
- Other-party candidate-share interval coverage in the Stage 4 Senate backtests remains below nominal; see the [poll correction recalibration](senate_poll_bias_recalibration.md).
- Candidate qualification remains unsettled for entries still sourced from secondary aggregations.

The forecast remains internal. Stage 6 historical as-of calibration is the next gate.
