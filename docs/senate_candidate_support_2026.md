# Senate candidate support and poll coverage

The 2026 nowcast keeps every listed ballot option in the data. A candidate's ballot status and their modeled chance of winning are separate. This matters in Senate races where one or more independents replace a major-party nominee, and in races with several minor-party candidates.

## Idaho and Nebraska diagnosis

The frozen NYT feed contains ten Idaho general-election questions. The race mapper previously rejected all ten because the feed used **James Risch** while the ballot registry used **Jim Risch**. A [reviewed source-ID match](../data/reference/nyt_alias_reviewed_2026.json) restores six current-ballot questions from five distinct polls. Four questions still name David Roth, who [announced the end of his Senate campaign](https://rothforidaho.org/); they remain excluded rather than being silently remapped. The [Idaho Secretary of State candidate database](https://canvass.sos.idaho.gov/eng/candidates/view/5113) identifies Jim Risch.

Among those five usable Idaho polls, Risch and Todd Achilles appear in all five. Achilles has a median 34% when named. Matt Loesby appears in three at a median 2%; Natalie Fleming appears in two at a median 8.5%. A presence-only majority rule would retain Loesby despite his low measured support.

Nebraska's [official September 11 general candidate list](https://sos.nebraska.gov/sites/default/files/doc/elections/2026/Final_Statewide_General_Candidate_Filing_List_9.11.26.pdf) includes Mike Marvin, so he is a real ballot candidate. The six usable NYT polls name Dan Osborn and Pete Ricketts, and none names Marvin. The old model split its broad other-party prior almost equally between Osborn and Marvin. That was a candidate-allocation error, not evidence that Marvin was tied in polls. The [current poll-coverage audit](../artifacts/calibration/senate_contender_coverage_2026.json) records candidate appearances and percentages for every Senate race.

## Current allocation rule

For a plurality Senate race with at least three distinct usable current-ballot polls, an other-party candidate is treated as a potential winner when **more than half** those polls report at least **5%** support for that candidate. D and R ballot nominees stay in the contender set. Polls excluded by the source quality rules do not count. Races without at least three usable polls keep the existing wider prior; ranked-choice and runoff races are unaffected.

Candidates below that threshold retain a **small, uncertain vote share**. Let `x` be a candidate's mean reported percentage across distinct usable polls, counting a poll that omits the candidate as zero. Historical screened Senate candidates provide paired `(x, y)` observations, where `y` is certified final vote share. A nonnegative intercept and slope are fitted by least squares:

```
expected minor share = alpha + beta * x
drawn minor share = max(0, expected minor share + empirical residual draw)
```

For the 2026 fit, 171 screened candidate observations from 2020, 2022, and 2024 give `alpha = 0.00381` and `beta = 1.824` when shares are fractions. Empirical residual quantiles are assigned according to each candidate's original prior-draw rank, preserving rank dependence. Remaining vote share is apportioned among the contenders in each draw. The fitted residuals, training cycles, and source hashes are in the [fit artifact](../data/reference/senate_minor_share_fit_2026.json). This is an allocation model; using eventual vote shares as its training target makes it provisional for a held-today nowcast.

## Historical checks

The [screen safety audit](../artifacts/calibration/senate_contender_screen_historical.json) found no eventual Senate winner screened in eligible 2020–2024 plurality races at 90, 30, or 7 days. Screened candidates nevertheless received nonzero final votes, as much as 5.9% at seven days. Setting their share to zero failed share-interval calibration and was rejected.

The paired seven-day terminal-proxy replays used the same 750 draws per race. The minor-share fit for each cycle used only earlier cycles:

| Cycle | Method | Senate winner Brier | Candidate-share MAE | 95% share coverage |
| --- | --- | ---: | ---: | ---: |
| 2022 | Previous allocation | 0.06792 | 2.21 points | 89.2% |
| 2022 | Poll-conditioned minor shares | 0.06785 | 2.12 points | 88.0% |
| 2024 | Previous allocation | 0.11083 | 2.33 points | 88.6% |
| 2024 | Poll-conditioned minor shares | 0.11081 | 2.22 points | 92.9% |

The 5%, 10%, and 15% support floors tied on the 2022 winner score; 5% is the least restrictive. The 2024 result is a useful check, but the threshold variants were inspected on 2024, so it is **not a pristine untouched holdout** for this policy. The archive's terminal-result and retrospective-snapshot limits also remain. The [compact threshold sensitivity](../artifacts/calibration/senate_minor_share_threshold_sensitivity.json), [baseline](../artifacts/calibration/senate_contender_replay_baseline.json), and [5% replay](../artifacts/calibration/senate_minor_share_replay_floor5.json) provide the paired scores.

These changes address the excessive candidate-level win chances in Nebraska and Idaho. They do not assign caucus affiliations to independents; chamber control must still be shown by explicit caucus scenario.
