"""Compare the old one-cycle Senate correction with the new 2024 holdout."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modeling"))
import stage4_poll_model as stage4


def main() -> None:
    parameters = json.loads((ROOT / "artifacts" / "stage4" / "model_parameters.json").read_text(encoding="utf-8"))
    coordinate = parameters["poll_error_model"]["coordinates"]["0"]
    coefficients = coordinate["coefficients"]
    connection = sqlite3.connect(ROOT / "data" / "processed" / "stage2.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        races = stage4.stage3.load_historical_races(connection)
        current_questions = stage4.load_current_questions(
            connection, ROOT / "data" / "processed" / "stage1.sqlite"
        )
    finally:
        connection.close()
    rows, inventory = stage4.senate_bias.load_observations(races)
    holdout = [row for row in rows if row.cycle == 2024]

    def old_question_prediction(question: stage4.PollQuestion) -> float:
        features = stage4.question_features(question)
        value = float(coordinate["intercept"])
        for name, item in features.items():
            if isinstance(item, str):
                value += coefficients.get(f"{name}={item}", 0.0)
            else:
                value += coefficients.get(name, 0.0)*item
        return value

    def old_prediction(row: stage4.senate_bias.Observation) -> float:
        question = stage4.PollQuestion(
            question_key="diagnostic", poll_id="diagnostic", race_key=row.race_key,
            office="senate", pollster=row.pollster, population=row.population,
            methodology="unknown", sponsor="", partisan="", internal="",
            sample_size=row.sample_size,
            election_date=stage4.senate_bias.election_day(row.cycle),
            end_date=row.end_date, available_date=row.end_date, options=(),
        )
        return old_question_prediction(question)

    new_model, _ = stage4.senate_bias.fit_through_cycle(rows, 2024)
    cutoff = datetime.fromisoformat(
        parameters["metadata"]["information_cutoff_utc"].replace("Z", "+00:00")
    ).replace(tzinfo=None)
    current_by_state = defaultdict(list)
    for question in current_questions:
        if (question.office != "senate" or question.available_date > cutoff
                or stage4.question_group_coords(question)[0] is None):
            continue
        age = max(0, (cutoff-question.end_date).days)
        weight = 2**(-age/30)*math.sqrt(max(question.sample_size, 100)/600)
        state = question.race_key.split("-")[2]
        current_by_state[state].append((
            old_question_prediction(question),
            new_model.predict(question.pollster, question.population, question.sample_size),
            weight,
        ))
    current_adjustments = {
        state: {
            "poll_count": len(values),
            "old_D_margin_correction_points_approx": 50*sum(old*w for old, _, w in values)/sum(w for _, _, w in values),
            "new_D_margin_correction_points_approx": 50*sum(new*w for _, new, w in values)/sum(w for _, _, w in values),
        }
        for state, values in sorted(current_by_state.items())
    }

    report = {
        "source_sha256": inventory["source_sha256"],
        "holdout_cycle": 2024,
        "old_2018_correction": stage4.senate_bias.score_predictor(holdout, old_prediction),
        "multi_cycle_correction": parameters["senate_poll_bias_calibration"]["held_out_2024"]["selected"],
        "no_correction": parameters["senate_poll_bias_calibration"]["held_out_2024"]["no_correction"],
        "current_adjustment_by_state": current_adjustments,
        "note": "Same 2024 race set and 30-day as-of poll weighting; old model was fitted only on 2018. Approximate margin-point metrics are 50 times D/R log-ratio error.",
    }
    path = ROOT / "artifacts" / "senate_poll_bias_comparison.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
