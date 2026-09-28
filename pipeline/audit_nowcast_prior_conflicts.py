"""Trace where the 2026 structural prior and live D/R race polls disagree."""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import pollster_quality  # noqa: E402
from modeling import stage4_poll_model as stage4  # noqa: E402


def margin(shares: np.ndarray, groups: list[str]) -> np.ndarray:
    d = shares[:, [i for i, group in enumerate(groups) if group == "D"]].sum(axis=1)
    r = shares[:, [i for i, group in enumerate(groups) if group == "R"]].sum(axis=1)
    return (d-r)/np.maximum(d+r, 1e-9)


def main() -> None:
    stage1_path = Path("data/processed/stage1.sqlite")
    stage2_path = Path("data/processed/stage2.sqlite")
    connection = sqlite3.connect(stage2_path)
    connection.row_factory = sqlite3.Row
    try:
        source_id = dict(connection.execute("SELECT key,value FROM build_metadata"))["source_snapshot_id"]
        weights, quality = pollster_quality.load_weights(
            stage1_path, Path("data/reference/pollster_ratings/ratings.csv"),
            snapshot_id=source_id,
        )
        source = sqlite3.connect(stage1_path)
        try:
            cutoff_token = source.execute(
                "SELECT retrieved_at_utc FROM source_snapshots WHERE snapshot_id=?", (source_id,)
            ).fetchone()[0]
        finally:
            source.close()
        cutoff = datetime.strptime(cutoff_token, "%Y%m%dT%H%M%SZ")
        history = stage4.stage3.load_historical_races(connection)
        transitions = stage4.stage3.build_transitions(history)
        current = stage4.stage3.load_current_races(connection)
        models = stage4.stage3.fit_office_models(transitions)
        allocation = stage4.stage3.fit_candidate_allocation(history)
        decomposition = stage4.stage3.decompose_covariance(transitions, models)
        prior = stage4.current_prior_draws(current, models, allocation, decomposition, 4000, 20260921)
        national, _ = stage4.fit_national_signal_update(
            connection, stage1_path, history, current, prior, cutoff,
            nowcast=True, quality_weights=weights,
        )
        questions = stage4.load_current_questions(connection, stage1_path)
        bias_model = stage4.fit_bias_model(
            stage4.load_historical_questions(connection),
            {race.source_race_id: race for race in history},
        )
        bias_model.half_life_days = stage4.CURRENT_POLL_HALF_LIFE_DAYS
    finally:
        connection.close()
    by_race = defaultdict(list)
    for question in questions:
        if question.available_date <= cutoff and question.end_date <= cutoff:
            by_race[question.race_key].append(question)
    output = []
    for item in current:
        race = item["race"]
        race_id = race["race_id"]
        candidates = item["candidates"]
        groups = [stage4.stage3.party_group(candidate["party"]) for candidate in candidates]
        if "D" not in groups or "R" not in groups:
            continue
        poll_values, poll_weights = [], []
        for question in by_race[race_id]:
            if weights.get(question.poll_id, 1.0) <= 0:
                continue
            observed = stage4.question_group_coords(question)[0]
            if observed is None:
                continue
            age = max(0, (cutoff-question.end_date).days)
            weight = (math.exp(-math.log(2)*age/bias_model.half_life_days)
                      * math.sqrt(max(question.sample_size, 100)/600)
                      * weights.get(question.poll_id, 1.0))
            poll_values.append(observed)
            poll_weights.append(weight)
        if not poll_values:
            continue
        keys = [candidate["ballot_entry_id"] for candidate in candidates]
        rows, values, variances, diagnostics = stage4.poll_contrasts(
            by_race[race_id], keys, groups, bias_model, cutoff,
            quality_weights=weights, apply_election_day_bias=False,
        )
        updated = stage4.affine_update_draws(national[race_id], rows, values, variances)
        updated = stage4.preserve_unpolled_candidate_mass(
            national[race_id], updated, keys, diagnostics["polled_candidate_keys"]
        )
        prior_margin = float(margin(national[race_id], groups).mean()*100)
        poll_margin = float(math.tanh(np.average(poll_values, weights=poll_weights)/2)*100)
        posterior_margin = float(margin(updated, groups).mean()*100)
        output.append({
            "race_id": race_id, "office": race["office"], "state": race["state"],
            "poll_count": len(poll_values), "rated_poll_count": diagnostics["rated_poll_count"],
            "prior_D_margin_points": prior_margin, "poll_D_margin_points": poll_margin,
            "posterior_D_margin_points": posterior_margin,
            "prior_minus_poll_margin_points": prior_margin-poll_margin,
        })
    output.sort(key=lambda row: abs(row["prior_minus_poll_margin_points"]), reverse=True)
    report = {"cutoff_utc": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "rating_source": quality["silver_path"], "races": output}
    path = Path("artifacts/nowcast_prior_conflicts.json")
    path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"polled_DR_races": len(output),
                      "largest_senate_conflicts": [row for row in output if row["office"] == "senate"][:12]}, indent=2))


if __name__ == "__main__":
    main()
