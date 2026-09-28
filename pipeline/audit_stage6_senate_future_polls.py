"""Check held-today Senate forecasts against polls released in the next week.

This is a noisy near-term proxy for support at the cutoff, independent of the
eventual election result. Poll fieldwork can still straddle the cutoff.
"""

from __future__ import annotations

import json
import hashlib
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

DB = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "artifacts/calibration/stage6_senate_future_polls.json"
LEADS = (30, 14)
WINDOW_DAYS = 7
DRAWS = 1500


def summarize(rows):
    if not rows:
        return {"n_questions": 0, "n_races": 0}
    z = np.array([row["z"] for row in rows], dtype=float)
    return {"n_questions": len(rows), "n_races": len({row["race_id"] for row in rows}),
            "mean_standardized_error": round(float(z.mean()), 4),
            "standardized_error_sd": round(float(z.std(ddof=1)), 4) if len(z) > 1 else None,
            "coverage80": round(float(np.mean(np.abs(z) <= 1.281552)), 4),
            "coverage95": round(float(np.mean(np.abs(z) <= 1.959964)), 4),
            "mean_log_predictive_density": round(float(np.mean(
                [-0.5 * (math.log(2 * math.pi * row["variance"]) + row["z"] ** 2)
                 for row in rows])), 4)}


def main() -> None:
    with sqlite3.connect(DB) as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
        calibration_questions = m.load_historical_questions(connection)
    questions, _ = load_wayback_polls(races)
    transitions = m.stage3.build_transitions(races)
    by_race = defaultdict(list)
    for question in questions:
        by_race[question.race_key].append(question)
    by_id = {race.source_race_id: race for race in races}
    results = []
    for cycle in (2020, 2022, 2024):
        training = [transition for transition in transitions if transition.target_cycle < cycle]
        holdout = [transition for transition in transitions if transition.target_cycle == cycle
                   and transition.office == "senate"]
        models = m.stage3.fit_office_models(training)
        allocation = m.stage3.fit_candidate_allocation(races, max_cycle=cycle - 1)
        covariance = m.stage3.residual_covariance(
            [transition for transition in training if transition.office == "senate"], models["senate"])
        bias = m.fit_bias_model(calibration_questions, by_id, training_cycle=2018,
                                senate_training_through=cycle - 2)
        bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
        for lead in LEADS:
            rng = np.random.default_rng(20260924 + cycle * 100 + lead)
            scores = defaultdict(list)
            for transition in holdout:
                race = transition.target
                keys = [candidate.candidate_key for candidate in race.candidates]
                groups = [candidate.group for candidate in race.candidates]
                d_indices = [index for index, group in enumerate(groups) if group == "D"]
                r_indices = [index for index, group in enumerate(groups) if group == "R"]
                if len(d_indices) != 1 or len(r_indices) != 1:
                    continue
                cutoff = by_race[race.source_race_id][0].election_date - timedelta(days=lead) if by_race[race.source_race_id] else None
                if cutoff is None:
                    continue
                past = [q for q in by_race[race.source_race_id]
                        if q.available_date <= cutoff and q.end_date <= cutoff]
                future = [q for q in by_race[race.source_race_id]
                          if cutoff < q.available_date <= cutoff + timedelta(days=WINDOW_DAYS)
                          and cutoff < q.end_date <= cutoff + timedelta(days=WINDOW_DAYS)]
                if not future:
                    continue
                group_draws = rng.multivariate_normal(
                    m.stage3.transition_predict(models["senate"], transition), covariance, size=DRAWS)
                other_target = m.stage3.transition_other_share_target(models["senate"], transition)
                if other_target is not None:
                    group_draws = m.stage3.calibrate_other_share(group_draws, other_target)
                prior = m.stage3.simulate_candidates(
                    group_draws, m.stage3.historical_candidate_dicts(race),
                    allocation["senate"]["incumbent_log_utility"],
                    allocation["senate"]["within_group_sigma"], rng,
                    allocation["senate"]["write_in_share_samples"])
                rows, values, variances, diagnostics = (
                    m.poll_contrasts(past, keys, groups, bias, cutoff,
                                     apply_election_day_bias=False)
                    if past else ([], [], [], {"polled_candidate_keys": []}))
                if rows:
                    updated = m.affine_update_draws(prior, rows, values, variances)
                    combined = m.preserve_unpolled_candidate_mass(
                        prior, updated, keys, diagnostics["polled_candidate_keys"])
                else:
                    combined = prior
                expected_row = m.contrast_row(len(keys), d_indices[0], r_indices[0])
                for question in future:
                    obs_rows, obs_values, obs_variances, _ = m.poll_contrasts(
                        [question], keys, groups, bias, question.available_date,
                        apply_election_day_bias=False)
                    for row, observed, measurement_variance in zip(obs_rows, obs_values, obs_variances):
                        if not np.array_equal(row, expected_row):
                            continue
                        for method, samples in (("results_only", prior), ("combined", combined)):
                            projected = m.alr_candidate(samples) @ row
                            predictive_mean = float(projected.mean())
                            predictive_variance = float(np.var(projected, ddof=1) + measurement_variance)
                            z = (observed - predictive_mean) / math.sqrt(predictive_variance)
                            scores[(method, "all")].append({"race_id": race.source_race_id,
                                                            "poll_id": question.poll_id,
                                                            "z": z, "variance": predictive_variance})
                            scores[(method, "past_polls" if past else "no_past_polls")].append(
                                scores[(method, "all")][-1])
            results.append({"cycle": cycle, "lead_days": lead,
                            "scores": {f"{method}:{stratum}": summarize(rows)
                                       for (method, stratum), rows in scores.items()}})
            print(cycle, lead, results[-1]["scores"].get("combined:all"), flush=True)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    report = {"design": "Compare D/R log-ratio forecasts at each cutoff with independent archived poll questions released and fielded within the next seven days. The measurement variance is included in predictive intervals; movement during the next week and shared poll errors remain possible.",
              "draws_per_race": DRAWS,
              "source_database_sha256": digest(DB),
              "stage3_code_sha256": digest(ROOT / "modeling/stage3_results_baseline.py"),
              "stage4_code_sha256": digest(ROOT / "modeling/stage4_poll_model.py"),
              "audit_code_sha256": digest(Path(__file__)),
              "cells": results}
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT, flush=True)


if __name__ == "__main__":
    main()
