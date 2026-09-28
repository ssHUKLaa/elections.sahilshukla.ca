"""Fit, backtest, and simulate the Stage 3 results-only candidate-share baseline.

The model operates on three ballot-party groups (Democratic, Republican, other)
with additive log-ratio transitions. It then allocates each group to the named
candidate vector. All fitted uncertainty components come from historical
transition residuals; polls are not read by this stage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.covariance import LedoitWolf


GROUPS = ("D", "R", "O")
GROUP_INDEX = {group: index for index, group in enumerate(GROUPS)}
D_PARTIES = {"D", "DEM", "DFL", "N(D)/D", "WF", "WFP", "WORKING_FAMILIES", "WEP"}
R_PARTIES = {"R", "REP", "R*", "CRV", "CONSERVATIVE"}
EXCLUDED_NAMES = ("blank", "under vote", "undervote", "over vote", "overvote", "void",
                  "continuing ballot", "exhausted ballot")
OFFICES = ("house", "senate", "governor")
MODEL_VERSION = "stage3-results-2.0"


@lru_cache(maxsize=1)
def house_population_crosswalk() -> tuple[dict[tuple[int, str, str], dict[str, Any]], dict[str, str]]:
    root = Path(__file__).resolve().parents[1]
    report = json.loads((root / "data/reference/stage6_house_population_crosswalk.json").read_text(encoding="utf-8"))
    crosswalk = {(int(name.split("_to_")[1]), row["state_fips"], row["target_district"]): row
                 for name, rows in report["transitions"].items() for row in rows}
    registry = json.loads((root / "data/reference/races_2026.json").read_text(encoding="utf-8"))
    source = root / registry["sources"]["census_cd120"]["path"]
    with zipfile.ZipFile(source) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            rows = csv.DictReader((line.decode("utf-8-sig") for line in stream), delimiter="|")
            state_codes = {row["USPS"]: row["GEOID"][:2] for row in rows}
    return crosswalk, state_codes
PREDICTIVE_SCALE_GRID = (0.20, 0.30, 0.40, 0.50, 0.65, 0.80, 1.00, 1.25, 1.50, 2.00, 3.00)
DR_SCALE_GRID = (0.30, 0.50, 0.65, 0.80, 1.00, 1.25)
OTHER_SCALE_GRID = (1.00, 1.50, 2.00, 3.00)


@dataclass(frozen=True)
class HistoricalCandidate:
    candidate_key: str
    name: str
    party: str
    group: str
    votes: int
    incumbent: bool
    winner: bool


@dataclass(frozen=True)
class HistoricalRace:
    source_race_id: str
    cycle: int
    office: str
    state: str
    district: str
    candidates: tuple[HistoricalCandidate, ...]

    @property
    def location(self) -> tuple[str, str, str]:
        district = self.district if self.office == "house" else self.office
        return self.office, self.state, district


@dataclass(frozen=True)
class Transition:
    office: str
    state: str
    target_cycle: int
    prior_cycle: int
    target: HistoricalRace
    prior: HistoricalRace
    prior_alr: np.ndarray
    target_alr: np.ndarray
    prior_selection: str = "same_district_label"
    prior_population_coverage: float = 1.0


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_timestamp(value: str) -> str:
    """Convert a YYYYMMDDTHHMMSSZ snapshot token to an ISO UTC timestamp."""
    match = re.search(r"(\d{8}T\d{6}Z)", value)
    if not match:
        raise ValueError(f"No UTC snapshot timestamp in {value!r}")
    token = match.group(1)
    return f"{token[0:4]}-{token[4:6]}-{token[6:8]}T{token[9:11]}:{token[11:13]}:{token[13:15]}Z"


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).lower().strip()
    tokens = [token for token in value.split() if token not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(tokens)


def first_last_key(value: str) -> str:
    tokens = normalize_name(value).split()
    return " ".join((tokens[0], tokens[-1])) if len(tokens) >= 2 else " ".join(tokens)


def official_name_key(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    party_words = {
        "republican", "democrat", "democratic", "libertarian", "independent",
        "green", "constitution", "conservative", "working families",
    }
    if len(parts) >= 2 and normalize_name(parts[-1]) in party_words:
        parts = parts[:-1]
    if len(parts) == 2:
        value = f"{parts[1]} {parts[0]}"
    elif parts:
        value = " ".join(parts)
    return first_last_key(value)


def party_group(party: str | None) -> str:
    value = (party or "").strip().upper()
    tokens = {token for token in re.split(r"[^A-Z]+", value) if token}
    if value in D_PARTIES or tokens & {"D", "DEM", "DFL"}:
        return "D"
    if value in R_PARTIES or tokens & {"R", "REP"}:
        return "R"
    return "O"


def is_excluded_name(name: str) -> bool:
    return normalize_name(name).startswith(EXCLUDED_NAMES)


def group_shares(race: HistoricalRace) -> np.ndarray:
    votes = np.zeros(3, dtype=float)
    for candidate in race.candidates:
        votes[GROUP_INDEX[candidate.group]] += candidate.votes
    # Jeffreys smoothing makes the log-ratio defined without materially moving large races.
    votes += 0.5
    return votes / votes.sum()


def alr(shares: np.ndarray) -> np.ndarray:
    """Return interpretable log odds for major-party split and major-party mass.

    The first coordinate is log(D/R).  The second is log((D+R)/O).  Keeping
    these processes separate prevents a near-zero other-party result from
    contaminating the Democratic-versus-Republican transition while retaining
    a proper three-part composition.
    """
    return np.array([
        math.log(shares[0] / shares[1]),
        math.log((shares[0] + shares[1]) / shares[2]),
    ])


def inv_alr(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values)
    d_within_major = 1.0 / (1.0 + np.exp(-np.clip(values[..., 0], -40, 40)))
    major = 1.0 / (1.0 + np.exp(-np.clip(values[..., 1], -40, 40)))
    return np.stack((major*d_within_major, major*(1.0-d_within_major), 1.0-major), axis=-1)


def current_states(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT DISTINCT state FROM races")}


def incumbent_lookup(connection: sqlite3.Connection) -> set[tuple[int, str, str, str, str]]:
    found: set[tuple[int, str, str, str, str]] = set()
    for cycle, office, state, district, name in connection.execute(
        """SELECT cycle,office,state,district,candidate_name FROM fec_candidate_results
        WHERE incumbent=1"""
    ):
        found.add((cycle, office, state, district, official_name_key(name)))
    return found


def load_historical_races(connection: sqlite3.Connection) -> list[HistoricalRace]:
    states = current_states(connection)
    incumbents = incumbent_lookup(connection)
    reconciled = {
        (row[0], row[1], row[2], row[3])
        for row in connection.execute(
            """SELECT cycle,office,state,district FROM result_reconciliation
            WHERE status IN ('exact','within_tolerance','regular_special_split_verified')"""
        )
    }
    resolved = {
        (row[0], row[1], row[2], row[3])
        for row in connection.execute(
            "SELECT DISTINCT cycle,office,state,district FROM historical_result_resolutions"
        )
    }
    reconciled |= resolved
    race_meta = {
        row[0]: row
        for row in connection.execute(
            """SELECT source_race_id,cycle,office,state,district,incumbent_party
            FROM historical_races WHERE stage IN ('general','jungle primary') AND special=0"""
        )
    }
    all_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
    share_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
    connection.row_factory = sqlite3.Row
    for row in connection.execute(
        """SELECT * FROM historical_results WHERE stage IN ('general','jungle primary') AND special=0
        AND votes IS NOT NULL
        ORDER BY source_race_id,result_round,source_candidate_id,candidate_name"""
    ):
        if row["state"] not in states or row["source_race_id"] not in race_meta:
            continue
        all_rows[row["source_race_id"]].append(row)
        if row["result_round"] in (None, "", "1"):
            if not is_excluded_name(row["candidate_name"] or ""):
                share_rows[row["source_race_id"]].append(row)

    official_replacements: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in connection.execute(
        "SELECT * FROM historical_result_resolutions ORDER BY source_race_id,source_candidate_id"
    ):
        official_replacements[row["source_race_id"]].append({
            "candidate_name": row["candidate_name"],
            "source_candidate_id": row["source_candidate_id"],
            "ballot_party": row["ballot_party"], "votes": row["votes"],
            "winner": row["winner"],
        })
    for source_race_id, rows in official_replacements.items():
        if source_race_id not in race_meta:
            raise ValueError(f"Official result resolution missing historical race {source_race_id}")
        all_rows[source_race_id] = rows
        share_rows[source_race_id] = rows

    races: list[HistoricalRace] = []
    for source_race_id, rows in share_rows.items():
        meta = race_meta[source_race_id]
        _, cycle, office, state, district, incumbent_party = meta
        if cycle is None or cycle < 2002 or office not in OFFICES:
            continue
        if office in {"house", "senate"}:
            official_district = ("00" if office == "house" and
                                 (state in {"AK", "DE", "ND", "SD", "VT", "WY"}
                                  or (state == "MT" and cycle <= 2020)) else district)
            if cycle % 2 or (cycle, office, state, official_district) not in reconciled:
                continue
        winner_keys = {
            first_last_key(row["candidate_name"] or "")
            for row in all_rows[source_race_id] if row["winner"]
        }
        combined: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = row["candidate_name"] or "Unnamed"
            source_key = row["source_candidate_id"] or first_last_key(name)
            item = combined.setdefault(
                source_key,
                {"name": name, "party": row["ballot_party"] or "", "votes": 0, "winner": False},
            )
            # Fusion-voting states can report one person on several party
            # lines under the same source candidate ID.  Sum those lines, but
            # retain a Democratic or Republican nomination when one exists;
            # row order must not turn a major-party winner into an "other"
            # winner through their Independence/Conservative ballot line.
            row_party = row["ballot_party"] or ""
            if party_group(item["party"]) == "O" and party_group(row_party) in {"D", "R"}:
                item["party"] = row_party
            item["votes"] += int(row["votes"])
            item["winner"] = item["winner"] or first_last_key(name) in winner_keys
        candidates: list[HistoricalCandidate] = []
        for source_key, item in combined.items():
            key = first_last_key(item["name"])
            historical_district = district if office == "house" else ("S" if office == "senate" else "G")
            incumbent = (cycle, office, state, historical_district, key) in incumbents
            candidates.append(
                HistoricalCandidate(
                    candidate_key=source_key,
                    name=item["name"],
                    party=item["party"],
                    group=party_group(item["party"]),
                    votes=item["votes"],
                    incumbent=incumbent,
                    winner=item["winner"],
                )
            )
        if candidates:
            if not any(candidate.winner for candidate in candidates):
                largest = max(range(len(candidates)), key=lambda index: candidates[index].votes)
                candidates[largest] = HistoricalCandidate(**{**candidates[largest].__dict__, "winner": True})
            races.append(
                HistoricalRace(
                    source_race_id=source_race_id,
                    cycle=int(cycle), office=office, state=state,
                    district=("00" if office == "house" and state == "MT" and cycle <= 2020
                              else district),
                    candidates=tuple(candidates),
                )
            )
    return races


def build_transitions(
    races: Iterable[HistoricalRace], *, use_candidate_move_prior: bool = True,
    use_population_crosswalk: bool = True,
) -> list[Transition]:
    races = list(races)
    by_location: dict[tuple[str, str, str], list[HistoricalRace]] = defaultdict(list)
    house_prior_winners: dict[tuple[int, str, str], list[HistoricalRace]] = defaultdict(list)
    for race in races:
        by_location[race.location].append(race)
        if race.office == "house":
            winner = max(race.candidates, key=lambda candidate: candidate.votes)
            house_prior_winners[(race.cycle, race.state, first_last_key(winner.name))].append(race)
    max_gap = {"house": 6, "senate": 6, "governor": 8}
    crosswalk, state_codes = house_population_crosswalk() if use_population_crosswalk else ({}, {})
    house_by_cycle = {(race.cycle, race.state, race.district): race for race in races
                      if race.office == "house"}
    transitions: list[Transition] = []
    for location_races in by_location.values():
        ordered = sorted(location_races, key=lambda race: (race.cycle, race.source_race_id))
        # At most one regular race per location and cycle. Prefer the row with the largest vote total.
        by_cycle: dict[int, HistoricalRace] = {}
        for race in ordered:
            if race.cycle not in by_cycle or sum(c.votes for c in race.candidates) > sum(c.votes for c in by_cycle[race.cycle].candidates):
                by_cycle[race.cycle] = race
        ordered = [by_cycle[cycle] for cycle in sorted(by_cycle)]
        pairs = []
        if ordered and ordered[0].office == "senate":
            # The two Senate seats in a state are distinct offices.  A regular
            # seat recurs six years later; adjacent statewide Senate elections
            # usually belong to different classes and must never be linked.
            for target in ordered:
                prior = by_cycle.get(target.cycle-6)
                if prior is not None:
                    pairs.append((prior, target))
        else:
            pairs = list(zip(ordered, ordered[1:]))
        for prior, target in pairs:
            if target.cycle - prior.cycle > max_gap[target.office]:
                continue
            prior_selection = "same_district_label"
            if target.office == "house" and target.cycle - prior.cycle > 4:
                prior_winner = max(prior.candidates, key=lambda candidate: candidate.votes)
                if not any(first_last_key(candidate.name) == first_last_key(prior_winner.name)
                           for candidate in target.candidates):
                    continue
                prior_selection = "extended_gap_same_winner"
            if target.office == "house" and use_candidate_move_prior:
                # A changed map can assign an incumbent's electorate a new
                # district number. If exactly one candidate on the target
                # ballot won a different district in the prior cycle, use that
                # candidate's prior race instead of an unrelated same-number
                # race. Ambiguous moves retain the original prior.
                moved = {
                    candidate_race.source_race_id: candidate_race
                    for candidate in target.candidates
                    for candidate_race in house_prior_winners.get(
                        (prior.cycle, target.state, first_last_key(candidate.name)), []
                    )
                    if candidate_race.district != target.district
                }
                if len(moved) == 1:
                    prior = next(iter(moved.values()))
                    prior_selection = "previous_winner_new_district_label"
            prior_alr = alr(group_shares(prior))
            if (target.office == "house" and prior_selection == "same_district_label"
                    and target.cycle in (2022, 2024) and prior.cycle == target.cycle - 2
                    and target.state in state_codes):
                row = crosswalk.get((target.cycle, state_codes[target.state], target.district))
                if row is not None:
                    components = [(item["population"], house_by_cycle.get(
                        (prior.cycle, target.state, item["prior_district"])))
                        for item in row["overlaps"]]
                    available = [(weight, race) for weight, race in components if race is not None]
                    total = sum(weight for weight, _ in available)
                    if total >= 0.95*row["population_2020"]:
                        shares = sum(weight*group_shares(race) for weight, race in available)/total
                        prior_alr = alr(shares)
                        prior_selection = "population_weighted_overlap"
            transitions.append(
                Transition(
                    office=target.office, state=target.state, target_cycle=target.cycle,
                    prior_cycle=prior.cycle, target=target, prior=prior,
                    prior_alr=prior_alr, target_alr=alr(group_shares(target)),
                    prior_selection=prior_selection,
                )
            )
    if use_population_crosswalk:
        existing_targets = {transition.target.source_race_id for transition in transitions}
        for target in races:
            if (target.office != "house" or target.cycle not in (2022, 2024)
                    or target.source_race_id in existing_targets
                    or target.state not in state_codes):
                continue
            row = crosswalk.get((target.cycle, state_codes[target.state], target.district))
            if row is None:
                continue
            prior_cycle = target.cycle - 2
            components = [(item["population"], house_by_cycle.get(
                (prior_cycle, target.state, item["prior_district"])))
                for item in row["overlaps"]]
            available = [(weight, prior) for weight, prior in components if prior is not None]
            total = sum(weight for weight, _ in available)
            coverage = total / row["population_2020"]
            # At least 90% of the target population must have a numeric old
            # district result. The unobserved remainder adds uncertainty in
            # simulations; it is never assigned invented votes.
            if coverage < 0.90:
                continue
            prior = max(available, key=lambda pair: pair[0])[1]
            shares = sum(weight * group_shares(candidate) for weight, candidate in available) / total
            transitions.append(Transition(
                office="house", state=target.state, target_cycle=target.cycle,
                prior_cycle=prior_cycle, target=target, prior=prior,
                prior_alr=alr(shares), target_alr=alr(group_shares(target)),
                prior_selection=("population_weighted_new_district" if coverage >= 0.95
                                 else "population_weighted_new_district_partial"),
                prior_population_coverage=coverage,
            ))
    return transitions


def coordinate_eligible(transition: Transition, coordinate: int) -> bool:
    """Return whether a transition identifies the requested log-ratio.

    An absent party is a structural zero, not a noisy observation near zero.
    In particular, D/R persistence cannot be learned from a race in which one
    major party did not field a candidate.  The same rule is applied to the
    major-party/other coordinate when no other-party candidate was present.
    """
    prior_groups = {candidate.group for candidate in transition.prior.candidates}
    target_groups = {candidate.group for candidate in transition.target.candidates}
    if coordinate == 0:
        return {"D", "R"} <= prior_groups and {"D", "R"} <= target_groups
    return set(GROUPS) <= prior_groups and set(GROUPS) <= target_groups


def ridge_fit(transitions: list[Transition], ridge: float | Iterable[float]) -> np.ndarray:
    penalties = (float(ridge), float(ridge)) if isinstance(ridge, (int, float)) else tuple(ridge)
    # Fit each coordinate only from its own lag.  Cross-coordinate terms would
    # let volatile minor-party turnout move the D/R estimate.
    coefficient = np.zeros((3, 2), dtype=float)
    for coordinate in range(2):
        subset = [transition for transition in transitions if coordinate_eligible(transition, coordinate)]
        design = np.array([[1.0, transition.prior_alr[coordinate]] for transition in subset])
        target = np.array([transition.target_alr[coordinate] for transition in subset])
        penalty = np.diag([0.0, penalties[coordinate]])
        fitted = np.linalg.solve(design.T @ design + penalty, design.T @ target)
        coefficient[0, coordinate] = fitted[0]
        coefficient[coordinate+1, coordinate] = fitted[1]
    return coefficient


def ridge_predict(coef: np.ndarray, prior_alr: np.ndarray) -> np.ndarray:
    return np.array([1.0, *prior_alr]) @ coef


def transition_predict(model: dict[str, Any], transition: Transition) -> np.ndarray:
    predicted = ridge_predict(model["coefficient"], transition.prior_alr)
    prior_groups = {candidate.group for candidate in transition.prior.candidates}
    target_groups = {candidate.group for candidate in transition.target.candidates}
    if {"D", "R"} <= target_groups:
        for missing_group in ("D", "R"):
            if missing_group not in prior_groups:
                predicted[0] = model["major_reentry_log_ratio_mean"][missing_group]
                break
    if set(GROUPS) <= target_groups and not set(GROUPS) <= prior_groups:
        predicted[1] = model["other_debut_log_ratio_mean"]
    return predicted


def historical_prior_extra_sd(transition: Transition, model: dict[str, Any]) -> float:
    """Propagate unknown population in a partial geographic prior.

    The missing block-group population can have any major-party preference.
    The uniform-bound variance is mapped through the fitted D/R persistence
    slope. It affects variance only, never the prior's partisan center.
    """
    coverage = transition.prior_population_coverage
    if coverage >= 1.0 or transition.office != "house":
        return 0.0
    observed = inv_alr(transition.prior_alr)
    missing = 1.0 - coverage
    low = math.log(coverage * observed[0] / (coverage * observed[1] + missing))
    high = math.log((coverage * observed[0] + missing) / (coverage * observed[1]))
    return abs(float(model["coefficient"][1, 0])) * (high - low) / math.sqrt(12.0)


def widen_historical_transition_draws(draws: np.ndarray, mean: np.ndarray,
                                      transition: Transition, model: dict[str, Any],
                                      rng: np.random.Generator) -> np.ndarray:
    """Scale extra elapsed years as a random walk and add partial-map error."""
    if transition.office != "house":
        return draws
    gap = transition.target_cycle - transition.prior_cycle
    if gap > 4:
        draws[:, 0] = mean[0] + (draws[:, 0] - mean[0]) * math.sqrt(gap / 2.0)
    extra = historical_prior_extra_sd(transition, model)
    if extra > 0:
        draws[:, 0] += rng.normal(0.0, extra, len(draws))
    return draws


def current_predict(model: dict[str, Any], prior_shares: np.ndarray, candidates: list[dict[str, Any]]) -> np.ndarray:
    predicted = ridge_predict(model["coefficient"], alr(prior_shares))
    has_current_other = any(party_group(candidate["party"]) == "O" for candidate in candidates)
    has_current_major_pair = all(
        any(party_group(candidate["party"]) == group for candidate in candidates)
        for group in ("D", "R")
    )
    if has_current_major_pair:
        for index, missing_group in enumerate(("D", "R")):
            if prior_shares[index] < 1e-8:
                predicted[0] = model["major_reentry_log_ratio_mean"][missing_group]
                break
    prior_not_three_way = float(prior_shares[2]) < 1e-8 or float(np.min(prior_shares[:2])) < 1e-8
    if has_current_other and has_current_major_pair and prior_not_three_way:
        predicted[1] = model["other_debut_log_ratio_mean"]
    return predicted


def calibrate_other_share(alr_draws: np.ndarray, target_share: float) -> np.ndarray:
    """Shift other-party log odds so their simulated arithmetic mean is calibrated."""
    adjusted = np.array(alr_draws, copy=True)
    low, high = -30.0, 30.0
    for _ in range(60):
        shift = (low+high)/2.0
        mean_other = float(np.mean(inv_alr(adjusted + np.array([0.0, shift]))[:, 2]))
        if mean_other > target_share:
            low = shift
        else:
            high = shift
    adjusted[:, 1] += (low+high)/2.0
    return adjusted


def transition_other_share_target(model: dict[str, Any], transition: Transition) -> float | None:
    target_groups = {candidate.group for candidate in transition.target.candidates}
    if "O" not in target_groups:
        return None
    prior_groups = {candidate.group for candidate in transition.prior.candidates}
    if set(GROUPS) <= target_groups and not set(GROUPS) <= prior_groups:
        return float(model["other_debut_share_mean"])
    return float(inv_alr(transition_predict(model, transition))[2])


def current_other_share_target(
    model: dict[str, Any], prior_shares: np.ndarray, candidates: list[dict[str, Any]],
) -> float | None:
    if not any(party_group(candidate["party"]) == "O" for candidate in candidates):
        return None
    has_current_major_pair = all(
        any(party_group(candidate["party"]) == group for candidate in candidates)
        for group in ("D", "R")
    )
    prior_not_three_way = float(prior_shares[2]) < 1e-8 or float(np.min(prior_shares[:2])) < 1e-8
    if has_current_major_pair and prior_not_three_way:
        return float(model["other_debut_share_mean"])
    return float(inv_alr(current_predict(model, prior_shares, candidates))[2])


def choose_ridge(transitions: list[Transition]) -> tuple[tuple[float, float], dict[str, dict[str, float]]]:
    grid = (0.0, 0.01, 0.1, 1.0, 10.0, 100.0)
    cycles = sorted({transition.target_cycle for transition in transitions})
    all_scores: dict[str, dict[str, float]] = {}
    selected: list[float] = []
    for coordinate in range(2):
        scores: dict[str, float] = {}
        for ridge in grid:
            errors = []
            for cycle in cycles:
                train = [transition for transition in transitions if transition.target_cycle != cycle]
                test = [transition for transition in transitions if transition.target_cycle == cycle and coordinate_eligible(transition, coordinate)]
                if len(train) < 10 or not test:
                    continue
                coef = ridge_fit(train, (ridge, ridge))
                errors.extend(
                    float((transition.target_alr[coordinate]-ridge_predict(coef, transition.prior_alr)[coordinate])**2)
                    for transition in test
                )
            scores[str(ridge)] = float(np.mean(errors)) if errors else math.inf
        selected.append(min(grid, key=lambda value: scores.get(str(value), math.inf)))
        all_scores[str(coordinate)] = scores
    return (selected[0], selected[1]), all_scores


def fit_office_models(transitions: list[Transition]) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    # Structural ballot absence is not evidence that a newly fielded major-party
    # candidate will receive essentially zero votes. Pool reentry elections
    # across offices because Senate and governor reentries are rare.
    reentry = {
        group: [transition.target_alr[0] for transition in transitions
                if group not in {candidate.group for candidate in transition.prior.candidates}
                and {"D", "R"} <= {candidate.group for candidate in transition.target.candidates}]
        for group in ("D", "R")
    }
    reentry_means = {
        group: float(np.mean(values)) if values else 0.0
        for group, values in reentry.items()
    }
    for office in OFFICES:
        office_transitions = [transition for transition in transitions if transition.office == office]
        ridge, scores = choose_ridge(office_transitions)
        coefficient = ridge_fit(office_transitions, ridge)
        # A unit-root partisan lean is the prespecified D/R structure.  Ridge
        # attenuation treats persistent state partisanship as measurement
        # error and pulls safe states toward 50-50.  Estimate only the average
        # inter-election swing around that persistent lean.
        contested = [
            transition for transition in office_transitions
            if coordinate_eligible(transition, 0)
        ]
        coefficient[0, 0] = float(np.mean([
            transition.target_alr[0]-transition.prior_alr[0]
            for transition in contested
        ]))
        coefficient[1, 0] = 1.0
        # Minor-party support is also persistent conditional on having appeared
        # in both elections.  The unconstrained ridge fit attenuates a prior
        # structural zero toward its conditional-sample intercept, which can
        # turn an untested new entrant into a candidate with 15-25% support.
        # Preserve the prior other-party mass and estimate only its average
        # change among recurring other-party contests.  A new entrant after a
        # structural zero therefore starts near zero and can subsequently be
        # moved by polls in Stage 4.
        recurring_other = [
            transition for transition in office_transitions
            if coordinate_eligible(transition, 1)
        ]
        coefficient[0, 1] = float(np.mean([
            transition.target_alr[1]-transition.prior_alr[1]
            for transition in recurring_other
        ]))
        coefficient[2, 1] = 1.0
        debut_other = [
            transition for transition in office_transitions
            if {candidate.group for candidate in transition.prior.candidates} == {"D", "R"}
            and set(GROUPS) <= {candidate.group for candidate in transition.target.candidates}
        ]
        debut_reference = debut_other or [
            transition for transition in office_transitions
            if set(GROUPS) <= {candidate.group for candidate in transition.target.candidates}
        ]
        debut_share_mean = (
            float(np.mean([group_shares(transition.target)[2] for transition in debut_reference]))
            if debut_reference else 0.02
        )
        debut_log_ratio_mean = math.log((1.0-debut_share_mean)/debut_share_mean)
        models[office] = {
            "ridge": ridge,
            "ridge_cv_mse": scores,
            "coefficient": coefficient,
            "major_reentry_log_ratio_mean": reentry_means,
            "major_reentry_training_counts": {group: len(values) for group, values in reentry.items()},
            "other_debut_log_ratio_mean": debut_log_ratio_mean,
            "other_debut_share_mean": debut_share_mean,
            "other_debut_transitions": len(debut_other),
            "training_transitions": len(office_transitions),
        }
    return models


def fit_candidate_allocation(races: list[HistoricalRace], max_cycle: int | None = None) -> dict[str, dict[str, float]]:
    parameters: dict[str, dict[str, float]] = {}
    for office in OFFICES:
        groups: list[tuple[int, np.ndarray, np.ndarray]] = []
        write_in_shares: list[float] = []
        for race in races:
            if race.office != office or (max_cycle is not None and race.cycle > max_cycle):
                continue
            total_votes = sum(candidate.votes for candidate in race.candidates)
            if total_votes > 0:
                write_in_shares.extend(
                    candidate.votes / total_votes for candidate in race.candidates
                    if candidate.party.upper() in {"W", "WRITE-IN"}
                )
            for group in GROUPS:
                candidates = [candidate for candidate in race.candidates if candidate.group == group]
                candidates = [candidate for candidate in candidates if candidate.party.upper() not in {"W", "WRITE-IN"}]
                if len(candidates) < 2:
                    continue
                votes = np.array([candidate.votes for candidate in candidates], dtype=float)
                if votes.sum() <= 0:
                    continue
                groups.append((race.cycle, np.array([candidate.incumbent for candidate in candidates], dtype=float), votes/votes.sum()))

        informative = [group for group in groups if 0 < group[1].sum() < len(group[1])]
        if informative:
            def loss(beta: float) -> float:
                values = []
                for _, incumbent, observed in informative:
                    utility = beta*incumbent
                    utility -= utility.max()
                    predicted = np.exp(utility)/np.exp(utility).sum()
                    values.append(-float(np.sum(observed*np.log(np.clip(predicted, 1e-12, 1.0)))))
                return float(np.mean(values))
            optimization = minimize_scalar(loss, method="brent")
            beta = float(optimization.x) if optimization.success and abs(optimization.x) < 20 else 0.0
        else:
            beta = 0.0
        residuals: list[float] = []
        for _, incumbent, observed in groups:
            log_observed = np.log(np.clip(observed, 1e-9, 1.0))
            log_observed -= log_observed.mean()
            fitted = beta*incumbent
            fitted -= fitted.mean()
            residuals.extend((log_observed-fitted).tolist())
        sigma = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
        parameters[office] = {
            "incumbent_log_utility": beta,
            "within_group_sigma": sigma,
            "multi_candidate_groups": len(groups),
            "informative_incumbent_groups": len(informative),
            "write_in_share_samples": write_in_shares,
        }
    return parameters


def covariance(samples: list[np.ndarray]) -> np.ndarray:
    matrix = np.asarray(samples, dtype=float)
    if len(matrix) < 2:
        return np.eye(2)*1e-6
    result = LedoitWolf().fit(matrix).covariance_
    return result + np.eye(2)*1e-9


def residual_covariance(
    transitions: list[Transition], model: dict[str, Any] | None = None,
) -> np.ndarray:
    """Diagonal residual covariance from identified coordinate observations.

    The two coordinates have different structural-missingness patterns, so a
    covariance estimated from a forced complete-case matrix is not meaningful.
    They are modeled as separate processes and coupled later through shared
    election, office, and state draws.
    """
    variances = []
    for coordinate in range(2):
        values = []
        for transition in transitions:
            if coordinate == 0 and not coordinate_eligible(transition, coordinate):
                continue
            if coordinate == 1:
                prior_groups = {candidate.group for candidate in transition.prior.candidates}
                target_groups = {candidate.group for candidate in transition.target.candidates}
                if not ({"D", "R"} <= prior_groups and set(GROUPS) <= target_groups):
                    continue
            predicted = (
                transition.prior_alr if model is None
                else transition_predict(model, transition)
            )
            values.append(float(transition.target_alr[coordinate]-predicted[coordinate]))
        variances.append(float(np.var(values, ddof=1)) if len(values) > 1 else 1e-6)
    return np.diag(np.maximum(variances, 1e-9))


def select_predictive_covariance_scale(transitions: list[Transition], seed: int = 202603) -> tuple[np.ndarray, dict[str, Any]]:
    """Select separate D/R and other-share scales by expanding-cycle CV."""
    cycles = sorted({transition.target_cycle for transition in transitions})
    validation_cycles = cycles[-3:]
    folds = []
    for validation_cycle in validation_cycles:
        training = [transition for transition in transitions if transition.target_cycle < validation_cycle]
        validation = [transition for transition in transitions if transition.target_cycle == validation_cycle]
        if len(training) < 100 or not validation:
            continue
        models = fit_office_models(training)
        covariances = {
            office: residual_covariance(
                [transition for transition in training if transition.office == office],
                models[office],
            )
            for office in OFFICES
        }
        folds.append((validation_cycle, validation, models, covariances))
    if not folds:
        return np.ones(2), {"selection": "fallback_no_complete_folds"}
    scores: dict[str, float] = {}
    coverage95: dict[str, float] = {}
    grid_index = 0
    for dr_scale in DR_SCALE_GRID:
        for other_scale in OTHER_SCALE_GRID:
            rng = np.random.default_rng(seed+grid_index)
            grid_index += 1
            log_scores = []
            covered = []
            scale_matrix = np.diag([dr_scale, other_scale])
            for _, validation, models, covariances in folds:
                for transition in validation:
                    present = {candidate.group for candidate in transition.target.candidates}
                    actual_group = max(transition.target.candidates, key=lambda candidate: candidate.votes).group
                    mean = transition_predict(models[transition.office], transition)
                    draws = rng.multivariate_normal(
                        mean,
                        covariances[transition.office] @ scale_matrix, size=400,
                    )
                    draws = widen_historical_transition_draws(
                        draws, mean, transition, models[transition.office], rng)
                    other_target = transition_other_share_target(models[transition.office], transition)
                    if other_target is not None:
                        draws = calibrate_other_share(draws, other_target)
                    shares = restricted_group_shares(draws, present)
                    probability = float(np.mean(np.argmax(shares, axis=1) == GROUP_INDEX[actual_group]))
                    log_scores.append(-math.log(max(probability, 1/800)))
                    actual = group_shares(transition.target)
                    low, high = np.quantile(shares, [0.025, 0.975], axis=0)
                    for group in present:
                        position = GROUP_INDEX[group]
                        covered.append(bool(low[position] <= actual[position] <= high[position]))
            key = f"{dr_scale},{other_scale}"
            scores[key] = float(np.mean(log_scores))
            coverage95[key] = float(np.mean(covered))
    eligible = [key for key in scores if coverage95[key] >= 0.90]
    selected_key = min(eligible or scores, key=lambda key: scores[key])
    selected = np.array([float(value) for value in selected_key.split(",")])
    return selected, {
        "validation_cycles": [cycle for cycle, _, _, _ in folds],
        "winner_log_score": scores, "group_share_coverage95": coverage95,
    }


def decompose_covariance(
    transitions: list[Transition], models: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    component_values = {
        "global": [[], []], "state": [[], []],
        "office": {office: [[], []] for office in OFFICES},
        "race": {office: [[], []] for office in OFFICES},
    }
    residual_records = []
    for coordinate in range(2):
        records = []
        for transition in transitions:
            if not coordinate_eligible(transition, coordinate):
                continue
            predicted = transition_predict(models[transition.office], transition)
            residual = float(transition.target_alr[coordinate]-predicted[coordinate])
            records.append((transition, residual))
            residual_records.append((transition, coordinate, residual))
        cycle_office_means = {}
        for key in sorted({(t.target_cycle, t.office) for t, _ in records}):
            cycle_office_means[key] = float(np.mean([
                value for transition, value in records
                if (transition.target_cycle, transition.office) == key
            ]))
        global_cycle = {}
        for cycle in sorted({transition.target_cycle for transition, _ in records}):
            global_cycle[cycle] = float(np.mean([
                value for (candidate_cycle, _), value in cycle_office_means.items()
                if candidate_cycle == cycle
            ]))
        component_values["global"][coordinate].extend(global_cycle.values())
        office_deviation = {
            key: value-global_cycle[key[0]] for key, value in cycle_office_means.items()
        }
        for (cycle, office), value in office_deviation.items():
            component_values["office"][office][coordinate].append(value)
        adjusted = []
        for transition, residual in records:
            base = global_cycle[transition.target_cycle] + office_deviation[(transition.target_cycle, transition.office)]
            adjusted.append((transition, residual-base))
        state_cycle = {}
        for key in sorted({(t.target_cycle, t.state) for t, _ in adjusted}):
            state_cycle[key] = float(np.mean([
                value for transition, value in adjusted
                if (transition.target_cycle, transition.state) == key
            ]))
        component_values["state"][coordinate].extend(state_cycle.values())
        for transition, residual in adjusted:
            component_values["race"][transition.office][coordinate].append(
                residual-state_cycle[(transition.target_cycle, transition.state)]
            )
    predictive_scale, scale_scores = select_predictive_covariance_scale(transitions)
    def diagonal(values: list[list[float]]) -> np.ndarray:
        return np.diag([
            (float(np.var(item, ddof=1)) if len(item) > 1 else 1e-6)*predictive_scale[index]
            for index, item in enumerate(values)
        ])
    global_cov = diagonal(component_values["global"])
    state_cov = diagonal(component_values["state"])
    office_cov = {office: diagonal(component_values["office"][office]) for office in OFFICES}
    race_cov = {office: diagonal(component_values["race"][office]) for office in OFFICES}
    normalization = {}
    for office in OFFICES:
        subset = [transition for transition in transitions if transition.office == office]
        target = residual_covariance(subset, models[office]) @ np.diag(predictive_scale)
        component_total = global_cov+office_cov[office]+state_cov+race_cov[office]
        normalization[office] = np.sqrt(
            np.diag(target)/np.maximum(np.diag(component_total), 1e-12)
        )
    return {
        "global": global_cov,
        "office": office_cov,
        "state": state_cov,
        "race": race_cov,
        "office_coordinate_normalization": normalization,
        "predictive_covariance_scale": predictive_scale,
        "predictive_covariance_scale_cv_log_score": scale_scores,
        "residual_records": residual_records,
    }


def restricted_group_shares(alr_draws: np.ndarray, present: set[str]) -> np.ndarray:
    shares = inv_alr(alr_draws)
    mask = np.array([group in present for group in GROUPS], dtype=float)
    shares *= mask
    sums = shares.sum(axis=1, keepdims=True)
    return shares/np.where(sums == 0, 1.0, sums)


def simulate_candidates(
    alr_draws: np.ndarray,
    candidates: list[dict[str, Any]],
    beta: float,
    sigma: float,
    rng: np.random.Generator,
    write_in_share_samples: list[float] | None = None,
) -> np.ndarray:
    groups = [party_group(candidate.get("party")) for candidate in candidates]
    group_draws = restricted_group_shares(alr_draws, set(groups))
    result = np.zeros((len(alr_draws), len(candidates)), dtype=float)
    write_in_indexes = [
        index for index, candidate in enumerate(candidates)
        if candidate.get("write_in_only", False)
        or str(candidate.get("party", "")).upper() in {"W", "WRITE-IN"}
    ]
    if write_in_indexes and write_in_share_samples:
        samples = np.asarray(write_in_share_samples, dtype=float)
        sampled = rng.choice(samples, size=(len(alr_draws), len(write_in_indexes)))
        sampled = np.maximum(sampled, 0.0)
        write_in_total = sampled.sum(axis=1)
        regular_other = [
            index for index, group in enumerate(groups)
            if group == "O" and index not in write_in_indexes
        ]
        if regular_other:
            # A listed write-in competes for the existing other-party mass.
            scale = np.minimum(1.0, 0.95*group_draws[:, GROUP_INDEX["O"]]
                               / np.maximum(write_in_total, 1e-12))
            sampled *= scale[:, None]
            write_in_total = sampled.sum(axis=1)
        else:
            # When all other-party entries are write-ins, historical write-in
            # shares replace the broad other-party group prior.
            major_total = group_draws[:, GROUP_INDEX["D"]] + group_draws[:, GROUP_INDEX["R"]]
            if np.any(major_total <= 0):
                raise ValueError("Write-in-only field has no major-party candidates")
            group_draws[:, GROUP_INDEX["D"]] *= (1-write_in_total)/major_total
            group_draws[:, GROUP_INDEX["R"]] *= (1-write_in_total)/major_total
            group_draws[:, GROUP_INDEX["O"]] = write_in_total
        for column, index in enumerate(write_in_indexes):
            result[:, index] = sampled[:, column]
    for group in GROUPS:
        if group not in groups:
            continue
        indexes = [
            index for index, candidate_group in enumerate(groups)
            if candidate_group == group and index not in write_in_indexes
        ]
        if not indexes:
            continue
        utility = np.column_stack([
            beta*float(candidates[index].get("incumbent", False))
            + rng.normal(0.0, sigma, len(alr_draws))
            for index in indexes
        ])
        utility -= utility.max(axis=1, keepdims=True)
        weights = np.exp(utility)
        weights /= weights.sum(axis=1, keepdims=True)
        for column, candidate_index in enumerate(indexes):
            budget = group_draws[:, GROUP_INDEX[group]]
            if group == "O" and write_in_indexes:
                budget = budget-result[:, write_in_indexes].sum(axis=1)
            result[:, candidate_index] = budget*weights[:, column]
    return result


def historical_candidate_dicts(race: HistoricalRace) -> list[dict[str, Any]]:
    return [
        {
            "candidate_key": candidate.candidate_key,
            "name": candidate.name,
            "party": candidate.party,
            "incumbent": candidate.incumbent,
            "actual_share": candidate.votes/sum(item.votes for item in race.candidates),
            "winner": candidate.winner,
            "write_in_only": candidate.party.upper() in {"W", "WRITE-IN"},
        }
        for candidate in race.candidates
    ]


def score_backtest(
    transitions: list[Transition], races: list[HistoricalRace], seed: int
) -> dict[str, Any]:
    training = [transition for transition in transitions if transition.target_cycle < 2024]
    holdout = [transition for transition in transitions if transition.target_cycle == 2024]
    models = fit_office_models(training)
    allocation = fit_candidate_allocation(races, max_cycle=2022)
    predictive_scale, predictive_scale_scores = select_predictive_covariance_scale(training, seed+17)
    total_model_cov: dict[str, np.ndarray] = {}
    baseline_cov: dict[str, np.ndarray] = {}
    for office in OFFICES:
        office_training = [transition for transition in training if transition.office == office]
        total_model_cov[office] = residual_covariance(
            office_training, models[office]
        ) @ np.diag(predictive_scale)
        baseline_cov[office] = residual_covariance(office_training)
    rng = np.random.default_rng(seed)
    metrics = {
        "model": defaultdict(list),
        "simple_previous_result": defaultdict(list),
    }
    by_office: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: {"model": defaultdict(list), "simple_previous_result": defaultdict(list)}
    )
    draws = 3000
    for transition in holdout:
        candidates = historical_candidate_dicts(transition.target)
        if not candidates:
            continue
        actual = np.array([candidate["actual_share"] for candidate in candidates])
        winner_indexes = [index for index, candidate in enumerate(candidates) if candidate["winner"]]
        winner_index = winner_indexes[0] if winner_indexes else int(np.argmax(actual))
        mean_model = transition_predict(models[transition.office], transition)
        specifications = {
            "model": (mean_model, total_model_cov[transition.office], allocation[transition.office]["incumbent_log_utility"]),
            "simple_previous_result": (transition.prior_alr, baseline_cov[transition.office], 0.0),
        }
        for name, (mean, cov, beta) in specifications.items():
            alr_draws = rng.multivariate_normal(mean, cov, size=draws)
            if name == "model":
                alr_draws = widen_historical_transition_draws(
                    alr_draws, mean, transition, models[transition.office], rng)
            other_target = transition_other_share_target(models[transition.office], transition)
            if name == "model" and other_target is not None:
                alr_draws = calibrate_other_share(alr_draws, other_target)
            candidate_draws = simulate_candidates(
                alr_draws, candidates, beta,
                allocation[transition.office]["within_group_sigma"], rng,
                allocation[transition.office]["write_in_share_samples"],
            )
            leader = np.argmax(candidate_draws, axis=1)
            probabilities = np.bincount(leader, minlength=len(candidates))/draws
            predicted_share = candidate_draws.mean(axis=0)
            lower80, upper80 = np.quantile(candidate_draws, [0.1, 0.9], axis=0)
            lower95, upper95 = np.quantile(candidate_draws, [0.025, 0.975], axis=0)
            values = {
                "log_score": -math.log(max(probabilities[winner_index], 1/draws/2)),
                "brier": float(np.sum((probabilities-np.eye(len(candidates))[winner_index])**2)),
                "share_mae": float(np.mean(np.abs(predicted_share-actual))),
                "coverage80": float(np.mean((actual >= lower80) & (actual <= upper80))),
                "coverage95": float(np.mean((actual >= lower95) & (actual <= upper95))),
            }
            for metric, value in values.items():
                metrics[name][metric].append(value)
                by_office[transition.office][name][metric].append(value)
    def summarize(source: dict[str, list[float]]) -> dict[str, float]:
        return {metric: float(np.mean(values)) for metric, values in source.items()}
    overall = {name: summarize(values) for name, values in metrics.items()}
    model_score = overall["model"]
    baseline_score = overall["simple_previous_result"]
    log_score_noninferiority_margin = 0.01
    gate = {
        "primary_proper_score": "winner_log_score",
        "winner_log_score_noninferiority_margin": log_score_noninferiority_margin,
        "winner_log_score_noninferior": (
            model_score["log_score"] <= baseline_score["log_score"] + log_score_noninferiority_margin
        ),
        "share_mae_beats_baseline": model_score["share_mae"] <= baseline_score["share_mae"],
        "no_obvious_undercoverage": model_score["coverage80"] >= 0.75 and model_score["coverage95"] >= 0.90,
        "passed": (
            model_score["log_score"] <= baseline_score["log_score"] + log_score_noninferiority_margin
            and model_score["share_mae"] <= baseline_score["share_mae"]
            and model_score["coverage80"] >= 0.75
            and model_score["coverage95"] >= 0.90
        ),
        "diagnostic_deltas_model_minus_baseline": {
            metric: model_score[metric]-baseline_score[metric]
            for metric in model_score
        },
        "limitation": (
            "The acceptance gate requires held-out winner-log-score noninferiority within 0.01 nat, "
            "better share MAE, and adequate interval coverage; Brier score is secondary."
        ),
    }
    return {
        "holdout_cycle": 2024,
        "holdout_races": len(holdout),
        "simulation_draws_per_race": draws,
        "overall": overall,
        "gate": gate,
        "by_office": {
            office: {name: summarize(values) for name, values in methods.items()}
            for office, methods in by_office.items()
        },
        "training_ridge": {
            office: {
                "selected": model["ridge"],
                "cv_mse": model["ridge_cv_mse"],
                "training_transitions": model["training_transitions"],
            }
            for office, model in models.items()
        },
        "predictive_covariance_scale": {
            "selected": predictive_scale.tolist(),
            "cv_winner_log_score": predictive_scale_scores,
        },
    }


def load_current_races(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    candidate_features = {
        row["ballot_entry_id"]: bool(row["prior_winner_match"])
        for row in connection.execute("SELECT * FROM candidate_features")
    }
    output = []
    for race in connection.execute("SELECT * FROM races ORDER BY office,state,race_id"):
        candidates = []
        for candidate in connection.execute(
            "SELECT * FROM candidates WHERE race_id=? ORDER BY ballot_entry_id", (race["race_id"],)
        ):
            candidates.append({
                "ballot_entry_id": candidate["ballot_entry_id"],
                "candidate_id": candidate["candidate_id"],
                "name": candidate["name"],
                "party": candidate["ballot_party"],
                "incumbent": candidate_features[candidate["ballot_entry_id"]],
                "status": candidate["status"],
                "write_in_only": bool(candidate["write_in_only"]),
            })
        fundamental = connection.execute(
            "SELECT * FROM race_fundamentals WHERE race_id=?", (race["race_id"],)
        ).fetchone()
        prior = np.array([
            fundamental["dem_share"] or 0.0,
            fundamental["rep_share"] or 0.0,
            fundamental["other_share"] or 0.0,
        ])
        prior = (prior+1e-9)/(prior.sum()+3e-9)
        output.append({
            "race": dict(race), "fundamental": dict(fundamental),
            "candidates": candidates, "prior_shares": prior,
        })
    return output


def quantile_summary(values: np.ndarray) -> dict[str, float]:
    quantiles = np.quantile(values, [0.025, 0.1, 0.5, 0.9, 0.975])
    return {
        "mean": float(np.mean(values)), "median": float(quantiles[2]),
        "interval80_low": float(quantiles[1]), "interval80_high": float(quantiles[3]),
        "interval95_low": float(quantiles[0]), "interval95_high": float(quantiles[4]),
    }


def distribution(values: np.ndarray) -> dict[str, float]:
    counts = Counter(int(value) for value in values)
    return {str(value): count/len(values) for value, count in sorted(counts.items())}


def serializable_parameters(
    models: dict[str, dict[str, Any]], allocation: dict[str, dict[str, float]], decomposition: dict[str, Any]
) -> dict[str, Any]:
    return {
        "party_group_transition": {
            office: {
                "selected_ridge": model["ridge"],
                "ridge_cv_mse": model["ridge_cv_mse"],
                "coefficient": model["coefficient"].tolist(),
                "major_reentry_log_ratio_mean": model["major_reentry_log_ratio_mean"],
                "major_reentry_training_counts": model["major_reentry_training_counts"],
                "other_debut_log_ratio_mean": model["other_debut_log_ratio_mean"],
                "other_debut_share_mean": model["other_debut_share_mean"],
                "other_debut_transitions": model["other_debut_transitions"],
                "training_transitions": model["training_transitions"],
            }
            for office, model in models.items()
        },
        "candidate_allocation": allocation,
        "covariance": {
            "global": decomposition["global"].tolist(),
            "office": {office: value.tolist() for office, value in decomposition["office"].items()},
            "state": decomposition["state"].tolist(),
            "race": {office: value.tolist() for office, value in decomposition["race"].items()},
            "office_coordinate_normalization": {
                office: value.tolist()
                for office, value in decomposition["office_coordinate_normalization"].items()
            },
            "predictive_scale": decomposition["predictive_covariance_scale"].tolist(),
            "predictive_scale_cv_log_score": decomposition["predictive_covariance_scale_cv_log_score"],
        },
        "coordinate_system": "separable log odds log(D/R) and log((D+R)/O)",
        "historical_zero_handling": "Jeffreys 0.5-vote pseudocount per party group",
    }


def simulate_2026(
    connection: sqlite3.Connection,
    current: list[dict[str, Any]],
    models: dict[str, dict[str, Any]],
    allocation: dict[str, dict[str, float]],
    decomposition: dict[str, Any],
    draws: int,
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = np.random.default_rng(seed)
    global_draw = rng.multivariate_normal(np.zeros(2), decomposition["global"], size=draws)
    office_draw = {
        office: rng.multivariate_normal(np.zeros(2), decomposition["office"][office], size=draws)
        for office in OFFICES
    }
    states = sorted({item["race"]["state"] for item in current})
    state_draw = {
        state: rng.multivariate_normal(np.zeros(2), decomposition["state"], size=draws)
        for state in states
    }
    seat_counts = {
        office: {group: np.zeros(draws, dtype=np.int16) for group in GROUPS}
        for office in OFFICES
    }
    results = []
    for item in current:
        race = item["race"]
        office = race["office"]
        candidates = item["candidates"]
        mean = current_predict(models[office], item["prior_shares"], candidates)
        multiplier = float(item["fundamental"]["uncertainty_multiplier"])
        race_error = rng.multivariate_normal(
            np.zeros(2), decomposition["race"][office], size=draws
        )*multiplier
        normalization = decomposition["office_coordinate_normalization"][office]
        alr_draws = mean + (
            global_draw + office_draw[office] + state_draw[race["state"]] + race_error
        )*normalization
        other_target = current_other_share_target(models[office], item["prior_shares"], candidates)
        if other_target is not None:
            alr_draws = calibrate_other_share(alr_draws, other_target)
        candidate_draws = simulate_candidates(
            alr_draws, candidates,
            allocation[office]["incumbent_log_utility"],
            allocation[office]["within_group_sigma"], rng,
            allocation[office]["write_in_share_samples"],
        )
        leader = np.argmax(candidate_draws, axis=1)
        candidate_output = []
        for index, candidate in enumerate(candidates):
            first_probability = float(np.mean(leader == index))
            summary = quantile_summary(candidate_draws[:, index])
            rule_is_direct = race["counting_rule"] == "plurality" or len(candidates) == 1
            candidate_output.append({
                **candidate,
                "party_group": party_group(candidate["party"]),
                "share": summary,
                "first_stage_leader_probability": first_probability,
                "eventual_win_probability": first_probability if rule_is_direct else None,
                "monte_carlo_standard_error": math.sqrt(first_probability*(1-first_probability)/draws),
            })
        for draw_index, candidate_index in enumerate(leader):
            group = party_group(candidates[int(candidate_index)]["party"])
            seat_counts[office][group][draw_index] += 1
        results.append({
            "race_id": race["race_id"], "office": office, "state": race["state"],
            "district_code": race["district_code"], "counting_rule": race["counting_rule"],
            "baseline_source": item["fundamental"]["baseline_source_race_id"],
            "geography_status": item["fundamental"]["geography_status"],
            "uncertainty_multiplier": multiplier,
            "ballot_status": race["ballot_status"],
            "winner_interpretation": (
                "eventual winner under plurality" if race["counting_rule"] == "plurality" or len(candidates) == 1
                else "first-stage leader only; Stage 5 must apply transfers or later-round rules"
            ),
            "candidates": candidate_output,
        })
    summaries: dict[str, Any] = {}
    for office in OFFICES:
        group_counts = seat_counts[office]
        joint = Counter(
            f"{int(group_counts['D'][index])}-{int(group_counts['R'][index])}-{int(group_counts['O'][index])}"
            for index in range(draws)
        )
        summaries[office] = {
            "seat_universe": int(sum(group_counts[group][0] for group in GROUPS)),
            "marginal_distributions": {group: distribution(values) for group, values in group_counts.items()},
            "joint_D_R_O_distribution": {key: count/draws for key, count in sorted(joint.items())},
            "interpretation": "plurality-equivalent first-stage leaders; nonplurality final rules are deferred to Stage 5",
        }
        if office == "house":
            summaries[office]["diagnostic_plurality_equivalent_control"] = {
                "D_218_or_more": float(np.mean(group_counts["D"] >= 218)),
                "R_218_or_more": float(np.mean(group_counts["R"] >= 218)),
                "neither": float(np.mean((group_counts["D"] < 218) & (group_counts["R"] < 218))),
            }
    return results, summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/stage3"))
    parser.add_argument("--draws", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()
    if args.draws < 1000:
        raise ValueError("At least 1,000 simulation draws are required")
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        build_metadata = dict(connection.execute("SELECT key,value FROM build_metadata"))
        races = load_historical_races(connection)
        transitions = build_transitions(races)
        backtest = score_backtest(transitions, races, args.seed+1)
        models = fit_office_models(transitions)
        allocation = fit_candidate_allocation(races)
        decomposition = decompose_covariance(transitions, models)
        parameters = serializable_parameters(models, allocation, decomposition)
        current = load_current_races(connection)
        race_forecasts, seat_summaries = simulate_2026(
            connection, current, models, allocation, decomposition, args.draws, args.seed
        )
    finally:
        connection.close()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_version": MODEL_VERSION,
        "stage": 3,
        "estimand": "candidate share at the next listed voting stage",
        "uses_polling": False,
        "data_database": str(args.database),
        "data_sha256": sha256(args.database),
        "model_code_sha256": sha256(Path(__file__)),
        "information_cutoff_utc": max(
            snapshot_timestamp(build_metadata["source_snapshot_id"]),
            snapshot_timestamp(build_metadata["historical_snapshot"]),
        ),
        "input_snapshot_ids": {
            "live_source_snapshot": build_metadata["source_snapshot_id"],
            "historical_snapshot": build_metadata["historical_snapshot"],
        },
        "random_seed": args.seed,
        "simulation_draws": args.draws,
        "historical_races": len(races),
        "historical_transitions": len(transitions),
    }
    parameter_document = {"metadata": metadata, "parameters": parameters, "backtest": backtest}
    forecast_document = {
        "metadata": metadata,
        "publication_status": "internal_stage3_baseline_not_for_publication",
        "nonplurality_limitation": "First-stage shares are modeled; eventual winner probabilities are null until Stage 5.",
        "race_count": len(race_forecasts),
        "races": race_forecasts,
        "joint_summaries": seat_summaries,
    }
    (args.output_dir/"model_parameters.json").write_text(
        json.dumps(parameter_document, indent=2, ensure_ascii=False)+"\n", encoding="utf-8"
    )
    (args.output_dir/"forecast_2026.json").write_text(
        json.dumps(forecast_document, indent=2, ensure_ascii=False)+"\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": "complete", "metadata": metadata,
        "backtest": backtest["overall"],
        "outputs": [str(args.output_dir/"model_parameters.json"), str(args.output_dir/"forecast_2026.json")],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
