"""Audit current Senate poll mapping and high-impact ballot options."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE1 = ROOT / "data/processed/stage1.sqlite"
STAGE2 = ROOT / "data/processed/stage2.sqlite"
FORECAST = ROOT / "artifacts/nowcast/forecast_2026.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_live_senate_input_audit.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    forecast = json.loads(FORECAST.read_text(encoding="utf-8"))
    races = {race["race_id"]: race for race in forecast["races"] if race["office"] == "senate"}
    with sqlite3.connect(STAGE2) as connection:
        connection.execute("ATTACH DATABASE ? AS stage1", (str(STAGE1),))
        by_race: dict[str, dict] = defaultdict(lambda: {
            "source_questions": set(), "source_polls": set(),
            "eligible_questions": set(), "eligible_polls": set(),
            "eligible_poll_end_dates": set(),
            "mapping_statuses": Counter(), "quarantined_options": Counter(),
        })
        for race_id, question_key, poll_id, status, eligible, end_date in connection.execute(
            "SELECT m.project_race_id, m.question_key, q.source_poll_id, "
            "m.mapping_status, m.model_eligible, p.end_date FROM current_question_map m "
            "JOIN stage1.questions q ON q.snapshot_id=m.snapshot_id "
            "AND q.question_key=m.question_key "
            "JOIN stage1.polls p ON p.snapshot_id=q.snapshot_id "
            "AND p.feed=q.feed AND p.source_poll_id=q.source_poll_id "
            "WHERE m.feed='senate' AND m.project_race_id LIKE 'S-2026-%' "
            "AND q.cycle='2026' AND q.stage='general'"
        ):
            record = by_race[race_id]
            record["source_questions"].add(question_key)
            record["source_polls"].add(poll_id)
            record["mapping_statuses"][status] += 1
            if eligible:
                record["eligible_questions"].add(question_key)
                record["eligible_polls"].add(poll_id)
                if end_date:
                    record["eligible_poll_end_dates"].add(end_date)
        for race_id, name, count in connection.execute(
            "SELECT m.project_race_id, o.source_candidate_name, COUNT(DISTINCT m.question_key) "
            "FROM current_question_map m JOIN current_option_map o "
            "ON o.snapshot_id=m.snapshot_id AND o.question_key=m.question_key "
            "WHERE m.feed='senate' AND m.project_race_id LIKE 'S-2026-%' "
            "AND m.mapping_status='quarantined_options' "
            "AND o.mapping_status='unmapped_candidate' "
            "GROUP BY m.project_race_id,o.source_candidate_name"
        ):
            by_race[race_id]["quarantined_options"][name or ""] = count
    result = []
    for race_id, race in races.items():
        record = by_race[race_id]
        candidates = [{
            "name": candidate["name"],
            "party": candidate["party"],
            "status": candidate["status"],
            "win_probability": candidate["eventual_win_probability"],
        } for candidate in race["candidates"]]
        winner_probs = sorted((candidate["win_probability"] for candidate in candidates), reverse=True)
        result.append({
            "race_id": race_id, "state": race["state"],
            "counting_rule": race["counting_rule"],
            "ballot_status": race["ballot_status"],
            "source_question_count": len(record["source_questions"]),
            "source_poll_count": len(record["source_polls"]),
            "eligible_question_count": len(record["eligible_questions"]),
            "eligible_poll_count": len(record["eligible_polls"]),
            "latest_eligible_poll_end_date": max(record["eligible_poll_end_dates"],
                key=lambda value: datetime.strptime(value, "%m/%d/%y"), default=None),
            "mapping_statuses": dict(record["mapping_statuses"]),
            "unmapped_candidate_names": dict(record["quarantined_options"]),
            "modeled_poll_count": race["poll_diagnostics"]["poll_count"],
            "runner_up_win_probability": winner_probs[1] if len(winner_probs) > 1 else 0.0,
            "other_win_probability": sum(candidate["win_probability"] for candidate in candidates
                                         if candidate["party"] not in {"DEM", "REP"}),
            "candidates": candidates,
        })
    result.sort(key=lambda item: item["runner_up_win_probability"], reverse=True)
    report = {
        "design": "For all current Senate races, join the frozen NYT Senate feed to reviewed Stage 2 question maps and the validated Stage 5 forecast. Rank races by runner-up win probability as an impact triage, not an independent probability estimate.",
        "source_hashes": {
            "stage1": sha(STAGE1),
            "stage2": sha(STAGE2),
            "forecast": sha(FORECAST),
        },
        "counts": {
            "senate_races": len(result),
            "races_with_source_polls_but_no_eligible_polls": sum(
                race["source_poll_count"] > 0 and race["eligible_poll_count"] == 0 for race in result
            ),
            "races_with_quarantined_general_questions": sum(
                race["mapping_statuses"].get("quarantined_options", 0) > 0 for race in result
            ),
        },
        "races": result,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], indent=2))
    for race in result[:12]:
        print(race["state"], round(race["runner_up_win_probability"], 3),
              race["eligible_poll_count"], race["unmapped_candidate_names"])
    print(OUTPUT)


if __name__ == "__main__":
    main()
