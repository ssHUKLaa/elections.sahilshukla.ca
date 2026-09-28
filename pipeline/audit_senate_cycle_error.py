"""Estimate held-out Senate polling-error variation shared within an election cycle.

This is a diagnostic of the current directional correction. It does not change
the accepted forecast or borrow current peer forecasts as training data.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modeling"))
import stage4_poll_model as stage4


def race_residuals(model, observations):
    by_race = defaultdict(list)
    for row in observations:
        error_points = 50*(row.error_logratio-model.predict(row.pollster, row.population, row.sample_size))
        by_race[row.race_key].append((error_points, row.weight))
    return np.array([
        np.average([item[0] for item in values], weights=[item[1] for item in values])
        for values in by_race.values()
    ])


def log_density(errors, race_sd, cycle_sd):
    covariance = np.eye(len(errors))*race_sd**2 + np.ones((len(errors), len(errors)))*cycle_sd**2
    sign, logdet = np.linalg.slogdet(covariance)
    if sign != 1:
        raise ValueError("Nonpositive predictive covariance")
    return float(-0.5*(len(errors)*math.log(2*math.pi)+logdet+errors @ np.linalg.solve(covariance, errors)))


def main():
    connection = sqlite3.connect(ROOT / "data/processed/stage2.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        history = stage4.stage3.load_historical_races(connection)
    finally:
        connection.close()
    observations, inventory = stage4.senate_bias.load_observations(history)
    parameters = json.loads((ROOT / "artifacts/stage4/model_parameters.json").read_text(encoding="utf-8"))
    selected = parameters["senate_poll_bias_calibration"]["selected"]
    folds = []
    for cycle in (2016, 2018, 2020, 2022, 2024):
        train = [row for row in observations if row.cycle < cycle]
        test = [row for row in observations if row.cycle == cycle]
        model = stage4.senate_bias.fit(train, selected["specification"], selected["alpha"])
        errors = race_residuals(model, test)
        folds.append({
            "cycle": cycle, "races": len(errors), "polls": len(test),
            "mean_residual_D_points": float(errors.mean()),
            "race_rmse_points": float(np.sqrt(np.mean(errors**2))),
            "race_residuals_D_points": errors.tolist(),
        })
    tuning = folds[:-1]
    within_variance = sum(
        sum((np.array(fold["race_residuals_D_points"])-fold["mean_residual_D_points"])**2)
        for fold in tuning
    )/sum(fold["races"]-1 for fold in tuning)
    cycle_means = np.array([fold["mean_residual_D_points"] for fold in tuning])
    observed_cycle_variance = float(np.var(cycle_means, ddof=1))
    mean_sampling_variance = float(np.mean([within_variance/fold["races"] for fold in tuning]))
    cycle_sd = math.sqrt(max(0.0, observed_cycle_variance-mean_sampling_variance))
    race_sd = math.sqrt(within_variance)
    heldout = np.array(folds[-1]["race_residuals_D_points"])
    report = {
        "method": "Fixed selected directional correction; whole-cycle chronological holdouts. Cycle variance estimated from 2016-2022 fold means after subtracting estimated within-cycle sampling variance; 2024 untouched for this variance estimate.",
        "source_sha256": inventory["source_sha256"],
        "directional_specification": selected,
        "folds": folds,
        "estimated_within_cycle_race_sd_points": race_sd,
        "estimated_shared_cycle_sd_points": cycle_sd,
        "tuning_cycle_means_sd_points": math.sqrt(observed_cycle_variance),
        "heldout_2024_predictive_log_density": {
            "independent_races": log_density(heldout, race_sd, 0.0),
            "shared_cycle_error": log_density(heldout, race_sd, cycle_sd),
        },
        "limitations": [
            "Only four tuning cycles estimate shared variation; precision is low.",
            "The archive is RealClearPolling-derived, not the live NYT source.",
            "The target mixes poll error and late movement between fieldwork and election.",
            "This evaluates predictive error covariance, not 2026 directional mean correction transportability.",
            "The specification was selected using the 2016-2022 folds; only 2024 is untouched for this variance check.",
        ],
    }
    path = ROOT / "artifacts/senate_cycle_error_audit.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {path}")
    print(f"Within-cycle race SD: {race_sd:.2f} margin points; shared-cycle SD: {cycle_sd:.2f}")
    print("2024 log density:", report["heldout_2024_predictive_log_density"])


if __name__ == "__main__":
    main()
