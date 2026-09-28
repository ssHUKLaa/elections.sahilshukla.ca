"""Score a seven-day 2020 race nowcast against final certified vote shares."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as stage4


def main() -> None:
    connection = sqlite3.connect("data/processed/stage2.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        races = stage4.stage3.load_historical_races(connection)
        transitions = stage4.stage3.build_transitions(races)
        questions = stage4.load_historical_questions(connection)
    finally:
        connection.close()
    bias_model = stage4.fit_bias_model(
        questions, {race.source_race_id: race for race in races},
        senate_training_through=2018,
    )
    bias_model.half_life_days = stage4.CURRENT_POLL_HALF_LIFE_DAYS
    report = stage4.backtest(
        races, transitions, questions, bias_model, seed=20260923,
        holdout_cycle=2020, posterior_inflation=1.0,
        cutoff_days=7, apply_election_day_bias=False,
    )
    report["interpretation"] = (
        "Seven-day polls are compared with final results, so this is a terminal "
        "proxy for held-today support, not a direct counterfactual-nowcast score. "
        "Seven days of real movement and turnout uncertainty remain. "
        "The historical poll source differs from the live NYT feed."
    )
    group_coverage = {
        key: values["combined"]["coverage95"]
        for key, values in report["by_office_candidate_group"].items()
    }
    report["nowcast_group_gate"] = {
        "criterion": "at least 90% observed coverage for every office and candidate group",
        "coverage95": group_coverage,
        "passed": all(value >= 0.90 for value in group_coverage.values()),
    }
    output = Path("artifacts/terminal_nowcast_audit.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "nowcast_group_gate": report["nowcast_group_gate"], "overall": report["overall"],
                      "by_office": report["by_office"]}, indent=2))


if __name__ == "__main__":
    main()
