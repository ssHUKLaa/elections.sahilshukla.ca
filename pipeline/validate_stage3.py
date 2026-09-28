"""Validate Stage 3 artifacts and optionally reproduce them from scratch."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/stage3"))
    parser.add_argument("--check-reproducibility", action="store_true")
    args = parser.parse_args()
    parameter_path = args.artifact_dir / "model_parameters.json"
    forecast_path = args.artifact_dir / "forecast_2026.json"
    errors: list[str] = []
    require(parameter_path.is_file(), f"missing {parameter_path}", errors)
    require(forecast_path.is_file(), f"missing {forecast_path}", errors)
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, indent=2))
        return 1

    parameters = json.loads(parameter_path.read_text(encoding="utf-8"))
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    meta = forecast["metadata"]
    require(meta.get("uses_polling") is False, "Stage 3 must not use polling", errors)
    require(bool(meta.get("information_cutoff_utc")), "information cutoff is missing", errors)
    require(bool(meta.get("input_snapshot_ids")), "input snapshot IDs are missing", errors)
    require(forecast.get("publication_status") == "internal_stage3_baseline_not_for_publication", "artifact must remain internal", errors)
    require(forecast.get("race_count") == 506, "forecast must contain 506 races", errors)
    require(len(forecast.get("races", [])) == 506, "race list count mismatch", errors)
    require(parameters.get("backtest", {}).get("gate", {}).get("passed") is True, "historical holdout gate failed", errors)
    senate_transition = parameters.get("parameters", {}).get("party_group_transition", {}).get("senate", {})
    senate_coefficient = senate_transition.get("coefficient", [])
    require(
        len(senate_coefficient) >= 2 and abs(senate_coefficient[1][0]-1.0) <= 1e-12,
        "Senate D/R persistence is not the accepted unit-root specification", errors,
    )
    for office, transition in parameters["parameters"]["party_group_transition"].items():
        coefficient = transition.get("coefficient", [])
        require(
            len(coefficient) >= 3 and abs(coefficient[2][1]-1.0) <= 1e-12,
            f"{office} other-party persistence is not the accepted unit-root specification", errors,
        )

    race_ids: set[str] = set()
    office_counts: dict[str, int] = {"house": 0, "senate": 0, "governor": 0}
    for race in forecast.get("races", []):
        race_id = race["race_id"]
        require(race_id not in race_ids, f"duplicate race {race_id}", errors)
        race_ids.add(race_id)
        office_counts[race["office"]] += 1
        candidates = race.get("candidates", [])
        require(bool(candidates), f"{race_id} has no candidates", errors)
        means = [candidate["share"]["mean"] for candidate in candidates]
        require(all(0.0 <= value <= 1.0 and math.isfinite(value) for value in means), f"{race_id} has invalid shares", errors)
        require(abs(sum(means)-1.0) <= 1e-9, f"{race_id} mean shares do not sum to one", errors)
        leader_probability = sum(candidate["first_stage_leader_probability"] for candidate in candidates)
        require(abs(leader_probability-1.0) <= 1e-9, f"{race_id} leader probabilities do not sum to one", errors)
        nonplurality = race["counting_rule"] != "plurality" and len(candidates) > 1
        if nonplurality:
            require(all(candidate["eventual_win_probability"] is None for candidate in candidates), f"{race_id} improperly assigns final winners", errors)
        else:
            require(all(candidate["eventual_win_probability"] is not None for candidate in candidates), f"{race_id} lacks direct winner probabilities", errors)

        if race["office"] == "senate" and race["state"] in {"AL", "AR", "KY", "WV", "WY"}:
            democratic_lead = sum(
                candidate["first_stage_leader_probability"]
                for candidate in candidates if candidate["party_group"] == "D"
            )
            require(democratic_lead < 0.15, f"{race_id} safe-state prior is implausibly diffuse", errors)

    require(office_counts == {"house": 435, "senate": 35, "governor": 36}, f"office counts wrong: {office_counts}", errors)
    joint = forecast.get("joint_summaries", {})
    for office, expected in office_counts.items():
        require(joint.get(office, {}).get("seat_universe") == expected, f"{office} joint seat universe mismatch", errors)
        probabilities = joint.get(office, {}).get("joint_D_R_O_distribution", {}).values()
        require(abs(sum(probabilities)-1.0) <= 1e-9, f"{office} joint distribution does not sum to one", errors)

    reproducible = None
    if args.check_reproducibility and not errors:
        replay = args.artifact_dir / ".validation" / "replay"
        replay.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, "modeling/stage3_results_baseline.py",
            "--database", meta["data_database"], "--output-dir", str(replay),
            "--draws", str(meta["simulation_draws"]), "--seed", str(meta["random_seed"]),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        require(completed.returncode == 0, f"replay failed: {completed.stderr}", errors)
        if completed.returncode == 0:
            reproducible = (
                digest(parameter_path) == digest(replay / "model_parameters.json")
                and digest(forecast_path) == digest(replay / "forecast_2026.json")
            )
            require(reproducible, "same seed and inputs did not reproduce byte-identical artifacts", errors)

    report = {
        "status": "passed" if not errors else "failed",
        "race_counts": office_counts,
        "simulation_draws": meta.get("simulation_draws"),
        "random_seed": meta.get("random_seed"),
        "backtest_gate": parameters.get("backtest", {}).get("gate"),
        "reproducible": reproducible,
        "artifact_sha256": {"parameters": digest(parameter_path), "forecast": digest(forecast_path)},
        "errors": errors,
    }
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
