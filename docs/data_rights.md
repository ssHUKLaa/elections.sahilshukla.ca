# Data access and reuse decisions

This file records conservative project decisions for source use. It is an engineering policy, not legal advice. Recheck source terms before a public launch.

## Wikipedia election summaries

The national candidate inventory may use the three English Wikipedia 2026 election summary pages under the Wikimedia licensing terms. Wikipedia text is generally available under [CC BY-SA 4.0 and GFDL](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content). Each snapshot records the article URL, revision ID, revision timestamp, retrieval time, and SHA-256 hash. Public derived artifacts must attribute the relevant articles and link to their histories. State election sources override Wikipedia when a reviewed state list is available.

## State and federal election authorities

Official election documents are retained as provenance for factual candidate, race, rule, geography, and result records. The source URL, retrieval time, hash, and any source-specific notice must remain attached. A government source does not automatically make every design element or third-party attachment unrestricted, so the public site should publish normalized facts and links rather than mirror source documents unless their reuse status is clear.

## New York Times polling downloads

The six user-supplied CSV endpoints are the planned live polling source. The current [New York Times Terms of Service](https://thenewyorktimeshelpcenter.helpjuice.com/115002797688-Policies/115014893428-Terms-of-Service/) require prior consent for uses that include software or models. On 21 September 2026, the project owner confirmed that permission had already been obtained directly from The New York Times. The repository records that confirmation in [`source_permissions_2026.json`](../data/reference/source_permissions_2026.json); the underlying correspondence remains outside the repository.

Project decision:

- Use the NYT feeds for acquisition, normalization, model fitting, and forecast operation under the permission confirmed by the project owner.
- Keep immutable raw snapshots outside Git and retain source attribution, retrieval times, and hashes.
- Publish derived forecasts and source links. Before publishing downloadable raw NYT rows or a public mirror of the feeds, confirm that the external correspondence explicitly permits raw redistribution.
- Keep a durable copy of the permission correspondence with the project's administrative records before public launch.

## Historical polls and election results

The original FiveThirtyEight historical-poll endpoints now redirect away from the CSV files. Stage 1 uses the Git tracked [`simonw/fivethirtyeight-polls`](https://github.com/simonw/fivethirtyeight-polls) archive, which includes a [CC BY 4.0 license](https://github.com/simonw/fivethirtyeight-polls/blob/main/LICENSE). Preserve FiveThirtyEight and archive attribution, a source link, the license link, and an indication of project modifications in any redistributed derivative.

The FEC's Federal Elections workbooks and the House Clerk's 2024 Election Statistics are official compilations of state-certified federal results. Preserve the agency attribution and publication URL.

The public FiveThirtyEight `election-results` repository does not include an explicit repository license. Use its files internally as a structured cross-check and retain each row's original source. Do not redistribute the raw archive until separate terms permit it. Normalized result facts used by the model must be reconciled to FEC or the cited state election authority in Stage 2.

The Senate local-lean model uses a frozen internal copy of that archive for historical fitting. Its 2024 major-party presidential state totals have been cross-checked against the FEC's official compilation; the full raw archive is ignored by Git and restored from a hash-verified manifest on a new host. The older generic-ballot trendline is from the separate [FiveThirtyEight data repository](https://github.com/fivethirtyeight/data/blob/master/congress-generic-ballot/README.md), whose [data page](https://data.fivethirtyeight.com/) states CC BY 4.0 for datasets unless otherwise noted. Attribute FiveThirtyEight and record that this project computed election-cutoff errors from the published trendline.

The national-signal validation also uses a frozen internal copy of FiveThirtyEight's [pollster-ratings raw poll archive](https://github.com/fivethirtyeight/data/blob/master/pollster-ratings/README.md). Its source URL and hash are in `data/reference/national_signals/source_manifest.json`; the raw CSV is ignored by Git. Attribute FiveThirtyEight for any published aggregate finding and describe this project's date filters and weighting. The archive records median field dates but does not establish first publication dates for older polls, so its results are not advertised as a strict as-of backtest.

The Senate poll-error recalibration uses an internal frozen copy of [Jack Whitcomb's RealClearPolling-derived 2006–2024 Senate compilation](https://github.com/Jack-Whitcomb/All-US-Senate-polls-2006-2024). The public repository has no explicit license, and the upstream compilation may have separate terms. The raw CSV is ignored by Git and restored only when its hash matches the manifest. Do not redistribute its poll rows or expose them through the website unless the rights have been verified. Model diagnostics report aggregate errors without reproducing polls.

## Review triggers

Recheck this decision when the permission scope changes, a source changes its terms, an endpoint begins returning license metadata, the project changes its publication or commercial scope, or a new polling provider is proposed.
