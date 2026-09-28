"""Explain missing regular Senate races in the historical joint replay."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as stage3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/calibration/stage6_historical_senate_gaps.json")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        history = stage3.load_historical_races(connection)
        transitions = stage3.build_transitions(history)
        rows = connection.execute("""SELECT source_race_id,cycle,state,stage FROM historical_races
            WHERE cycle IN (2020,2022,2024) AND office='senate'
            AND stage IN ('general','jungle primary') AND special=0
            ORDER BY cycle,state""").fetchall()
        reconciliation = {(row["cycle"], row["state"]): row["status"] for row in
                          connection.execute("""SELECT cycle,state,status FROM result_reconciliation
                              WHERE cycle IN (2020,2022,2024) AND office='senate'""")}
    numeric = {r.source_race_id for r in history if r.office == "senate"}
    modeled = {t.target.source_race_id for t in transitions if t.office == "senate"}
    report = {}
    for cycle in (2020, 2022, 2024):
        expected = [r for r in rows if r["cycle"] == cycle]
        missing = []
        for row in expected:
            race_id = row["source_race_id"]
            if race_id in modeled:
                continue
            status = reconciliation.get((cycle, row["state"]))
            missing.append({"state": row["state"], "source_race_id": race_id,
                            "reconciliation_status": status,
                            "numeric_result_eligible": race_id in numeric,
                            "reason": "no_same_seat_six_year_prior" if race_id in numeric
                            else "official_or_archive_result_unavailable"})
        report[str(cycle)] = {"regular_first_stage_races": len(expected),
                              "modeled_transitions": len(expected)-len(missing),
                              "missing": missing}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
