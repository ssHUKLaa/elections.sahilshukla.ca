"""Audit the signed 2018-trained D/R poll correction on the 2020 holdout."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math
from pathlib import Path
import sqlite3
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modeling import stage3_results_baseline as stage3  # noqa: E402
from modeling import stage4_poll_model as stage4  # noqa: E402


def summarize(label: str, values: list[tuple[float, float]]) -> None:
    raw = np.array([item[0] for item in values])
    corrected = np.array([item[1] for item in values])
    print(
        f"{label}: {len(values)} races; raw signed error {raw.mean():+.3f}, "
        f"adjusted signed error {corrected.mean():+.3f}; "
        f"raw MAE {np.abs(raw).mean():.3f}, adjusted MAE {np.abs(corrected).mean():.3f}"
    )


def main() -> None:
    connection = sqlite3.connect(ROOT / "data" / "processed" / "stage2.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        historical = stage3.load_historical_races(connection)
        by_id = {race.source_race_id: race for race in historical}
        questions = stage4.load_historical_questions(connection)
    finally:
        connection.close()
    model = stage4.fit_bias_model(questions, by_id)
    grouped = defaultdict(list)
    for question in questions:
        race = by_id.get(question.race_key)
        if race is None or race.cycle != 2020:
            continue
        if not stage4.eligible_at_cutoff(question, stage4.CUTOFF_DAYS):
            continue
        observed = stage4.question_group_coords(question)[0]
        if observed is None:
            continue
        cutoff = datetime(2020, 11, 3)-timedelta(days=stage4.CUTOFF_DAYS)
        age = max(0, (cutoff-question.end_date).days)
        weight = math.exp(-math.log(2)*age/model.half_life_days) * math.sqrt(
            max(question.sample_size, 100.0)/600.0
        )
        bias = stage4.predict_bias(model, question)[0]
        grouped[question.race_key].append((observed, observed-bias, weight))

    by_office = defaultdict(list)
    for race_id, observations in grouped.items():
        race = by_id[race_id]
        actual = stage4.race_actual_coords(race)[0]
        weights = [item[2] for item in observations]
        raw = np.average([item[0] for item in observations], weights=weights)
        corrected = np.average([item[1] for item in observations], weights=weights)
        by_office[race.office].append((float(raw-actual), float(corrected-actual)))
    for office in stage3.OFFICES:
        if by_office[office]:
            summarize(office, by_office[office])
    summarize("all", [item for values in by_office.values() for item in values])
    print("Errors are D/R log ratios. Positive means polls overstated Democrats.")


if __name__ == "__main__":
    main()
