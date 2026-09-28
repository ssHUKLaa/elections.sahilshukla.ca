"""Trace pivotal Senate races from accepted NYT questions to the forecast.

Read-only with respect to the model: this writes a diagnostic report from the
frozen Stage 1/2 inputs and accepted Stage 4/5 artifacts. Peer estimates are
deliberately kept out of the calculation.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modeling"))
import stage4_poll_model as stage4

STATES = ("AK", "IA", "ME", "MI", "OH", "TX")


def margin(candidates: list[dict], field: str) -> float | None:
    d = sum(c[field]["mean"] for c in candidates if c["party_group"] == "D")
    r = sum(c[field]["mean"] for c in candidates if c["party_group"] == "R")
    return (d-r)/(d+r) if d > 0 and r > 0 else None


def weighted_margin(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    logratio = sum(row[key]*row["weight"] for row in rows)/sum(row["weight"] for row in rows)
    return math.tanh(logratio/2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "senate_race_trace.json")
    args = parser.parse_args()
    parameters = json.loads((ROOT / "artifacts/stage4/model_parameters.json").read_text(encoding="utf-8"))
    stage4_path = ROOT / "artifacts/stage4/forecast_2026.json"
    stage5_path = ROOT / "artifacts/stage5/forecast_2026.json"
    stage1_path = ROOT / "data/processed/stage1.sqlite"
    stage2_path = ROOT / "data/processed/stage2.sqlite"
    for path, key in ((stage1_path, "stage1_data_sha256"), (stage2_path, "data_sha256")):
        if stage4.sha256(path) != parameters["metadata"][key]:
            raise RuntimeError(f"Input has changed since accepted Stage 4: {path}")
    forecast4 = json.loads(stage4_path.read_text(encoding="utf-8"))
    forecast5 = json.loads(stage5_path.read_text(encoding="utf-8"))
    components = json.loads((ROOT / "artifacts/senate_component_audit.json").read_text(encoding="utf-8"))
    if components["stage1_sha256"] != stage4.sha256(stage1_path) or components["stage2_sha256"] != stage4.sha256(stage2_path):
        raise RuntimeError("Component audit uses a different input snapshot")
    cutoff = datetime.fromisoformat(parameters["metadata"]["information_cutoff_utc"].replace("Z", "+00:00")).replace(tzinfo=None)
    half_life = float(parameters["current_poll_recency"]["half_life_days"])

    connection = sqlite3.connect(stage2_path)
    connection.row_factory = sqlite3.Row
    try:
        history = stage4.stage3.load_historical_races(connection)
        historical_questions = stage4.load_historical_questions(connection)
        bias_model = stage4.fit_bias_model(historical_questions, {race.source_race_id: race for race in history})
        bias_model.half_life_days = half_life
        questions = stage4.load_current_questions(connection, stage1_path)
    finally:
        connection.close()

    race4 = {row["race_id"]: row for row in forecast4["races"] if row["office"] == "senate"}
    race5 = {row["race_id"]: row for row in forecast5["races"] if row["office"] == "senate"}
    output = {}
    for race_id, record in race4.items():
        state = record["state"]
        if state not in STATES:
            continue
        used_keys = set(record["poll_diagnostics"]["question_keys"])
        poll_rows = []
        for question in questions:
            if question.race_key != race_id or question.question_key not in used_keys:
                continue
            if question.available_date > cutoff:
                raise RuntimeError(f"Future question in accepted forecast: {question.question_key}")
            raw, _ = stage4.question_group_coords(question)
            if raw is None:
                continue
            age = max(0, (cutoff-question.end_date).days)
            weight = 2**(-age/half_life)*math.sqrt(max(question.sample_size, 100)/600)
            bias = stage4.predict_bias(bias_model, question)[0]
            d_pct = sum(option.pct for option in question.options if option.candidate_key and option.party_group == "D")
            r_pct = sum(option.pct for option in question.options if option.candidate_key and option.party_group == "R")
            poll_rows.append({
                "poll_id": question.poll_id, "question_key": question.question_key,
                "pollster": question.pollster, "population": question.population,
                "end_date": question.end_date.strftime("%Y-%m-%d"),
                "available_date": question.available_date.strftime("%Y-%m-%d"),
                "age_days": age, "sample_size": question.sample_size,
                "D_pct": d_pct, "R_pct": r_pct,
                "raw_D_R_margin": (d_pct-r_pct)/(d_pct+r_pct),
                "correction_D_R_margin_points_approx": 50*bias,
                "raw_logratio": raw, "adjusted_logratio": raw-bias, "weight": weight,
            })
        poll_rows.sort(key=lambda row: (row["end_date"], row["pollster"]), reverse=True)
        if len(poll_rows) != record["poll_diagnostics"]["question_count"]:
            raise RuntimeError(f"Could not reconstruct all accepted D/R questions for {state}")
        by_window = {}
        for label, maximum_age in (("all_accepted", None), ("last_90_days", 90), ("last_30_days", 30)):
            subset = [row for row in poll_rows if maximum_age is None or row["age_days"] <= maximum_age]
            by_window[label] = {
                "poll_count": len(subset),
                "raw_margin": weighted_margin(subset, "raw_logratio"),
                "bias_adjusted_margin": weighted_margin(subset, "adjusted_logratio"),
                "mean_correction_margin_points_approx": (
                    sum(row["correction_D_R_margin_points_approx"]*row["weight"] for row in subset)
                    /sum(row["weight"] for row in subset) if subset else None
                ),
                "latest_end_date": max((row["end_date"] for row in subset), default=None),
            }
        baseline = components["variants"]["accepted_components"]["races"][race_id]
        no_bias = components["variants"]["without_senate_poll_bias_correction"]["races"][race_id]
        no_polls = components["variants"]["without_race_polls"]["races"][race_id]
        output[state] = {
            "race_id": race_id, "counting_rule": record["counting_rule"],
            "candidates": [{
                "name": candidate["name"], "party_group": candidate["party_group"],
                "prior_winner_match_flag": candidate["incumbent"],
            } for candidate in record["candidates"]],
            "stage3_prior_margin": margin(record["candidates"], "stage3_share"),
            "national_local_without_race_polls_margin": no_polls["D_R_margin"],
            "poll_windows": by_window,
            "final_margin": margin(record["candidates"], "share"),
            "final_D_win_probability": sum(candidate["eventual_win_probability"] for candidate in race5[race_id]["candidates"] if candidate["party_group"] == "D"),
            "component_replay_D_win_probability": baseline["D_win_probability"],
            "no_bias_replay_D_win_probability": no_bias["D_win_probability"],
            "no_race_polls_replay_D_win_probability": no_polls["D_win_probability"],
            "polls": poll_rows,
        }
    report = {
        "cutoff_utc": parameters["metadata"]["information_cutoff_utc"],
        "snapshot_ids": parameters["metadata"]["input_snapshot_ids"],
        "current_poll_half_life_days": half_life,
        "margin_definition": "D minus R divided by D plus R; positive favors Democrats",
        "method": "Raw and corrected poll margins are tanh(weighted mean D/R log ratio divided by 2); final margins use posterior mean candidate shares. These are not an additive decomposition.",
        "component_replay_note": "No-bias and no-race-poll probabilities use 20,000 paired draws with other components held fixed; they are uncalibrated diagnostics.",
        "races": output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}")
    for state, row in output.items():
        recent = row["poll_windows"]["last_90_days"]
        print(f"{state}: prior {row['stage3_prior_margin']:+.1%}, national/local {row['national_local_without_race_polls_margin']:+.1%}, "
              f"90d polls {recent['raw_margin']:+.1%}, corrected {recent['bias_adjusted_margin']:+.1%}, "
              f"final {row['final_margin']:+.1%}, D win {row['final_D_win_probability']:.1%}")


if __name__ == "__main__":
    main()
