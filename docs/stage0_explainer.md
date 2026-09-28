# Stage 0 report: what was decided and built

## What Stage 0 was for

Stage 0 defined exactly what the 2026 forecast will predict before any statistical model is written. Its purpose was to prevent the new model from inheriting assumptions from the 2024 project, especially the assumption that every election is simply a Democrat versus a Republican.

Stage 0 answers five questions:

1. Which elections belong in the forecast?
2. Which candidates currently belong to each election?
3. How is the winner of each election determined?
4. What outputs must the model eventually produce?
5. Which data sources may the project use, and how will their history be preserved?

The Stage 0 gate passes because every race has a source-labeled candidate field and an explicit counting rule. Candidate lists will still change, so later stages must continue monitoring them.

## Forecast scope

The core forecast contains **506 elections**:

| Office | Races | Meaning |
| --- | ---: | --- |
| U.S. House | 435 | Every voting House district |
| U.S. Senate | 35 | 33 regular Class II elections plus the Florida and Ohio special elections |
| Governor | 36 | The 36 states holding gubernatorial elections in 2026 |

Territorial governors and nonvoting House delegates are outside the core forecast. They can be added later as a separately labeled extension.

The race universe is independent of polling coverage. An election remains in the model even if no one has polled it.

## Candidate and ballot registry

The current registry contains **1,413 candidate entries across all 506 races**. Each entry records:

- a stable race identifier;
- a project candidate identifier;
- the candidate's ballot name;
- the ballot party label;
- whether the candidate is a write-in;
- the source and source record;
- the source status, such as certified, official but changing, or secondary-source snapshot; and
- notes needed to interpret the entry.

The registry does not force candidates into Democratic and Republican columns. Independents, Libertarians, Greens, minor parties, nonpartisan candidates, same-party matchups, and write-ins remain separate candidates. This supports ballots such as Republican versus independent, Republican versus independent versus Democrat, and fields with several independent candidates.

Party label, endorsement, and expected Senate caucus are separate ideas. For example, an independent candidate remains independent in the race forecast even if that candidate is expected to caucus with a major party after being elected.

## Where candidate information came from

Candidate coverage uses a source hierarchy:

1. **Reviewed state election sources** take priority.
2. **Exact-revision Wikipedia election summaries** fill races without a completed state-source review.
3. Poll appearances and FEC filings do not establish ballot qualification.

The current split is:

| Registry status | Races |
| --- | ---: |
| Certified state list ingested | 112 |
| Other reviewed official state list | 49 |
| Wikipedia snapshot pending state replacement | 345 |

State material was reviewed for California, Texas, Alabama, Washington, Illinois, Maryland, Maine, North Carolina, South Dakota, and Montana. Raw documents are stored as immutable, timestamped snapshots with URLs and SHA-256 hashes.

The Wikipedia snapshot records the exact article revision for the House, Senate, and governor summaries. It is an efficient national starting point rather than final certification. When a state source and Wikipedia differ, the state source wins.

As a quality check, the Wikipedia fields were compared with all 161 state-reviewed races. **151 matched** after normalizing harmless name differences. The ten differences consisted of three alternate name forms and seven candidates found in state sources but absent from Wikipedia. Those state candidates were retained. Most of the omissions were independent or minor-party candidates, which confirms why the model needs both broad aggregation and state overrides.

## Election rules

Every race has a declared winner-selection rule:

| Rule | Races | Model behavior needed later |
| --- | ---: | --- |
| Plurality | 477 | Candidate with the most votes wins |
| Majority followed by top-two runoff | 22 | Simulate the first election and, when necessary, a later runoff |
| Ranked choice | 6 | Simulate first choices and uncertain vote transfers |
| Majority followed by legislative selection | 1 | If no Vermont governor candidate wins a majority, model or present the General Assembly decision as a conditional scenario |

The main exceptions are:

- **Alaska:** top-four general-election fields decided by ranked choice.
- **Maine:** ranked choice for federal general elections; plurality for governor.
- **Georgia:** a candidate needs a majority or the top two proceed to a runoff.
- **Louisiana House:** November is an open primary; a majority winner is elected immediately, otherwise the top two proceed to the December election.
- **California and Washington:** top-two primaries can produce same-party general elections.
- **Vermont governor:** a popular-vote majority is required; otherwise the General Assembly chooses among the top three.

These rules are part of the race records rather than manual switches inside the model.

## What the model is required to predict

The primary target is a vector of candidate vote shares, not a two-party margin. For each race, the finished model must publish:

- expected vote share for every candidate;
- 80% and 95% predictive intervals;
- eventual win probability for every candidate;
- the most likely winner;
- poll count and latest poll date;
- the data cutoff and model version; and
- an explanation of the data used.

For possible runoffs, the model must forecast the first stage and a conditional final stage. For ranked-choice races, first-choice polling alone is insufficient: the model will require a transfer model with uncertainty.

House and Senate control probabilities must come from joint simulations. The same national and state polling-error draws will affect related races together. This prevents the seat forecast from treating hundreds of races as independent coin flips and becoming falsely certain.

Senate race winners and Senate control are kept separate. An independent victory is reported as an independent victory. Caucus assumptions enter only when calculating control of the chamber, and the vice president's tie-breaking party must be stated.

## Mathematical principles fixed before modeling

The plan rules out hand-set campaign effects and subjective probability adjustments. The model must instead:

- write down the estimand, likelihood, priors, covariance structure, and update process;
- estimate uncertain effects from historical elections with partial pooling;
- distinguish sampling error, pollster effects, shared polling error, campaign movement, fundamentals uncertainty, and ballot uncertainty;
- give unpolled races wide, historically calibrated priors rather than treating them as safe;
- preserve each poll's full answer vector, including undecided and other responses;
- train and test using genuine historical information cutoffs;
- compare model variants with proper scoring rules and interval coverage; and
- retain shared national and state uncertainty in chamber simulations.

Potential predictors such as presidential approval, generic ballot, endorsements, candidate experience, and campaign finance will be added only if they improve held-out historical forecasts.

## NYT polling data

The six NYT feeds supplied for the project have been downloaded once and inventoried. The files contain individual presidential approval polls, an approval average, Senate polls, House polls, governor polls, and other-office polls.

Important findings from the initial snapshot include:

- poll files use one row per answer option, so rows must be grouped by poll and question;
- national generic-ballot questions appear in the House file and must not be treated as House district polls;
- poll questions often use different candidate combinations within the same race;
- unnamed responses such as undecided and someone else are responses, not candidates;
- source candidate IDs cannot replace project candidate IDs; and
- the meaning of the NYT `created_at` field still needs confirmation before it can serve as a publication timestamp.

Initial November-stage coverage was 27 of 35 Senate races, 91 of 435 House races, and 32 of 36 governor races. Lack of polling does not remove a race from the forecast.

The project owner confirmed direct permission from NYT to use the feeds. The permission record allows Stage 1 to use them for ingestion and modeling. Before publishing a downloadable copy of the raw rows, the external correspondence should be checked specifically for raw redistribution rights.

## Reproducibility and provenance

Raw downloads are stored under `data/raw/`, which is excluded from Git. Each snapshot contains a manifest with its URL, retrieval time, byte count, hash, and available revision metadata. A changed source creates a new directory instead of overwriting an earlier file.

Derived reference files are committed separately. The Stage 0 validator checks:

- the exact 435/35/36 office counts;
- unique race and ballot-entry identifiers;
- at least one candidate field for every race;
- no unresolved counting rules;
- the expected counts for each counting-rule branch;
- preservation of independent candidates; and
- revision metadata for the Wikipedia snapshot; and
- candidate names free of Wikipedia party-stripe delimiters.

The final validation result was:

```text
Stage 0 valid: 506 races, 1414 candidate entries,
1055 secondary-source entries
```

The 26 September roster repair separated candidates that the original Wikipedia summary parser had joined across a party stripe. The [repair audit](../artifacts/calibration/ballot_name_repair_2026.json) records 37 cleaned names and one recovered candidate. Future snapshots use the corrected parser; `python pipeline/test_wikipedia_candidate_parser.py` checks the adjacent-candidate case.

## What Stage 0 does not claim

Stage 0 does not produce election probabilities. It establishes the definitions and source inventory that later work must obey.

Candidate fields can still change through withdrawal, replacement, litigation, or corrected certification. Wikipedia-backed races need progressive replacement with state-source data, especially competitive and unusual contests. Missouri's 2026 House geography also needs state confirmation before district baselines or maps are produced.

The candidate identifiers are sufficient for the current inventory, but identity resolution will need strengthening when historical results, finance records, and changing name forms are joined.

## What happens in Stage 1

Stage 1 builds the raw-data foundation:

1. Implement normalized adapters for the authorized NYT polling feeds.
2. Preserve every question and answer option rather than reducing polls to a Democratic-Republican margin.
3. Confirm publication-time semantics and enforce information cutoffs.
4. Collect historical polls and certified House, Senate, and governor results.
5. Add scheduled immutable snapshots and schema-change alerts.
6. Demonstrate that repeated ingestion is idempotent.
7. Demonstrate an as-of replay using only information available at the chosen historical time.

The first model should be built only after those acquisition checks pass. It will be a results-only candidate-share baseline, followed later by polling and national-signal components that must prove their value in backtesting.
