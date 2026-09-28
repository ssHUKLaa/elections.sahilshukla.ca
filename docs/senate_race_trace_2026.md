# Pivotal Senate race audit — September 21, 2026 snapshot

**Target notice:** This trace follows the legacy eventual-election model. Its poll and component diagnostics remain valid descriptions of that run, but its final win chances do not represent the [election-held-today nowcast](nowcast_remediation.md) requested on 23 September 2026.

Run `python pipeline/audit_senate_races.py` to reproduce the [machine-readable trace](../artifacts/senate_race_trace.json). It verifies the frozen Stage 1/2 hashes before using the accepted NYT questions, fitted poll correction, Stage 4 and Stage 5 forecasts, and the [paired component audit](../artifacts/senate_component_audit.json). Positive margins favor Democrats. Poll margins are **two-party D/R margins**, so Alaska's margin is not a candidate's first-choice margin or a ranked-choice win chance. All race probabilities here are Democratic eventual win chances.

| Race | Stage 3 prior | National/local, no race polls | Last 90 days raw polls (n) | Last 90 days corrected polls | Final margin | Our D win | [DDHQ D win](https://votes.decisiondeskhq.com/forecast/2026/senate) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Alaska | R+13.1 | R+3.9 | R+0.9 (6) | R+4.3 | R+4.6 | 36% | 61% |
| Iowa | R+6.6 | R+1.2 | R+0.3 (12) | R+3.9 | R+1.8 | 40% | 50% |
| Maine | R+9.0 | R+0.2 | D+2.1 (9) | R+2.2 | R+1.6 | 41% | 53% |
| Michigan | D+1.7 | D+7.7 | D+2.1 (17) | R+1.9 | D+1.0 | 55% | 68% |
| Ohio | R+6.1 | R+0.4 | D+5.3 (6) | D+1.6 | D+0.8 | 54% | 54% |
| Texas | R+9.7 | R+2.6 | D+2.9 (19) | R+0.8 | R+1.2 | 44% | 55% |

DDHQ's live values were read September 22, 2026; the internal snapshot closed September 21 at 20:45 UTC. Those external numbers are a discrepancy check, not a model input. Silver Bulletin's [September 20 headline](https://www.natesilver.net/p/expert-ratings-are-ignoring-signs) was about 65% Democratic Senate control, while [DDHQ's September 22 headline](https://votes.decisiondeskhq.com/forecast/2026/senate) was 53%; our accepted Stage 5 estimate is 38.1% conditional on other-party winners caucusing with Democrats. Differences in update time, race definition, and caucus assumptions can affect the comparison.

## What moves the races

The fitted poll correction subtracts roughly 3–4 points from a typical D/R margin in these races. It changes the recent polling leader in Maine, Michigan, and Texas. In the paired component replay, setting only the mean correction to zero moves Democratic win chances from **41% to 58% in Maine**, **55% to 69% in Michigan**, and **43% to 59% in Texas**. It moves Democratic Senate control from 37% to 65% in that replay. This no-correction run retains the fitted error variances and is **not** a calibrated alternative forecast.

National and local information generally moves the Stage 3 prior toward Democrats. In Michigan, however, the no-race-poll margin is D+7.7 while recent raw race polls average D+2.1; race polls pull the final estimate toward the Republicans even before considering the historical correction. In Ohio, our eventual win chance matches DDHQ's 54% despite the correction. The disagreement is therefore concentrated in particular races, not a uniform gap in every race.

Alaska needs a separate candidate-level check. The current ballot lists Mary Peltola and three Republican candidates, including **two distinct Dan Sullivans**. After the prior-winner match repair, Stage 3 gives Dan S. Sullivan about **39.4%** of first choices and the other Republicans about **8.5% each**, instead of splitting Republican support almost equally. With race polls removed, the paired ranked-choice replay gives Peltola **66%** despite an aggregate R+3.9 D/R margin. With the accepted race polls, her win chance is **36%**. The prior allocation and the fitted transfer profile still need direct validation against historical multi-candidate ranked-choice contests before relying on Alaska's probability.

The audit found and repaired a **Stage 2 name-matching miss** in two important incumbent races. The official 2020 result has winner `Sullivan, Dan`, but the 2026 ballot lists `Dan S. Sullivan`; the official Maine winner is `Collins, Susan Margaret`, while the ballot lists `Susan M. Collins`. Both now have `prior_winner_match=1` through [reviewed exact-race aliases](../data/reference/prior_winner_alias_reviewed_2026.json). The other Dan Sullivan in Alaska remains a distinct person with no prior-winner match. The full rerun moved conditional Democratic Senate control from **37.6% to 38.1%** and Peltola's win chance from **32.1% to 35.7%**. The field named `incumbent` in model output specifically means a verified **prior general-election winner match**; it does not cover an appointed senator such as Ohio's Jon Husted.

## Audit limits and next checks

- The historical correction was learned from a RealClearPolling-derived archive and tested at a fixed 43-day cutoff. Live race polls come from the NYT feed. The held-out 2024 check supports a correction in that archive but does not prove its full size transfers to NYT polling in 2026.
- The target is poll D/R log ratio minus eventual vote D/R log ratio. It contains late campaign movement as well as survey error. A fixed deterministic correction may therefore overstate what is known today about the direction of this cycle's error.
- The live 30-day poll half-life has not passed a whole-cycle historical selection check. All accepted polls remain in the model; the 90-day and 30-day rows in the trace are descriptive windows.
- The raw-to-corrected-to-final columns are sequential descriptive views, **not additive effects**. Final candidate shares also reflect the national/local starting estimate, poll covariance, and, for Alaska, within-party allocation and ranked-choice transfers.

The [cycle-wide error audit](senate_cycle_error_audit.md) finds only weak evidence for adding extra shared variance and slightly worse held-out 2024 predictive density. The next model work should validate source transfer and live recency. Alaska also needs a candidate-share and transfer check. These should be evaluated as competing forecasts, not tuned to match DDHQ or Silver Bulletin's current headline.
