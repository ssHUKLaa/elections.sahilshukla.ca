"""Cycle-held-out terminal-proxy checks for the frozen 2026 nowcast.

The result of a race is only a proxy for support at an earlier cutoff.  This
script deliberately does not fit a correction to the cycle being scored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m
from modeling import stage5_outcome_model as stage5
from modeling import senate_minor_share
from modeling import historical_pollster_quality
from pipeline.load_stage6_wayback_polls import load as load_wayback_polls

DB = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "artifacts/calibration/stage6_report.json"
LEADS = (90, 30, 7)
METHODS = ("results_only", "polls_only", "combined")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(scores: dict[str, list[float]]) -> dict:
    return {name: round(float(np.mean(values)), 6) for name, values in scores.items() if values}


def district_continuity(races, transitions):
    previous = defaultdict(set)
    for race in races:
        if race.office == "house":
            for candidate in race.candidates:
                previous[(race.cycle, race.state, m.stage3.first_last_key(candidate.name))].add(race.district)
    result = {}
    for transition in transitions:
        if transition.office != "house":
            continue
        target = transition.target
        locations = [previous[(transition.prior_cycle, target.state,
                               m.stage3.first_last_key(candidate.name))]
                     for candidate in target.candidates]
        result[target.source_race_id] = (
            "documented_candidate_move" if any(any(d != target.district for d in loc) for loc in locations)
            else "same_district_candidate" if any(locations)
            else "no_candidate_continuity_evidence"
        )
    return result


def run_cell(cycle, lead, transitions, questions, models, allocation, covariances, bias, draws, continuity,
             *, screen_senate_contenders=False, minor_share_fit=None,
             contender_support_floor_pct=5.0, quality_weights=None):
    rng = np.random.default_rng(20260924 + cycle * 100 + lead)
    by_race = defaultdict(list)
    for question in questions:
        if m.eligible_at_cutoff(question, lead):
            by_race[question.race_key].append(question)
    groups = defaultdict(lambda: {name: defaultdict(list) for name in METHODS})
    counts = defaultdict(int)
    failures = []
    winner_misses = []
    for transition in transitions:
        race = transition.target
        candidates = m.stage3.historical_candidate_dicts(race)
        keys = [candidate.candidate_key for candidate in race.candidates]
        party_groups = [candidate.group for candidate in race.candidates]
        mean = m.stage3.transition_predict(models[race.office], transition)
        group_draws = rng.multivariate_normal(
            mean,
            covariances[race.office], size=draws,
        )
        group_draws = m.stage3.widen_historical_transition_draws(
            group_draws, mean, transition, models[race.office], rng)
        other_target = m.stage3.transition_other_share_target(models[race.office], transition)
        if other_target is not None:
            group_draws = m.stage3.calibrate_other_share(group_draws, other_target)
        prior = m.stage3.simulate_candidates(
            group_draws, candidates, allocation[race.office]["incumbent_log_utility"],
            allocation[race.office]["within_group_sigma"], rng,
            allocation[race.office]["write_in_share_samples"],
        )
        race_questions = by_race.get(race.source_race_id, [])
        rows, values, variances, diagnostics = m.poll_contrasts(
            race_questions, keys, party_groups, bias,
            race_questions[0].election_date - timedelta(days=lead) if race_questions else None,
            quality_weights=quality_weights,
            apply_election_day_bias=False,
        ) if race_questions else ([], [], [], {"poll_count": 0, "polled_candidate_keys": []})
        unique_groups = set(party_groups)
        ballot = ("two_major" if unique_groups == {"D", "R"} and len(keys) == 2
                  else "same_group_multi" if len(keys) > len(unique_groups)
                  else "other_ballot")
        prior_votes = defaultdict(int)
        for candidate in transition.prior.candidates:
            prior_votes[candidate.group] += candidate.votes
        two_party_votes = prior_votes["D"] + prior_votes["R"]
        if two_party_votes:
            prior_margin = abs(prior_votes["D"] - prior_votes["R"]) / two_party_votes
            competitiveness = "prior_close" if prior_margin <= 0.10 else "prior_safe"
        else:
            competitiveness = "prior_no_two_party"
        density = "no_polls" if not rows else ("one_poll" if diagnostics["poll_count"] == 1 else "multiple_polls")
        strata = ("all", f"office:{race.office}", f"density:{density}",
                  f"ballot:{ballot}", f"competitiveness:{competitiveness}",
                  f"office_density:{race.office}:{density}")
        if race.office == "house":
            strata += (f"district_continuity:{continuity[race.source_race_id]}",)
        actual = np.array([candidate.votes for candidate in race.candidates], dtype=float)
        actual /= actual.sum()
        winner = int(np.argmax(actual))
        predictions = {"results_only": prior}
        if rows:
            updated = m.affine_update_draws(prior, rows, values, variances)
            predictions["combined"] = m.preserve_unpolled_candidate_mass(
                prior, updated, keys, diagnostics["polled_candidate_keys"])
            predictions["polls_only"] = m.flat_poll_draws(len(keys), rows, values, variances, draws, rng)
        else:
            predictions["combined"] = prior
        if screen_senate_contenders and minor_share_fit and race.office == "senate" and race.state not in {"AK", "GA"}:
            contender_item = {
                "race": {"office": "senate", "counting_rule": "plurality"},
                "candidates": [{"ballot_entry_id": candidate.candidate_key,
                                "party": candidate.party} for candidate in race.candidates],
            }
            screen = stage5.senate_contender_screen(
                contender_item, race_questions, quality_weights,
                support_floor_pct=contender_support_floor_pct,
            )
            predictions = {
                method: senate_minor_share.apply(samples, screen, minor_share_fit)
                for method, samples in predictions.items()
            }
        for stratum in strata:
            counts[stratum] += 1
            for method, samples in predictions.items():
                for metric, value in m.score_draws(samples, actual, winner).items():
                    groups[stratum][method][metric].append(value)
        combined_score = m.score_draws(predictions["combined"], actual, winner)
        expected_share = predictions["combined"].mean(axis=0)
        winner_interval = np.quantile(predictions["combined"][:, winner], [0.025, 0.975])
        winner_misses.append({"race_id": race.source_race_id, "office": race.office,
                             "state": race.state, "winner": keys[winner],
                             "forecast_favorite": keys[int(np.argmax(expected_share))],
                             "winner_probability": round(float(np.mean(
                                 np.argmax(predictions["combined"], axis=1) == winner)), 4),
                             "winner_actual_share": round(float(actual[winner]), 4),
                             "winner_predicted_share": round(float(expected_share[winner]), 4),
                             "winner_share_interval95": [round(float(x), 4) for x in winner_interval],
                             "brier": round(combined_score["brier"], 4),
                             "poll_count": diagnostics["poll_count"]})
        if rows and race.office == "senate":
            lower, upper = np.quantile(predictions["combined"], [0.025, 0.975], axis=0)
            for index, candidate in enumerate(race.candidates):
                if not lower[index] <= actual[index] <= upper[index]:
                    failures.append({"race_id": race.source_race_id,
                                     "candidate": candidate.candidate_key,
                                     "actual": round(float(actual[index]), 4),
                                     "interval95": [round(float(lower[index]), 4), round(float(upper[index]), 4)],
                                     "poll_count": diagnostics["poll_count"]})
    return {
        "cycle": cycle, "lead_days": lead, "n_races": counts["all"],
        "n_polled_races": counts.get("all", 0) - counts.get("density:no_polls", 0),
        "strata": {key: {"n_races": counts[key], "methods": {
            method: summary(values) for method, values in methods.items() if values
        }} for key, methods in groups.items()},
        "senate_polled_share_coverage_failures": failures,
        "largest_winner_misses": sorted(winner_misses, key=lambda item: item["brier"], reverse=True)[:15],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--draws", type=int, default=1500)
    parser.add_argument("--screen-senate-contenders", action="store_true")
    parser.add_argument("--contender-support-floor-pct", type=float, default=5.0)
    parser.add_argument("--cycles", type=int, nargs="+", default=(2020, 2022, 2024))
    parser.add_argument("--leads", type=int, nargs="+", default=LEADS)
    parser.add_argument("--skip-supplemental", action="store_true")
    args = parser.parse_args()
    if args.draws < 500:
        parser.error("at least 500 draws are required")
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
        calibration_questions = m.load_historical_questions(connection)
    questions, wayback_diagnostics = load_wayback_polls(races)
    transitions = m.stage3.build_transitions(races)
    continuity = district_continuity(races, transitions)
    by_id = {race.source_race_id: race for race in races}
    cells = []
    supplemental_senate_cells = []
    coverage = {}
    rating_editions = {}
    for cycle in args.cycles:
        training = [transition for transition in transitions if transition.target_cycle < cycle]
        holdout = [transition for transition in transitions if transition.target_cycle == cycle]
        if not holdout:
            continue
        models = m.stage3.fit_office_models(training)
        allocation = m.stage3.fit_candidate_allocation(races, max_cycle=cycle-1)
        covariances = {office: m.stage3.residual_covariance(
            [transition for transition in training if transition.office == office], models[office]
        ) for office in m.OFFICES}
        # The available historical poll source supplies 2018 calibration rows.
        # Do not fit poll errors using observations from the scored cycle.
        bias = m.fit_bias_model(calibration_questions, by_id, training_cycle=2018,
                                senate_training_through=cycle-2)
        bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
        quality_weights, rating_editions[str(cycle)] = historical_pollster_quality.load(cycle)
        screen_fn = lambda item, qs, weights: stage5.senate_contender_screen(
            item, qs, weights, support_floor_pct=args.contender_support_floor_pct,
        )
        minor_fit = (
            senate_minor_share.fit(races, questions, cycle-2, screen_fn)
            if args.screen_senate_contenders and cycle > 2020 else None
        )
        coverage[str(cycle)] = {"holdout_races": len(holdout),
                                "deduplicated_poll_questions_in_archive": sum(q.race_key in {
                                    t.target.source_race_id for t in holdout} for q in questions)}
        for lead in args.leads:
            cell = run_cell(cycle, lead, holdout, questions, models, allocation,
                            covariances, bias, args.draws, continuity,
                            screen_senate_contenders=args.screen_senate_contenders,
                            minor_share_fit=minor_fit,
                            contender_support_floor_pct=args.contender_support_floor_pct,
                            quality_weights=quality_weights)
            cells.append(cell)
            print(f"{cycle} {lead}d: {cell['n_races']} races, {cell['n_polled_races']} polled", flush=True)
            if cycle in (2022, 2024) and not args.skip_supplemental:
                # This independent compilation has fieldwork dates but no
                # publication timestamps. Require a seven-day release lag;
                # score it separately from the timestamped 538 archive.
                senate_rows, _ = m.senate_bias.load_observations(races, lead + 7)
                senate_questions = [
                    replace(q, available_date=q.end_date + timedelta(days=7))
                    for q in m.senate_archive_questions(senate_rows, by_id, cycle)
                    if max(by_id[q.race_key].candidates, key=lambda candidate: candidate.votes).group != "O"
                ]
                senate_cell = run_cell(
                    cycle, lead, [t for t in holdout if t.office == "senate"],
                        senate_questions, models, allocation, covariances, bias, args.draws, continuity,
                        screen_senate_contenders=args.screen_senate_contenders,
                        minor_share_fit=minor_fit,
                        contender_support_floor_pct=args.contender_support_floor_pct,
                        quality_weights=quality_weights,
                )
                supplemental_senate_cells.append(senate_cell)
                print(f"  supplemental Senate: {senate_cell['n_polled_races']} polled races", flush=True)
    by_cycle = {str(c): max((cell["n_polled_races"] for cell in cells if cell["cycle"] == c), default=0)
                for c in (2020, 2022, 2024)}
    gate = {"status": "incomplete", "passed": False,
            "reasons": ["Earlier-date election results are an imperfect proxy for a held-today nowcast.",
                        "Historical ballot rosters come from final results and may reveal later candidate entries or withdrawals at early cutoffs.",
                        "This race-level report covers the Stage 3/4 core; dated national signals and joint seat outcomes are evaluated in the separate Stage 6 joint replay.",
                        "Historical 538 CSVs were captured after the elections; their row creation dates are used, but retrospective source revisions cannot be fully ruled out.",
                        "The separate joint replay remains partial for 2020 and 2022 House seats and approximates historical counting rules."]}
    report = {"design": {"target": "election-held-at-cutoff nowcast",
                         "validation_target": "certified eventual vote shares and winners (terminal proxy)",
                         "training_rule": "fit on cycles strictly before each holdout; 2018 poll error calibration only",
                         "leads_days": args.leads, "draws_per_race": args.draws,
                         "current_model_version": stage5.MODEL_VERSION,
                         "senate_contender_screen": args.screen_senate_contenders,
                         "contender_support_floor_pct": args.contender_support_floor_pct,
                         "source_database_sha256": digest(args.database),
                         "stage6_code_sha256": digest(Path(__file__)),
                         "poll_loader_code_sha256": digest(ROOT / "pipeline/load_stage6_wayback_polls.py"),
                         "stage3_code_sha256": digest(ROOT / "modeling/stage3_results_baseline.py"),
                         "stage4_code_sha256": digest(ROOT / "modeling/stage4_poll_model.py"),
                         "stage5_code_sha256": digest(ROOT / "modeling/stage5_outcome_model.py")},
              "historical_pollster_ratings": rating_editions,
              "archive_coverage": coverage, "polled_races_by_cycle_at_7_days": by_cycle,
              "wayback_poll_processing": wayback_diagnostics,
              "cells": cells,
              "supplemental_senate_archive": {
                  "source_url": "https://github.com/Jack-Whitcomb/All-US-Senate-polls-2006-2024",
                  "source_sha256": json.loads((ROOT / "data/reference/poll_error/source_manifest.json").read_text())["senate_polls"]["sha256"],
                  "availability_assumption": "fieldwork end date plus seven days; publication date absent",
                  "scope": "two-party Senate questions only; independent-led and same-party ballots unsupported",
                  "cells": supplemental_senate_cells,
              },
              "gate": gate}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
