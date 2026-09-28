"""Paired 2026 Senate counterfactuals from the frozen Stage 1/2 snapshot.

These are diagnostic removals of individual model components, not alternative
forecasts. All variants use the same Stage 3 draws and per-race outcome seeds.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage5_outcome_model as stage5

stage4 = stage5.stage4
stage3 = stage5.stage3


def race_seed(seed: int, race_id: str) -> int:
    digest = hashlib.sha256(f"{seed}:{race_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def summarize_variant(name, current, priors, questions_by_race, bias_model, cutoff,
                      inflation, runoff_model, transfers, seed, polls=True):
    count = len(next(iter(priors.values())))
    seats = {group: np.zeros(count, dtype=np.int16) for group in stage3.GROUPS}
    races = {}
    for item in current:
        race = item["race"]
        if race["office"] != "senate":
            continue
        race_id = race["race_id"]
        candidates = item["candidates"]
        keys = [candidate["ballot_entry_id"] for candidate in candidates]
        groups = [stage3.party_group(candidate["party"]) for candidate in candidates]
        prior = priors[race_id]
        if polls:
            rows, values, variances, diagnostics = stage4.poll_contrasts(
                questions_by_race.get(race_id, []), keys, groups, bias_model, cutoff
            )
            posterior = stage4.affine_update_draws(prior, rows, values, variances, inflation)
            shares = stage4.preserve_unpolled_candidate_mass(
                prior, posterior, keys, diagnostics["polled_candidate_keys"]
            )
            poll_count = diagnostics["poll_count"]
        else:
            shares = prior
            poll_count = 0
        rule = race["counting_rule"]
        rng = np.random.default_rng(race_seed(seed, race_id))
        if rule == "plurality" or len(candidates) == 1:
            winners = np.argmax(shares, axis=1)
        elif rule == "ranked_choice":
            winners, _ = stage5.rcv_winners(shares, candidates, transfers, rng)
        elif rule == "majority_then_top_two_runoff":
            winners, _ = stage5.runoff_winners(shares, candidates, runoff_model, rng)
        elif rule == "majority_then_legislative_selection":
            winners, _ = stage5.vermont_winners(shares, candidates)
        else:
            raise ValueError((race_id, rule))
        for index, group in enumerate(groups):
            seats[group] += winners == index
        d = shares[:, [group == "D" for group in groups]].sum(axis=1)
        r = shares[:, [group == "R" for group in groups]].sum(axis=1)
        margin = float(np.mean((d-r)/np.maximum(d+r, 1e-9))) if "D" in groups and "R" in groups else None
        races[race_id] = {
            "state": race["state"], "poll_count": poll_count,
            "D_R_margin": margin,
            "D_win_probability": float(np.mean(np.isin(winners, [i for i, group in enumerate(groups) if group == "D"]))),
            "R_win_probability": float(np.mean(np.isin(winners, [i for i, group in enumerate(groups) if group == "R"]))),
            "O_win_probability": float(np.mean(np.isin(winners, [i for i, group in enumerate(groups) if group == "O"]))),
        }
    return {
        "label": name, "draws": count,
        "expected_D_winners": float(np.mean(seats["D"])),
        "D_control_if_other_winners_caucus_D": float(np.mean(34 + seats["D"] + seats["O"] >= 51)),
        "D_control_if_other_winners_caucus_R": float(np.mean(34 + seats["D"] >= 51)),
        "R_control_if_other_winners_caucus_D": float(np.mean(31 + seats["R"] >= 50)),
        "R_control_if_other_winners_caucus_R": float(np.mean(31 + seats["R"] + seats["O"] >= 50)),
        "races": races,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "senate_component_audit.json")
    args = parser.parse_args()
    if args.draws < 1000:
        raise ValueError("At least 1,000 paired draws are required")
    parameters_path = ROOT / "artifacts" / "stage4" / "model_parameters.json"
    parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    cutoff_text = parameters["metadata"]["information_cutoff_utc"]
    cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00")).replace(tzinfo=None)
    stage1_path = ROOT / "data" / "processed" / "stage1.sqlite"
    stage2_path = ROOT / "data" / "processed" / "stage2.sqlite"
    for path, key in ((stage1_path, "stage1_data_sha256"), (stage2_path, "data_sha256")):
        if stage4.sha256(path) != parameters["metadata"][key]:
            raise RuntimeError(f"Frozen input differs from accepted Stage 4: {path}")
    connection = sqlite3.connect(stage2_path)
    connection.row_factory = sqlite3.Row
    try:
        historical = stage3.load_historical_races(connection)
        transitions = stage3.build_transitions(historical)
        current = stage3.load_current_races(connection)
        models = stage3.fit_office_models(transitions)
        allocation = stage3.fit_candidate_allocation(historical)
        decomposition = stage3.decompose_covariance(transitions, models)
        stage3_draws = stage4.current_prior_draws(current, models, allocation, decomposition, args.draws, args.seed)
        questions = stage4.load_current_questions(connection, stage1_path)
        history_questions = stage4.load_historical_questions(connection)
        bias_model = stage4.fit_bias_model(history_questions, {race.source_race_id: race for race in historical})
        bias_model.half_life_days = float(parameters["current_poll_recency"]["half_life_days"])
        runoff_model = stage5.fit_runoff_model(stage5.paired_runoffs(connection))
        transfers, _ = stage5.rcv_transfer_evidence(connection)
        by_race = defaultdict(list)
        for question in questions:
            if question.available_date <= cutoff:
                by_race[question.race_key].append(question)
        inflation = float(parameters["posterior_covariance_inflation"]["selected"])
        variants = {}

        def record(name, priors, model=bias_model, polls=True):
            print(f"Auditing {name}", flush=True)
            variants[name] = summarize_variant(
                name, current, priors, by_race, model, cutoff, inflation,
                runoff_model, transfers, args.seed, polls
            )

        default_priors, national = stage4.fit_national_signal_update(
            connection, stage1_path, historical, current, stage3_draws, cutoff
        )
        record("accepted_components", default_priors)
        record("without_race_polls", default_priors, polls=False)

        no_bias = copy.deepcopy(bias_model)
        no_bias.senate_bias_model = None
        for fitted in no_bias.models.values():
            fitted.intercept_ = 0.0
            fitted.coef_[:] = 0.0
        record("without_senate_poll_bias_correction", default_priors, no_bias)

        no_floor = copy.deepcopy(bias_model)
        for coordinate in no_floor.shared_variance["senate"]:
            no_floor.shared_variance["senate"][coordinate] = 0.0
        record("without_senate_shared_poll_error", default_priors, no_floor)

        record("without_national_or_local_update", stage3_draws)

        no_generic_priors, _ = stage4.fit_national_signal_update(
            connection, stage1_path, historical, current, stage3_draws, cutoff,
            include_generic=False
        )
        record("without_generic_ballot", no_generic_priors)
        del no_generic_priors

        no_fundamentals_priors, _ = stage4.fit_national_signal_update(
            connection, stage1_path, historical, current, stage3_draws, cutoff,
            include_fundamentals=False
        )
        record("without_approval_fundamentals", no_fundamentals_priors)
        del no_fundamentals_priors

        no_local_priors, _ = stage4.fit_national_signal_update(
            connection, stage1_path, historical, current, stage3_draws, cutoff,
            include_senate_local_lean=False
        )
        record("without_fitted_senate_local_lean", no_local_priors)
        del no_local_priors
    finally:
        connection.close()
    baseline = variants["accepted_components"]
    for label, variant in variants.items():
        variant["delta_D_control_if_O_caucus_D_vs_baseline"] = (
            variant["D_control_if_other_winners_caucus_D"] - baseline["D_control_if_other_winners_caucus_D"]
        )
        variant["delta_expected_D_winners_vs_baseline"] = variant["expected_D_winners"] - baseline["expected_D_winners"]
    result = {
        "method": "paired one-component-at-a-time diagnostic; no variant is a calibrated replacement forecast",
        "cutoff_utc": cutoff_text,
        "snapshot_ids": parameters["metadata"]["input_snapshot_ids"],
        "stage1_sha256": stage4.sha256(stage1_path),
        "stage2_sha256": stage4.sha256(stage2_path),
        "draws": args.draws, "seed": args.seed,
        "accepted_stage5_D_control_if_O_caucus_D": json.loads(
            (ROOT / "artifacts" / "stage5" / "forecast_2026.json").read_text(encoding="utf-8")
        )["joint_summaries"]["senate"]["full_chamber"]["caucus_scenarios"]["all_other_winners_caucus_D"]["D_control_probability"],
        "variants": variants, "national_signals": national,
        "limitations": [
            "All probabilities condition on a stated caucus choice for other-party winners.",
            "One-at-a-time effects need not add because model components interact.",
            "Removing shared poll error is a deliberately overconfident diagnostic, not an endorsed setting.",
            "The Senate mean correction is fitted across cycles; 30-day live recency still needs whole-cycle validation.",
            "Monte Carlo replay uses fewer draws and per-race outcome seeds, so small differences from the accepted Stage 5 run are expected.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}")
    for name, variant in variants.items():
        print(f"{name:39s} D control {variant['D_control_if_other_winners_caucus_D']:.1%} "
              f"delta {variant['delta_D_control_if_O_caucus_D_vs_baseline']:+.1%} "
              f"expected D winners {variant['expected_D_winners']:.2f}")


if __name__ == "__main__":
    main()
