"""Select an area-overlap prior on 2022 House races and evaluate 2024 once."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m
from pipeline.load_stage6_wayback_polls import load as load_wayback_polls
from pipeline.run_stage6_calibration import district_continuity, run_cell

DB = ROOT / "data/processed/stage2.sqlite"
CROSSWALK = ROOT / "data/reference/stage6_house_area_crosswalk.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_house_crosswalk_sensitivity.json"
THRESHOLDS = (None, 0.5, 0.65, 0.8)


def state_codes() -> dict[str, str]:
    registry = json.loads((ROOT / "data/reference/races_2026.json").read_text(encoding="utf-8"))
    source = ROOT / registry["sources"]["census_cd120"]["path"]
    with zipfile.ZipFile(source) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            rows = csv.DictReader((line.decode("utf-8-sig") for line in stream), delimiter="|")
            return {row["USPS"]: row["GEOID"][:2] for row in rows}


def score(cell):
    result = {}
    for key in ("all", "density:no_polls", "density:one_poll", "density:multiple_polls",
                "district_continuity:no_candidate_continuity_evidence"):
        if key in cell["strata"]:
            result[key] = {"n_races": cell["strata"][key]["n_races"],
                           **cell["strata"][key]["methods"]["combined"]}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
        calibration_questions = m.load_historical_questions(connection)
    questions, _ = load_wayback_polls(races)
    transitions = m.stage3.build_transitions(races)
    continuity = district_continuity(races, transitions)
    codes = state_codes()
    raw = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    walks = {}
    for name, rows in raw["transitions"].items():
        cycle = int(name.split("_to_")[1])
        walks.update({(cycle, row["state_fips"], row["target_district"]): row
                      for row in rows})
    previous = {(race.cycle, race.state, race.district): race for race in races
                if race.office == "house"}

    def rekey(transition, threshold):
        if threshold is None or transition.office != "house" or transition.target_cycle not in (2022, 2024):
            return transition, None
        if transition.prior_selection != "same_district_label":
            return transition, None
        row = walks.get((transition.target_cycle, codes[transition.state], transition.target.district))
        if row is None or row["dominant_area_fraction"] < threshold:
            return transition, None
        old_district = row["dominant_prior_district"]
        if old_district == transition.prior.district:
            return transition, None
        prior = previous.get((transition.prior_cycle, transition.state, old_district))
        if prior is None:
            return transition, None
        return replace(transition, prior=prior, prior_alr=m.stage3.alr(m.stage3.group_shares(prior)),
                       prior_selection="area_overlap_dominant"), row

    def evaluate(cycle, threshold):
        fitted = [rekey(t, threshold)[0] for t in transitions if t.target_cycle < cycle]
        holdout = [rekey(t, threshold)[0] for t in transitions
                   if t.target_cycle == cycle and t.office == "house"]
        training = [t for t in fitted if t.target_cycle < cycle]
        models = m.stage3.fit_office_models(training)
        allocation = m.stage3.fit_candidate_allocation(races, max_cycle=cycle-1)
        covariances = {office: m.stage3.residual_covariance(
            [t for t in training if t.office == office], models[office]) for office in m.OFFICES}
        bias = m.fit_bias_model(calibration_questions, {r.source_race_id: r for r in races},
                                training_cycle=2018, senate_training_through=cycle-2)
        bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
        affected = [t for t in holdout if t.prior_selection == "area_overlap_dominant"]
        cell = run_cell(cycle, 7, holdout, questions, models, allocation, covariances,
                        bias, 1000, continuity)
        return {"full_house": score(cell), "rekeyed_holdout_races": len(affected),
                "rekeyed_training_races": sum(t.prior_selection == "area_overlap_dominant" for t in training)}

    selection = {"baseline" if threshold is None else str(threshold): evaluate(2022, threshold)
                 for threshold in THRESHOLDS}
    # The primary score was declared before inspecting 2024. A tie favors the
    # simpler policy with fewer changed priors.
    eligible = [(selection[str(threshold)]["full_house"]["all"]["log_score"],
                 -threshold, threshold) for threshold in THRESHOLDS if threshold is not None]
    best_experimental = min(eligible)[2]
    baseline_2022 = selection["baseline"]["full_house"]["all"]["log_score"]
    selected = (best_experimental if selection[str(best_experimental)]["full_house"]["all"]["log_score"]
                < baseline_2022 else None)
    # Keep the best experimental rule visible as a diagnostic, even if the
    # predeclared 2022 score rejects it. It cannot be promoted in that case.
    holdout = {"baseline": evaluate(2024, None),
               "best_experimental": evaluate(2024, best_experimental)}
    report = {
        "design": "Seven-day terminal-proxy replay. Candidate continuity takes precedence. Area overlap is tested only as a single dominant old district, never as a vote-share weight.",
        "crosswalk_source_sha256": __import__("hashlib").sha256(CROSSWALK.read_bytes()).hexdigest(),
        "selection_score": "2022 full House winner log score; lower is better",
        "selection_2022": selection, "best_experimental_minimum_area_fraction": best_experimental,
        "selected_minimum_area_fraction": selected,
        "untouched_2024": holdout,
        "promotion_passed": selected is not None and (
            holdout["best_experimental"]["full_house"]["all"]["log_score"]
            <= holdout["baseline"]["full_house"]["all"]["log_score"] + 0.01),
        "promotion_rule": "Require 2022 improvement over baseline and 2024 noninferiority on full-House log score, with no material interval undercoverage.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": selected, "best_experimental": best_experimental,
                      "2022": {key: value["full_house"]["all"] for key, value in selection.items()},
                      "2024": {key: value["full_house"]["all"] for key, value in holdout.items()}},
                     indent=2), flush=True)


if __name__ == "__main__":
    main()
