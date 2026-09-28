# Ballot review: first independent Senate cases

The [reviewed entry file](../data/reference/ballot_entries_reviewed_2026.json) is a small, dated proof of the ballot schema. It is **not** the complete 2026 candidate registry.

| Senate race | State election source | Current interpretation |
| --- | --- | --- |
| South Dakota | [Secretary of State 2026 general list](https://vip.sdsos.gov/candidatelist.aspx?eid=774) | Mike Rounds (R) and Brian L Bengs (I) are listed active. Julian Beaudion (D) is listed withdrawn on 4 August 2026. A question with all three candidates represents an older ballot scenario and cannot be treated as a current three-way poll. |
| Montana | [Secretary of State federal general list](https://candidatefiling.mt.gov/candidatefiling/CandidateList.aspx?e=450002987) | Kurt Alme (R), Alani Bankhead (D), Seth Bodnar (I), and Kyle Austin (L) appear on the general candidate list with status `FILED`; Jami Dee Woodman is listed as write-in. The filing list is not labeled here as final certification. R–I questions omit candidates listed by the state and need a question-specific treatment. |

The NYT Senate snapshot contains additional South Dakota questions naming the now-withdrawn Democrat and Montana questions naming Steve Daines or Reilly Neill. It also assigns different NYT candidate IDs or party labels to the same named person in some hypothetical questions. Match on the **dated question and official ballot entry**, not candidate name or NYT candidate ID alone. An R–I Kansas question names Adam Hamilton as independent, while the [Kansas Secretary of State's official primary results](https://sos.ks.gov/elections/26elec/2026-Primary-Election-Official-Vote-Totals.pdf) list him as a Democratic candidate; treat that poll as a hypothetical configuration until the Kansas general ballot is checked.

Next candidate-review batch: official general-election lists for the remaining Senate states, then governors and House districts. Every entry needs state source, status, ballot label, effective date, and any withdrawal/replacement. Record caucus intent separately from ballot party, and leave it unresolved where no dated statement or official record supports it.
