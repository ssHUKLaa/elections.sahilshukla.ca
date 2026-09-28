"""Validate Stage 5 rule resolution, chamber accounting, and reproducibility."""

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


def pmf_probability(pmf: dict[str, float], predicate) -> float:
    total = 0.0
    for key, probability in pmf.items():
        d, r, o = map(int, key.split("-"))
        if predicate(d, r, o):
            total += probability
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/nowcast"))
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--stage1-database", type=Path, default=Path("data/processed/stage1.sqlite"))
    parser.add_argument("--check-reproducibility", action="store_true")
    parser.add_argument("--ratings", type=Path, default=Path("data/reference/pollster_ratings/ratings.csv"))
    parser.add_argument("--silver-ratings", type=Path, default=Path("data/reference/pollster_ratings/silver_2026.csv"))
    args = parser.parse_args()
    parameter_path = args.artifact_dir / "model_parameters.json"
    forecast_path = args.artifact_dir / "forecast_2026.json"
    impact_path = args.artifact_dir / "fundamentals_impact_2026.json"
    extremes_path = args.artifact_dir / "senate_extremes_2026.json"
    errors: list[str] = []
    require(parameter_path.is_file(), f"missing {parameter_path}", errors)
    require(forecast_path.is_file(), f"missing {forecast_path}", errors)
    require(impact_path.is_file(), f"missing {impact_path}", errors)
    require(extremes_path.is_file(), f"missing {extremes_path}", errors)
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, indent=2))
        return 1

    parameters = json.loads(parameter_path.read_text(encoding="utf-8"))
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    impact = json.loads(impact_path.read_text(encoding="utf-8"))
    extremes = json.loads(extremes_path.read_text(encoding="utf-8"))
    metadata = forecast["metadata"]
    require(extremes.get("information_cutoff_utc") == metadata["information_cutoff_utc"],
            "Senate extremes cutoff mismatch", errors)
    require(extremes.get("simulation_draws") == metadata["simulation_draws"],
            "Senate extremes draw count mismatch", errors)
    require(extremes.get("random_seed") == metadata["random_seed"],
            "Senate extremes seed mismatch", errors)
    senate_races = {race["state"]: race for race in forecast["races"] if race["office"] == "senate"}
    joint_seat_counts = [34 + int(d) + int(o)
                         for key in forecast["joint_summaries"]["senate"]["joint_D_R_O_distribution"]
                         for d, _, o in [key.split("-")]]
    for key, expected_seats in (("best_democratic", max(joint_seat_counts)),
                                ("best_republican", min(joint_seat_counts))):
        scenario = extremes.get(key, {})
        winners = scenario.get("winners", {})
        require(set(winners) == set(senate_races), f"{key} Senate state coverage mismatch", errors)
        require(0 <= scenario.get("draw_index", -1) < metadata["simulation_draws"],
                f"{key} draw index out of range", errors)
        d_seats = 34
        r_seats = 31
        for state, winner in winners.items():
            race = senate_races.get(state)
            if race is None:
                continue
            require(any(candidate["candidate_id"] == winner.get("candidate_id") and
                        candidate["party_group"] == winner.get("party_group")
                        for candidate in race["candidates"]),
                    f"{key} winner mismatch in {state}", errors)
            if winner.get("party_group") in ("D", "O"):
                d_seats += 1
            else:
                r_seats += 1
        require(scenario.get("D_and_independent_seats") == d_seats == expected_seats,
                f"{key} Democratic caucus seat count mismatch", errors)
        require(scenario.get("R_seats") == r_seats == 100 - expected_seats,
                f"{key} Republican caucus seat count mismatch", errors)
    require(metadata.get("stage") == 5, "wrong stage metadata", errors)
    require(metadata.get("simulation_draws", 0) >= 62500, "too few draws for <0.2-point worst-case Monte Carlo SE", errors)
    status = forecast.get("publication_status")
    require(status in ("internal_provisional_nowcast_not_for_publication",
                       "public_nowcast_approved_with_limitations"),
            "unrecognized publication status", errors)
    if status == "public_nowcast_approved_with_limitations":
        gate_path = Path("artifacts/calibration/stage6_public_gate.json")
        require(gate_path.is_file(), "public forecast lacks Stage 6 gate", errors)
        if gate_path.is_file():
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
            require(gate.get("status") == "passed" and
                    gate.get("owner_model_decision") == "accepted_with_documented_governor_limitations" and
                    gate.get("live_model_version") == metadata.get("model_version"),
                    "public forecast lacks approval for this model version", errors)
            approved_code = gate.get("approved_model_code_sha256", {})
            require(len(approved_code) == 4, "public gate lacks approved code hashes", errors)
            for key, approved in approved_code.items():
                require(metadata.get(key) == approved,
                        f"public forecast differs from approved {key}", errors)
    require("if voting occurred at information cutoff" in metadata.get("estimand", ""), "nowcast estimand missing", errors)
    require(metadata.get("pollster_ratings_sha256") == digest(args.ratings), "538 ratings snapshot hash mismatch", errors)
    require(metadata.get("silver_ratings_sha256") == digest(args.silver_ratings), "Silver ratings snapshot hash mismatch", errors)
    require(metadata.get("model_code_sha256") == digest(Path("modeling/stage5_outcome_model.py")), "outcome model code hash mismatch", errors)
    require(metadata.get("stage3_model_code_sha256") == digest(Path("modeling/stage3_results_baseline.py")), "structural model code hash mismatch", errors)
    require(metadata.get("house_population_crosswalk_sha256") == digest(Path("data/reference/stage6_house_population_crosswalk.json")), "population crosswalk hash mismatch", errors)
    require(metadata.get("house_official_resolutions_sha256") == digest(Path("data/reference/stage6_house_2024_official_resolutions.json")), "official House resolutions hash mismatch", errors)
    require(metadata.get("stage4_model_code_sha256") == digest(Path("modeling/stage4_poll_model.py")), "first-stage model code hash mismatch", errors)
    require(metadata.get("national_model_code_sha256") == digest(Path("modeling/national_environment.py")), "national model code hash mismatch", errors)
    require(metadata.get("generic_error_calibration_sha256") == digest(Path("data/reference/stage6_generic_error_calibration.json")),
            "generic-ballot error calibration hash mismatch", errors)
    require(metadata.get("national_source_manifest_sha256") == digest(Path("data/reference/national_environment/source_manifest.json")), "national source manifest hash mismatch", errors)
    require(metadata.get("pollster_quality_code_sha256") == digest(Path("modeling/pollster_quality.py")), "pollster quality code hash mismatch", errors)
    require(metadata.get("fundamentals_features_code_sha256") == digest(Path("modeling/fundamentals_features_2026.py")), "fundamentals feature code hash mismatch", errors)
    require(metadata.get("governor_local_lean_code_sha256") == digest(Path("modeling/governor_local_lean.py")),
            "governor local-lean code hash mismatch", errors)
    require(metadata.get("senate_minor_share_code_sha256") == digest(Path("modeling/senate_minor_share.py")),
            "Senate minor-share model code hash mismatch", errors)
    require(metadata.get("senate_minor_share_fit_sha256") == digest(Path("data/reference/senate_minor_share_fit_2026.json")),
            "Senate minor-share fit hash mismatch", errors)
    require(impact.get("metadata") == metadata, "impact report metadata does not match forecast", errors)
    require([step.get("step") for step in impact.get("summary", [])] ==
            ["baseline", "district_map", "governor_approval", "open_seat_candidate_experience"],
            "fundamentals ablation stages missing or unordered", errors)
    require(len(impact.get("race_impacts", [])) == 506, "fundamentals race impacts incomplete", errors)
    require(all(abs(row.get("feature_log_odds_shifts", {}).get("governor_approval", 0.0)) < 1e-12
                for row in impact.get("race_impacts", [])),
            "unvalidated governor approval effect entered a live race", errors)
    governor_fit = parameters.get("additional_fundamentals", {}).get("fit", {}).get("governor", {})
    require(parameters.get("additional_fundamentals", {}).get("fit", {}).get("governor", {}).get("feature_names") ==
            ["open_seat_prior_winner_signed", "other_prior_elected_winner_signed"],
            "governor fit still contains unvalidated approval coefficient", errors)
    require(governor_fit.get("active_in_2026_nowcast") is False,
            "legacy governor open-seat fit must be marked inactive", errors)
    local_lean = parameters.get("national_signal_update", {}).get("governor_local_lean", {})
    impact_local_lean = impact.get("governor_local_lean", {})
    require(local_lean.get("enabled") is True, "fitted governor local-lean model is not enabled", errors)
    require(local_lean.get("selected_specification") == "previous_and_presidential",
            "governor local-lean specification differs from the expanding-cycle selection", errors)
    require(len(local_lean.get("current_race_impacts", [])) == 36,
            "governor local-lean diagnostics do not cover all 36 races", errors)
    require(impact_local_lean == local_lean,
            "fundamentals impact governor local-lean diagnostics differ from model parameters", errors)
    require(all(abs(row.get("feature_log_odds_shifts", {}).get("open_seat_candidate_experience", 0.0)) < 1e-12
                for row in impact.get("race_impacts", []) if row.get("office") == "governor"),
            "legacy governor open-seat adjustment remains active", errors)
    sources = impact.get("input_metadata", {})
    require(sources.get("map", {}).get("old_sha256") == digest(Path("data/reference/house_presidential_2026/downballot_2024_old_maps.csv")),
            "old-map source hash mismatch", errors)
    require(sources.get("map", {}).get("new_sha256") == digest(Path("data/reference/house_presidential_2026/downballot_2024_current_maps.csv")),
            "2026-map source hash mismatch", errors)
    require(sources.get("approval_sha256") == digest(Path("data/reference/governor_approval/morning_consult_2025q4_net.csv")),
            "current governor approval source hash mismatch", errors)
    require(metadata.get("data_sha256") == digest(args.database), "Stage 2 database hash mismatch", errors)
    require(metadata.get("stage1_data_sha256") == digest(args.stage1_database), "Stage 1 database hash mismatch", errors)
    quality = parameters.get("pollster_quality", {})
    national = parameters.get("national_signal_update", {})
    approval_prior = national.get("approval_conditioned_prior") or {}
    historical_fundamentals = national.get("historical_fundamentals") or {}
    require(isinstance(approval_prior.get("implied_D_two_party_margin"), (int, float)),
            "approval-conditioned national prior missing", errors)
    require(isinstance(historical_fundamentals.get("approve"), (int, float))
            and isinstance(historical_fundamentals.get("disapprove"), (int, float)),
            "current approval average missing from national prior", errors)
    require("structural_prior_plus_generic" in national.get("sensitivity", {}),
            "structural-prior sensitivity missing", errors)
    require("approval_prior_plus_generic_legacy" in national.get("sensitivity", {}),
            "approval-plus-generic comparison missing", errors)
    require("generic_only" in national.get("sensitivity", {}),
            "generic-only comparison missing", errors)
    require(national.get("national_center_source") == "generic_ballot_with_small_approval_blend",
            "live national center has an unexpected signal rule", errors)
    weight = national.get("approval_blend_weight")
    require(weight == 0.05, "approval blend weight differs from stated 5% policy", errors)
    if isinstance(weight, (int, float)):
        generic_signal = national.get("generic_ballot") or {}
        approval_signal = national.get("approval_conditioned_prior") or {}
        posterior = national.get("posterior") or {}
        expected_mean = ((1-weight)*generic_signal.get("raw_logratio_mean", 0)
                         + weight*approval_signal.get("national_D_R_logratio_mean", 0))
        expected_sd = ((1-weight)*generic_signal.get("observation_sd_logratio", 0)
                       + weight*approval_signal.get("national_D_R_logratio_sd", 0))
        require(abs(posterior.get("national_D_R_logratio_mean", 999)-expected_mean) < 1e-10,
                "live national center differs from stated signal blend", errors)
        require(abs(posterior.get("national_D_R_logratio_sd", 999)-expected_sd) < 1e-10,
                "live national uncertainty differs from covariance-robust bound", errors)
    require((national.get("generic_ballot") or {}).get("effective_poll_count", 0) > 0,
            "no usable generic-ballot observations", errors)
    coverage = quality.get("feed_coverage", {})
    require(quality.get("live_snapshot_id") == metadata.get("input_snapshot_ids", {}).get("live_source_snapshot"),
            "pollster ratings were matched against the wrong NYT snapshot", errors)
    require(coverage.get("senate_silver", 0) > 0,
            "no Silver-rated Senate polls", errors)
    for feed in ("senate", "house", "governor", "other", "president_approval_polls"):
        require(coverage.get(f"{feed}_total", 0) == sum(
            coverage.get(f"{feed}_{kind}", 0)
            for kind in ("silver", "538_fallback", "silver_banned", "unrated")
        ), f"{feed} pollster rating categories do not reconcile", errors)
    require(forecast.get("race_count") == 506 and len(forecast.get("races", [])) == 506, "forecast must contain 506 races", errors)

    office_counts = Counter()
    rule_counts = Counter()
    senate_sullivans = {}
    max_mcse = 0.0
    for race in forecast["races"]:
        race_id = race["race_id"]
        office_counts[race["office"]] += 1
        rule_counts[race["counting_rule"]] += 1
        candidates = race["candidates"]
        require(0 <= race["poll_diagnostics"]["rated_poll_count"] <= race["poll_diagnostics"]["poll_count"],
                f"{race_id} invalid rated-poll count", errors)
        require(bool(candidates), f"{race_id} has no candidates", errors)
        means = [candidate["first_stage_share"]["mean"] for candidate in candidates]
        first = [candidate["first_stage_leader_probability"] for candidate in candidates]
        eventual = [candidate["eventual_win_probability"] for candidate in candidates]
        require(abs(sum(means)-1) <= 1e-9, f"{race_id} first-stage means do not sum to one", errors)
        require(abs(sum(first)-1) <= 1e-9, f"{race_id} first-stage leader probabilities do not sum to one", errors)
        require(abs(sum(eventual)-1) <= 1e-9, f"{race_id} eventual probabilities do not sum to one", errors)
        require(all(0 <= value <= 1 and math.isfinite(value) for value in eventual), f"{race_id} has invalid eventual probability", errors)
        max_mcse = max(max_mcse, *(candidate["monte_carlo_standard_error"] for candidate in candidates))
        for candidate in candidates:
            require("▌" not in candidate["name"],
                    f"{race_id} candidate name contains a source delimiter", errors)
            if race["counting_rule"] == "plurality" or len(candidates) == 1:
                require(candidate["eventual_win_probability"] == candidate["first_stage_leader_probability"], f"{race_id} plurality winner differs from leader", errors)
            if race_id == "S-2026-AK-II-regular" and "SULLIVAN" in candidate["ballot_entry_id"]:
                senate_sullivans[candidate["candidate_id"]] = candidate["name"]
    require(dict(office_counts) == {"governor": 36, "house": 435, "senate": 35}, f"office counts wrong: {dict(office_counts)}", errors)
    require(max_mcse < 0.002, f"maximum candidate Monte Carlo SE {max_mcse:.6f} is not below 0.002", errors)
    require(senate_sullivans == {
        "PERSON-AK-DAN-J-SULLIVAN": "Daniel J. Sullivan Jr.",
        "PERSON-AK-DAN-S-SULLIVAN": "Dan S. Sullivan",
    }, f"Alaska Sullivan identities collapsed or mislabeled: {senate_sullivans}", errors)

    for office, expected in office_counts.items():
        summary = forecast["joint_summaries"][office]
        require(summary["seat_universe"] == expected, f"{office} seat universe mismatch", errors)
        require(abs(sum(summary["joint_D_R_O_distribution"].values())-1) <= 1e-9, f"{office} joint PMF does not sum to one", errors)
        for key in summary["joint_D_R_O_distribution"]:
            require(sum(map(int, key.split("-"))) == expected, f"{office} draw {key} loses a seat", errors)

    house = forecast["joint_summaries"]["house"]
    house_pmf = house["joint_D_R_O_distribution"]
    reconstructed = {
        "D_control_probability": pmf_probability(house_pmf, lambda d, r, o: d >= 218),
        "R_control_probability": pmf_probability(house_pmf, lambda d, r, o: r >= 218),
        "neither_probability": pmf_probability(house_pmf, lambda d, r, o: d < 218 and r < 218),
    }
    for key, value in reconstructed.items():
        require(abs(value-house["control"][key]) <= 1e-12, f"House {key} does not match raw joint PMF", errors)

    senate = forecast["joint_summaries"]["senate"]
    senate_pmf = senate["joint_D_R_O_distribution"]
    scenarios = senate["full_chamber"]["caucus_scenarios"]
    expected_scenarios = {
        "other_winners_unaligned": (
            pmf_probability(senate_pmf, lambda d, r, o: 34+d >= 51),
            pmf_probability(senate_pmf, lambda d, r, o: 31+r >= 50),
        ),
        "all_other_winners_caucus_D": (
            pmf_probability(senate_pmf, lambda d, r, o: 34+d+o >= 51),
            pmf_probability(senate_pmf, lambda d, r, o: 31+r >= 50),
        ),
        "all_other_winners_caucus_R": (
            pmf_probability(senate_pmf, lambda d, r, o: 34+d >= 51),
            pmf_probability(senate_pmf, lambda d, r, o: 31+r+o >= 50),
        ),
    }
    for scenario, (d_control, r_control) in expected_scenarios.items():
        require(abs(scenarios[scenario]["D_control_probability"]-d_control) <= 1e-12, f"{scenario} D control mismatch", errors)
        require(abs(scenarios[scenario]["R_control_probability"]-r_control) <= 1e-12, f"{scenario} R control mismatch", errors)
    require(senate["full_chamber"]["overall_control_probability"] is None, "unweighted caucus scenarios must not produce overall Senate control", errors)
    cross_chamber = forecast["joint_summaries"].get("cross_chamber", {})
    correlation = cross_chamber.get("house_D_senate_D_elected_seat_correlation")
    require(correlation is not None and math.isfinite(correlation) and -1 <= correlation <= 1,
            "cross-chamber seat correlation invalid", errors)
    combined = cross_chamber.get("house_D_control_senate_D_control_by_caucus_scenario", {})
    for scenario, senate_control in scenarios.items():
        probability = combined.get(scenario)
        if probability is not None:
            lower = max(0.0, house["control"]["D_control_probability"] + senate_control["D_control_probability"] - 1)
            upper = min(house["control"]["D_control_probability"], senate_control["D_control_probability"])
            require(lower - 1e-12 <= probability <= upper + 1e-12,
                    f"{scenario} cross-chamber control violates marginal bounds", errors)
        else:
            require(False, f"{scenario} cross-chamber control missing", errors)

    runoff = parameters["runoff_model"]
    require(runoff["pairs"] >= 30, "too few runoff training pairs", errors)
    require(runoff["leave_one_pair_out_brier"] <= runoff["uninformed_brier"]+1e-12, "runoff model is worse than an uninformed winner forecast", errors)
    rcv = parameters["ranked_choice_model"]
    require(rcv["evidence"]["elimination_events"] >= 5, "ranked-choice transfer evidence missing", errors)
    for source, profile in rcv["transfer_profiles"].items():
        require(abs(sum(profile[key] for key in ("D", "R", "O", "exhausted"))-1) <= 1e-9, f"RCV profile {source} does not sum to one", errors)

    reproducible = None
    if args.check_reproducibility and not errors:
        replay = args.artifact_dir / ".validation" / "replay"
        replay.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, "modeling/stage5_outcome_model.py", "--output-dir", str(replay),
            "--draws", str(metadata["simulation_draws"]), "--seed", str(metadata["random_seed"]),
            "--database", str(args.database), "--stage1-database", str(args.stage1_database),
        ]
        command += ["--ratings", str(args.ratings), "--silver-ratings", str(args.silver_ratings),
                    "--current-poll-half-life-days", str(parameters["current_poll_half_life_days"])]
        if metadata.get("reconstruction", {}).get("kind") == "retrospective_poll_cutoff":
            command += ["--information-cutoff-utc", metadata["information_cutoff_utc"]]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        require(completed.returncode == 0, f"replay failed: {completed.stderr}", errors)
        if completed.returncode == 0:
            replay_forecast = json.loads((replay / "forecast_2026.json").read_text(encoding="utf-8"))
            comparable_forecast = dict(forecast)
            comparable_forecast["publication_status"] = replay_forecast["publication_status"]
            reproducible = (digest(parameter_path) == digest(replay/"model_parameters.json") and
                            comparable_forecast == replay_forecast and
                            digest(extremes_path) == digest(replay/"senate_extremes_2026.json"))
            require(reproducible, "same inputs and seed did not reproduce byte-identical Stage 5 artifacts", errors)

    report = {
        "status": "passed" if not errors else "failed", "race_counts": dict(office_counts),
        "rule_counts": dict(rule_counts), "max_candidate_mcse": max_mcse,
        "runoff_holdout": {"pairs": runoff["pairs"], "accuracy": runoff["leave_one_pair_out_winner_accuracy"], "brier": runoff["leave_one_pair_out_brier"]},
        "rcv_elimination_events": rcv["evidence"]["elimination_events"],
        "reproducible": reproducible,
        "artifact_sha256": {"parameters": digest(parameter_path), "forecast": digest(forecast_path)},
        "errors": errors,
    }
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
