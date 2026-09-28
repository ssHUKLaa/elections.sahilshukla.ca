"""Join official candidate extracts and manual reviews to every 2026 race.

The gate report is intentionally strict: a race without a reviewed source or
counting rule remains open, and no missing candidate is synthesized from polls.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    universe = load("data/reference/races_2026.json")
    imported = load("data/reference/ballot_entries_official_subset_2026.json")
    reviewed = load("data/reference/ballot_entries_reviewed_2026.json")
    washington = load("data/reference/ballot_entries_wa_reviewed_2026.json")
    illinois = load("data/reference/ballot_entries_il_2026.json")
    alabama = load("data/reference/ballot_entries_al_2026.json")
    wikipedia = load("data/reference/ballot_entries_wikipedia_2026.json")
    entries = (imported["entries"] + reviewed["entries"] + washington["entries"]
               + illinois["entries"] + alabama["entries"] + wikipedia["entries"])
    by_entry_id = {entry["ballot_entry_id"]: entry for entry in entries}
    if len(by_entry_id) != len(entries):
        raise ValueError("Ballot entry ID collision across source catalogs")
    by_race = defaultdict(list)
    for entry in entries:
        by_race[entry["race_id"]].append(entry)
    universe_ids = {race["race_id"] for race in universe["races"]}
    if set(by_race) - universe_ids:
        raise ValueError(f"Candidate maps outside race universe: {sorted(set(by_race) - universe_ids)}")

    race_records = []
    for race in universe["races"]:
        race_id = race["race_id"]
        candidates = sorted(by_race[race_id], key=lambda entry: entry["ballot_entry_id"])
        sources = sorted({entry["source_key"] for entry in candidates})
        if not candidates:
            ballot_status = "unreviewed"
        elif any(entry["status"] == "secondary_source_general_list" for entry in candidates):
            ballot_status = "secondary_source_snapshot"
        elif any(entry["status"] == "listed_general_unfinalized" for entry in candidates):
            ballot_status = "official_list_unfinalized"
        elif any(entry["status"] == "filed_on_state_general_list" for entry in candidates):
            ballot_status = "official_filing_list_reviewed"
        elif any(entry["status"] == "certified_general" for entry in candidates):
            ballot_status = "certified_list_ingested"
        else:
            ballot_status = "official_list_reviewed"
        race_records.append({
            **race,
            "ballot_status": ballot_status,
            "candidate_source_keys": sources,
            "ballot_entry_ids": [entry["ballot_entry_id"] for entry in candidates],
            "candidate_count": len(candidates),
        })
    counts = Counter(record["ballot_status"] for record in race_records)
    rule_counts = Counter(record["counting_rule"] for record in race_records)
    missing = [record for record in race_records if record["ballot_status"] == "unreviewed"]
    pending_rules = [record for record in race_records if record["counting_rule"] == "state_rule_pending"]
    gate_passed = not missing and not pending_rules
    document = {
        "version": "1.0-stage0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "race_universe_version": universe["version"],
        "source_catalogs": [
            "data/reference/ballot_entries_official_subset_2026.json",
            "data/reference/ballot_entries_reviewed_2026.json",
            "data/reference/ballot_entries_wa_reviewed_2026.json",
            "data/reference/ballot_entries_il_2026.json",
            "data/reference/ballot_entries_al_2026.json",
            "data/reference/ballot_entries_wikipedia_2026.json",
        ],
        "status_counts": dict(counts),
        "counting_rule_counts": dict(rule_counts),
        "stage_0_gate_passed": gate_passed,
        "stage_0_gate_reason": (
            "Every race has a source-labeled candidate field and an explicit counting rule. "
            "Secondary-source entries remain subject to final state-source verification and change monitoring."
            if gate_passed else "Unreviewed races or pending election rules remain."
        ),
        "races": race_records,
        "entries": sorted(entries, key=lambda entry: entry["ballot_entry_id"]),
    }
    output = Path("data/reference/ballot_registry_2026.json")
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Stage 0 ballot and rule gate",
        "",
        f"Generated `{document['generated_at_utc']}` from source-backed catalogs. This is a **coverage audit**, not a national certified candidate list.",
        "",
        "| Check | Count |",
        "| --- | ---: |",
        f"| Race universe | {len(race_records)} |",
        f"| Races with candidate source entries | {len(race_records) - len(missing)} |",
        f"| Races without candidate source entries | {len(missing)} |",
        f"| Candidate entries, including withdrawal/write-in records | {len(entries)} |",
        f"| Races with counting rule pending | {len(pending_rules)} |",
        "",
        "## Ballot-source statuses",
        "",
    ]
    lines.extend(f"- `{status}`: {count} races." for status, count in sorted(counts.items()))
    lines += [
        "",
        "California, Texas, and Alabama lists are certified general-election sources. Washington's certified House entries were visually checked from a scanned PDF. Illinois is an active-candidate export that the state updates every 15 minutes and explicitly warns can change. Maryland lists active candidates; Maine has a general-election list with withdrawals tracked separately; North Carolina warns its list is not final. South Dakota and Montana were reviewed individually. Remaining races use exact-revision Wikipedia summary snapshots as the national aggregation layer. The [source cross-check](ballot_source_crosscheck.md) records differences. A source label only establishes what that version said; later corrections must create new snapshots.",
        "",
        "## Uncovered candidate fields by office",
        "",
    ]
    for office in ("senate", "governor", "house"):
        open_races = [record for record in missing if record["office"] == office]
        states = sorted({record["state"] for record in open_races})
        detail = ", ".join(states) if states else "none"
        lines.append(f"- {office.title()}: {len(open_races)} races in {len(states)} states: {detail}.")
    lines += [
        "",
        "## Election rules currently recorded",
        "",
    ]
    lines.extend(f"- `{rule}`: {count} races." for rule, count in sorted(rule_counts.items()))
    lines += [
        "",
        ("**Stage 0 gate: PASSED.** The planning inventory covers every race, candidate field, and counting rule. "
         "State-source verification, withdrawals, write-ins, fusion lines, and source changes remain recurring data-quality checks before any forecast run."
         if gate_passed else
         "**Stage 0 gate: OPEN.** Complete candidate coverage and counting-rule review, then rerun this report."),
        "",
    ]
    Path("docs/stage0_gate.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {output} and docs/stage0_gate.md; reviewed races={len(race_records)-len(missing)}, pending rules={len(pending_rules)}")


if __name__ == "__main__":
    main()
