"""Run the 2026 election-held-at-cutoff nowcast under each counting rule.

The model keeps ballot identity, vote choice, office winner, and Senate caucus
membership distinct. It fits current-support shares, then applies plurality,
runoff, ranked-choice, or Vermont joint-assembly rules within common draws.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

try:
    from modeling import pollster_quality, senate_minor_share
    from modeling import fundamentals_features_2026 as fundamentals_features
except ModuleNotFoundError:
    import pollster_quality
    import senate_minor_share
    import fundamentals_features_2026 as fundamentals_features


ROOT = Path(__file__).resolve().parents[1]
STAGE4_PATH = ROOT / "modeling" / "stage4_poll_model.py"
SPEC = importlib.util.spec_from_file_location("stage4_poll_model", STAGE4_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load Stage 4 model")
stage4 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage4
SPEC.loader.exec_module(stage4)
stage3 = stage4.stage3

MODEL_VERSION = "nowcast-2026-0.20"
GROUPS = stage3.GROUPS
MINOR_SHARE_FIT = ROOT / "data/reference/senate_minor_share_fit_2026.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def distribution(values: np.ndarray) -> dict[str, float]:
    counts = Counter(int(value) for value in values)
    return {str(value): count / len(values) for value, count in sorted(counts.items())}


def paired_runoffs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Extract first-stage/runoff pairs with the same two finalists."""
    connection.row_factory = sqlite3.Row
    meta = list(connection.execute(
        """SELECT * FROM historical_races
        WHERE office IN ('house','senate','governor')
        AND stage IN ('general','jungle primary','runoff')"""
    ))
    grouped: dict[tuple[Any, ...], list[sqlite3.Row]] = defaultdict(list)
    for row in meta:
        grouped[(row["cycle"], row["office"], row["state"], row["district"], row["special"])].append(row)

    output = []
    for key, races in grouped.items():
        runoff = [row for row in races if row["stage"] == "runoff"]
        first = [row for row in races if row["stage"] in {"general", "jungle primary"}]
        if not runoff or not first:
            continue
        # A location can contain unrelated special and regular races. Candidate
        # overlap, rather than row order, determines the valid pair.
        best = None
        for first_row in first:
            first_votes = {
                row["source_candidate_id"] or stage3.first_last_key(row["candidate_name"] or ""): int(row["votes"])
                for row in connection.execute(
                    "SELECT * FROM historical_results WHERE source_race_id=? AND votes IS NOT NULL",
                    (first_row["source_race_id"],),
                ) if row["votes"] > 0
            }
            for runoff_row in runoff:
                runoff_votes = {
                    row["source_candidate_id"] or stage3.first_last_key(row["candidate_name"] or ""): int(row["votes"])
                    for row in connection.execute(
                        "SELECT * FROM historical_results WHERE source_race_id=? AND votes IS NOT NULL",
                        (runoff_row["source_race_id"],),
                    ) if row["votes"] > 0
                }
                common = sorted(set(first_votes) & set(runoff_votes))
                if len(common) != 2:
                    continue
                score = sum(runoff_votes[candidate] for candidate in common)
                if best is None or score > best[0]:
                    best = (score, first_row, runoff_row, first_votes, runoff_votes, common)
        if best is None:
            continue
        _, first_row, runoff_row, first_votes, runoff_votes, common = best
        left, right = common
        output.append({
            "cycle": key[0], "office": key[1], "state": key[2], "district": key[3],
            "first_race_id": first_row["source_race_id"], "runoff_race_id": runoff_row["source_race_id"],
            "x": math.log(first_votes[left] / first_votes[right]),
            "y": math.log(runoff_votes[left] / runoff_votes[right]),
        })
    return output


def fit_runoff_model(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit runoff finalist log odds from their normalized first-stage log odds.

    Ridge strength is selected by leave-one-pair-out winner Brier score. The
    zero-centered prior lets weak historical persistence shrink toward an
    honest coin flip. Residual variance represents movement between dates.
    """
    if len(pairs) < 3:
        return {"intercept": 0.0, "slope": 1.0, "residual_sd": 0.20, "pairs": len(pairs)}
    x = np.array([row["x"] for row in pairs])
    y = np.array([row["y"] for row in pairs])
    design = np.column_stack((np.ones(len(x)), x))
    target = np.array([0.0, 0.0])
    candidates = (0.1, 1.0, 4.0, 10.0, 40.0, 100.0)
    cv: dict[float, tuple[float, list[tuple[float, int]]]] = {}
    for ridge in candidates:
        predictions = []
        for index in range(len(pairs)):
            keep = np.arange(len(pairs)) != index
            d = design[keep]
            penalty = np.diag([ridge, ridge])
            fitted = np.linalg.solve(d.T @ d + penalty, d.T @ y[keep] + penalty @ target)
            residual = y[keep] - d @ fitted
            sd = max(float(np.sqrt(np.mean(residual**2))), 0.06)
            z = float(np.array([1.0, x[index]]) @ fitted) / sd
            probability = 0.5*(1.0+math.erf(z/math.sqrt(2.0)))
            predictions.append((probability, int(y[index] > 0)))
        cv[ridge] = (float(np.mean([(p-a)**2 for p, a in predictions])), predictions)
    selected_ridge = min(candidates, key=lambda ridge: cv[ridge][0])
    if cv[selected_ridge][0] >= 0.25:
        beta = np.zeros(2)
        residual_sd = max(float(np.sqrt(np.mean(y**2))), 0.06)
        predictions = [(0.5, int(value > 0)) for value in y]
        selected_ridge_output: float | str = "uninformed_fallback"
    else:
        penalty = np.diag([selected_ridge, selected_ridge])
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ y + penalty @ target)
        residual = y - design @ beta
        residual_sd = max(float(np.sqrt(np.mean(residual**2))), 0.06)
        predictions = cv[selected_ridge][1]
        selected_ridge_output = selected_ridge
    accuracy = float(np.mean([(probability >= 0.5) == bool(actual) for probability, actual in predictions]))
    brier = float(np.mean([(probability-actual)**2 for probability, actual in predictions]))
    return {
        "intercept": float(beta[0]), "slope": float(beta[1]), "residual_sd": residual_sd,
        "selected_ridge": selected_ridge_output,
        "ridge_cv_brier": {str(ridge): result[0] for ridge, result in cv.items()},
        "pairs": len(pairs), "leave_one_pair_out_winner_accuracy": accuracy,
        "leave_one_pair_out_brier": brier, "uninformed_brier": 0.25,
    }


def rcv_transfer_evidence(connection: sqlite3.Connection, *, before_cycle: int | None = None) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Estimate group transfer destinations from recorded RCV round deltas."""
    connection.row_factory = sqlite3.Row
    race_ids = [row[0] for row in connection.execute(
        """SELECT r.source_race_id FROM historical_results r
        JOIN historical_races h ON h.source_race_id=r.source_race_id
        WHERE r.result_round IS NOT NULL AND r.result_round NOT IN ('','1')
        AND (? IS NULL OR h.cycle < ?)
        GROUP BY r.source_race_id""", (before_cycle, before_cycle)
    )]
    evidence: dict[str, dict[str, list[float]]] = {
        group: {destination: [] for destination in (*GROUPS, "exhausted")} for group in GROUPS
    }
    used_events = []
    for race_id in race_ids:
        rounds: dict[int, dict[str, tuple[str, float]]] = defaultdict(dict)
        for row in connection.execute(
            """SELECT * FROM historical_results WHERE source_race_id=?
            AND votes IS NOT NULL ORDER BY CAST(result_round AS INTEGER)""", (race_id,)
        ):
            try:
                round_number = int(row["result_round"] or 1)
            except ValueError:
                continue
            candidate = row["source_candidate_id"] or stage3.first_last_key(row["candidate_name"] or "")
            rounds[round_number][candidate] = (stage3.party_group(row["ballot_party"]), float(row["votes"]))
        ordered = sorted(rounds)
        for earlier, later in zip(ordered, ordered[1:]):
            before, after = rounds[earlier], rounds[later]
            eliminated = set(before) - set(after)
            if not eliminated:
                continue
            eliminated_by_group = defaultdict(float)
            for candidate in eliminated:
                eliminated_by_group[before[candidate][0]] += before[candidate][1]
            gains_by_group = defaultdict(float)
            for candidate in set(before) & set(after):
                gain = max(0.0, after[candidate][1] - before[candidate][1])
                gains_by_group[after[candidate][0]] += gain
            outgoing = sum(eliminated_by_group.values())
            gains = sum(gains_by_group.values())
            exhausted = max(0.0, outgoing-gains)
            if outgoing <= 0:
                continue
            # When several candidates disappear in a skipped published round,
            # their group shares apportion the aggregate observed flow.
            for source_group, source_votes in eliminated_by_group.items():
                for destination in GROUPS:
                    evidence[source_group][destination].append(gains_by_group[destination] / outgoing)
                evidence[source_group]["exhausted"].append(exhausted / outgoing)
            used_events.append({"race_id": race_id, "from_round": earlier, "to_round": later})

    profiles: dict[str, dict[str, float]] = {}
    for source_group in GROUPS:
        # Weak affinity prior plus equally weighted elimination events. Raw vote
        # totals are not treated as independent transfer observations.
        prior = {destination: (3.0 if destination == source_group else 1.0) for destination in GROUPS}
        prior["exhausted"] = 1.0
        totals = dict(prior)
        event_count = max((len(values) for values in evidence[source_group].values()), default=0)
        for destination, values in evidence[source_group].items():
            totals[destination] += 8.0 * sum(values)
        normalizer = sum(totals.values())
        profiles[source_group] = {destination: value/normalizer for destination, value in totals.items()}
        profiles[source_group]["concentration"] = normalizer
    return profiles, {"recorded_rcv_races": len(race_ids), "elimination_events": len(used_events), "events": used_events}


def runoff_winners(
    shares: np.ndarray, candidates: list[dict[str, Any]], model: dict[str, Any], rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, Any]]:
    draws = len(shares)
    winners = np.empty(draws, dtype=np.int16)
    runoff = np.zeros(draws, dtype=bool)
    finalists = Counter()
    shocks = rng.normal(0.0, model["residual_sd"], size=draws)
    for draw in range(draws):
        order = np.argsort(-shares[draw], kind="stable")
        if shares[draw, order[0]] > 0.5 or len(candidates) == 1:
            winners[draw] = order[0]
            continue
        runoff[draw] = True
        left, right = int(order[0]), int(order[1])
        finalists[tuple(sorted((left, right)))] += 1
        x = math.log(max(shares[draw, left], 1e-9) / max(shares[draw, right], 1e-9))
        y = model["intercept"] + model["slope"]*x + shocks[draw]
        winners[draw] = left if y >= 0 else right
    return winners, {
        "runoff_probability": float(runoff.mean()),
        "finalist_pair_probabilities": {
            "|".join(candidates[index]["ballot_entry_id"] for index in pair): count/draws
            for pair, count in sorted(finalists.items())
        },
    }


def rcv_winners(
    shares: np.ndarray, candidates: list[dict[str, Any]], profiles: dict[str, dict[str, float]],
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, Any]]:
    draws, candidate_count = shares.shape
    if candidate_count <= 2:
        return np.argmax(shares, axis=1).astype(np.int16), {
            "reached_elimination_round_probability": 0.0,
            "maximum_candidates": candidate_count,
        }
    groups = [stage3.party_group(candidate["party"]) for candidate in candidates]
    destinations = (*GROUPS, "exhausted")
    sampled_profiles = {}
    for source_group in GROUPS:
        profile = profiles[source_group]
        alpha = np.array([profile[destination]*profile["concentration"] for destination in destinations])
        sampled_profiles[source_group] = rng.dirichlet(alpha, size=draws)
    winners = np.empty(draws, dtype=np.int16)
    used_elimination = np.zeros(draws, dtype=bool)
    exhausted_final = np.zeros(draws)
    for draw in range(draws):
        votes = shares[draw].copy()
        active = np.ones(candidate_count, dtype=bool)
        exhausted = 0.0
        while active.sum() > 1:
            continuing = votes[active].sum()
            active_indexes = np.flatnonzero(active)
            leader = int(active_indexes[np.argmax(votes[active_indexes])])
            if continuing > 0 and votes[leader] > continuing/2:
                winners[draw] = leader
                break
            used_elimination[draw] = True
            # Stable ballot order supplies a reproducible exact-tie convention.
            eliminated = int(active_indexes[np.argmin(votes[active_indexes])])
            mass = votes[eliminated]
            active[eliminated] = False
            recipients = np.flatnonzero(active)
            profile = sampled_profiles[groups[eliminated]][draw]
            weights = np.zeros(len(recipients)+1)
            for position, recipient in enumerate(recipients):
                same_group = [index for index in recipients if groups[index] == groups[recipient]]
                denominator = sum(votes[index]+0.01 for index in same_group)
                weights[position] = profile[GROUPS.index(groups[recipient])] * (votes[recipient]+0.01)/denominator
            weights[-1] = profile[-1]
            weights /= weights.sum()
            votes[recipients] += mass*weights[:-1]
            exhausted += mass*weights[-1]
        else:
            winners[draw] = int(np.flatnonzero(active)[0])
        exhausted_final[draw] = exhausted
    return winners, {
        "reached_elimination_round_probability": float(used_elimination.mean()),
        "mean_exhausted_share": float(exhausted_final.mean()),
        "maximum_candidates": candidate_count,
    }


def vermont_winners(shares: np.ndarray, candidates: list[dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    leaders = np.argmax(shares, axis=1).astype(np.int16)
    has_majority = np.max(shares, axis=1) > 0.5
    scenarios: dict[str, list[float]] = {"plurality_winner_convention": []}
    groups = [stage3.party_group(candidate["party"]) for candidate in candidates]
    for preferred in GROUPS:
        scenario = leaders.copy()
        for draw in np.flatnonzero(~has_majority):
            top_three = np.argsort(-shares[draw], kind="stable")[:3]
            options = [index for index in top_three if groups[index] == preferred]
            if options:
                scenario[draw] = max(options, key=lambda index: shares[draw, index])
        scenarios[f"assembly_prefers_{preferred}"] = [float(np.mean(scenario == index)) for index in range(len(candidates))]
    scenarios["plurality_winner_convention"] = [float(np.mean(leaders == index)) for index in range(len(candidates))]
    return leaders, {
        "joint_assembly_probability": float(np.mean(~has_majority)),
        "conditional_candidate_probabilities": scenarios,
        "default": "plurality_winner_convention",
    }


def senate_contender_screen(
    item: dict[str, Any], questions: list[Any], quality_weights: dict[str, float] | None,
    *, support_floor_pct: float = 5.0,
) -> dict[str, Any]:
    """Screen other-party Senate contenders using distinct usable polls.

    Presence alone is insufficient: a candidate with 2% in most surveys
    should not inherit a large equal-share allocation of the other-party
    structural prior. The 5% support floor was selected from 5/10/15%
    sensitivity cases on 2022 and checked on 2024. Screening applies only
    with at least three independent polls naming two current candidates.
    """
    candidates = item["candidates"]
    keys = {candidate["ballot_entry_id"] for candidate in candidates}
    by_poll: dict[str, dict[str, float]] = defaultdict(dict)
    for question in questions:
        if (quality_weights or {}).get(question.poll_id, 1.0) <= 0:
            continue
        mapped = [option for option in question.options
                  if option.candidate_key in keys and option.pct > 0]
        if len(mapped) < 2:
            continue
        for option in mapped:
            previous = by_poll[question.poll_id].get(option.candidate_key, 0.0)
            by_poll[question.poll_id][option.candidate_key] = max(previous, option.pct)
    count = len(by_poll)
    supported = {
        key: sum(share.get(key, 0.0) >= support_floor_pct for share in by_poll.values())
        for key in keys
    }
    poll_mean_pct = {
        key: sum(share.get(key, 0.0) for share in by_poll.values())/count if count else 0.0
        for key in keys
    }
    candidate_keys = [candidate["ballot_entry_id"] for candidate in candidates]
    if item["race"]["office"] != "senate" or item["race"]["counting_rule"] != "plurality" or count < 3:
        return {"applied": False, "usable_poll_count": count,
                "retained_indices": list(range(len(candidates))), "candidate_keys": candidate_keys,
                "poll_mean_pct": poll_mean_pct, "excluded_candidates": []}
    retained = [
        index for index, candidate in enumerate(candidates)
        if stage3.party_group(candidate["party"]) in {"D", "R"}
        or 2*supported[candidate["ballot_entry_id"]] > count
    ]
    if len(retained) < 2:
        retained = list(range(len(candidates)))
    return {
        "applied": len(retained) < len(candidates),
        "usable_poll_count": count,
        "support_floor_pct": support_floor_pct,
        "retained_indices": retained,
        "candidate_keys": candidate_keys,
        "poll_mean_pct": poll_mean_pct,
        "supporting_polls": supported,
        "excluded_candidates": [candidates[i]["ballot_entry_id"] for i in range(len(candidates))
                                if i not in retained],
    }


def first_stage_draws(
    connection: sqlite3.Connection, stage1_path: Path, draws: int, seed: int,
    posterior_inflation: float, current_poll_half_life_days: float,
    cutoff: datetime, *, quality_weights: dict[str, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray], dict[str, Any], Any, dict[str, Any]]:
    historical = stage3.load_historical_races(connection)
    transitions = stage3.build_transitions(historical)
    current = stage3.load_current_races(connection)
    models = stage3.fit_office_models(transitions)
    allocation = stage3.fit_candidate_allocation(historical)
    decomposition = stage3.decompose_covariance(transitions, models)
    structural_fit = stage4.structural.fit(transitions, models, stage3)
    stage3_draws = stage4.current_prior_draws(
        current, models, allocation, decomposition, draws, seed, structural_fit,
    )
    national_draws, national = stage4.fit_national_signal_update(
        connection, stage1_path, historical, current, stage3_draws, cutoff,
        nowcast=True, quality_weights=quality_weights,
        include_governor_local_lean=True,
        governor_uncertainty_seed=seed,
    )
    feature_effects = fundamentals_features.fit_effects(transitions, models, historical)
    feature_shifts, feature_metadata = fundamentals_features.current_shifts(
        current, historical, feature_effects,
    )
    questions = stage4.load_current_questions(connection, stage1_path)
    historical_questions = stage4.load_historical_questions(connection)
    bias_model = stage4.fit_bias_model(historical_questions, {race.source_race_id: race for race in historical})
    bias_model.half_life_days = current_poll_half_life_days
    minor_share_fit = json.loads(MINOR_SHARE_FIT.read_text(encoding="utf-8"))
    by_race: dict[str, list[Any]] = defaultdict(list)
    for question in questions:
        if question.available_date <= cutoff and question.end_date <= cutoff:
            by_race[question.race_key].append(question)
    output = {}
    diagnostics = {}
    steps = ("baseline", "district_map", "governor_approval", "open_seat_candidate_experience")
    ablation_counts = {
        step: {office: {group: np.zeros(draws, dtype=np.int16) for group in stage3.GROUPS}
               for office in stage3.OFFICES}
        for step in steps
    }
    race_impacts = []
    for item in current:
        race_id = item["race"]["race_id"]
        keys = [candidate["ballot_entry_id"] for candidate in item["candidates"]]
        groups = [stage3.party_group(candidate["party"]) for candidate in item["candidates"]]
        rows, values, variances, diag = stage4.poll_contrasts(
            by_race.get(race_id, []), keys, groups, bias_model, cutoff,
            quality_weights=quality_weights,
            apply_election_day_bias=False,
        )
        contender_screen = senate_contender_screen(
            item, by_race.get(race_id, []), quality_weights,
        )
        diag["contender_screen"] = {key: value for key, value in contender_screen.items()
                                    if key != "retained_indices"}
        ballot_groups = set(groups)
        ballot_class = stage4.structural.ballot_class(ballot_groups, float(item["prior_shares"][2]))
        diag["structural_prior_class"] = ballot_class
        prior = national_draws[race_id]
        if ballot_class != "ordinary" and rows:
            final_prior = prior
            for step in steps:
                delta = feature_shifts[race_id].get(step, 0.0)
                if abs(delta) > 1e-12:
                    final_prior = fundamentals_features.shift_candidate_shares(
                        final_prior, item["candidates"], delta,
                    )
            conflict_fit = stage4.fit_prior_covariance_scale(
                final_prior, rows, values, variances,
            )
        else:
            conflict_fit = {"scale": 1.0, "log_marginal_likelihood_gain": 0.0,
                            "upper_search_bound_reached": False}
        diag["prior_conflict_fit"] = {
            key: round(value, 4) if isinstance(value, float) else value
            for key, value in conflict_fit.items()
        }
        prior_scale = float(conflict_fit["scale"])
        previous = None
        summaries = {}
        for step in steps:
            delta = feature_shifts[race_id].get(step, 0.0)
            if abs(delta) > 1e-12:
                prior = fundamentals_features.shift_candidate_shares(prior, item["candidates"], delta)
            if step == steps[-1] and rows and prior.shape[1] >= 2:
                z = stage4.alr_candidate(prior)
                covariance = (stage4.LedoitWolf().fit(z).covariance_
                              + np.eye(z.shape[1])*1e-8)*prior_scale
                h = np.vstack(rows)
                projected = h @ covariance @ h.T
                observation = np.diag(np.maximum(variances, 1e-6))
                leverage = np.diag(projected @ np.linalg.solve(projected+observation,
                                                                np.eye(len(rows))))
                diag["poll_contrast_leverage"] = [round(float(value), 4) for value in leverage]
            if previous is None or abs(delta) > 1e-12:
                updated = stage4.affine_update_draws(
                    prior, rows, values, variances, posterior_inflation, prior_scale,
                )
                posterior = stage4.preserve_unpolled_candidate_mass(
                    prior, updated, keys, diag["polled_candidate_keys"],
                )
            else:
                posterior = previous
            posterior = senate_minor_share.apply(posterior, contender_screen, minor_share_fit)
            previous = posterior
            leaders = np.argmax(posterior, axis=1)
            for index, group in enumerate(groups):
                ablation_counts[step][item["race"]["office"]][group] += leaders == index
            d_indices = [i for i,g in enumerate(groups) if g == "D"]
            r_indices = [i for i,g in enumerate(groups) if g == "R"]
            d_share = posterior[:, d_indices].sum(axis=1)
            r_share = posterior[:, r_indices].sum(axis=1)
            summaries[step] = {
                "mean_D_minus_R_share_points": round(float(np.mean(d_share-r_share))*100, 3),
                "D_first_stage_leader_probability": round(float(np.mean(np.isin(leaders, d_indices))), 5),
            }
        output[race_id] = posterior
        race_impacts.append({"race_id":race_id,"office":item["race"]["office"],
                             "state":item["race"]["state"],"feature_log_odds_shifts":feature_shifts[race_id],
                             "steps":summaries})
        diagnostics[race_id] = diag
    ablation = {"steps":list(steps),"counts":ablation_counts,"races":race_impacts,
                "effects":feature_effects,"input_metadata":feature_metadata,
                "governor_local_lean": national.get("governor_local_lean", {}),
                "structural_prior_fit":structural_fit,
                "interpretation":"Paired draws, same race polls; first-stage leaders before runoff or ranked-choice counting. Baseline includes the fitted governor local-lean model; its separate pre-poll before/after impact is recorded under governor_local_lean."}
    return current, output, national, diagnostics, ablation


def summarize_control(counts: dict[str, np.ndarray], threshold: int) -> dict[str, Any]:
    d, r = counts["D"], counts["R"]
    return {
        "D_control_probability": float(np.mean(d >= threshold)),
        "R_control_probability": float(np.mean(r >= threshold)),
        "neither_probability": float(np.mean((d < threshold) & (r < threshold))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--stage1-database", type=Path, default=Path("data/processed/stage1.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/nowcast"))
    parser.add_argument("--draws", type=int, default=75000)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--ratings", type=Path, default=Path("data/reference/pollster_ratings/ratings.csv"))
    parser.add_argument("--silver-ratings", type=Path, default=Path("data/reference/pollster_ratings/silver_2026.csv"))
    parser.add_argument("--current-poll-half-life-days", type=float, default=stage4.CURRENT_POLL_HALF_LIFE_DAYS)
    parser.add_argument("--information-cutoff-utc", type=str,
                        help="Retrospective UTC cutoff, YYYY-MM-DDTHH:MM:SSZ; must precede the source snapshot")
    args = parser.parse_args()
    if args.draws < 1000:
        raise ValueError("At least 1,000 simulation draws are required")
    if args.current_poll_half_life_days <= 0:
        raise ValueError("Current poll half-life must be positive")
    posterior_inflation = 1.0
    current_poll_half_life_days = args.current_poll_half_life_days
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        build_metadata = dict(connection.execute("SELECT key,value FROM build_metadata"))
        snapshot_id = build_metadata["source_snapshot_id"]
        quality_weights, quality_report = pollster_quality.load_weights(
            args.stage1_database, args.ratings, args.silver_ratings,
            snapshot_id=snapshot_id,
        )
        stage1_connection = sqlite3.connect(args.stage1_database)
        try:
            source_row = stage1_connection.execute(
                "SELECT retrieved_at_utc FROM source_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
        finally:
            stage1_connection.close()
        if source_row is None:
            raise ValueError(f"Missing Stage 1 source snapshot {snapshot_id}")
        source_cutoff = datetime.strptime(source_row[0], "%Y%m%dT%H%M%SZ")
        cutoff = (datetime.strptime(args.information_cutoff_utc, "%Y-%m-%dT%H:%M:%SZ")
                  if args.information_cutoff_utc else source_cutoff)
        if cutoff > source_cutoff:
            raise ValueError("Retrospective cutoff cannot be later than the source snapshot")
        cutoff_text = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        current, shares_by_race, national, poll_diagnostics, ablation = first_stage_draws(
            connection, args.stage1_database, args.draws, args.seed,
            posterior_inflation, current_poll_half_life_days, cutoff,
            quality_weights=quality_weights,
        )
        runoff_pairs = paired_runoffs(connection)
        runoff_model = fit_runoff_model(runoff_pairs)
        transfer_profiles, transfer_meta = rcv_transfer_evidence(connection)
    finally:
        connection.close()

    rng = np.random.default_rng(args.seed+5)
    winner_by_race: dict[str, np.ndarray] = {}
    rule_details: dict[str, dict[str, Any]] = {}
    race_output = []
    seat_counts = {
        office: {group: np.zeros(args.draws, dtype=np.int16) for group in GROUPS}
        for office in stage3.OFFICES
    }
    for item in current:
        race = item["race"]
        race_id = race["race_id"]
        candidates = [dict(candidate) for candidate in item["candidates"]]
        # The source aggregation abbreviated the challenger. Preserve its stable
        # person/ballot IDs while exposing the verified distinct full name.
        for candidate in candidates:
            if candidate["candidate_id"] == "PERSON-AK-DAN-J-SULLIVAN":
                candidate["source_name"] = candidate["name"]
                candidate["name"] = "Daniel J. Sullivan Jr."
        shares = shares_by_race[race_id]
        rule = race["counting_rule"]
        if rule == "plurality" or len(candidates) == 1:
            winners = np.argmax(shares, axis=1).astype(np.int16)
            details = {"module": "plurality", "tie_rule": "stable ballot-entry order"}
        elif rule == "majority_then_top_two_runoff":
            winners, details = runoff_winners(shares, candidates, runoff_model, rng)
            details["module"] = "majority_then_top_two_runoff"
        elif rule == "ranked_choice":
            winners, details = rcv_winners(shares, candidates, transfer_profiles, rng)
            details["module"] = "instant_runoff_ranked_choice"
        elif rule == "majority_then_legislative_selection":
            winners, details = vermont_winners(shares, candidates)
            details["module"] = "vermont_joint_assembly"
        else:
            raise ValueError(f"Unsupported counting rule {rule!r} for {race_id}")
        winner_by_race[race_id] = winners
        rule_details[race_id] = details
        groups = [stage3.party_group(candidate["party"]) for candidate in candidates]
        candidate_output = []
        for index, candidate in enumerate(candidates):
            win_probability = float(np.mean(winners == index))
            candidate_output.append({
                **candidate, "party_group": groups[index],
                "first_stage_share": stage3.quantile_summary(shares[:, index]),
                "first_stage_leader_probability": float(np.mean(np.argmax(shares, axis=1) == index)),
                "eventual_win_probability": win_probability,
                "monte_carlo_standard_error": math.sqrt(win_probability*(1-win_probability)/args.draws),
            })
        for index, group in enumerate(groups):
            seat_counts[race["office"]][group] += winners == index
        race_output.append({
            "race_id": race_id, "office": race["office"], "state": race["state"],
            "district_code": race["district_code"], "counting_rule": rule,
            "ballot_status": race["ballot_status"], "rule_diagnostics": details,
            "poll_diagnostics": poll_diagnostics[race_id], "candidates": candidate_output,
        })

    joint = {}
    for office, counts in seat_counts.items():
        tuples = Counter(
            f"{int(counts['D'][draw])}-{int(counts['R'][draw])}-{int(counts['O'][draw])}"
            for draw in range(args.draws)
        )
        joint[office] = {
            "seat_universe": int(sum(counts[group][0] for group in GROUPS)),
            "marginal_distributions": {group: distribution(values) for group, values in counts.items()},
            "joint_D_R_O_distribution": {key: value/args.draws for key, value in sorted(tuples.items())},
        }
    joint["house"]["control"] = summarize_control(seat_counts["house"], 218)

    # 65 seats are not on the 2026 ballot: 34 Democratic-caucus and 31
    # Republican-caucus. A Republican vice president breaks a 50-50 tie.
    senate_elected = seat_counts["senate"]
    caucus_scenarios = {}
    for scenario, other_to_d, other_to_r in (
        ("other_winners_unaligned", 0, 0),
        ("all_other_winners_caucus_D", 1, 0),
        ("all_other_winners_caucus_R", 0, 1),
    ):
        d = 34 + senate_elected["D"] + other_to_d*senate_elected["O"]
        r = 31 + senate_elected["R"] + other_to_r*senate_elected["O"]
        # With the stated Republican VP assumption, R organizes a 50-50 Senate.
        caucus_scenarios[scenario] = {
            "D_caucus_distribution": distribution(d), "R_caucus_distribution": distribution(r),
            "D_control_probability": float(np.mean(d >= 51)),
            "R_control_probability": float(np.mean(r >= 50)),
            "unresolved_probability": float(np.mean((d < 51) & (r < 50))),
        }
    joint["senate"]["full_chamber"] = {
        "not_up_baseline": {"D_caucus": 34, "R_caucus": 31},
        "vice_president_assumption": "Republican JD Vance breaks a 50-50 organizing tie",
        "caucus_scenarios": caucus_scenarios,
        "overall_control_probability": None,
        "reason_overall_omitted": "No evidence-based weights have been assigned to unsettled independent-winner caucus scenarios.",
    }
    house_d_seats = seat_counts["house"]["D"]
    senate_d_seats = seat_counts["senate"]["D"]
    house_d_control = house_d_seats >= 218
    joint["cross_chamber"] = {
        "house_D_senate_D_elected_seat_correlation": float(np.corrcoef(house_d_seats, senate_d_seats)[0, 1]),
        "house_D_control_senate_D_control_by_caucus_scenario": {
            scenario: float(np.mean(house_d_control & (
                34 + senate_d_seats + other_to_d*senate_elected["O"] >= 51
            )))
            for scenario, other_to_d in (
                ("other_winners_unaligned", 0),
                ("all_other_winners_caucus_D", 1),
                ("all_other_winners_caucus_R", 0),
            )
        },
    }

    ablation_summary = []
    for step in ablation["steps"]:
        counts = ablation["counts"][step]
        house_d = counts["house"]["D"]
        senate_d = counts["senate"]["D"]
        senate_o = counts["senate"]["O"]
        ablation_summary.append({
            "step":step,
            "house_D_expected_seats":round(float(np.mean(house_d)),3),
            "house_D_218_probability_first_stage":round(float(np.mean(house_d>=218)),5),
            "senate_D_expected_elected_seats":round(float(np.mean(senate_d)),3),
            "senate_D_51_caucus_probability_all_O_to_D_first_stage":round(float(np.mean(34+senate_d+senate_o>=51)),5),
            "governor_D_expected_wins":round(float(np.mean(counts["governor"]["D"])),3),
        })

    metadata = {
        "model_version": MODEL_VERSION, "stage": 5,
        "estimand": "office winner if voting occurred at information cutoff, after jurisdiction-specific counting",
        "information_cutoff_utc": cutoff_text, "random_seed": args.seed,
        "simulation_draws": args.draws, "data_sha256": sha256(args.database),
        "stage1_data_sha256": sha256(args.stage1_database), "model_code_sha256": sha256(Path(__file__)),
        "stage3_model_code_sha256": sha256(ROOT / "modeling/stage3_results_baseline.py"),
        "house_population_crosswalk_sha256": sha256(ROOT / "data/reference/stage6_house_population_crosswalk.json"),
        "house_official_resolutions_sha256": sha256(ROOT / "data/reference/stage6_house_2024_official_resolutions.json"),
        "stage4_model_code_sha256": sha256(STAGE4_PATH),
        "senate_minor_share_code_sha256": sha256(ROOT / "modeling/senate_minor_share.py"),
        "senate_minor_share_fit_sha256": sha256(MINOR_SHARE_FIT),
        "structural_model_code_sha256": sha256(stage4.STRUCTURAL_PATH),
        "national_model_code_sha256": sha256(stage4.NATIONAL_PATH),
        "generic_error_calibration_sha256": sha256(stage4.NATIONAL_ERROR),
        "national_source_manifest_sha256": sha256(stage4.national_env.REFERENCE / "source_manifest.json"),
        "pollster_quality_code_sha256": sha256(ROOT / "modeling/pollster_quality.py"),
        "fundamentals_features_code_sha256": sha256(ROOT / "modeling/fundamentals_features_2026.py"),
        "governor_local_lean_code_sha256": sha256(ROOT / "modeling/governor_local_lean.py"),
        "pollster_ratings_sha256": sha256(args.ratings),
        "silver_ratings_sha256": sha256(args.silver_ratings),
        "input_snapshot_ids": {
            "live_source_snapshot": build_metadata["source_snapshot_id"],
            "historical_snapshot": build_metadata["historical_snapshot"],
        },
    }
    if args.information_cutoff_utc:
        metadata["reconstruction"] = {
            "kind": "retrospective_poll_cutoff",
            "source_snapshot_retrieved_at_utc": source_cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limitation": "Uses a later saved poll feed and the currently reviewed candidate and map inputs; not a forecast recorded at the cutoff.",
        }
    parameters = {
        "metadata": metadata,
        "runoff_model": {**runoff_model, "training_pairs": runoff_pairs},
        "ranked_choice_model": {
            "transfer_profiles": transfer_profiles, "evidence": transfer_meta,
            "uncertainty": "Dirichlet transfer profile sampled per draw; historical elimination events receive equal weight.",
        },
        "vermont_joint_assembly": {
            "default": "plurality-winner convention",
            "sensitivity": "conditional D-, R-, and O-preferring assembly scenarios are stored on the race",
        },
        "senate_accounting": {
            "current_chamber": {"R": 53, "D": 45, "I_caucusing_D": 2},
            "seats_in_2026_universe": {"R_caucus": 22, "D_caucus": 13},
            "not_up_baseline": {"R_caucus": 31, "D_caucus": 34},
        },
        "national_signal_update": national,
        "additional_fundamentals": {"fit":ablation["effects"],"sources":ablation["input_metadata"]},
        "structural_prior": ablation["structural_prior_fit"],
        "pollster_quality": quality_report,
        "nowcast_limitations": "Provisional: race poll variance and structural prior covariance have not been refitted to terminal current-support error; generic-ballot uncertainty uses three recent seven-day terminal-proxy cycles. The 5% approval blend weight is a stated policy choice rather than a backtested optimum; its uncertainty uses a worst-case positive-correlation bound. Economic sentiment is not an input.",
        "current_poll_half_life_days": current_poll_half_life_days,
        "identity_assertion": {
            "race_id": "S-2026-AK-II-regular",
            "people": [
                {"candidate_id": "PERSON-AK-DAN-S-SULLIVAN", "name": "Dan S. Sullivan"},
                {"candidate_id": "PERSON-AK-DAN-J-SULLIVAN", "name": "Daniel J. Sullivan Jr."},
            ],
            "distinct": True,
        },
    }
    forecast = {
        "metadata": metadata, "publication_status": "internal_provisional_nowcast_not_for_publication",
        "race_count": len(race_output), "races": race_output, "joint_summaries": joint,
    }
    senate_caucus_seats = 34 + senate_elected["D"] + senate_elected["O"]
    senate_races = [race for race in race_output if race["office"] == "senate"]

    def senate_extreme(draw_index: int) -> dict[str, Any]:
        winners = {}
        for race in senate_races:
            winner = race["candidates"][int(winner_by_race[race["race_id"]][draw_index])]
            winners[race["state"]] = {
                "race_id": race["race_id"],
                "candidate_id": winner["candidate_id"],
                "name": winner["name"],
                "party": winner["party"],
                "party_group": winner["party_group"],
            }
        d_seats = int(senate_caucus_seats[draw_index])
        return {"draw_index": draw_index, "D_and_independent_seats": d_seats,
                "R_seats": 100 - d_seats, "winners": winners}

    senate_extremes = {
        "information_cutoff_utc": cutoff_text,
        "random_seed": args.seed,
        "simulation_draws": args.draws,
        "selection_rule": "First joint draw attaining the most or fewest D-plus-independent caucus seats; all other winners caucus with D",
        "best_democratic": senate_extreme(int(np.argmax(senate_caucus_seats))),
        "best_republican": senate_extreme(int(np.argmin(senate_caucus_seats))),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ablation_output = {"metadata":metadata,"interpretation":ablation["interpretation"],
                       "summary":ablation_summary,"race_impacts":ablation["races"],
                       "governor_local_lean":ablation["governor_local_lean"],
                       "training":ablation["effects"],"input_metadata":ablation["input_metadata"]}
    (args.output_dir / "model_parameters.json").write_text(json.dumps(parameters, indent=2)+"\n", encoding="utf-8")
    (args.output_dir / "forecast_2026.json").write_text(json.dumps(forecast, indent=2)+"\n", encoding="utf-8")
    (args.output_dir / "senate_extremes_2026.json").write_text(
        json.dumps(senate_extremes, indent=2)+"\n", encoding="utf-8")
    (args.output_dir / "fundamentals_impact_2026.json").write_text(json.dumps(ablation_output, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({
        "status": "complete", "metadata": metadata,
        "runoff_training_pairs": len(runoff_pairs), "rcv_elimination_events": transfer_meta["elimination_events"],
        "house_control": joint["house"]["control"],
        "senate_control_scenarios": caucus_scenarios,
        "fundamentals_impact":ablation_summary,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
