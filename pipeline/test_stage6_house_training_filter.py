"""Test removing identifiable map-mismatched House transitions from training."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m
from pipeline.load_stage6_wayback_polls import load as load_wayback_polls
from pipeline.run_stage6_calibration import district_continuity, run_cell


def fit_and_score(training, holdout, races, questions, calibration_questions, continuity):
    models = m.stage3.fit_office_models(training)
    allocation = m.stage3.fit_candidate_allocation(races, max_cycle=2022)
    covariances = {office: m.stage3.residual_covariance(
        [t for t in training if t.office == office], models[office]
    ) for office in m.OFFICES}
    bias = m.fit_bias_model(calibration_questions,
                            {race.source_race_id: race for race in races},
                            training_cycle=2018, senate_training_through=2022)
    bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
    return run_cell(2024, 7, holdout, questions, models, allocation, covariances,
                    bias, 1500, continuity)


def main():
    with sqlite3.connect(ROOT / "data/processed/stage2.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
        calibration_questions = m.load_historical_questions(connection)
    questions, _ = load_wayback_polls(races)
    transitions = m.stage3.build_transitions(races, use_candidate_move_prior=False)
    continuity = district_continuity(races, transitions)
    training = [t for t in transitions if t.target_cycle < 2024]
    filtered = [t for t in training if not (
        t.office == "house" and t.target_cycle == 2022
        and continuity[t.target.source_race_id] == "documented_candidate_move"
    )]
    holdout = [t for t in transitions if t.target_cycle == 2024]
    baseline = fit_and_score(training, holdout, races, questions, calibration_questions, continuity)
    candidate = fit_and_score(filtered, holdout, races, questions, calibration_questions, continuity)
    strata = ("all", "office:house", "district_continuity:documented_candidate_move",
              "district_continuity:same_district_candidate")
    output = {"design": "2024 untouched-cycle seven-day sensitivity; filter chosen from 2022 candidate-move evidence; identical polls and random seed",
              "removed_house_2022_transitions": len(training)-len(filtered),
              "strata": {name: {"n_races": baseline["strata"][name]["n_races"],
                                "all_training": baseline["strata"][name]["methods"]["combined"],
                                "filtered_training": candidate["strata"][name]["methods"]["combined"]}
                         for name in strata}}
    path = ROOT / "artifacts/calibration/stage6_training_filter_sensitivity.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
