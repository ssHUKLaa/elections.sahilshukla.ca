"""Describe seven-day Senate D/R poll error by held-out cycle and race."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m
from pipeline.load_stage6_wayback_polls import load as load_wayback_polls


def main() -> None:
    with sqlite3.connect(ROOT / "data/processed/stage2.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
    questions, _ = load_wayback_polls(races)
    by_race = defaultdict(list)
    for question in questions:
        if m.eligible_at_cutoff(question, 7):
            by_race[question.race_key].append(question)
    report = {}
    for cycle in (2020, 2022, 2024):
        rows = []
        for race in races:
            if race.office != "senate" or race.cycle != cycle:
                continue
            groups = defaultdict(list)
            for candidate in race.candidates:
                groups[candidate.group].append(candidate)
            if len(groups["D"]) != 1 or len(groups["R"]) != 1:
                continue
            if max(race.candidates, key=lambda item: item.votes).group == "O":
                continue
            dem_key = groups["D"][0].candidate_key
            rep_key = groups["R"][0].candidate_key
            election_date = m.senate_bias.election_day(cycle)
            cutoff = election_date - timedelta(days=7)
            estimates = []
            for question in by_race[race.source_race_id]:
                option_by_id = {option.candidate_key: option for option in question.options}
                if dem_key not in option_by_id or rep_key not in option_by_id:
                    continue
                dem = option_by_id[dem_key].pct
                rep = option_by_id[rep_key].pct
                if dem <= 0 or rep <= 0:
                    continue
                age = max(0, (cutoff - question.end_date).days)
                weight = math.exp(-math.log(2)*age/30)*math.sqrt(max(question.sample_size, 100)/600)
                estimates.append((math.log(dem/rep), weight, question.pollster))
            if not estimates:
                continue
            poll_log = float(np.average([x[0] for x in estimates], weights=[x[1] for x in estimates]))
            actual_log = math.log(groups["D"][0].votes/groups["R"][0].votes)
            error = 100*(math.tanh(poll_log/2)-math.tanh(actual_log/2))
            rows.append({"race_id": race.source_race_id, "state": race.state,
                         "poll_questions": len(estimates), "pollsters": len({x[2] for x in estimates}),
                         "D_margin_poll_pct": round(100*math.tanh(poll_log/2), 2),
                         "D_margin_result_pct": round(100*math.tanh(actual_log/2), 2),
                         "poll_minus_result_margin_points": round(error, 2)})
        errors = np.array([row["poll_minus_result_margin_points"] for row in rows])
        report[str(cycle)] = {
            "n_races": len(rows),
            "mean_poll_minus_result_D_margin_points": round(float(errors.mean()), 3) if len(errors) else None,
            "sd_across_races_margin_points": round(float(errors.std(ddof=1)), 3) if len(errors) > 1 else None,
            "mae_margin_points": round(float(np.mean(abs(errors))), 3) if len(errors) else None,
            "races": sorted(rows, key=lambda row: abs(row["poll_minus_result_margin_points"]), reverse=True),
        }
    output = {"design": "Seven-day, same-race named D/R poll log-ratio averages against eventual D/R vote margins. Ignores third-party vote-share error; excludes O-won races. A terminal proxy with real late movement, not direct held-today calibration.",
              "cycles": report}
    path = ROOT / "artifacts/calibration/stage6_senate_poll_error.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({cycle: {k: v for k, v in data.items() if k != "races"}
                      for cycle, data in report.items()}, indent=2))


if __name__ == "__main__":
    main()
