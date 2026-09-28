# Stage 3: results-only baseline

## Purpose

Stage 3 estimates candidate shares before using any 2026 polling. It covers all 435 House, 35 Senate, and 36 governor races and supplies the prior that Stage 4 updates.

## Repair in version 1.4

The original transition model treated structural absences as tiny vote shares and linked adjacent statewide Senate elections even when they were different seats. That made safe states too uncertain and gave preliminary minor-party candidates implausibly large forecasts.

Version 1.4 applies these rules:

- Senate transitions compare the same seat six years apart. Class II races use the 2020 result; the Florida and Ohio Class III specials use 2022.
- The D/R coordinate is fitted only when both major parties contested both elections. Its persistence coefficient is fixed at one, with the average historical swing estimated from eligible transitions.
- Fusion labels such as `N(D)/D` and `DEM/IP/WF` retain their Democratic or Republican grouping.
- A structurally uncontested same-seat result cannot be interpreted as zero partisan support. Stage 2 supplies a documented nearby statewide fallback where required.
- Other-party support uses a hurdle model. Recurring three-way contests retain their prior support; a new third-party line starts from the historical mean debut share for that office. Simulated arithmetic means are calibrated to those targets so a wide log-odds distribution cannot inflate a 2% center into a 20% average.

## Mathematical model

The three party-group shares use two separate coordinates:

```text
x1 = log(D / R)
x2 = log((D + R) / O)
```

The coordinates never predict one another. Historical residuals are decomposed into national-cycle, office-cycle, state-cycle, and race components. Joint draws share the applicable components across races. Within each party group, a softmax allocation distributes support among named candidates using an estimated incumbency term and historical within-group dispersion.

The model targets the next listed voting stage. Ranked-choice transfers and runoff outcomes remain Stage 5 responsibilities.

## Holdout test

The full 2024 cycle is held out; all fitted quantities for this test use earlier target cycles. Lower scores and errors are better.

| Metric | Stage 3 | Previous-result baseline |
| --- | ---: | ---: |
| Winner log score | 0.2207 | 0.2749 |
| Multiclass Brier | 0.1189 | 0.1368 |
| Candidate-share MAE | 0.0386 | 0.0571 |
| 80% interval coverage | 81.0% | 86.3% |
| 95% interval coverage | 90.7% | 90.8% |

The gate requires winner-log-score noninferiority within 0.01 nat, lower share MAE, at least 75% coverage for nominal 80% intervals, and at least 90% coverage for nominal 95% intervals. Version 1.4 passes every condition.

## Outputs

- `artifacts/stage3/model_parameters.json`: fitted transitions, debut-share parameters, covariance components, allocation parameters, and holdout metrics.
- `artifacts/stage3/forecast_2026.json`: candidate distributions and joint first-stage leader counts from 50,000 draws.
- `modeling/stage3_results_baseline.py`: model and simulator.
- `pipeline/validate_stage3.py`: structural, accounting, calibration, and replay checks.

The artifacts remain internal inputs to later stages.

## Reproduce on Ubuntu ARM

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-stage3.txt
.venv/bin/python modeling/stage3_results_baseline.py --draws 50000 --seed 20260921
.venv/bin/python pipeline/validate_stage3.py --check-reproducibility
```
