"""Auditable 2026 geography, incumbency/experience, and governor approval shifts.

All shifts are in Democratic-versus-Republican log vote odds. Coefficients for
candidate and approval features are fitted to historical general elections;
the geography shift is the observed change in presidential vote odds between
the old and new district boundaries.
"""

from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

try:
    from modeling import stage3_results_baseline as stage3
except ModuleNotFoundError:
    import stage3_results_baseline as stage3

ROOT = Path(__file__).resolve().parents[1]
HOUSE = ROOT / "data/reference/house_presidential_2026"
APPROVAL = ROOT / "data/reference/governor_approval"
STATES = {
    "Alabama":"AL", "Alaska":"AK", "Arizona":"AZ", "Arkansas":"AR", "California":"CA",
    "Colorado":"CO", "Connecticut":"CT", "Delaware":"DE", "Florida":"FL", "Georgia":"GA",
    "Hawaii":"HI", "Idaho":"ID", "Illinois":"IL", "Indiana":"IN", "Iowa":"IA",
    "Kansas":"KS", "Kentucky":"KY", "Louisiana":"LA", "Maine":"ME", "Maryland":"MD",
    "Massachusetts":"MA", "Michigan":"MI", "Minnesota":"MN", "Mississippi":"MS", "Missouri":"MO",
    "Montana":"MT", "Nebraska":"NE", "Nevada":"NV", "New Hampshire":"NH", "New Jersey":"NJ",
    "New Mexico":"NM", "New York":"NY", "North Carolina":"NC", "North Dakota":"ND", "Ohio":"OH",
    "Oklahoma":"OK", "Oregon":"OR", "Pennsylvania":"PA", "Rhode Island":"RI",
    "South Carolina":"SC", "South Dakota":"SD", "Tennessee":"TN", "Texas":"TX", "Utah":"UT",
    "Vermont":"VT", "Virginia":"VA", "Washington":"WA", "West Virginia":"WV",
    "Wisconsin":"WI", "Wyoming":"WY",
}


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def presidential_votes(path: Path) -> dict[str, tuple[int, int]]:
    rows = list(csv.reader(path.open(encoding="utf-8-sig", newline="")))
    out = {}
    for row in rows:
        if len(row) < 6 or not row[0] or "-" not in row[0]:
            continue
        district = row[0].strip()
        if len(district) > 5:
            continue
        # The current-map sheet has a spacer column; the old-map sheet does not.
        try:
            columns = (4, 5) if "current_maps" in path.name else (3, 4)
            d, r = (int(row[i].replace(",", "")) for i in columns)
        except (ValueError, IndexError):
            continue
        if d > 0 and r > 0:
            if district in out:
                raise ValueError(f"Duplicate presidential district {district}")
            out[district] = d, r
    if len(out) != 435:
        raise ValueError(f"Expected 435 presidential districts in {path}: {len(out)}")
    return out


def house_map_shifts() -> tuple[dict[str, float], dict[str, Any]]:
    old_path = HOUSE / "downballot_2024_old_maps.csv"
    new_path = HOUSE / "downballot_2024_current_maps.csv"
    old, new = presidential_votes(old_path), presidential_votes(new_path)
    if old.keys() != new.keys():
        raise ValueError("Old and 2026 map district identifiers differ")
    shifts = {k: math.log(new[k][0]/new[k][1]) - math.log(old[k][0]/old[k][1]) for k in old}
    return shifts, {
        "source": "The Downballot, 2024 presidential votes by 2024 and 2026 House boundaries",
        "old_url": "https://docs.google.com/spreadsheets/d/1ng1i_Dm_RMDnEvauH44pgE6JCUsapcuu8F2pCfeLWFo/edit?gid=1491069057",
        "new_url": "https://docs.google.com/spreadsheets/d/1eZfaFI-c-PFOoKx1-zZA2MP0_dxRq_LVK0re3BOQqy0/edit?gid=1491069057",
        "old_sha256": source_hash(old_path), "new_sha256": source_hash(new_path),
        "districts": len(shifts), "changed_over_one_point_log_odds": sum(abs(v)>0.04 for v in shifts.values()),
    }


def historical_approval() -> dict[tuple[str, int], float]:
    path = APPROVAL / "sead_governor_quarterly_v1.csv"
    out = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            # Quarter 3 is the final pre-election quarter, avoiding returns.
            if int(row["quarter"]) != 3 or not row["Approval_Smoothed"] or not row["Disapproval_Smoothed"]:
                continue
            state = STATES.get(row["state"])
            if state:
                out[state, int(row["year"])] = (
                    float(row["Approval_Smoothed"])-float(row["Disapproval_Smoothed"])
                ) / 100.0
    return out


def current_approval() -> dict[str, tuple[float, str, str]]:
    out = {}
    with (APPROVAL / "morning_consult_2025q4_net.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            state = STATES[row["state"]]
            out[state] = float(row["net_approval"])/100.0, row["governor"], row["survey_end"]
    if len(out) != 50:
        raise ValueError("Governor approval table does not cover 50 states")
    return out


def current_house_incumbents() -> dict[str, str]:
    path = HOUSE / "downballot_2024_current_maps.csv"
    out = {}
    for row in csv.reader(path.open(encoding="utf-8-sig", newline="")):
        if len(row) >= 2 and len(row[0]) <= 5 and "-" in row[0]:
            out[row[0]] = row[1]
    if len(out) != 435:
        raise ValueError("Current-map incumbent column does not cover 435 districts")
    return out


def _winner(race: stage3.HistoricalRace) -> stage3.HistoricalCandidate | None:
    return next((c for c in race.candidates if c.winner and c.group in {"D", "R"}), None)


def _candidate_features(
    candidates: list[tuple[str, str]], prior_winner: tuple[str, str] | None,
    prior_officeholders: set[tuple[str, str]],
) -> tuple[float, float, bool]:
    """Signed returning-winner and other elected-office experience indicators."""
    returning = 0.0
    experience = 0.0
    winner_running = False
    for name, group in candidates:
        if group not in {"D", "R"}:
            continue
        sign = 1.0 if group == "D" else -1.0
        key = stage3.first_last_key(name)
        if prior_winner and (key, group) == prior_winner:
            returning += sign
            winner_running = True
        elif (key, group) in prior_officeholders:
            experience += sign
    return returning, experience, winner_running


def _history_index(races: list[stage3.HistoricalRace]) -> dict[str, list[stage3.HistoricalRace]]:
    by_state = defaultdict(list)
    for race in races:
        if race.cycle < 2026:
            by_state[race.state].append(race)
    for rows in by_state.values():
        rows.sort(key=lambda r: r.cycle)
    return by_state


def _past_winners(rows: list[stage3.HistoricalRace], before: int) -> set[tuple[str, str]]:
    return {
        (stage3.first_last_key(c.name), c.group)
        for r in rows if r.cycle < before
        for c in r.candidates if c.winner and c.group in {"D", "R"}
    }


def _ridge_fit(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    return np.linalg.solve(x.T @ x + alpha*np.eye(x.shape[1]), x.T @ y)


def fit_effects(transitions: list[stage3.Transition], models: dict[str, Any], historical: list[stage3.HistoricalRace]) -> dict[str, Any]:
    by_state = _history_index(historical)
    records: dict[str, list[tuple[int, list[float], float]]] = defaultdict(list)
    for tr in transitions:
        if tr.target_cycle >= 2026 or not stage3.coordinate_eligible(tr, 0):
            continue
        winner = _winner(tr.prior)
        prior_key = (stage3.first_last_key(winner.name), winner.group) if winner else None
        past = _past_winners(by_state[tr.state], tr.target_cycle)
        returning, experience, winner_running = _candidate_features(
            [(c.name,c.group) for c in tr.target.candidates], prior_key, past,
        )
        residual = float(tr.target_alr[0] - stage3.transition_predict(models[tr.office], tr)[0])
        open_seat = (1.0 if winner.group == "D" else -1.0) if winner and not winner_running else 0.0
        predictors = [open_seat, experience]
        records[tr.office].append((tr.target_cycle, predictors, residual))
    out = {}
    for office in stage3.OFFICES:
        rows = records[office]
        if not rows:
            raise ValueError(f"No training rows for {office} candidate effects")
        years = sorted({row[0] for row in rows})
        x = np.array([row[1] for row in rows], dtype=float)
        y = np.array([row[2] for row in rows], dtype=float)
        cycles = np.array([row[0] for row in rows])
        # Remove the election-wide residual so features cannot learn a national swing.
        for year in years:
            y[cycles == year] -= np.mean(y[cycles == year])
        scores = {}
        for alpha in (0.1, 1.0, 10.0, 100.0, 1000.0):
            errors = []
            for year in years:
                train, test = cycles != year, cycles == year
                if sum(train) < x.shape[1]+5:
                    continue
                beta = _ridge_fit(x[train], y[train], alpha)
                errors.extend((y[test]-x[test]@beta).tolist())
            scores[str(alpha)] = float(np.mean(np.square(errors))) if errors else math.inf
        alpha = min((0.1, 1.0, 10.0, 100.0, 1000.0), key=lambda a:scores[str(a)])
        beta = _ridge_fit(x, y, alpha)
        out[office] = {
            "coefficients": beta.tolist(), "selected_ridge": alpha, "leave_cycle_out_mse": scores,
            "training_rows": len(rows), "training_cycles": years,
            "feature_names": ["open_seat_prior_winner_signed", "other_prior_elected_winner_signed"],
            "active_in_2026_nowcast": office != "governor",
            "superseded_by": ("modeling/governor_local_lean.py" if office == "governor" else None),
        }
    return out


def current_shifts(current: list[dict[str, Any]], historical: list[stage3.HistoricalRace],
                   effects: dict[str, Any]) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    maps, map_meta = house_map_shifts()
    approval = current_approval()
    house_incumbents = current_house_incumbents()
    by_state = _history_index(historical)
    output = {}
    coverage = Counter()
    for item in current:
        race = item["race"]
        office, state, race_id = race["office"], race["state"], race["race_id"]
        candidates = item["candidates"]
        fundamental = item["fundamental"]
        winner_group = stage3.party_group(fundamental["prior_winner_party"])
        reviewed_incumbents = [c for c in candidates if c["incumbent"]]
        if len(reviewed_incumbents) > 1:
            raise ValueError(f"Multiple prior-winner matches for {race_id}")
        prior_key = ((stage3.first_last_key(reviewed_incumbents[0]["name"]),
                      stage3.party_group(reviewed_incumbents[0]["party"]))) if reviewed_incumbents else None
        sitting_keys = {c["ballot_entry_id"] for c in reviewed_incumbents}
        if office == "house":
            district_key = state + "-" + ("AL" if race["district_code"] == "00" else race["district_code"])
            published_name = house_incumbents[district_key]
            published_key = stage3.first_last_key(published_name)
            published_matches = [c for c in candidates if stage3.first_last_key(c["name"]) == published_key]
            if published_key and len(published_matches) == 1:
                sitting_keys.add(published_matches[0]["ballot_entry_id"])
        elif office == "governor" and state in approval:
            published_name = approval[state][1].split(" (")[0]
            published_key = stage3.first_last_key(published_name)
            published_matches = [c for c in candidates if stage3.first_last_key(c["name"]) == published_key]
            if published_key and len(published_matches) == 1:
                sitting_keys.add(published_matches[0]["ballot_entry_id"])
        past = _past_winners(by_state[state], 2026)
        returning, experience = 0.0, 0.0
        for candidate in candidates:
            group = stage3.party_group(candidate["party"])
            if group not in {"D", "R"}:
                continue
            sign = 1.0 if group == "D" else -1.0
            key = stage3.first_last_key(candidate["name"]), group
            if candidate["ballot_entry_id"] in sitting_keys:
                returning += sign
            elif key != prior_key and key in past:
                # A different person can share the incumbent's first and last
                # names (the two Dan Sullivans in Alaska are a live example).
                experience += sign
        # The Stage 2 incumbent flag is reviewed against the official previous
        # winner, including manual aliases. Do not infer it from duplicate
        # historical archive rows or a same-name winner of another contest.
        winner_running = bool(sitting_keys)
        beta = effects[office]["coefficients"]
        shifts = {"district_map":0.0, "governor_approval":0.0, "open_seat_candidate_experience":0.0}
        groups = {stage3.party_group(c["party"]) for c in candidates}
        if {"D","R"} <= groups:
            if office == "house":
                key = state + "-" + ("AL" if race["district_code"] == "00" else race["district_code"])
                shifts["district_map"] = maps[key]
                if abs(shifts["district_map"]) > 1e-6:
                    coverage["changed_house_map"] += 1
            open_seat = (1 if winner_group == "D" else -1) if winner_group in {"D","R"} and not winner_running else 0
            if office == "governor":
                # The governor open-seat term is superseded by the local-lean
                # model fitted in governor_local_lean.py. Applying both would
                # count the same open-seat structure twice.
                shifts["open_seat_candidate_experience"] = 0.0
            else:
                shifts["open_seat_candidate_experience"] = beta[0]*open_seat + beta[1]*experience
            if returning:
                coverage["returning_winner_races"] += 1
                if not reviewed_incumbents:
                    coverage["sitting_incumbent_source_matches"] += 1
            elif winner_group in {"D","R"}:
                coverage["open_seat_races"] += 1
            if experience:
                coverage["other_prior_officeholder_races"] += 1
            # Approval is retained only to verify the incumbent's identity. Its
            # forecast effect is disabled until dated historical replay is possible.
        output[race_id] = shifts
    meta = {"map":map_meta,"approval_source":"Morning Consult, October-December 2025 three-month registered-voter rollup",
            "approval_url":"https://pro.morningconsult.com/trackers/governor-approval-ratings",
            "governor_approval_forecast_effect":"disabled_pending_dated_historical_validation",
            "approval_survey_end":"2025-12-31", "approval_observations":len(approval),
            "approval_sha256":source_hash(APPROVAL/"morning_consult_2025q4_net.csv"),
            "historical_approval_source":"Singer State Executive Approval Dataset v1, UNC Dataverse doi:10.15139/S3/QHHQEF",
            "historical_approval_sha256":source_hash(APPROVAL/"sead_governor_quarterly_v1.csv"),
            "coverage":dict(coverage)}
    return output, meta


def shift_shares(shares: np.ndarray, log_odds_shift: float) -> np.ndarray:
    if abs(log_odds_shift) < 1e-12:
        return shares
    out = np.array(shares, copy=True)
    out[:, 0] *= math.exp(log_odds_shift/2)
    out[:, 1] *= math.exp(-log_odds_shift/2)
    return out/out.sum(axis=1, keepdims=True)


def shift_candidate_shares(shares: np.ndarray, candidates: list[dict[str, Any]],
                           log_odds_shift: float) -> np.ndarray:
    if abs(log_odds_shift) < 1e-12:
        return shares
    out = np.array(shares, copy=True)
    for i, candidate in enumerate(candidates):
        group = stage3.party_group(candidate["party"])
        if group == "D":
            out[:, i] *= math.exp(log_odds_shift/2)
        elif group == "R":
            out[:, i] *= math.exp(-log_odds_shift/2)
    return out/out.sum(axis=1, keepdims=True)
