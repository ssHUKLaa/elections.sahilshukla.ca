# Pollster quality in the 2026 nowcast

**Sources.** The NYT snapshot supplies a stable `pollster_rating_id` but leaves `numeric_grade` blank. The nowcast joins that ID to [Silver Bulletin's January 14, 2026 ratings](https://www.natesilver.net/p/pollster-ratings-silver-bulletin). When Silver has no entry, it uses [538's published numeric grade](https://github.com/fivethirtyeight/data/tree/master/pollster-ratings). The original Silver workbook, normalized CSV, source links, retrieval timestamp, and hashes are in `data/reference/pollster_ratings/`. Silver Bulletin / Nate Silver and Eli McKown-Dawson are credited for the Silver data.

**Weights.** Silver's Predictive Plus-Minus (PPM) estimates future polling error relative to an average pollster in margin points; lower is better. The poll-weight multiplier is

`(E / (E + PPM))²`,

where `E = 5.39015667` margin points is the poll-count-weighted mean Simple Expected Error in the Silver workbook. This treats expected absolute error as proportional to standard deviation and weights by inverse variance. The baseline comes from the source file, and all observed denominators are positive. Silver-banned firms receive zero weight. For a firm absent from Silver but rated by 538, the multiplier is `sqrt(538 numeric grade / mean 538 grade in the current NYT snapshot)`; that mean is 2.05751455 in the 23 September run. Unrated firms receive weight 1. These multipliers combine with the model's sample-size and recency weights; they do not impose a partisan shift.

| NYT feed | Poll records | Silver rated | 538 fallback | Silver banned | Unrated |
| --- | ---: | ---: | ---: | ---: | ---: |
| Senate | 638 | 511 | 9 | 2 | 116 |
| House | 1,090 | 893 | 11 | 16 | 170 |
| Governor | 753 | 604 | 5 | 2 | 142 |
| Other | 165 | 137 | 1 | 0 | 27 |
| Presidential approval polls | 1,031 | 867 | 29 | 16 | 119 |

These are raw poll-record counts from the frozen 23 September NYT snapshot. The nowcast used 619 mapped race polls after question and ballot checks; 512 of those have a Silver or fallback rating. The approval average conditions the national prior; individual approval polls are not a separate likelihood term.

**Current diagnostic result.** The 75,000-draw internal nowcast at `2026-09-23T17:21:36Z` gives Democrats 60.1% Senate control if every other-party winner caucuses with them, and 80.9% House control. The national estimate combines an approval-conditioned D+8.9 prior with the current generic ballot at D+7.1, yielding D+7.85. These values include the historical write-in allocation, structural major-party reentry, and multi-candidate poll-contrast fixes. [Uncertainty calibration remains provisional](nowcast_remediation.md); the result is not approved for publication.
