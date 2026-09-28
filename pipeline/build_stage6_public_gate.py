"""Compile an evidence-based public calibration gate from the frozen reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling.fundamentals_features_2026 import house_map_shifts

DB = ROOT / "data/processed/stage2.sqlite"
FORECAST = ROOT / "artifacts/nowcast"
JOINT = ROOT / "artifacts/calibration/stage6_joint_replay.json"
RACE = ROOT / "artifacts/calibration/stage6_repaired_race_replay.json"
CROSSWALK_TEST = ROOT / "artifacts/calibration/stage6_house_population_crosswalk_test.json"
NATIONAL = ROOT / "artifacts/calibration/stage6_national_snapshots.json"
CROSSWALK = ROOT / "data/reference/stage6_house_population_crosswalk.json"
MISSOURI = ROOT / "data/reference/stage6_missouri_map_status.json"
MISSOURI_CANDIDATES = ROOT / "data/reference/stage6_missouri_2026_certified_house_candidates.json"
HISTORICAL_MAPS = ROOT / "data/reference/stage6_historical_house_map_shifts.json"
FROZEN = ROOT / "artifacts/calibration/frozen_2026-09-27_v020"
GOVERNOR_AUDIT = ROOT / "artifacts/calibration/stage6_governor_approval_audit.json"
GOVERNOR_LEAN_AUDIT = ROOT / "artifacts/calibration/governor_local_lean_audit.json"
GOVERNOR_PAIRED = ROOT / "artifacts/calibration/governor_local_lean_paired_replay.json"
HOUSE_AUDIT = ROOT / "artifacts/calibration/stage6_house_2020_audit.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_public_gate.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(script: str, *args: str) -> dict:
    command = [sys.executable, str(ROOT / "pipeline" / script), *args]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{script} failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--forecast-dir", type=Path, default=FORECAST)
    parser.add_argument("--joint", type=Path, default=JOINT)
    parser.add_argument("--race", type=Path, default=RACE)
    parser.add_argument("--crosswalk-test", type=Path, default=CROSSWALK_TEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    stage2 = validate("validate_stage2.py", "--database", str(args.database))
    stage5 = validate("validate_stage5.py", "--database", str(args.database),
                      "--artifact-dir", str(args.forecast_dir))
    joint = json.loads(args.joint.read_text(encoding="utf-8"))
    race = json.loads(args.race.read_text(encoding="utf-8"))
    selection = json.loads(args.crosswalk_test.read_text(encoding="utf-8"))
    national = json.loads(NATIONAL.read_text(encoding="utf-8"))
    crosswalk = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    missouri = json.loads(MISSOURI.read_text(encoding="utf-8"))
    missouri_candidates = json.loads(MISSOURI_CANDIDATES.read_text(encoding="utf-8"))
    historical_maps = json.loads(HISTORICAL_MAPS.read_text(encoding="utf-8"))
    governor_audit = json.loads(GOVERNOR_AUDIT.read_text(encoding="utf-8"))
    governor_lean_audit = json.loads(GOVERNOR_LEAN_AUDIT.read_text(encoding="utf-8"))
    governor_paired = json.loads(GOVERNOR_PAIRED.read_text(encoding="utf-8"))
    house_audit = json.loads(HOUSE_AUDIT.read_text(encoding="utf-8"))
    frozen = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))
    current_map_shifts, _ = house_map_shifts()
    missouri_shift_zero = all(abs(current_map_shifts[f"MO-{district:02d}"]) < 1e-12
                              for district in range(1, 9))
    forecast = json.loads((args.forecast_dir / "forecast_2026.json").read_text(encoding="utf-8"))
    if forecast["publication_status"] not in (
            "internal_provisional_nowcast_not_for_publication",
            "public_nowcast_approved_with_limitations"):
        raise ValueError("Unexpected forecast publication status")
    forecast_missouri = {
        race["district_code"]: {candidate["party_group"]: candidate["name"]
                                 for candidate in race["candidates"]}
        for race in forecast["races"] if race["office"] == "house" and race["state"] == "MO"
    }
    certified_missouri = {
        district: {party: names[1] for party, names in candidates.items()}
        for district, candidates in missouri_candidates["districts"].items()
    }
    frozen_forecast = json.loads((FROZEN / "forecast_2026.json").read_text(encoding="utf-8"))
    comparable_forecast = dict(forecast)
    comparable_forecast["publication_status"] = frozen_forecast["publication_status"]
    freeze_matches = (comparable_forecast == frozen_forecast
                      and frozen["frozen_artifact_sha256"]["forecast_2026.json"]
                      == sha(FROZEN / "forecast_2026.json")
                      and frozen["frozen_artifact_sha256"]["model_parameters.json"]
                      == sha(args.forecast_dir / "model_parameters.json")
                      == sha(FROZEN / "model_parameters.json")
                      and frozen["information_cutoff_utc"] == forecast["metadata"]["information_cutoff_utc"])
    if not freeze_matches:
        raise ValueError("The version 0.20 forecast freeze differs from the live artifact")
    if forecast["metadata"]["model_version"] != "nowcast-2026-0.20" or frozen["model_version"] != "nowcast-2026-0.20":
        raise ValueError("This gate requires the accepted version 0.20 forecast")
    database_sha = sha(args.database)
    for name, actual in (("joint", joint["design"]["source_database_sha256"]),
                         ("governor audit", governor_lean_audit["database_sha256"]),
                         ("governor paired replay", governor_paired["source_database_sha256"]),
                         ("race", race["design"]["source_database_sha256"]),
                         ("crosswalk_test", selection["database_sha256"]),
                         ("forecast", forecast["metadata"]["data_sha256"])):
        if actual != database_sha:
            raise ValueError(f"{name} uses a different Stage 2 database")
    if joint["design"]["national_snapshot_sha256"] != sha(NATIONAL):
        raise ValueError("Joint replay uses stale national snapshots")
    if joint["design"]["historical_house_map_shifts_sha256"] != sha(HISTORICAL_MAPS):
        raise ValueError("Joint replay uses stale historical House map shifts")
    if historical_maps["stage2_database_sha256"] != database_sha:
        raise ValueError("Historical House map shifts use a different Stage 2 database")
    if historical_maps["crosswalk_sha256"] != sha(CROSSWALK):
        raise ValueError("Historical House map shifts use a different population crosswalk")
    if selection["crosswalk_sha256"] != sha(CROSSWALK):
        raise ValueError("Crosswalk test uses stale boundaries")
    for component, path in (("stage3", ROOT / "modeling/stage3_results_baseline.py"),
                            ("stage4", ROOT / "modeling/stage4_poll_model.py"),
                            ("stage5", ROOT / "modeling/stage5_outcome_model.py")):
        observed = sha(path)
        if joint["design"][f"{component}_code_sha256"] != observed:
            raise ValueError(f"Joint replay uses stale {component} code")
    governor_code = sha(ROOT / "modeling/governor_local_lean.py")
    if (joint["design"]["governor_local_lean_code_sha256"] != governor_code
            or governor_lean_audit["model_code_sha256"] != governor_code):
        raise ValueError("Governor local-lean evidence uses stale model code")
    if governor_paired["source_code_sha256"] != sha(ROOT / "pipeline/run_stage6_joint_replay.py"):
        raise ValueError("Paired governor replay uses stale replay code")
    if joint["design"]["source_code_sha256"] != sha(ROOT / "pipeline/run_stage6_joint_replay.py"):
        raise ValueError("Joint replay uses stale replay code")
    if len(national["snapshots"]) != 12:
        raise ValueError("Historical national cutoff coverage changed")
    cells = {(cell["cycle"], cell["lead_days"]): cell for cell in joint["cells"]}
    race_cells = {(cell["cycle"], cell["lead_days"]): cell for cell in race["cells"]}
    results = []
    for cycle in (2020, 2022, 2024):
        for lead in (90, 30, 7):
            cell = cells[cycle, lead]
            house = cell["office_seats"]["house"]
            senate = cell["office_seats"]["senate"]
            results.append({"cycle": cycle, "lead_days": lead,
                            "house_seats": house["race_count"],
                            "house_actual_D": house["actual_D_wins"],
                            "house_predicted_D": house["predicted_D_wins_mean"],
                            "house_95_interval": house["interval95"],
                            "house_actual_in_95_interval": house["interval95"][0] <= house["actual_D_wins"] <= house["interval95"][1],
                            "senate_races": senate["race_count"],
                            "senate_actual_D": senate["actual_D_wins"],
                            "senate_predicted_D": senate["predicted_D_wins_mean"],
                            "senate_95_interval": senate["interval95"],
                            "senate_actual_in_95_interval": senate["interval95"][0] <= senate["actual_D_wins"] <= senate["interval95"][1],
                            "cross_chamber_correlation": cell["house_senate_D_wins_correlation"]})
    seven_day_senate_coverage = {
        str(cycle): race_cells[cycle, 7]["strata"]["office:senate"]["methods"]["combined"]["coverage95"]
        for cycle in (2020, 2022, 2024)
    }
    checks = {
        "data_and_live_validators": {"passed": stage2["status"] == "passed" and stage5["status"] == "passed",
                                     "stage2": stage2["status"], "stage5": stage5["status"]},
        "official_2024_house_seat_outcomes": {"passed": all(cells[2024, lead]["office_seats"]["house"]["race_count"] == 435
                                                       for lead in (90, 30, 7)),
                                               "numeric_vote_share_seats": 433,
                                               "unopposed_outcome_only_seats": 2},
        "population_weighted_crosswalk": {"passed": bool(selection["promotion_passed"]) and
                                                   all(len(rows) == 435 for rows in crosswalk["transitions"].values()),
                                          "selection_2022_log_score": selection["results"]["2022"],
                                          "2024_is_pristine_holdout": False},
        "dated_national_and_pollster_inputs": {"passed": len(national["snapshots"]) == 12 and
                                                len(race["historical_pollster_ratings"]) == 3 and
                                                joint["design"]["poll_source"]["deduplicated_questions"] > 0,
                                               "national_snapshots": len(national["snapshots"]),
                                               "pollster_editions": {cycle: info["rating_edition"] for cycle, info in race["historical_pollster_ratings"].items()}},
        "historical_full_chamber_coverage": {"passed": all(cells[cycle, lead]["office_seats"]["house"]["race_count"] == 435
                                                    for cycle in (2020, 2022, 2024) for lead in (90, 30, 7)),
                                             "house_seats_by_cycle": {str(cycle): cells[cycle, 7]["office_seats"]["house"]["race_count"]
                                                                      for cycle in (2020, 2022, 2024)}},
        "historical_regular_senate_coverage": {
            "passed": all(cells[cycle, lead]["office_seats"]["senate"]["race_count"] == expected
                          for cycle, expected in ((2020, 33), (2022, 34), (2024, 33))
                          for lead in (90, 30, 7)),
            "regular_races_by_cycle": {"2020": 33, "2022": 34, "2024": 33},
            "modeled_races_by_cycle": {str(cycle): cells[cycle, 7]["office_seats"]["senate"]["race_count"]
                                       for cycle in (2020, 2022, 2024)},
            "special_elections_not_in_replay": True},
        "historical_feature_parity": {
            "passed": governor_audit["status"] == "reviewed_feature_disabled" and
                      not joint["design"]["governor_approval_enabled"] and
                      all(not cell["local_feature_coverage"].get("governor_approval", 0)
                          for cell in joint["cells"]),
            "house_map_shift_replayed": bool(joint["design"]["historical_house_map_shifts_enabled"]) and
                                        all(cells[cycle, 7]["local_feature_coverage"].get("house_presidential_map_shift", 0)
                                            == historical_maps["race_coverage"][str(cycle)]["map_shift_races"]
                                            for cycle in (2020, 2022, 2024)),
            "counting_rule_precycle_fits_replayed": bool(joint["design"]["counting_rule_training_pairs"]),
            "governor_approval_effect": "disabled_in_live_and_replay_pending_dated_validation",
            "audit_sha256": sha(GOVERNOR_AUDIT),
            "audit_scope": "Governor approval audit is an earlier development review; current replay independently checks that the feature is disabled."},
        "governor_local_lean_review": {
            "passed": governor_lean_audit["training_rows"] == 234 and
                      joint["design"]["governor_local_lean"]["enabled"] and
                      governor_paired["all_non_governor_probabilities_equal"] and
                      len(governor_paired["cells"]) == 9 and
                      all(cell["non_governor_winner_probabilities_exactly_equal"]
                          for cell in governor_paired["cells"]),
            "owner_decision": "accepted_for_release_with_documented_limitations",
            "old_governor_winner_log_loss": governor_paired["summary"]["old_model"]["winner_log_loss"],
            "revised_governor_winner_log_loss": governor_paired["summary"]["revised_model"]["winner_log_loss"],
            "cross_party_incumbent_95_coverage": governor_paired["summary"]["revised_model"]["cross_party_incumbent_margin_intervals"]["coverage95"],
            "distinct_cross_party_incumbent_races": 9,
            "audit_sha256": sha(GOVERNOR_LEAN_AUDIT),
            "paired_replay_sha256": sha(GOVERNOR_PAIRED)},
        "historical_house_interval_review": {
            "passed": house_audit["status"] == "reviewed_no_live_change_required" and
                      cells[2020, 7]["office_seats"]["house"]["race_count"] == 435,
            "finding": "The chronological 2020 miss remains; the live 2026 generic-ballot variance already includes the later observed error scale. The forensic wider interval is not a backtest score.",
            "seven_day_actual_D": cells[2020, 7]["office_seats"]["house"]["actual_D_wins"],
            "seven_day_interval95": cells[2020, 7]["office_seats"]["house"]["interval95"],
            "audit_sha256": sha(HOUSE_AUDIT),
            "audit_scope": "Earlier review; current replay retains the 2020 House diagnostic."},
        "live_missouri_house_map": {"passed": bool(missouri["current_2022_map_matches_model"])
                                               and missouri_shift_zero,
                                    "model_assumption": missouri["current_model_assumption"],
                                    "status_as_of_verification": missouri["status"],
                                    "verified_on": missouri["verified_on"],
                                    "eight_district_shifts_zero": missouri_shift_zero,
                                    "future_court_orders_require_recheck": True},
        "live_missouri_house_candidates": {
            "passed": forecast_missouri == certified_missouri,
            "districts_checked": len(forecast_missouri),
            "official_certification": missouri_candidates["source_url"],
            "official_certification_date": missouri_candidates["source_date"],
            "reviewed_on": missouri_candidates["reviewed_on"],
            "reference_sha256": sha(MISSOURI_CANDIDATES)},
    }
    passed = all(value["passed"] for value in checks.values())
    report = {"status": "passed" if passed else "open",
              "prelaunch_status": "passed" if passed else "open",
              "stage6_prelaunch_evidence_passed": passed,
              "public_calibration_claim_supported": False,
              "calibration_claim_limit": "Three inspected, correlated historical cycles and terminal-result proxies cannot establish nominal held-today coverage.",
              "scope": "Version 0.20 prelaunch evidence gate for the held-today 2026 nowcast; deployment operations have separate checks",
              "owner_model_decision": "accepted_with_documented_governor_limitations",
              "approved_model_code_sha256": {
                  key: forecast["metadata"][key]
                  for key in ("model_code_sha256", "stage3_model_code_sha256",
                              "stage4_model_code_sha256", "governor_local_lean_code_sha256")},
              "frozen_live_cutoff": forecast["metadata"]["information_cutoff_utc"],
              "live_model_version": forecast["metadata"]["model_version"],
              "hashes": {"stage2_database": database_sha,
                         "forecast": sha(args.forecast_dir / "forecast_2026.json"),
                         "frozen_source_forecast": sha(FROZEN / "forecast_2026.json"),
                         "national_snapshots": sha(NATIONAL),
                         "population_crosswalk": sha(CROSSWALK),
                         "historical_house_map_shifts": sha(HISTORICAL_MAPS),
                         "frozen_v020_manifest": sha(FROZEN / "manifest.json"),
                         "missouri_map_status": sha(MISSOURI),
                         "missouri_certified_house_candidates": sha(MISSOURI_CANDIDATES),
                         "joint_replay": sha(args.joint), "race_replay_development_reference": sha(args.race),
                         "governor_local_lean_audit": sha(GOVERNOR_LEAN_AUDIT),
                         "governor_paired_replay": sha(GOVERNOR_PAIRED)},
              "checks": checks,
              "postrelease_evaluation": {
                  "pristine_2026_outcome_holdout": {
                      "status": "pending_election",
                      "prospective_forecast_frozen": freeze_matches,
                      "release_blocker": False,
                      "reason": "Score the frozen forecast after the 2026 election; the result is not available before release."},
                  "direct_held_today_truth": {
                      "status": "unobservable",
                      "release_blocker": False,
                      "reason": "Support at a past cutoff is latent; later certified results include opinion and turnout changes."}},
              "terminal_proxy_results": results,
              "seven_day_senate_candidate_share_coverage95": seven_day_senate_coverage,
              "candidate_share_replay_scope": "The separate race replay predates version 0.20 and is retained as development evidence, not a current-code parity check.",
              "interpretation": "A passing prelaunch review permits release with documented limitations; it does not prove nominal probability calibration. Governor winner log loss slightly worsened and cross-party incumbent coverage remains weak. Terminal outcomes are diagnostics, not direct labels for an earlier held-today estimand. No partisan correction or interval tuning was chosen from these proxy misses."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"],
                      "passed_checks": sum(item["passed"] for item in checks.values()),
                      "total_checks": len(checks),
                      "house_coverage": checks["historical_full_chamber_coverage"]["house_seats_by_cycle"]}, indent=2))


if __name__ == "__main__":
    main()
