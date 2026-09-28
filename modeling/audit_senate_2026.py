"""Expose Senate prior, recent polls, and forecast in comparable D/R margins."""

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

import stage4_poll_model as stage4

ROOT = Path(__file__).resolve().parents[1]


def margin(candidates, share_key):
    d = r = 0.0
    for candidate in candidates:
        value = candidate[share_key]["mean"]
        if candidate["party_group"] == "D":
            d += value
        elif candidate["party_group"] == "R":
            r += value
    return (d-r)/(d+r) if d > 0 and r > 0 else None


def main():
    connection = sqlite3.connect(ROOT / "data" / "processed" / "stage2.sqlite")
    connection.row_factory = sqlite3.Row
    questions = stage4.load_current_questions(connection, ROOT / "data" / "processed" / "stage1.sqlite")
    connection.close()
    stage4_forecast = json.loads((ROOT / "artifacts" / "stage4" / "forecast_2026.json").read_text())
    stage5_forecast = json.loads((ROOT / "artifacts" / "stage5" / "forecast_2026.json").read_text())
    local = json.loads((ROOT / "artifacts" / "senate_local_lean_research.json").read_text())
    before = json.loads((ROOT / "artifacts" / "senate_local_lean_before.json").read_text())
    cutoff = datetime.fromisoformat(stage4_forecast["metadata"]["information_cutoff_utc"].replace("Z", "+00:00")).replace(tzinfo=None)
    stage5_by_id = {race["race_id"]: race for race in stage5_forecast["races"]}
    rows = []
    for race in stage4_forecast["races"]:
        if race["office"] != "senate":
            continue
        values = []
        weights = []
        latest = None
        for question in questions:
            if question.race_key != race["race_id"] or question.end_date > cutoff:
                continue
            age = (cutoff-question.end_date).days
            if age > 90:
                continue
            coordinate, _ = stage4.question_group_coords(question)
            if coordinate is None:
                continue
            weight = 2.0**(-age/30.0)*math.sqrt(max(question.sample_size, 100)/600)
            values.append(coordinate)
            weights.append(weight)
            latest = max(latest, question.end_date) if latest else question.end_date
        poll_margin = math.tanh(sum(v*w for v, w in zip(values, weights))/sum(weights)/2) if values else None
        old = before["senate_races"][race["race_id"]]
        final = stage5_by_id[race["race_id"]]
        rows.append({"race_id": race["race_id"], "state": race["state"],
                     "prior_stage3_margin": margin(race["candidates"], "stage3_share"),
                     "previous_forecast_margin": margin(old["candidates"], "first_stage_share"),
                     "new_forecast_margin": margin(race["candidates"], "share"),
                     "recent_raw_poll_margin": poll_margin,
                     "recent_poll_count": len(values),
                     "latest_poll_date": latest.isoformat() if latest else None,
                     "fitted_local_lean": local["current_predictions"].get(race["race_id"], {}).get("predicted_lean"),
                     "D_win_probability_before": sum(c["eventual_win_probability"] for c in old["candidates"] if c["party_group"] == "D"),
                     "D_win_probability_after": sum(c["eventual_win_probability"] for c in final["candidates"] if c["party_group"] == "D")})
    summary = {"metadata": stage5_forecast["metadata"], "races": rows,
               "house_D_control_before": before["house_D_control"],
               "house_D_control_after": stage5_forecast["joint_summaries"]["house"]["control"]["D_control_probability"],
               "senate_D_control_if_O_caucus_D_before": before["senate_D_control_if_O_D"],
               "senate_D_control_if_O_caucus_D_after": stage5_forecast["joint_summaries"]["senate"]["full_chamber"]["caucus_scenarios"]["all_other_winners_caucus_D"]["D_control_probability"]}
    path = ROOT / "artifacts" / "senate_race_audit.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"metadata", "races"}}, indent=2))
    print("largest forecast-versus-recent-poll gaps:")
    for row in sorted((r for r in rows if r["recent_raw_poll_margin"] is not None and r["new_forecast_margin"] is not None),
                      key=lambda r: abs(r["new_forecast_margin"]-r["recent_raw_poll_margin"]), reverse=True)[:12]:
        print(row["state"], row["recent_poll_count"], round(100*row["recent_raw_poll_margin"], 1),
              round(100*row["new_forecast_margin"], 1), round(row["D_win_probability_after"], 3))


if __name__ == "__main__":
    main()
