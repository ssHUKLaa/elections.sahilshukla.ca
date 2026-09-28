"""Audit named options in NYT Senate questions against manually reviewed ballots."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> None:
    entries = json.loads(
        Path("data/reference/ballot_entries_reviewed_2026.json").read_text(
            encoding="utf-8"
        )
    )
    aliases = json.loads(
        Path("data/reference/nyt_alias_reviewed_2026.json").read_text(
            encoding="utf-8"
        )
    )
    matching_snapshots = []
    for path in Path("data/raw/nyt").iterdir():
        manifest_path = path / "manifest.json"
        if path.is_dir() and manifest_path.exists() and not path.name.endswith(".incomplete"):
            candidate_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if aliases["feed_sha256"] == candidate_manifest["files"]["senate"]["sha256"]:
                matching_snapshots.append(path)
    if not matching_snapshots:
        raise ValueError("No NYT Senate snapshot matches the reviewed alias file hash")
    snapshot = max(matching_snapshots)
    by_entry = {entry["ballot_entry_id"]: entry for entry in entries["entries"]}
    by_alias = {}
    for alias in aliases["matches"]:
        key = (
            alias["state"],
            alias["source_candidate_id"],
            alias["source_party"],
        )
        if key in by_alias or alias["ballot_entry_id"] not in by_entry:
            raise ValueError(f"Ambiguous or invalid reviewed alias: {key}")
        by_alias[key] = alias

    expected = defaultdict(set)
    for entry in entries["entries"]:
        if not entry["write_in_only"]:
            expected[entry["race_id"]].add(entry["ballot_entry_id"])
    questions: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with (snapshot / "senate.csv").open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if (
                row["stage"] == "general"
                and row["election_date"] == "2026-11-03"
                and row["state"] in {"SD", "MT"}
            ):
                questions[row["state"], row["question_id"]].append(row)

    counts = defaultdict(Counter)
    unknown_names = defaultdict(Counter)
    for (state, _), rows in questions.items():
        race_id = f"S-2026-{state}-II-regular"
        matched = set()
        unknown = []
        for row in rows:
            if row["party"] == "NONE":
                continue
            key = state, row["candidate_id"], row["party"]
            alias = by_alias.get(key)
            if alias is None:
                unknown.append(row["candidate_name"] + " [" + row["party"] + "]")
            elif row["candidate_name"] != alias["source_name"]:
                raise ValueError(f"NYT name changed for reviewed source ID: {key}")
            else:
                matched.add(alias["ballot_entry_id"])
        if unknown:
            label = "unmatched_or_old_candidate"
            unknown_names[state].update(unknown)
        elif matched == expected[race_id]:
            label = "all_printed_candidates_named"
        else:
            label = "only_subset_of_printed_candidates_named"
        counts[state][label] += 1

    lines = [
        "# Reviewed ballot question audit",
        "",
        f"NYT Senate snapshot: `{snapshot.as_posix()}`. Official-list reviews: [South Dakota and Montana](ballot_review.md).",
        "A question naming every printed candidate still needs response-option and publication-time checks before model use.",
        "",
        "| State | All printed candidates named | Only a subset named | Unmatched or old candidate named |",
        "| --- | ---: | ---: | ---: |",
    ]
    for state in ("SD", "MT"):
        c = counts[state]
        lines.append(
            f"| {state} | {c['all_printed_candidates_named']} | "
            f"{c['only_subset_of_printed_candidates_named']} | "
            f"{c['unmatched_or_old_candidate']} |"
        )
    lines += [
        "",
        "Unmatched names/labels include historical, withdrawn, or hypothetical candidates. This audit does not automatically decide why a question differs; inspect field dates and source questionnaire before using it.",
        "",
    ]
    for state in ("SD", "MT"):
        values = unknown_names[state]
        lines.append(
            f"- {state} unmatched names: "
            + (", ".join(f"{name} ({count} questions)" for name, count in values.most_common()) or "none")
            + "."
        )
    output = Path("docs/ballot_question_audit.md")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {output}; questions audited: {len(questions)}")


if __name__ == "__main__":
    main()
