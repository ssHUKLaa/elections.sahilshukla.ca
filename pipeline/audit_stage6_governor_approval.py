"""Record the paired governor approval ablation and the live removal check."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "artifacts/calibration"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log_score(cell: dict) -> float:
    rows = [race for race in cell["races"] if race["office"] == "governor"]
    return sum(-math.log(max(race["winner_probability"], 1e-12)) for race in rows) / len(rows)


def main() -> None:
    on_path = CAL / "stage6_governor_2020_approval_on.json"
    off_path = CAL / "stage6_governor_2020_approval_off.json"
    old_impact_path = CAL / "stage6_governor_approval_live_impact_before_removal.json"
    live_path = ROOT / "artifacts/nowcast/fundamentals_impact_2026.json"
    on = read(on_path)["cells"][0]
    off = read(off_path)["cells"][0]
    old_impact = read(old_impact_path)
    live = read(live_path)
    assert (on["cycle"], on["lead_days"], on["draws"]) == (2020, 7, 2000)
    assert (off["cycle"], off["lead_days"], off["draws"]) == (2020, 7, 2000)
    assert on["local_feature_coverage"]["governor_approval"] == 5
    assert all(abs(row["feature_log_odds_shifts"]["governor_approval"]) < 1e-12
               for row in live["race_impacts"])
    assert live["training"]["governor"]["feature_names"] == [
        "open_seat_prior_winner_signed", "other_prior_elected_winner_signed"]
    on_score, off_score = log_score(on), log_score(off)
    rows = old_impact["race_impacts"]
    report = {
        "status": "reviewed_feature_disabled",
        "decision": "Exclude sitting-governor approval from the release model and historical replay until dated, usable 2022/2024 approval data can support full as-of testing.",
        "evidence_hashes": {"approval_on_2020": digest(on_path),
                            "approval_off_2020": digest(off_path),
                            "prior_live_impact": digest(old_impact_path),
                            "current_live_impact": digest(live_path)},
        "paired_2020_seven_day_replay": {
            "governor_races": on["office_seats"]["governor"]["race_count"],
            "approval_covered_races": on["local_feature_coverage"]["governor_approval"],
            "winner_log_score_with_approval": on_score,
            "winner_log_score_without_approval": off_score,
            "with_minus_without": on_score - off_score,
            "note": "Small, inspected diagnostic; the approval series is retrospectively smoothed."},
        "prior_2026_live_impact": {
            "affected_governor_races": len(rows),
            "largest_absolute_first_stage_D_probability_change": max(
                abs(row["first_stage_D_probability_change"]) for row in rows),
            "note": "Prior live paired impact, before removal. First-stage leaders do not incorporate final runoff/RCV counting."},
        "current_release_model": {
            "model_version": live["metadata"]["model_version"],
            "governor_approval_coefficient_present": False,
            "nonzero_live_approval_shifts": 0},
        "source_limitations": [
            "Singer State Executive Approval Database v1 ends in 2020 and its smoothed values lack verified as-of release dates.",
            "Morning Consult published 2022 approval workbooks, but the complete later historical trended dataset is listed as Pro+ access; the 2024 public report covers the three incumbent races at a published quarter only.",
        ],
        "sources": [
            "https://pro.morningconsult.com/instant-intel/democratic-governors-are-resisting-bidens-decline",
            "https://pro.morningconsult.com/analyst-reports/us-governor-approval-outlook-october-2024",
        ],
    }
    out = CAL / "stage6_governor_approval_audit.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "with": on_score,
                      "without": off_score, "nonzero_live_shifts": 0}, indent=2))


if __name__ == "__main__":
    main()
