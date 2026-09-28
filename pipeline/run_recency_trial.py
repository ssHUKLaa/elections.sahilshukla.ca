"""Rebuild Stages 4 and 5 with a chosen live-poll half-life and report Senate results.

This runner is portable across Windows and Linux because every child command
uses the same Python interpreter that launched this file.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATES = ("AK", "IA", "ME", "MI", "OH", "TX", "GA", "NC", "NH")


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run(*arguments: str) -> None:
    command = [sys.executable, *arguments]
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def party_probability(race: dict, party: str) -> float:
    return sum(
        float(candidate.get("eventual_win_probability") or 0.0)
        for candidate in race["candidates"]
        if candidate["party_group"] == party
    )


def party_mean_share(race: dict, party: str) -> float:
    return sum(
        float(candidate["first_stage_share"]["mean"])
        for candidate in race["candidates"]
        if candidate["party_group"] == party
    )


def control_probability(forecast: dict | None) -> float | None:
    if forecast is None:
        return None
    return float(
        forecast["joint_summaries"]["senate"]["full_chamber"]["caucus_scenarios"]
        ["all_other_winners_caucus_D"]["D_control_probability"]
    )


def report(before: dict | None, after: dict, half_life: float) -> str:
    before_control = control_probability(before)
    after_control = control_probability(after)
    lines = ["SENATE RECENCY TRIAL", f"Live race-poll half-life: {half_life:g} days"]
    if before_control is not None:
        lines.extend((
            f"Democratic control before (all O caucus D): {before_control:.1%}",
            f"Democratic control after  (all O caucus D): {after_control:.1%}",
            f"Change:                    {after_control-before_control:+.1%}",
        ))
    else:
        lines.append(f"Democratic control (all O caucus D): {after_control:.1%}")

    races = {
        race["state"]: race
        for race in after["races"]
        if race["office"] == "senate"
    }
    lines.extend(("", "State   D win   Mean D-R margin"))
    for state in STATES:
        race = races[state]
        probability = party_probability(race, "D")
        margin = party_mean_share(race, "D") - party_mean_share(race, "R")
        lines.append(f"{state:>5}  {probability:>6.1%}  {margin:>+15.1%}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--half-life-days", type=float, default=30.0)
    parser.add_argument("--draws", type=int, default=75_000)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()
    if args.half_life_days <= 0:
        parser.error("--half-life-days must be positive")
    if args.draws < 1_000:
        parser.error("--draws must be at least 1000")

    stage5_path = ROOT / "artifacts" / "stage5" / "forecast_2026.json"
    prior_parameters = load(ROOT / "artifacts" / "stage4" / "model_parameters.json")
    prior_half_life = (
        prior_parameters.get("current_poll_recency", {}).get("half_life_days")
        if prior_parameters else None
    )
    before = load(stage5_path) if prior_half_life != args.half_life_days else None
    common = ["--draws", str(args.draws), "--seed", str(args.seed)]
    run(
        "modeling/stage4_poll_model.py",
        *common,
        "--current-poll-half-life-days",
        str(args.half_life_days),
    )
    run("pipeline/validate_stage4.py")
    run("modeling/stage5_outcome_model.py", *common)
    run("pipeline/validate_stage5.py")
    after = load(stage5_path)
    if after is None:
        raise RuntimeError("Stage 5 did not produce its forecast artifact")
    output = report(before, after, args.half_life_days)
    print("\n" + output)
    report_path = ROOT / "artifacts" / "recency_trial_report.txt"
    report_path.write_text(output, encoding="utf-8")
    print(f"Saved report: {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
