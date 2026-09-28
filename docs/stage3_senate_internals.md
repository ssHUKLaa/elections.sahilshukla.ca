# Stage 3 Senate internals

**Artifact cutoff:** `2026-09-23T22:50:54Z`  
**Model:** `stage3-results-2.0`  
**Simulation:** 50,000 joint draws with seed `20260921`  
**Status:** internal results-only baseline; not a public forecast

## Read this first

These probabilities expose the Stage 3 machinery before polling, ballot-rule transfers, final candidate qualification, or Senate caucus accounting. Independent and same-party fields remain sparsely identified, so this 35-seat first-stage distribution is unsuitable as a chamber forecast by itself.

The Senate output covers only the 35 modeled 2026 races. It does not add the 65 seats that are not up for election and therefore does not calculate Senate control.

## Fitted transition

The model uses these two coordinates:

```text
x1 = log(D / R)
x2 = log((D + R) / O)
```

The fitted Senate equations are:

```text
x1_next = -0.008041 + 1.000000 * x1_previous
x2_next = 0.299249 + 1.000000 * x2_previous
```

They use 163 Senate transitions. The fitted persistence coefficients are constrained to one; leave-one-cycle-out ridge results are retained as diagnostics. Other-party debuts use 8 eligible transitions and a mean share of 2.8%.

| Coordinate | Ridge | Cross-validated MSE |
| --- | ---: | ---: |
| log(D/R) | 0.0 | 0.069001 |
| log(D/R) | 0.01 | 0.068999 |
| log(D/R) | 0.1 | 0.068983 |
| log(D/R) | 1.0 | 0.068971 |
| log(D/R) | 10.0 | 0.077717 |
| log(D/R) | 100.0 | 0.180012 |
| log((D+R)/O) | 0.0 | 2.396207 |
| log((D+R)/O) | 0.01 | 2.396199 |
| log((D+R)/O) | 0.1 | 2.396127 |
| log((D+R)/O) | 1.0 | 2.395416 |
| log((D+R)/O) | 10.0 | 2.389259 |
| log((D+R)/O) | 100.0 | 2.381300 |

## Candidate allocation

Within the same party group, the fitted incumbent utility is `2.638518`, equivalent to about `13.99` times the softmax weight before candidate noise. The residual within-group standard deviation is `1.209294`.

There were 162 historical multi-candidate groups, but only **9** contained both an incumbent and a non-incumbent. The apparent incumbency effect is therefore weakly identified and should not be given a strong substantive interpretation.

## Residual covariance

Values below are standard deviations on the two log-odds coordinates. They are shared across the election as indicated, then added before converting back to candidate shares.

| Component | SD for `log(D/R)` | SD for `log((D+R)/O)` |
| --- | ---: | ---: |
| National cycle | 0.228 | 1.110 |
| Senate office cycle | 0.125 | 0.265 |
| State cycle | 0.256 | 1.256 |
| Senate race | 0.180 | 1.678 |

The covariance components preserve shared election, office, state, and race uncertainty. Stage 4 updates these draws with polling and calibrates posterior covariance on a separate historical cycle.

## Senate-only 2024 holdout

| Metric | Stage 3 | Previous-result baseline |
| --- | ---: | ---: |
| Winner log score | 0.4462 | 0.5075 |
| Multiclass Brier | 0.2809 | 0.2768 |
| Candidate-share MAE | 0.0497 | 0.0721 |
| 80% interval coverage | 64.3% | 78.6% |
| 95% interval coverage | 86.8% | 90.7% |

The Senate subset improves winner log score and share MAE. Its 95% coverage is below nominal, which remains a limitation of this small office-level holdout even though the all-office acceptance gate passes.

## Joint distribution across the 35 modeled seats

These are first-stage candidate leaders grouped by ballot party. They are not projected final Senate membership.

| Leader group | Mean seats | Median | 80% interval |
| --- | ---: | ---: | ---: |
| Democratic | 13.30 | 13 | 8–19 |
| Republican | 21.60 | 22 | 16–27 |
| Independent/other | 0.09 | 0 | 0–0 |

## Race internals

`Leader` is the probability of finishing first at the modeled voting stage. `Eventual win` is populated only when Stage 3 treats the listed stage as directly decisive.

### AK — `S-2026-AK-II-regular`

Rule: `ranked_choice` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:AK:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Dan S. Sullivan | REP | R | 43.4% | 23.8%–58.0% | 53.8% | — |
| Mary Peltola | DEM | D | 43.2% | 35.7%–50.9% | 44.1% | — |
| Gerald Heikes | REP | R | 6.6% | 0.4%–18.0% | 1.1% | — |
| Dan J. Sullivan | REP | R | 6.7% | 0.4%–18.3% | 1.0% | — |

### AL — `S-2026-AL-II-regular`

Rule: `plurality` · Ballot status: `certified_list_ingested` · Baseline: `official:2020:senate:AL:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Barry Moore | REP | R | 60.2% | 52.8%–67.5% | 96.0% | 96.0% |
| Everett Wess | DEM | D | 39.8% | 32.5%–47.2% | 4.0% | 4.0% |

### AR — `S-2026-AR-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:AR:S` · Uncertainty multiplier: `1.25`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Tom Cotton | REP | R | 66.2% | 58.3%–73.8% | 99.3% | 99.3% |
| Jeff Wadlin | LIB | O | 2.4% | 0.0%–5.7% | 0.6% | 0.6% |
| Hallie Shoffner | DEM | D | 31.4% | 24.4%–38.8% | 0.1% | 0.1% |

### CO — `S-2026-CO-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:CO:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| John Hickenlooper | DEM | D | 54.5% | 46.9%–62.1% | 77.7% | 77.7% |
| Mark Baisley | REP | R | 45.5% | 37.9%–53.1% | 22.3% | 22.3% |

### DE — `S-2026-DE-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:DE:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Chris Coons | DEM | D | 60.7% | 53.3%–67.9% | 96.6% | 96.6% |
| Michael Katz | REP | R | 39.3% | 32.1%–46.7% | 3.4% | 3.4% |

### FL — `S-2026-FL-III-special`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2022:senate:FL:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Ashley Moody | REP | R | 57.9% | 50.3%–65.4% | 92.0% | 92.0% |
| Angie Nixon | DEM | D | 41.3% | 33.9%–48.9% | 7.9% | 7.9% |
| Neil Gillespie | IND | O | 0.8% | 0.0%–1.7% | 0.0% | 0.0% |

### GA — `S-2026-GA-II-regular`

Rule: `majority_then_top_two_runoff` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:GA:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Mike Collins | REP | R | 51.1% | 43.4%–58.8% | 57.4% | — |
| Jon Ossoff | DEM | D | 48.9% | 41.2%–56.6% | 42.6% | — |

### IA — `S-2026-IA-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:IA:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Ashley Hinson | REP | R | 52.3% | 44.3%–60.3% | 72.0% | 72.0% |
| Josh Turek | DEM | D | 45.3% | 37.5%–53.3% | 27.5% | 27.5% |
| Thomas Laehn | LIB | O | 2.3% | 0.1%–5.7% | 0.5% | 0.5% |

### ID — `S-2026-ID-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:ID:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Jim Risch | REP | R | 95.6% | 88.4%–99.8% | 99.7% | 99.7% |
| Todd Achilles | IND | O | 1.5% | 0.0%–3.6% | 0.1% | 0.1% |
| Natalie Fleming | IND | O | 1.5% | 0.0%–3.6% | 0.1% | 0.1% |
| Matt Loesby | LIB | O | 1.5% | 0.0%–3.6% | 0.1% | 0.1% |

### IL — `S-2026-IL-II-regular`

Rule: `plurality` · Ballot status: `official_list_reviewed` · Baseline: `official:2020:senate:IL:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Juliana Stratton | DEM | D | 55.5% | 46.7%–64.2% | 90.2% | 90.2% |
| Don Tracy | REP | R | 39.8% | 31.7%–47.9% | 8.0% | 8.0% |
| Whitfield Harrington Jr | ACP | O | 4.7% | 0.2%–12.3% | 1.8% | 1.8% |

### KS — `S-2026-KS-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:KS:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Roger Marshall | REP | R | 56.1% | 48.5%–63.7% | 85.0% | 85.0% |
| Adam Hamilton | DEM | D | 43.9% | 36.3%–51.5% | 15.0% | 15.0% |

### KY — `S-2026-KY-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:KY:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Andy Barr | REP | R | 60.2% | 52.7%–67.5% | 95.9% | 95.9% |
| Charles Booker | DEM | D | 39.8% | 32.5%–47.3% | 4.1% | 4.1% |

### LA — `S-2026-LA-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:LA:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Julia Letlow | REP | R | 63.4% | 56.1%–70.4% | 99.0% | 99.0% |
| Jamie Davis | DEM | D | 36.6% | 29.6%–43.9% | 1.0% | 1.0% |

### MA — `S-2026-MA-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:MA:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Ed Markey | DEM | D | 66.3% | 59.3%–73.0% | 99.8% | 99.8% |
| John Deaton | REP | R | 33.7% | 27.0%–40.7% | 0.2% | 0.2% |

### ME — `S-2026-ME-II-regular`

Rule: `ranked_choice` · Ballot status: `official_list_reviewed` · Baseline: `official:2020:senate:ME:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Susan M. Collins | REP | R | 54.7% | 47.0%–62.2% | 78.5% | — |
| Troy D. Jackson | DEM | D | 45.3% | 37.8%–53.0% | 21.5% | — |

### MI — `S-2026-MI-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:MI:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Abdul El-Sayed | DEM | D | 50.0% | 42.2%–57.8% | 54.4% | 54.4% |
| Mike Rogers | REP | R | 48.6% | 40.8%–56.4% | 45.5% | 45.5% |
| Douglas P. Marsh | GRE | O | 0.5% | 0.0%–1.0% | 0.0% | 0.0% |
| Lydia Christensen | LIB | O | 0.5% | 0.0%–1.0% | 0.0% | 0.0% |
| Tim Long | OTH | O | 0.5% | 0.0%–1.0% | 0.0% | 0.0% |

### MN — `S-2026-MN-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:MN:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Peggy Flanagan | DEM | D | 52.6% | 44.9%–60.2% | 67.0% | 67.0% |
| Michele Tafoya | REP | R | 47.4% | 39.8%–55.1% | 33.0% | 33.0% |

### MS — `S-2026-MS-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:MS:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Cindy Hyde-Smith | REP | R | 54.4% | 46.7%–62.2% | 80.5% | 80.5% |
| Scott Colom | DEM | D | 44.3% | 36.6%–52.0% | 19.3% | 19.3% |
| Ty Pinkins | IND | O | 1.3% | 0.0%–3.0% | 0.1% | 0.1% |

### MT — `S-2026-MT-II-regular`

Rule: `plurality` · Ballot status: `official_filing_list_reviewed` · Baseline: `official:2020:senate:MT:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Kurt Alme | REP | R | 53.6% | 45.4%–61.6% | 80.1% | 80.1% |
| Alani Bankhead | DEM | D | 43.6% | 35.7%–51.6% | 19.4% | 19.4% |
| Seth Bodnar | IND | O | 1.4% | 0.0%–3.4% | 0.2% | 0.2% |
| Kyle Austin | LIB | O | 1.4% | 0.0%–3.4% | 0.2% | 0.2% |
| Jami Dee Woodman | NON | O | 0.0% | 0.0%–0.0% | 0.0% | 0.0% |

### NC — `S-2026-NC-II-regular`

Rule: `plurality` · Ballot status: `official_list_unfinalized` · Baseline: `official:2020:senate:NC:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Michael Whatley | REP | R | 49.4% | 41.1%–57.6% | 56.9% | 56.9% |
| Roy Cooper | DEM | D | 47.3% | 39.1%–55.5% | 42.5% | 42.5% |
| Michael Dublin | GRE | O | 1.6% | 0.0%–3.9% | 0.3% | 0.3% |
| Shannon W. Bray | LIB | O | 1.7% | 0.0%–4.0% | 0.3% | 0.3% |

### NE — `S-2026-NE-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:NE:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Pete Ricketts | REP | R | 87.7% | 65.4%–99.4% | 96.6% | 96.6% |
| Dan Osborn | IND | O | 6.1% | 0.2%–17.2% | 1.7% | 1.7% |
| Mike Marvin | OTH | O | 6.2% | 0.2%–17.4% | 1.7% | 1.7% |

### NH — `S-2026-NH-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:NH:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Chris Pappas | DEM | D | 56.7% | 48.9%–64.4% | 90.2% | 90.2% |
| John E. Sununu | REP | R | 41.5% | 33.9%–49.2% | 9.6% | 9.6% |
| Edmond LaPlante | OTH | O | 1.8% | 0.1%–4.2% | 0.3% | 0.3% |

### NJ — `S-2026-NJ-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:NJ:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Cory Booker | DEM | D | 58.0% | 50.5%–65.4% | 91.2% | 91.2% |
| Justin Murphy | REP | R | 42.0% | 34.6%–49.5% | 8.8% | 8.8% |

### NM — `S-2026-NM-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:NM:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Ben Ray Luján | DEM | D | 52.9% | 45.2%–60.6% | 68.6% | 68.6% |
| Larry Marker | REP | R | 47.1% | 39.4%–54.8% | 31.4% | 31.4% |

### OH — `S-2026-OH-III-special`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2022:senate:OH:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Jon Husted | REP | R | 53.2% | 45.5%–60.8% | 70.3% | 70.3% |
| Sherrod Brown | DEM | D | 46.8% | 39.2%–54.5% | 29.7% | 29.7% |
| Greg Levy | IND | O | 0.0% | 0.0%–0.0% | 0.0% | 0.0% |
| William Redpath | LIB | O | 0.0% | 0.0%–0.0% | 0.0% | 0.0% |

### OK — `S-2026-OK-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:OK:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Kevin Hern | REP | R | 63.6% | 55.6%–71.3% | 99.4% | 99.4% |
| N'Kiyla Jasmine Thomas | DEM | D | 33.2% | 26.1%–40.4% | 0.3% | 0.3% |
| Sevier White | LIB | O | 1.1% | 0.0%–2.5% | 0.1% | 0.1% |
| Curtis Stinnett | IND | O | 1.1% | 0.0%–2.6% | 0.1% | 0.1% |
| Ron Meinhardt | IND | O | 1.1% | 0.0%–2.6% | 0.1% | 0.1% |

### OR — `S-2026-OR-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:OR:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Jeff Merkley | DEM | D | 58.8% | 51.3%–66.2% | 93.5% | 93.5% |
| David Brock Smith | REP | R | 41.2% | 33.8%–48.7% | 6.5% | 6.5% |

### RI — `S-2026-RI-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:RI:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Jack Reed | DEM | D | 66.1% | 59.2%–72.9% | 99.8% | 99.8% |
| Raymond McKay | REP | R | 33.7% | 27.0%–40.7% | 0.2% | 0.2% |
| Michael Bahry | IND | O | 0.1% | 0.0%–0.3% | 0.0% | 0.0% |

### SC — `S-2026-SC-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:SC:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Darline Graham | REP | R | 54.7% | 47.0%–62.4% | 81.5% | 81.5% |
| Annie Andrews | DEM | D | 44.2% | 36.7%–51.9% | 18.5% | 18.5% |
| Mark Hackett | OTH | O | 0.5% | 0.0%–1.1% | 0.0% | 0.0% |
| Kasie Whitener | LIB | O | 0.5% | 0.0%–1.1% | 0.0% | 0.0% |
| Catherine Fleming Bruce | DEM | D | 0.0% | 0.0%–0.0% | 0.0% | 0.0% |

### SD — `S-2026-SD-II-regular`

Rule: `plurality` · Ballot status: `official_list_reviewed` · Baseline: `official:2020:senate:SD:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Mike Rounds | REP | R | 100.0% | 100.0%–100.0% | 100.0% | 100.0% |
| Brian L Bengs | IND | O | 0.0% | 0.0%–0.0% | 0.0% | 0.0% |

### TN — `S-2026-TN-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:TN:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Bill Hagerty | REP | R | 62.6% | 55.0%–70.0% | 99.2% | 99.2% |
| Marquita Bradshaw | DEM | D | 35.4% | 28.4%–42.7% | 0.8% | 0.8% |
| Catherine Whitson | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| Robert Jones | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| Andrew Gerena | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| David Sutman Jr. | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| James Macon III | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| Jeremy Hearn | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| Yoshi Matthews | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |
| Tharon Chandler | IND | O | 0.2% | 0.0%–0.5% | 0.0% | 0.0% |

### TX — `S-2026-TX-II-regular`

Rule: `plurality` · Ballot status: `certified_list_ingested` · Baseline: `official:2020:senate:TX:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| KEN PAXTON | REP | R | 54.0% | 46.0%–61.8% | 80.0% | 80.0% |
| JAMES TALARICO | DEM | D | 44.1% | 36.4%–51.9% | 19.6% | 19.6% |
| TED BROWN | LIB | O | 2.0% | 0.1%–4.7% | 0.3% | 0.3% |

### VA — `S-2026-VA-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:VA:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Mark Warner | DEM | D | 55.7% | 48.1%–63.2% | 83.4% | 83.4% |
| Bert Mizusawa | REP | R | 44.3% | 36.8%–51.9% | 16.6% | 16.6% |

### WV — `S-2026-WV-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:WV:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Shelley Moore Capito | REP | R | 70.7% | 63.8%–77.3% | 99.7% | 99.7% |
| S. Marshall Wilson | OTH | O | 2.0% | 0.1%–4.7% | 0.3% | 0.3% |
| Rachel Fetty Anderson | DEM | D | 27.3% | 21.3%–33.7% | 0.0% | 0.0% |
| Rio Phillips | OTH | O | 0.0% | 0.0%–0.0% | 0.0% | 0.0% |

### WY — `S-2026-WY-II-regular`

Rule: `plurality` · Ballot status: `secondary_source_snapshot` · Baseline: `official:2020:senate:WY:S` · Uncertainty multiplier: `1.00`

| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Harriet Hageman | REP | R | 72.8% | 66.5%–78.7% | 100.0% | 100.0% |
| James W. Byrd | DEM | D | 27.2% | 21.3%–33.5% | 0.0% | 0.0% |
