"""Audit how often each 2026 Senate ballot candidate appears in usable polls."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def report(database: Path, stage1_database: Path) -> dict:
    with sqlite3.connect(database) as connection:
        connection.execute("ATTACH DATABASE ? AS stage1", (str(stage1_database),))
        poll_ids: dict[str, set[str]] = defaultdict(set)
        for race_id, poll_id in connection.execute(
            "SELECT m.project_race_id, q.source_poll_id FROM current_question_map m "
            "JOIN stage1.questions q ON q.snapshot_id=m.snapshot_id "
            "AND q.question_key=m.question_key "
            "WHERE m.model_eligible=1 AND m.project_race_id LIKE 'S-2026-%'"
        ):
            poll_ids[race_id].add(poll_id)
        appearances: dict[tuple[str, str], set[str]] = defaultdict(set)
        observed: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for race_id, candidate_id, poll_id, pct in connection.execute(
            "SELECT m.project_race_id, o.ballot_entry_id, q.source_poll_id, o.pct "
            "FROM current_question_map m "
            "JOIN stage1.questions q ON q.snapshot_id=m.snapshot_id "
            "AND q.question_key=m.question_key "
            "JOIN current_option_map o ON o.snapshot_id=m.snapshot_id "
            "AND o.question_key=m.question_key "
            "WHERE m.model_eligible=1 AND m.project_race_id LIKE 'S-2026-%' "
            "AND o.ballot_entry_id IS NOT NULL"
        ):
            appearances[(race_id, candidate_id)].add(poll_id)
            if pct is not None:
                observed[(race_id, candidate_id, poll_id)].append(float(pct))
        candidates = connection.execute(
            "SELECT race_id, ballot_entry_id, name, ballot_party, write_in_only "
            "FROM candidates WHERE race_id LIKE 'S-2026-%' ORDER BY race_id,name"
        ).fetchall()
    races: dict[str, dict] = {}
    for race_id, candidate_id, name, party, write_in_only in candidates:
        n = len(poll_ids[race_id])
        count = len(appearances[(race_id, candidate_id)])
        shares = [statistics.mean(observed[(race_id, candidate_id, poll_id)])
                  for poll_id in appearances[(race_id, candidate_id)]
                  if observed[(race_id, candidate_id, poll_id)]]
        race = races.setdefault(race_id, {"usable_polls": n, "candidates": []})
        race["candidates"].append({
            "ballot_entry_id": candidate_id,
            "name": name,
            "party": party,
            "write_in_only": bool(write_in_only),
            "polls_naming_candidate": count,
            "fraction": count/n if n else None,
            "majority_named": 2*count > n if n else None,
            "median_pct_when_named": statistics.median(shares) if shares else None,
            "polls_at_least_10_pct": sum(pct >= 10 for pct in shares),
        })
    return {"design": "Count distinct source polls with at least one eligible current-ballot question. A candidate is named if any eligible question in that poll names that ballot entry. No-poll races remain unclassified.",
            "races": races}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--stage1-database", type=Path, default=ROOT / "data/processed/stage1.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/calibration/senate_contender_coverage_2026.json")
    args = parser.parse_args()
    result = report(args.database, args.stage1_database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for race_id, race in result["races"].items():
        if race["usable_polls"] >= 3:
            excluded = [c["name"] for c in race["candidates"] if not c["majority_named"]
                        and c["party"] not in {"DEM", "REP"}]
            if excluded:
                print(race_id, race["usable_polls"], json.dumps(excluded, ensure_ascii=True))
    print(args.output)


if __name__ == "__main__":
    main()
