"""Validate Stage 4 forecast, backtest, provenance, and reproducibility."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/stage4"))
    parser.add_argument("--stage3-artifact-dir", type=Path, default=Path("artifacts/stage3"))
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
    stage3_path = args.stage3_artifact_dir / "forecast_2026.json"
    stage3 = json.loads(stage3_path.read_text(encoding="utf-8")) if stage3_path.is_file() else None
    meta = forecast["metadata"]
    require(meta.get("stage") == 4, "wrong stage metadata", errors)
    require(bool(meta.get("information_cutoff_utc")), "information cutoff missing", errors)
    require(meta.get("current_source_eligible_questions") == 666, "source-eligible question count changed", errors)
    require(meta.get("current_selected_questions_after_poll_race_deduplication") == 603, "deduplicated question count changed", errors)
    require(forecast.get("publication_status") == "internal_stage4_not_for_publication", "artifact must remain internal", errors)
    require(forecast.get("race_count") == 506 and len(forecast.get("races", [])) == 506, "forecast must contain 506 races", errors)
    backtest = parameters.get("backtest", {})
    require(backtest.get("gate", {}).get("passed") is True, "Stage 4 holdout gate failed", errors)
    national = parameters.get("national_signal_update", {})
    require(bool(national), "national signal update missing", errors)
    senate_bias = parameters.get("senate_poll_bias_calibration", {})
    senate_holdout = senate_bias.get("held_out_2024", {})
    require(senate_holdout.get("gate_passed") is True,
            "Senate poll correction lacks a passing 2024 holdout", errors)
    require(senate_bias.get("major_party_interval_gate_passed") is True,
            "Senate D/R 95% intervals fail the 2020/2024 holdout gate", errors)
    require(senate_bias.get("inventory", {}).get("eligible_races", 0) >= 100,
            "multi-cycle Senate poll archive has insufficient matched races", errors)
    require(parameters.get("poll_error_model", {}).get("senate_D_R_correction") is not None,
            "Senate D/R correction is missing from model parameters", errors)
    require("generic_ballot" in national and "historical_fundamentals" in national, "generic or fitted fundamentals signal missing", errors)
    posterior_margin = national.get("posterior", {}).get("implied_D_two_party_margin")
    require(posterior_margin is not None and -1.0 < posterior_margin < 1.0, "national signal posterior is invalid", errors)
    local = national.get("senate_local_lean", {})
    require(local.get("training_races", 0) >= 300, "Senate local-lean training evidence missing", errors)
    previous_errors = [row["later_rmse"] for row in local.get("grid", [])
                       if row.get("specification") == "previous" and row.get("later_rmse") is not None]
    require(bool(previous_errors) and local.get("selected", {}).get("later_rmse", math.inf) < min(previous_errors),
            "Senate local lean does not improve later cycles over the previous-seat-only model", errors)
    inflation = parameters.get("posterior_covariance_inflation", {})
    require(inflation.get("selected", 0) >= 1.0, "posterior covariance inflation calibration missing", errors)
    result = backtest.get("overall", {}).get("results_only", {})
    combined = backtest.get("overall", {}).get("combined", {})
    require(
        combined.get("log_score", math.inf) < result.get("log_score", -math.inf)
        or combined.get("brier", math.inf) < result.get("brier", -math.inf),
        "combined model improves neither proper score", errors,
    )

    stage3_by_race = {race["race_id"]: race for race in stage3["races"]} if stage3 else {}
    counts = Counter()
    selected_question_ids: set[str] = set()
    office_counts = Counter()
    for race in forecast["races"]:
        race_id = race["race_id"]
        office_counts[race["office"]] += 1
        counts[(race["office"], race["update_status"])] += 1
        candidates = race["candidates"]
        require(bool(candidates), f"{race_id} has no candidates", errors)
        means = [candidate["share"]["mean"] for candidate in candidates]
        probabilities = [candidate["first_stage_leader_probability"] for candidate in candidates]
        require(all(math.isfinite(value) and 0 <= value <= 1 for value in means), f"{race_id} has invalid shares", errors)
        require(abs(sum(means)-1) <= 1e-9, f"{race_id} shares do not sum to one", errors)
        require(abs(sum(probabilities)-1) <= 1e-9, f"{race_id} probabilities do not sum to one", errors)
        diagnostics = race["poll_diagnostics"]
        selected_question_ids.update(diagnostics["question_keys"])
        if race["update_status"] == "race_polls_and_national_signals":
            require(diagnostics["poll_count"] > 0 and diagnostics["contrast_count"] > 0, f"{race_id} has empty poll update", errors)
        else:
            require(diagnostics["poll_count"] == 0 and diagnostics["contrast_count"] == 0, f"{race_id} prior-only status conflicts with polls", errors)
        if stage3:
            prior = stage3_by_race[race_id]
            prior_by_id = {candidate["ballot_entry_id"]: candidate for candidate in prior["candidates"]}
            for candidate in candidates:
                old = prior_by_id[candidate["ballot_entry_id"]]
                require(candidate["stage3_share"] == old["share"], f"{race_id} stored Stage 3 share differs from accepted artifact", errors)
                require(candidate["stage3_first_stage_leader_probability"] == old["first_stage_leader_probability"], f"{race_id} stored Stage 3 probability differs from accepted artifact", errors)
        nonplurality = race["counting_rule"] != "plurality" and len(candidates) > 1
        if nonplurality:
            require(all(candidate["eventual_win_probability"] is None for candidate in candidates), f"{race_id} assigns unsupported eventual winners", errors)

    expected_counts = {
        ("house", "race_polls_and_national_signals"): 78, ("house", "national_signals_only"): 357,
        ("senate", "race_polls_and_national_signals"): 24, ("senate", "national_signals_only"): 11,
        ("governor", "race_polls_and_national_signals"): 27, ("governor", "national_signals_only"): 9,
    }
    require(dict(counts) == expected_counts, f"poll coverage changed: {dict(counts)}", errors)
    require(len(selected_question_ids) == 603, f"expected 603 unique selected question keys, got {len(selected_question_ids)}", errors)
    require(dict(office_counts) == {"house": 435, "senate": 35, "governor": 36}, f"office counts wrong: {dict(office_counts)}", errors)
    for office, expected in office_counts.items():
        summary = forecast["joint_summaries"][office]
        require(summary["seat_universe"] == expected, f"{office} seat accounting mismatch", errors)
        require(abs(sum(summary["joint_D_R_O_distribution"].values())-1) <= 1e-9, f"{office} joint PMF does not sum to one", errors)

    reproducible = None
    if args.check_reproducibility and not errors:
        replay = args.artifact_dir / ".validation" / "replay"
        replay.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, "modeling/stage4_poll_model.py", "--output-dir", str(replay),
            "--draws", str(meta["simulation_draws"]), "--seed", str(meta["random_seed"]),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        require(completed.returncode == 0, f"replay failed: {completed.stderr}", errors)
        if completed.returncode == 0:
            reproducible = digest(parameter_path) == digest(replay/"model_parameters.json") and digest(forecast_path) == digest(replay/"forecast_2026.json")
            require(reproducible, "same inputs and seed did not reproduce byte-identical artifacts", errors)

    report = {
        "status": "passed" if not errors else "failed", "race_counts": dict(office_counts),
        "poll_coverage": {f"{office}:{status}": value for (office, status), value in sorted(counts.items())},
        "selected_questions": len(selected_question_ids), "backtest_gate": backtest.get("gate"),
        "reproducible": reproducible,
        "artifact_sha256": {"parameters": digest(parameter_path), "forecast": digest(forecast_path)},
        "errors": errors,
    }
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
