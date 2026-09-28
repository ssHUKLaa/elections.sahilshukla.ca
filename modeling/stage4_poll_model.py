"""Fit, backtest, and run the Stage 4 candidate-vector polling update.

The model treats Stage 3 candidate shares as a logistic-normal prior. Poll
questions contribute named-candidate log-ratio contrasts. Historical poll
errors fit partially pooled pollster, population, method, sponsor, office, and
time effects. Polls sharing a race retain an empirical common-error floor.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from sklearn.covariance import LedoitWolf
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge


ROOT = Path(__file__).resolve().parents[1]
STAGE3_PATH = ROOT / "modeling" / "stage3_results_baseline.py"
SPEC = importlib.util.spec_from_file_location("stage3_results_baseline", STAGE3_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load Stage 3 model")
stage3 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage3
SPEC.loader.exec_module(stage3)

NATIONAL_PATH = ROOT / "modeling" / "national_environment.py"
NATIONAL_ERROR = ROOT / "data/reference/stage6_generic_error_calibration.json"
NATIONAL_SPEC = importlib.util.spec_from_file_location("national_environment", NATIONAL_PATH)
if NATIONAL_SPEC is None or NATIONAL_SPEC.loader is None:
    raise RuntimeError("Unable to load national environment model")
national_env = importlib.util.module_from_spec(NATIONAL_SPEC)
sys.modules[NATIONAL_SPEC.name] = national_env
NATIONAL_SPEC.loader.exec_module(national_env)
LOCAL_PATH = ROOT / "modeling" / "senate_local_lean.py"
LOCAL_SPEC = importlib.util.spec_from_file_location("senate_local_lean", LOCAL_PATH)
if LOCAL_SPEC is None or LOCAL_SPEC.loader is None:
    raise RuntimeError("Unable to load Senate local-lean model")
local_lean = importlib.util.module_from_spec(LOCAL_SPEC)
sys.modules[LOCAL_SPEC.name] = local_lean
LOCAL_SPEC.loader.exec_module(local_lean)
GOVERNOR_LOCAL_PATH = ROOT / "modeling" / "governor_local_lean.py"
GOVERNOR_LOCAL_SPEC = importlib.util.spec_from_file_location(
    "governor_local_lean", GOVERNOR_LOCAL_PATH,
)
if GOVERNOR_LOCAL_SPEC is None or GOVERNOR_LOCAL_SPEC.loader is None:
    raise RuntimeError("Unable to load governor local-lean model")
governor_local_lean = importlib.util.module_from_spec(GOVERNOR_LOCAL_SPEC)
sys.modules[GOVERNOR_LOCAL_SPEC.name] = governor_local_lean
GOVERNOR_LOCAL_SPEC.loader.exec_module(governor_local_lean)
SENATE_BIAS_PATH = ROOT / "modeling" / "senate_poll_bias.py"
SENATE_BIAS_SPEC = importlib.util.spec_from_file_location("senate_poll_bias", SENATE_BIAS_PATH)
if SENATE_BIAS_SPEC is None or SENATE_BIAS_SPEC.loader is None:
    raise RuntimeError("Unable to load Senate poll-bias calibration")
senate_bias = importlib.util.module_from_spec(SENATE_BIAS_SPEC)
sys.modules[SENATE_BIAS_SPEC.name] = senate_bias
SENATE_BIAS_SPEC.loader.exec_module(senate_bias)
STRUCTURAL_PATH = ROOT / "modeling" / "structural_uncertainty_2026.py"
STRUCTURAL_SPEC = importlib.util.spec_from_file_location("structural_uncertainty_2026", STRUCTURAL_PATH)
if STRUCTURAL_SPEC is None or STRUCTURAL_SPEC.loader is None:
    raise RuntimeError("Unable to load structural uncertainty model")
structural = importlib.util.module_from_spec(STRUCTURAL_SPEC)
sys.modules[STRUCTURAL_SPEC.name] = structural
STRUCTURAL_SPEC.loader.exec_module(structural)

MODEL_VERSION = "stage4-polls-2.0"
OFFICES = stage3.OFFICES
CUTOFF_DAYS = 43
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
HALF_LIVES = (14.0, 30.0, 60.0, 120.0)
CURRENT_POLL_HALF_LIFE_DAYS = 30.0
APPROVAL_BLEND_WEIGHT = 0.05


@dataclass(frozen=True)
class PollOption:
    candidate_key: str | None
    party_group: str | None
    pct: float
    response_kind: str
    label: str


@dataclass(frozen=True)
class PollQuestion:
    question_key: str
    poll_id: str
    race_key: str
    office: str
    pollster: str
    population: str
    methodology: str
    sponsor: str
    partisan: str
    internal: str
    sample_size: float
    election_date: datetime
    end_date: datetime
    available_date: datetime
    options: tuple[PollOption, ...]

    @property
    def days_before(self) -> float:
        return max(0.0, (self.election_date - self.end_date).days)


@dataclass
class BiasModel:
    vectorizer: DictVectorizer
    models: dict[int, Ridge]
    selected_alpha: dict[int, float]
    residual_variance: dict[str, dict[int, float]]
    shared_variance: dict[str, dict[int, float]]
    same_group_variance: dict[str, float]
    training_rows: dict[int, int]
    half_life_days: float
    senate_bias_model: Any | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_date(value: str | None) -> datetime:
    if not value:
        raise ValueError("missing date")
    token = value.strip().split()[0]
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(token, fmt)
        except ValueError:
            pass
    raise ValueError(f"unsupported date {value!r}")


def softmax(values: np.ndarray) -> np.ndarray:
    values = values - values.max(axis=-1, keepdims=True)
    weights = np.exp(np.clip(values, -50, 50))
    return weights / weights.sum(axis=-1, keepdims=True)


def alr_candidate(shares: np.ndarray) -> np.ndarray:
    shares = np.clip(shares, 1e-9, 1.0)
    return np.log(shares[..., :-1] / shares[..., [-1]])


def inv_alr_candidate(values: np.ndarray) -> np.ndarray:
    zeros = np.zeros((*values.shape[:-1], 1))
    return softmax(np.concatenate((values, zeros), axis=-1))


def psd_sqrt(matrix: np.ndarray, inverse: bool = False) -> np.ndarray:
    values, vectors = np.linalg.eigh((matrix + matrix.T) / 2)
    values = np.clip(values, 1e-9, None)
    powers = 1.0 / np.sqrt(values) if inverse else np.sqrt(values)
    return (vectors * powers) @ vectors.T


def contrast_row(candidate_count: int, left: int, right: int) -> np.ndarray:
    row = np.zeros(candidate_count - 1)
    if left < candidate_count - 1:
        row[left] += 1.0
    if right < candidate_count - 1:
        row[right] -= 1.0
    return row


def question_features(question: PollQuestion) -> dict[str, float | str]:
    return {
        "office": question.office,
        "pollster": question.pollster or "unknown",
        "population": question.population or "unknown",
        "methodology": question.methodology or "unknown",
        "sponsor": "sponsored" if question.sponsor else "unsponsored",
        "partisan": question.partisan or "none",
        "internal": question.internal or "false",
        "days_scaled": question.days_before / 100.0,
        "log_n": math.log(max(question.sample_size, 100.0)) / 10.0,
    }


def question_group_coords(question: PollQuestion) -> tuple[float | None, float | None]:
    totals = defaultdict(float)
    for option in question.options:
        if option.candidate_key and option.party_group:
            totals[option.party_group] += max(option.pct, 0.0)
    first = None
    second = None
    if totals["D"] > 0 and totals["R"] > 0:
        first = math.log(totals["D"] / totals["R"])
    if totals["D"] + totals["R"] > 0 and totals["O"] > 0:
        second = math.log((totals["D"] + totals["R"]) / totals["O"])
    return first, second


def race_actual_coords(race: Any) -> tuple[float, float]:
    return tuple(float(value) for value in stage3.alr(stage3.group_shares(race)))


def deduplicate_questions(questions: list[PollQuestion]) -> list[PollQuestion]:
    selected: dict[tuple[str, str], PollQuestion] = {}
    for question in questions:
        key = (question.race_key, question.poll_id)
        mapped = sum(option.candidate_key is not None for option in question.options)
        existing = selected.get(key)
        existing_mapped = sum(option.candidate_key is not None for option in existing.options) if existing else -1
        if existing is None or (mapped, question.question_key) > (existing_mapped, existing.question_key):
            selected[key] = question
    return sorted(selected.values(), key=lambda q: (q.race_key, q.available_date, q.poll_id))


def load_historical_questions(connection: sqlite3.Connection) -> list[PollQuestion]:
    rows = connection.execute(
        """SELECT * FROM historical_poll_questions
        WHERE office IN ('house','senate','governor') AND stage='general'
        ORDER BY source_key,question_key"""
    ).fetchall()
    options_by_question: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for option in connection.execute(
        """SELECT * FROM historical_poll_options
        ORDER BY source_key,question_key,option_index"""
    ):
        options_by_question[(option["source_key"], option["question_key"])].append(option)
    output = []
    for row in rows:
        try:
            raw = json.loads(row["raw_json"])
            election_date = parse_date(row["election_date"])
            end_date = parse_date(row["end_date"])
            available = parse_date(row["source_created_at"])
        except (ValueError, json.JSONDecodeError):
            continue
        options = []
        for option in options_by_question[(row["source_key"], row["question_key"])]:
            candidate_key = option["source_candidate_id"] if option["response_kind"] == "candidate" else None
            options.append(PollOption(
                candidate_key=candidate_key,
                party_group=stage3.party_group(option["party"]) if candidate_key else None,
                pct=float(option["pct"] or 0.0), response_kind=option["response_kind"],
                label=option["candidate_name"] or option["answer"] or "",
            ))
        output.append(PollQuestion(
            question_key=row["question_key"], poll_id=row["source_poll_id"],
            race_key=row["source_race_id"], office=row["office"],
            pollster=row["pollster"] or "unknown", population=row["population"] or "unknown",
            methodology=row["methodology"] or "unknown", sponsor=raw.get("sponsors", "") or "",
            partisan=raw.get("partisan", "") or "", internal=raw.get("internal", "") or "",
            sample_size=float(row["sample_size"] or 600.0), election_date=election_date,
            end_date=end_date, available_date=available, options=tuple(options),
        ))
    return deduplicate_questions(output)


def senate_archive_questions(
    observations: list[senate_bias.Observation], races_by_id: dict[str, Any], cycle: int,
) -> list[PollQuestion]:
    """Two-party Senate questions for independent full-model cycle checks.

    The archive has fieldwork end dates but no publication timestamps, so the
    end date is a provisional availability date. This can favor the holdout
    by a few days near its cutoff and is recorded as a limitation.
    """
    output = []
    for index, row in enumerate(observations):
        if row.cycle != cycle:
            continue
        race = races_by_id[row.race_key]
        candidates = {
            group: [candidate for candidate in race.candidates if candidate.group == group]
            for group in ("D", "R")
        }
        if any(len(candidates[group]) != 1 for group in candidates):
            continue
        options = tuple(PollOption(
            candidate_key=candidates[group][0].candidate_key,
            party_group=group, pct=percent, response_kind="candidate",
            label=candidates[group][0].name,
        ) for group, percent in (("D", row.pct_d), ("R", row.pct_r)))
        output.append(PollQuestion(
            question_key=f"rcp:{cycle}:{row.race_key}:{index}",
            poll_id=f"rcp:{cycle}:{row.race_key}:{index}", race_key=row.race_key,
            office="senate", pollster=row.pollster, population=row.population,
            methodology="unknown", sponsor="", partisan="", internal="",
            sample_size=row.sample_size, election_date=senate_bias.election_day(cycle),
            end_date=row.end_date, available_date=row.end_date, options=options,
        ))
    return output


def load_current_questions(stage2_connection: sqlite3.Connection, stage1_path: Path) -> list[PollQuestion]:
    stage2_connection.execute("ATTACH DATABASE ? AS live", (str(stage1_path),))
    rows = stage2_connection.execute(
        """SELECT qm.*,q.source_poll_id,q.sample_size,q.population,q.election_date,q.raw_question_json,
        p.pollster,p.methodology,p.sponsors,p.start_date,p.end_date,p.source_created_at,p.raw_poll_json
        FROM current_question_map qm
        JOIN live.questions q ON q.snapshot_id=qm.snapshot_id AND q.question_key=qm.question_key
        JOIN live.polls p ON p.snapshot_id=q.snapshot_id AND p.feed=q.feed AND p.source_poll_id=q.source_poll_id
        WHERE qm.model_eligible=1 ORDER BY qm.question_key"""
    ).fetchall()
    option_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for option in stage2_connection.execute(
        """SELECT o.* FROM current_option_map o
        JOIN current_question_map q ON q.snapshot_id=o.snapshot_id AND q.question_key=o.question_key
        WHERE q.model_eligible=1 ORDER BY o.question_key,o.option_index"""
    ):
        option_rows[option["question_key"]].append(option)
    output = []
    for row in rows:
        try:
            raw = json.loads(row["raw_poll_json"])
            raw_question = json.loads(row["raw_question_json"])
            election_date = parse_date(row["election_date"])
            end_date = parse_date(row["end_date"])
            available = parse_date(row["source_created_at"])
        except (ValueError, json.JSONDecodeError):
            continue
        options = []
        for option in option_rows[row["question_key"]]:
            key = option["ballot_entry_id"] if option["mapping_status"].startswith("mapped") else None
            options.append(PollOption(
                candidate_key=key,
                party_group=stage3.party_group(option["source_party"]) if key else None,
                pct=float(option["pct"] or 0.0), response_kind=option["response_kind"],
                label=option["source_candidate_name"] or option["source_answer"] or "",
            ))
        output.append(PollQuestion(
            question_key=row["question_key"], poll_id=row["source_poll_id"],
            race_key=row["project_race_id"], office=stage2_connection.execute(
                "SELECT office FROM races WHERE race_id=?", (row["project_race_id"],)
            ).fetchone()[0],
            pollster=row["pollster"] or "unknown", population=row["population"] or "unknown",
            methodology=row["methodology"] or "unknown", sponsor=row["sponsors"] or "",
            partisan=raw_question.get("partisan", "") or "", internal=raw.get("internal", "") or "",
            sample_size=float(row["sample_size"] or 600.0), election_date=election_date,
            end_date=end_date, available_date=available, options=tuple(options),
        ))
    stage2_connection.execute("DETACH DATABASE live")
    return deduplicate_questions(output)


def margin_to_logratio(margin: float) -> float:
    return math.log((1.0+margin)/(1.0-margin))


def weighted_mean_variance(values: list[float], weights: list[float]) -> tuple[float, float, float]:
    array = np.asarray(values, dtype=float)
    weight = np.asarray(weights, dtype=float)
    mean = float(np.average(array, weights=weight))
    variance = float(np.average((array-mean)**2, weights=weight))
    effective = float(weight.sum()**2 / max(np.sum(weight**2), 1e-9))
    return mean, variance, effective


def generic_observations(
    connection: sqlite3.Connection, stage1_path: Path, cutoff: datetime,
    quality_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    connection.execute("ATTACH DATABASE ? AS national_live", (str(stage1_path),))
    rows = connection.execute(
        """SELECT m.question_key,q.source_poll_id,q.sample_size,q.population,
        p.pollster,p.end_date,p.source_created_at
        FROM current_question_map m
        JOIN national_live.questions q ON q.snapshot_id=m.snapshot_id AND q.question_key=m.question_key
        JOIN national_live.polls p ON p.snapshot_id=q.snapshot_id AND p.feed=q.feed AND p.source_poll_id=q.source_poll_id
        WHERE m.observation_type='generic_ballot' ORDER BY m.question_key"""
    ).fetchall()
    options = defaultdict(dict)
    for row in connection.execute(
        """SELECT o.question_key,o.source_party,o.pct FROM current_option_map o
        JOIN current_question_map m ON m.snapshot_id=o.snapshot_id AND m.question_key=o.question_key
        WHERE m.observation_type='generic_ballot' AND o.source_party IN ('DEM','REP')"""
    ):
        options[row["question_key"]][row["source_party"]] = float(row["pct"])
    priority = {"lv": 4, "rv": 3, "v": 2, "a": 1}
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (quality_weights or {}).get(row["source_poll_id"], 1.0) <= 0:
            continue
        shares = options[row["question_key"]]
        if not {"DEM", "REP"} <= shares.keys() or min(shares.values()) <= 0:
            continue
        try:
            end = parse_date(row["end_date"])
            available = parse_date(row["source_created_at"])
        except ValueError:
            continue
        if available > cutoff or end > cutoff:
            continue
        item = {
            "question_key": row["question_key"], "poll_id": row["source_poll_id"],
            "pollster": row["pollster"] or "unknown", "population": row["population"] or "unknown",
            "sample_size": float(row["sample_size"] or 600), "end_date": end,
            "logratio": math.log(shares["DEM"]/shares["REP"]),
            "quality_weight": (quality_weights or {}).get(row["source_poll_id"], 1.0),
        }
        old = selected.get(item["poll_id"])
        rank = (priority.get(item["population"], 0), item["sample_size"], item["question_key"])
        old_rank = (priority.get(old["population"], 0), old["sample_size"], old["question_key"]) if old else None
        if old is None or rank > old_rank:
            selected[item["poll_id"]] = item
    connection.execute("DETACH DATABASE national_live")
    return sorted(selected.values(), key=lambda item: (item["end_date"], item["poll_id"]))


def historical_generic_benchmark(
    connection: sqlite3.Connection, historical_races: list[Any], cutoff_days: int,
    max_age_days: int | None = None,
) -> dict[str, float]:
    cutoff = datetime(2020, 11, 3)-timedelta(days=cutoff_days)
    values, weights = [], []
    seen_polls = set()
    for row in connection.execute(
        """SELECT q.source_key,q.question_key,q.source_poll_id,q.end_date,q.source_created_at,q.sample_size
        FROM historical_poll_questions q
        WHERE q.office='generic_ballot' AND q.cycle=2020 ORDER BY q.source_created_at DESC,q.question_key"""
    ):
        if row["source_poll_id"] in seen_polls:
            continue
        try:
            end = parse_date(row["end_date"])
            available = parse_date(row["source_created_at"])
        except ValueError:
            continue
        if available > cutoff or end > cutoff:
            continue
        shares = {
            option["party"]: float(option["pct"])
            for option in connection.execute(
                """SELECT party,pct FROM historical_poll_options
                WHERE source_key=? AND question_key=? AND party IN ('DEM','REP')""",
                (row["source_key"], row["question_key"]),
            )
        }
        if not {"DEM", "REP"} <= shares.keys() or min(shares.values()) <= 0:
            continue
        age = max(0, (cutoff-end).days)
        if max_age_days is not None and age > max_age_days:
            continue
        weight = math.exp(-math.log(2)*age/30.0)*math.sqrt(max(float(row["sample_size"] or 600), 100)/600)
        values.append(math.log(shares["DEM"]/shares["REP"]))
        weights.append(weight)
        seen_polls.add(row["source_poll_id"])
    mean, variance, effective = weighted_mean_variance(values, weights)
    dem = rep = 0.0
    for party, votes in connection.execute(
        """SELECT party,SUM(votes) FROM fec_candidate_results
        WHERE cycle=2020 AND office='house' GROUP BY party"""
    ):
        if stage3.party_group(party) == "D":
            dem += votes
        elif stage3.party_group(party) == "R":
            rep += votes
    actual = math.log(dem/rep)
    return {
        "poll_mean_logratio": mean, "actual_logratio": actual,
        "absolute_2020_miss": abs(mean-actual), "poll_variance": variance,
        "effective_poll_count": effective, "poll_count": len(values),
    }


def blend_national_signals(
    generic_mean: float, generic_sd: float, approval_mean: float,
    approval_sd: float, approval_weight: float,
) -> tuple[float, float]:
    """Small policy blend with an SD bound valid for any error correlation."""
    if not 0 <= approval_weight <= 1:
        raise ValueError("Approval blend weight must be in [0, 1]")
    if generic_sd <= 0 or approval_sd <= 0:
        raise ValueError("National signal standard deviations must be positive")
    generic_weight = 1.0-approval_weight
    mean = generic_weight*generic_mean + approval_weight*approval_mean
    # Triangle inequality corresponds to the maximum variance over unknown
    # correlation in [-1, 1]; the additional signal cannot narrow uncertainty.
    sd_upper_bound = generic_weight*generic_sd + approval_weight*approval_sd
    return mean, sd_upper_bound**2


def fit_national_signal_update(
    connection: sqlite3.Connection, stage1_path: Path, historical_races: list[Any],
    current: list[dict[str, Any]], prior_draws: dict[str, np.ndarray], cutoff: datetime,
    *, include_generic: bool = True, include_fundamentals: bool = True,
    include_senate_local_lean: bool = True,
    include_governor_local_lean: bool = False,
    nowcast: bool = False, quality_weights: dict[str, float] | None = None,
    governor_uncertainty_seed: int = 0,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    generic = generic_observations(connection, stage1_path, cutoff, quality_weights)
    recent = [item for item in generic if (cutoff-item["end_date"]).days <= 180]
    values = [item["logratio"] for item in recent]
    weights = [
        math.exp(-math.log(2)*max(0, (cutoff-item["end_date"]).days)/30.0)
        * math.sqrt(max(item["sample_size"], 100)/600)
        * item["quality_weight"]
        for item in recent
    ]
    generic_mean, generic_variance, generic_effective = weighted_mean_variance(values, weights)
    if nowcast:
        # Recent seven-day terminal misses proxy survey error. Use their RMS
        # magnitude for uncertainty; their signed mean cannot identify a
        # held-today partisan correction because late movement is included.
        historical = json.loads(NATIONAL_ERROR.read_text(encoding="utf-8"))
        if historical["training_cycles"] != [2020, 2022, 2024] or historical["cutoff_days_before_election"] != 7:
            raise ValueError("Unexpected pinned generic-ballot error calibration")
        generic_sd = math.sqrt(
            generic_variance/max(generic_effective, 1.0)
            + historical["rms_error_logratio"]**2
        )
        snapshot_id = dict(connection.execute("SELECT key,value FROM build_metadata"))["source_snapshot_id"]
        fundamentals = national_env.current_estimate(stage1_path, cutoff.date(), snapshot_id)
        fundamentals["nowcast_interpretation"] = (
            "Approval-conditioned historical House-vote prediction used as a "
            "national prior proxy; its target is the eventual election result, "
            "so this remains provisional for voting at the cutoff."
        )
        fundamentals_mean = margin_to_logratio(fundamentals["margin"])
        fundamentals_sd = 2.0*fundamentals["margin_sd"]/(1.0-fundamentals["margin"]**2)
    else:
        historical = historical_generic_benchmark(connection, historical_races, CUTOFF_DAYS)
        generic_sd = math.sqrt(
            generic_variance/max(generic_effective, 1.0) + historical["absolute_2020_miss"]**2
        )
        generic_sd = max(generic_sd, 0.02)
        snapshot_id = dict(connection.execute("SELECT key,value FROM build_metadata"))["source_snapshot_id"]
        fundamentals = national_env.current_estimate(stage1_path, cutoff.date(), snapshot_id)
        fundamentals_mean = margin_to_logratio(fundamentals["margin"])
        fundamentals_sd = 2.0*fundamentals["margin_sd"]/(1.0-fundamentals["margin"]**2)

    house_ids = [item["race"]["race_id"] for item in current if item["race"]["office"] == "house"]
    house_groups = {
        item["race"]["race_id"]: [stage3.party_group(candidate["party"]) for candidate in item["candidates"]]
        for item in current if item["race"]["office"] == "house"
    }
    draw_count = len(next(iter(prior_draws.values())))
    dem = np.zeros(draw_count)
    rep = np.zeros(draw_count)
    for race_id in house_ids:
        draws = prior_draws[race_id]
        for index, group in enumerate(house_groups[race_id]):
            if group == "D":
                dem += draws[:, index]
            elif group == "R":
                rep += draws[:, index]
    prior_national = np.log(np.clip(dem, 1e-9, None)/np.clip(rep, 1e-9, None))
    prior_mean = float(prior_national.mean())
    prior_variance = float(np.var(prior_national, ddof=1))

    # Stage 3 supplies local deviations and shared structure. The live
    # national center is mostly generic ballot, with a small approval blend.
    # Their joint error has not been identified with the available archive.
    def posterior(include_generic: bool = True, include_fundamentals: bool = True,
                  generic_value: float = generic_mean,
                  generic_sd_multiplier: float = 1.0,
                  fundamentals_sd_multiplier: float = 1.0,
                  combine_with_prior: bool = False) -> tuple[float, float]:
        if nowcast:
            selected_mean = fundamentals_mean if include_fundamentals else prior_mean
            selected_variance = (
                (fundamentals_sd*fundamentals_sd_multiplier)**2
                if include_fundamentals else prior_variance
            )
            if not include_generic:
                return selected_mean, selected_variance
            observation_variance = (generic_sd*generic_sd_multiplier)**2
            if not combine_with_prior:
                if not include_fundamentals:
                    return generic_value, observation_variance
                return blend_national_signals(
                    generic_value, math.sqrt(observation_variance),
                    selected_mean, math.sqrt(selected_variance),
                    APPROVAL_BLEND_WEIGHT,
                )
            variance = 1.0/(1.0/selected_variance + 1.0/observation_variance)
            mean = variance*(selected_mean/selected_variance + generic_value/observation_variance)
            return mean, variance
        fundamental_variance = (fundamentals_sd*fundamentals_sd_multiplier)**2
        if not include_fundamentals:
            if not include_generic:
                raise ValueError("At least one national signal is required")
            return generic_value, (generic_sd*generic_sd_multiplier)**2
        if not include_generic:
            return fundamentals_mean, fundamental_variance
        observation_variance = (generic_sd*generic_sd_multiplier)**2
        variance = 1.0/(1.0/fundamental_variance + 1.0/observation_variance)
        mean = variance*(fundamentals_mean/fundamental_variance + generic_value/observation_variance)
        return mean, variance

    posterior_mean, posterior_variance = posterior(
        include_generic=include_generic, include_fundamentals=include_fundamentals
    )
    transformed_national = posterior_mean + (prior_national-prior_mean)*math.sqrt(posterior_variance/prior_variance)
    shift = transformed_national-prior_national
    updated = {}
    for item in current:
        race_id = item["race"]["race_id"]
        draws = prior_draws[race_id].copy()
        groups = [stage3.party_group(candidate["party"]) for candidate in item["candidates"]]
        multiplier = np.ones_like(draws)
        for index, group in enumerate(groups):
            if group == "D":
                multiplier[:, index] = np.exp(shift/2)
            elif group == "R":
                multiplier[:, index] = np.exp(-shift/2)
        draws *= multiplier
        draws /= draws.sum(axis=1, keepdims=True)
        updated[race_id] = draws

    senate_local_predictions, senate_local_report = (
        local_lean.build_current(current) if include_senate_local_lean else ({}, {"audit_omitted": True})
    )
    for item in current:
        race_id = item["race"]["race_id"]
        if race_id not in senate_local_predictions:
            continue
        draws = updated[race_id]
        groups = [stage3.party_group(candidate["party"]) for candidate in item["candidates"]]
        if "D" not in groups or "R" not in groups:
            continue
        d = draws[:, [i for i, group in enumerate(groups) if group == "D"]].sum(axis=1)
        r = draws[:, [i for i, group in enumerate(groups) if group == "R"]].sum(axis=1)
        existing = np.log(np.clip(d, 1e-9, None)/np.clip(r, 1e-9, None))
        # Preserve local and office residuals while replacing the race mean.
        local_residual = existing-transformed_national
        local_residual -= local_residual.mean()
        fitted_lean = senate_local_predictions[race_id]["predicted_lean"]
        target_margin = np.clip(np.tanh(transformed_national/2)+fitted_lean, -0.95, 0.95)
        desired = np.log((1+target_margin)/(1-target_margin))+local_residual
        adjustment = desired-existing
        for index, group in enumerate(groups):
            if group == "D":
                draws[:, index] *= np.exp(adjustment/2)
            elif group == "R":
                draws[:, index] *= np.exp(-adjustment/2)
        draws /= draws.sum(axis=1, keepdims=True)
        updated[race_id] = draws

    governor_local_report = {"enabled": False, "reason": "disabled_for_this_call"}
    if include_governor_local_lean:
        transitions = stage3.build_transitions(historical_races)
        database_path = Path(connection.execute("PRAGMA database_list").fetchone()[2])
        governor_predictions, governor_fit = governor_local_lean.predict_current(
            current, historical_races, transitions, database_path,
        )
        race_impacts = []
        for item in current:
            race_id = item["race"]["race_id"]
            prediction = governor_predictions.get(race_id)
            if prediction is None:
                continue
            draws = updated[race_id]
            groups = [stage3.party_group(candidate["party"]) for candidate in item["candidates"]]
            d_indices = [index for index, group in enumerate(groups) if group == "D"]
            r_indices = [index for index, group in enumerate(groups) if group == "R"]
            if not d_indices or not r_indices:
                continue
            d = draws[:, d_indices].sum(axis=1)
            r = draws[:, r_indices].sum(axis=1)
            before_d_lead = float(np.mean(np.isin(np.argmax(draws, axis=1), d_indices)))
            before_margin = float(np.mean((d - r) / np.clip(d + r, 1e-12, None)))
            residual_seed = int.from_bytes(hashlib.sha256(
                f"{governor_uncertainty_seed}:{race_id}".encode("utf-8")
            ).digest()[:8], "big")
            draws, uncertainty_report = governor_local_lean.recenter_candidate_draws(
                draws, groups, transformed_national, prediction["predicted_lean"],
                prediction.get("uncertainty_logratio_sd"), residual_seed,
            )
            updated[race_id] = draws
            after_d = draws[:, d_indices].sum(axis=1)
            after_r = draws[:, r_indices].sum(axis=1)
            after_leaders = np.argmax(draws, axis=1)
            after_d_lead = float(np.mean(np.isin(after_leaders, d_indices)))
            after_margin = float(np.mean((after_d - after_r)
                                         / np.clip(after_d + after_r, 1e-12, None)))
            race_impacts.append({
                "race_id": race_id, "state": item["race"]["state"],
                "predicted_local_lean": prediction["predicted_lean"],
                "inputs": prediction["inputs"],
                "uncertainty_calibration": {
                    **prediction.get("uncertainty_calibration", {}),
                    **uncertainty_report,
                },
                "pre_poll_margin_before": before_margin,
                "pre_poll_margin_after": after_margin,
                "pre_poll_D_leader_probability_before": before_d_lead,
                "pre_poll_D_leader_probability_after": after_d_lead,
            })
        governor_local_report = {
            "enabled": True,
            "estimand": "state governor D-minus-R margin relative to the drawn national House margin",
            "selected_specification": governor_fit["selected_specification"],
            "selected_ridge_alpha": governor_fit["selected_ridge_alpha"],
            "coefficients": governor_fit["coefficients"],
            "uncertainty_calibration": governor_fit["uncertainty_calibration"],
            "subgroup_scores": governor_fit["subgroup_scores"],
            "excluded_missing_major_party_rows": governor_fit["excluded_missing_major_party_rows"],
            "training_rows": governor_fit["training_rows"],
            "training_cycles": governor_fit["training_cycles"],
            "expanding_cycle_tuning": governor_fit["expanding_cycle_evaluation"]["selected"]["tuning"],
            "expanding_cycle_later_check": governor_fit["expanding_cycle_evaluation"]["selected"]["later_cycles"],
            "candidate_specification_scores": governor_fit["expanding_cycle_evaluation"]["scores"],
            "current_race_impacts": race_impacts,
            "source_hashes": governor_fit["source_hashes"],
            "legacy_governor_open_seat_shift": "disabled; open-seat status is not separately applied",
        }

    sensitivity = {}
    sensitivity_cases = ({
        "generic_only": {"include_fundamentals": False},
        "structural_prior_plus_generic": {"include_fundamentals": False, "combine_with_prior": True},
        "approval_prior_plus_generic_legacy": {"combine_with_prior": True},
        "approval_prior_only": {"include_generic": False},
        "generic_error_doubled": {"generic_sd_multiplier": 2.0},
        "FLIPR_adjusted_generic_D_plus_8_6": {"generic_value": margin_to_logratio(0.086)},
    } if nowcast else {
        "fundamentals_only": {"include_generic": False},
        "both_default": {},
        "generic_error_doubled": {"generic_sd_multiplier": 2.0},
        "fundamentals_error_doubled": {"fundamentals_sd_multiplier": 2.0},
        "both_FLIPR_adjusted_generic_D_plus_8_6": {"generic_value": margin_to_logratio(0.086)},
    })
    for label, kwargs in sensitivity_cases.items():
        mean, variance = posterior(**kwargs)
        sensitivity[label] = {
            "national_D_R_logratio_mean": mean, "national_D_R_logratio_sd": math.sqrt(variance),
            "implied_D_two_party_margin": math.tanh(mean/2),
        }
    return updated, {
        "prior": {
            "national_D_R_logratio_mean": prior_mean, "national_D_R_logratio_sd": math.sqrt(prior_variance),
            "implied_D_two_party_margin": math.tanh(prior_mean/2),
        },
        "approval_conditioned_prior": ({
            "national_D_R_logratio_mean": fundamentals_mean,
            "national_D_R_logratio_sd": fundamentals_sd,
            "implied_D_two_party_margin": fundamentals["margin"],
        } if nowcast else None),
        "generic_ballot": {
            "raw_logratio_mean": generic_mean, "raw_implied_D_two_party_margin": math.tanh(generic_mean/2),
            "observation_sd_logratio": generic_sd, "poll_count_last_180_days": len(recent),
            "effective_poll_count": generic_effective, "half_life_days": 30,
            "historical_error_calibration": historical,
            "nowcast_quality_weighted": nowcast,
            "FLIPR_likely_voter_adjusted_context": {
                "implied_D_two_party_margin": 0.086,
                "source": "User-supplied Nate Silver/FLIPR description",
                "use_in_likelihood": "sensitivity case only; it is an adjusted view of the same generic-ballot evidence and is not counted as an independent observation",
            },
        },
        "historical_fundamentals": fundamentals,
        "senate_local_lean": senate_local_report,
        "governor_local_lean": governor_local_report,
        "national_center_source": "generic_ballot_with_small_approval_blend" if nowcast else "fundamentals_plus_generic",
        "approval_blend_weight": APPROVAL_BLEND_WEIGHT if nowcast else None,
        "combination_limitation": (
            "Nowcast blends 95% of the current generic-ballot D/R log ratio with 5% of the approval-and-previous-vote fit. This 5% weight is a stated modeling choice, not historically calibrated. The SD uses a perfect-positive-correlation upper bound, so the approval signal does not create false precision. Generic-ballot uncertainty uses the RMS of three recent seven-day terminal-proxy misses; current-support uncertainty is not fully validated, and economic sentiment is not an input."
            if nowcast else
            "Historical fundamentals and generic-ballot errors are treated as conditionally independent. Their covariance is not identifiable from the current two-cycle generic archive; this run remains internal."
        ),
        "posterior": {
            "national_D_R_logratio_mean": posterior_mean,
            "national_D_R_logratio_sd": math.sqrt(posterior_variance),
            "implied_D_two_party_margin": math.tanh(posterior_mean/2),
        },
        "sensitivity": sensitivity,
    }


def eligible_at_cutoff(question: PollQuestion, cutoff_days: int) -> bool:
    cutoff = question.election_date - timedelta(days=cutoff_days)
    return question.available_date <= cutoff and question.end_date <= cutoff


def ridge_cv(x: np.ndarray, y: np.ndarray, groups: list[str]) -> tuple[Ridge, float]:
    fold = np.array([int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 5 for group in groups])
    scores = {}
    for alpha in ALPHAS:
        errors = []
        for held in range(5):
            train = fold != held
            test = fold == held
            if train.sum() < 20 or not test.any():
                continue
            model = Ridge(alpha=alpha).fit(x[train], y[train])
            errors.extend((y[test] - model.predict(x[test])) ** 2)
        scores[alpha] = float(np.mean(errors)) if errors else math.inf
    selected = min(scores, key=scores.get)
    return Ridge(alpha=selected).fit(x, y), float(selected)


def intraclass_floor(residuals: list[tuple[str, float]], total_variance: float) -> float:
    grouped: dict[str, list[float]] = defaultdict(list)
    for race_key, value in residuals:
        grouped[race_key].append(value)
    within = [np.var(values, ddof=1) for values in grouped.values() if len(values) > 1]
    means = [np.mean(values) for values in grouped.values()]
    mean_n = np.mean([len(values) for values in grouped.values()]) if grouped else 1.0
    within_variance = float(np.mean(within)) if within else total_variance
    between = float(np.var(means, ddof=1)) if len(means) > 1 else total_variance
    floor = max(0.0, between - within_variance / max(mean_n, 1.0))
    return min(max(floor, 0.05 * total_variance), 0.9 * total_variance)


def fit_bias_model(
    questions: list[PollQuestion], races_by_id: dict[str, Any], training_cycle: int = 2018,
    senate_training_through: int = 2024,
) -> BiasModel:
    samples: dict[int, list[tuple[dict[str, Any], float, str, str, str]]] = {0: [], 1: []}
    same_group: dict[str, list[float]] = defaultdict(list)
    for question in questions:
        race = races_by_id.get(question.race_key)
        if race is None or race.cycle != training_cycle or not eligible_at_cutoff(question, CUTOFF_DAYS):
            continue
        actual_coords = race_actual_coords(race)
        observed = question_group_coords(question)
        for coordinate in range(2):
            if observed[coordinate] is not None:
                samples[coordinate].append((
                    question_features(question), observed[coordinate] - actual_coords[coordinate],
                    question.race_key, question.office, question.poll_id,
                ))
        actual_by_id = {candidate.candidate_key: candidate for candidate in race.candidates}
        mapped = [option for option in question.options if option.candidate_key in actual_by_id and option.pct > 0]
        for i, left in enumerate(mapped):
            for right in mapped[i+1:]:
                if left.party_group != right.party_group:
                    continue
                left_actual = actual_by_id[left.candidate_key].votes + 0.5
                right_actual = actual_by_id[right.candidate_key].votes + 0.5
                same_group[question.office].append(
                    math.log(left.pct/right.pct) - math.log(left_actual/right_actual)
                )

    vectorizer = DictVectorizer(sparse=False)
    all_features = [item[0] for coordinate in samples.values() for item in coordinate]
    vectorizer.fit(all_features)
    models = {}
    selected_alpha = {}
    residual_variance: dict[str, dict[int, float]] = {office: {} for office in OFFICES}
    shared_variance: dict[str, dict[int, float]] = {office: {} for office in OFFICES}
    training_rows = {}
    for coordinate in range(2):
        rows = samples[coordinate]
        x = vectorizer.transform([item[0] for item in rows])
        y = np.array([item[1] for item in rows])
        model, alpha = ridge_cv(x, y, [item[2] for item in rows])
        models[coordinate] = model
        selected_alpha[coordinate] = alpha
        training_rows[coordinate] = len(rows)
        predictions = model.predict(x)
        for office in OFFICES:
            office_rows = [(rows[index][2], y[index]-predictions[index]) for index in range(len(rows)) if rows[index][3] == office]
            values = [value for _, value in office_rows]
            variance = float(np.var(values, ddof=1)) if len(values) > 2 else float(np.var(y-predictions, ddof=1))
            residual_variance[office][coordinate] = max(variance, 0.01)
            shared_variance[office][coordinate] = intraclass_floor(office_rows, residual_variance[office][coordinate])
    same_group_variance = {
        office: max(float(np.var(values, ddof=1)), 0.05) if len(values) > 2 else 1.0
        for office, values in ((office, same_group[office]) for office in OFFICES)
    }
    provisional = BiasModel(
        vectorizer, models, selected_alpha, residual_variance, shared_variance,
        same_group_variance, training_rows, 60.0,
    )
    provisional.half_life_days = select_half_life(questions, races_by_id, provisional, training_cycle)
    senate_rows, _ = senate_bias.load_observations(list(races_by_id.values()), CUTOFF_DAYS)
    provisional.senate_bias_model, _ = senate_bias.fit_through_cycle(
        senate_rows, senate_training_through
    )
    return provisional


def predict_bias(model: BiasModel, question: PollQuestion) -> tuple[float, float]:
    x = model.vectorizer.transform([question_features(question)])
    first = float(model.models[0].predict(x)[0])
    if question.office == "senate" and model.senate_bias_model is not None:
        first = model.senate_bias_model.predict(
            question.pollster, question.population, question.sample_size
        )
    return first, float(model.models[1].predict(x)[0])


def poll_pair_bias(model: BiasModel, question: PollQuestion, left_group: str, right_group: str) -> float:
    first, second = predict_bias(model, question)
    if (left_group, right_group) == ("D", "R"):
        return first
    if (left_group, right_group) == ("R", "D"):
        return -first
    utility = {"D": second + first/2, "R": second - first/2, "O": 0.0}
    return utility[left_group] - utility[right_group]


def pair_variance(model: BiasModel, office: str, left_group: str, right_group: str) -> tuple[float, float]:
    if {left_group, right_group} == {"D", "R"}:
        return model.residual_variance[office][0], model.shared_variance[office][0]
    if left_group == right_group:
        variance = model.same_group_variance[office]
        return variance, 0.15 * variance
    total = model.residual_variance[office][1] + 0.25 * model.residual_variance[office][0]
    shared = model.shared_variance[office][1] + 0.25 * model.shared_variance[office][0]
    return total, min(shared, 0.9*total)


def poll_contrasts(
    questions: list[PollQuestion], candidate_keys: list[str], candidate_groups: list[str],
    model: BiasModel, cutoff_date: datetime,
    *, quality_weights: dict[str, float] | None = None,
    apply_election_day_bias: bool = True,
) -> tuple[list[np.ndarray], list[float], list[float], dict[str, Any]]:
    index = {key: position for position, key in enumerate(candidate_keys)}
    grouped: dict[tuple[int, int], list[tuple[float, float, float, PollQuestion]]] = defaultdict(list)
    used_polls: set[str] = set()
    used_pollsters: set[str] = set()
    latest: datetime | None = None
    noncandidate_mass = []
    for question in questions:
        if (quality_weights or {}).get(question.poll_id, 1.0) <= 0:
            continue
        mapped = [option for option in question.options if option.candidate_key in index and option.pct > 0]
        if len(mapped) < 2:
            continue
        mapped.sort(key=lambda option: index[option.candidate_key])
        # Keep a directly observed D/R contrast when both major parties are
        # named. Using an other-party reference would turn that comparison
        # into two much noisier major/other contrasts under the diagonal
        # likelihood approximation below.
        reference = max(
            mapped,
            key=lambda option: (
                candidate_groups[index[option.candidate_key]] == "R",
                candidate_groups[index[option.candidate_key]] == "D",
                option.pct,
            ),
        )
        ref_index = index[reference.candidate_key]
        for option in mapped:
            if option.candidate_key == reference.candidate_key:
                continue
            left_index = index[option.candidate_key]
            observed = math.log(option.pct/reference.pct)
            bias = (poll_pair_bias(model, question, candidate_groups[left_index], candidate_groups[ref_index])
                    if apply_election_day_bias else 0.0)
            total_var, shared_var = pair_variance(
                model, question.office, candidate_groups[left_index], candidate_groups[ref_index]
            )
            age = max(0.0, (cutoff_date-question.end_date).days)
            recency = math.exp(-math.log(2)*age/model.half_life_days)
            sample_weight = math.sqrt(max(question.sample_size, 100.0)/600.0)
            quality = (quality_weights or {}).get(question.poll_id, 1.0)
            grouped[(left_index, ref_index)].append((observed-bias, recency*sample_weight*quality, total_var, question))
        used_polls.add(question.poll_id)
        used_pollsters.add(question.pollster)
        latest = max(latest, question.end_date) if latest else question.end_date
        noncandidate_mass.append(sum(option.pct for option in question.options if not option.candidate_key))

    rows, values, variances = [], [], []
    question_ids = set()
    for (left, right), observations in sorted(grouped.items()):
        weights = np.array([item[1] for item in observations])
        estimates = np.array([item[0] for item in observations])
        total_var = float(np.average([item[2] for item in observations], weights=weights))
        _, shared = pair_variance(model, observations[0][3].office, candidate_groups[left], candidate_groups[right])
        independent = max(total_var-shared, 0.01)
        effective = max(float(weights.sum()), 1e-6)
        rows.append(contrast_row(len(candidate_keys), left, right))
        values.append(float(np.average(estimates, weights=weights)))
        variances.append(shared + independent/effective)
        question_ids.update(item[3].question_key for item in observations)
    diagnostics = {
        "poll_count": len(used_polls), "question_count": len(question_ids),
        "poll_ids": sorted(used_polls), "question_keys": sorted(question_ids),
        "pollsters": sorted(used_pollsters),
        "rated_poll_count": sum((quality_weights or {}).get(poll_id, 1.0) > 0 and poll_id in (quality_weights or {}) for poll_id in used_polls),
        "election_day_bias_applied": apply_election_day_bias,
        "latest_poll_end_date": latest.strftime("%Y-%m-%d") if latest else None,
        "mean_noncandidate_response_pct": float(np.mean(noncandidate_mass)) if noncandidate_mass else None,
        "contrast_count": len(rows),
        "polled_candidate_keys": sorted({
            option.candidate_key
            for question in questions for option in question.options
            if option.candidate_key in index and option.pct > 0
        }),
    }
    return rows, values, variances, diagnostics


def gaussian_update(
    prior_mean: np.ndarray, prior_cov: np.ndarray,
    rows: list[np.ndarray], values: list[float], variances: list[float],
) -> tuple[np.ndarray, np.ndarray]:
    if not rows:
        return prior_mean, prior_cov
    h = np.vstack(rows)
    r = np.diag(np.maximum(variances, 1e-6))
    precision = np.linalg.pinv(prior_cov) + h.T @ np.linalg.solve(r, h)
    covariance = np.linalg.pinv(precision)
    mean = covariance @ (
        np.linalg.pinv(prior_cov) @ prior_mean + h.T @ np.linalg.solve(r, np.asarray(values))
    )
    return mean, (covariance+covariance.T)/2 + np.eye(len(mean))*1e-9


def affine_update_draws(
    prior_draws: np.ndarray, rows: list[np.ndarray], values: list[float], variances: list[float],
    covariance_inflation: float = 1.0,
    prior_covariance_scale: float = 1.0,
) -> np.ndarray:
    if not rows or prior_draws.shape[1] < 2:
        return prior_draws.copy()
    z = alr_candidate(prior_draws)
    prior_mean = z.mean(axis=0)
    source_cov = LedoitWolf().fit(z).covariance_ + np.eye(z.shape[1])*1e-8
    posterior_mean, posterior_cov = gaussian_update(
        prior_mean, source_cov*prior_covariance_scale, rows, values, variances,
    )
    posterior_cov *= covariance_inflation
    transform = psd_sqrt(posterior_cov) @ psd_sqrt(source_cov, inverse=True)
    posterior_z = posterior_mean + (z-prior_mean) @ transform.T
    return inv_alr_candidate(posterior_z)


def fit_prior_covariance_scale(
    prior_draws: np.ndarray, rows: list[np.ndarray], values: list[float], variances: list[float],
) -> dict[str, float | bool]:
    """Empirical-Bayes race-prior scale from the marginal poll likelihood.

    The lower bound of one only widens the historically fitted prior. A broad
    upper bound is numerical; hitting it is explicitly reported for review.
    """
    if not rows or prior_draws.shape[1] < 2:
        return {"scale": 1.0, "log_marginal_likelihood_gain": 0.0,
                "upper_search_bound_reached": False}
    z = alr_candidate(prior_draws)
    mean = z.mean(axis=0)
    covariance = LedoitWolf().fit(z).covariance_ + np.eye(z.shape[1])*1e-8
    h = np.vstack(rows)
    projected = h @ covariance @ h.T
    observation = np.diag(np.maximum(variances, 1e-6))
    discrepancy = np.asarray(values)-h @ mean

    def negative_log_marginal(log_scale: float) -> float:
        predictive = math.exp(log_scale)*projected+observation
        sign, logdet = np.linalg.slogdet(predictive)
        if sign <= 0:
            return math.inf
        return 0.5*(float(logdet)+float(discrepancy @ np.linalg.solve(predictive, discrepancy)))

    upper = math.log(1e6)
    result = minimize_scalar(negative_log_marginal, bounds=(0.0, upper), method="bounded",
                             options={"xatol": 1e-4})
    selected = float(result.x) if result.success else 0.0
    if negative_log_marginal(0.0) <= negative_log_marginal(selected):
        selected = 0.0
    return {"scale": float(math.exp(selected)),
            "log_marginal_likelihood_gain": float(negative_log_marginal(0.0)-negative_log_marginal(selected)),
            "upper_search_bound_reached": selected >= upper-1e-3}


def preserve_unpolled_candidate_mass(
    prior: np.ndarray, posterior: np.ndarray, candidate_keys: list[str], polled_keys: list[str],
) -> np.ndarray:
    """Apply poll contrasts within their named candidate subset.

    A poll that names D and R but omits an independent identifies the D/R split;
    it contains no observation about the independent's total vote share.
    """
    observed = [index for index, key in enumerate(candidate_keys) if key in set(polled_keys)]
    unobserved = [index for index in range(len(candidate_keys)) if index not in observed]
    if len(observed) < 2 or not unobserved:
        return posterior
    result = np.array(posterior, copy=True)
    result[:, unobserved] = prior[:, unobserved]
    available = 1.0-prior[:, unobserved].sum(axis=1)
    observed_draws = posterior[:, observed]
    observed_draws /= np.maximum(
        observed_draws.sum(axis=1, keepdims=True), np.finfo(float).tiny
    )
    result[:, observed] = observed_draws*available[:, None]
    return result


def flat_poll_draws(
    candidate_count: int, rows: list[np.ndarray], values: list[float], variances: list[float],
    draws: int, rng: np.random.Generator,
) -> np.ndarray:
    dimension = candidate_count-1
    mean, covariance = gaussian_update(
        np.zeros(dimension), np.eye(dimension)*25.0, rows, values, variances
    )
    return inv_alr_candidate(rng.multivariate_normal(mean, covariance, size=draws))


def select_half_life(
    questions: list[PollQuestion], races_by_id: dict[str, Any], model: BiasModel, cycle: int
) -> float:
    scores = {}
    for half_life in HALF_LIVES:
        model.half_life_days = half_life
        errors = []
        by_race = defaultdict(list)
        for question in questions:
            race = races_by_id.get(question.race_key)
            if race is not None and race.cycle == cycle and eligible_at_cutoff(question, CUTOFF_DAYS):
                by_race[question.race_key].append(question)
        for race_key, race_questions in by_race.items():
            race = races_by_id[race_key]
            keys = [candidate.candidate_key for candidate in race.candidates]
            groups = [candidate.group for candidate in race.candidates]
            cutoff = race_questions[0].election_date-timedelta(days=CUTOFF_DAYS)
            rows, values, variances, _ = poll_contrasts(race_questions, keys, groups, model, cutoff)
            if not rows:
                continue
            actual = np.array([candidate.votes for candidate in race.candidates], dtype=float)
            actual /= actual.sum()
            estimate = gaussian_update(np.zeros(len(keys)-1), np.eye(len(keys)-1)*25, rows, values, variances)[0]
            errors.append(float(np.mean((inv_alr_candidate(estimate)-actual)**2)))
        scores[half_life] = float(np.mean(errors)) if errors else math.inf
    return min(scores, key=scores.get)


def score_draws(draws: np.ndarray, actual: np.ndarray, winner: int) -> dict[str, float]:
    leaders = np.argmax(draws, axis=1)
    probabilities = np.bincount(leaders, minlength=len(actual))/len(draws)
    lower80, upper80 = np.quantile(draws, [0.1, 0.9], axis=0)
    lower95, upper95 = np.quantile(draws, [0.025, 0.975], axis=0)
    return {
        "log_score": -math.log(max(probabilities[winner], 0.5/len(draws))),
        "brier": float(np.sum((probabilities-np.eye(len(actual))[winner])**2)),
        "share_mae": float(np.mean(np.abs(draws.mean(axis=0)-actual))),
        "coverage80": float(np.mean((actual >= lower80) & (actual <= upper80))),
        "coverage95": float(np.mean((actual >= lower95) & (actual <= upper95))),
    }


def summarize_metrics(values: dict[str, list[float]]) -> dict[str, float]:
    return {key: float(np.mean(item)) for key, item in values.items()}


def backtest(
    races: list[Any], transitions: list[Any], questions: list[PollQuestion],
    bias_model: BiasModel, seed: int, holdout_cycle: int = 2020,
    posterior_inflation: float = 1.0,
    cutoff_days: int = CUTOFF_DAYS,
    apply_election_day_bias: bool = True,
) -> dict[str, Any]:
    training = [transition for transition in transitions if transition.target_cycle < holdout_cycle]
    holdout = [transition for transition in transitions if transition.target_cycle == holdout_cycle]
    office_models = stage3.fit_office_models(training)
    allocation = stage3.fit_candidate_allocation(races, max_cycle=holdout_cycle-1)
    total_cov = {}
    for office in OFFICES:
        subset = [transition for transition in training if transition.office == office]
        total_cov[office] = stage3.residual_covariance(
            subset, office_models[office]
        )
    by_race = defaultdict(list)
    for question in questions:
        if eligible_at_cutoff(question, cutoff_days):
            by_race[question.race_key].append(question)
    rng = np.random.default_rng(seed)
    metrics = {name: defaultdict(list) for name in ("results_only", "polls_only", "combined")}
    by_office = defaultdict(lambda: {name: defaultdict(list) for name in metrics})
    by_group = defaultdict(lambda: {name: defaultdict(list) for name in metrics})
    coverage_failures = []
    included = 0
    draws = 4000
    for transition in holdout:
        race = transition.target
        race_questions = by_race.get(race.source_race_id, [])
        if not race_questions:
            continue
        keys = [candidate.candidate_key for candidate in race.candidates]
        groups = [candidate.group for candidate in race.candidates]
        rows, values, variances, diagnostics = poll_contrasts(
            race_questions, keys, groups, bias_model,
            race_questions[0].election_date-timedelta(days=cutoff_days),
            apply_election_day_bias=apply_election_day_bias,
        )
        if not rows:
            continue
        included += 1
        candidates = stage3.historical_candidate_dicts(race)
        group_draws = rng.multivariate_normal(
            stage3.transition_predict(office_models[race.office], transition),
            total_cov[race.office], size=draws,
        )
        other_target = stage3.transition_other_share_target(office_models[race.office], transition)
        if other_target is not None:
            group_draws = stage3.calibrate_other_share(group_draws, other_target)
        prior = stage3.simulate_candidates(
            group_draws, candidates, allocation[race.office]["incumbent_log_utility"],
            allocation[race.office]["within_group_sigma"], rng,
            allocation[race.office]["write_in_share_samples"],
        )
        combined = affine_update_draws(prior, rows, values, variances, posterior_inflation)
        combined = preserve_unpolled_candidate_mass(
            prior, combined, keys, diagnostics["polled_candidate_keys"]
        )
        polls = flat_poll_draws(len(keys), rows, values, variances, draws, rng)
        actual = np.array([candidate.votes for candidate in race.candidates], dtype=float)
        actual /= actual.sum()
        winner = int(np.argmax(actual))
        for name, candidate_draws in (("results_only", prior), ("polls_only", polls), ("combined", combined)):
            scores = score_draws(candidate_draws, actual, winner)
            for metric, value in scores.items():
                metrics[name][metric].append(value)
                by_office[race.office][name][metric].append(value)
            lower95, upper95 = np.quantile(candidate_draws, [0.025, 0.975], axis=0)
            for index, candidate in enumerate(race.candidates):
                by_group[(race.office, candidate.group)][name]["coverage95"].append(
                    float(lower95[index] <= actual[index] <= upper95[index])
                )
                if name == "combined" and race.office == "senate" and not (
                    lower95[index] <= actual[index] <= upper95[index]
                ):
                    coverage_failures.append({
                        "race_id": race.source_race_id, "group": candidate.group,
                        "actual": float(actual[index]), "lower95": float(lower95[index]),
                        "upper95": float(upper95[index]), "poll_count": diagnostics["poll_count"],
                    })
    overall = {name: summarize_metrics(values) for name, values in metrics.items()}
    result = overall["results_only"]
    combined = overall["combined"]
    gate = {
        "holdout_cycle": holdout_cycle,
        "cutoff_days_before_election": cutoff_days,
        "poll_updated_races": included,
        "combined_improves_log_or_brier": (
            combined["log_score"] < result["log_score"] or combined["brier"] < result["brier"]
        ),
        "no_obvious_undercoverage": combined["coverage80"] >= 0.75 and combined["coverage95"] >= 0.90,
    }
    gate["passed"] = gate["combined_improves_log_or_brier"] and gate["no_obvious_undercoverage"]
    return {
        "design": {
            "calibration_cycle": 2018, "holdout_cycle": holdout_cycle,
            "cutoff_days_before_election": cutoff_days,
            "election_day_bias_applied": apply_election_day_bias,
            "availability_warning": "Historical source-created timestamps have unverified timezone; calendar-date comparisons are used conservatively.",
            "simulation_draws_per_race": draws,
        },
        "overall": overall,
        "by_office": {
            office: {name: summarize_metrics(values) for name, values in methods.items()}
            for office, methods in by_office.items()
        },
        "by_office_candidate_group": {
            f"{office}:{group}": {name: summarize_metrics(values) for name, values in methods.items()}
            for (office, group), methods in by_group.items()
        },
        "senate_combined_coverage_failures": coverage_failures,
        "gate": gate,
    }


def select_posterior_inflation(
    races: list[Any], transitions: list[Any], questions: list[PollQuestion],
    bias_model: BiasModel, seed: int,
) -> tuple[float, dict[str, Any]]:
    grid = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
    results = {}
    for index, factor in enumerate(grid):
        result = backtest(
            races, transitions, questions, bias_model, seed+index,
            holdout_cycle=2018, posterior_inflation=factor,
        )
        combined = result["overall"]["combined"]
        results[str(factor)] = combined
    eligible = [
        factor for factor in grid
        if results[str(factor)]["coverage80"] >= 0.75
        and results[str(factor)]["coverage95"] >= 0.90
    ]
    selected = min(
        eligible or grid,
        key=lambda factor: results[str(factor)]["log_score"],
    )
    return float(selected), {
        "calibration_cycle": 2018,
        "selection_rule": "lowest combined winner log score subject to 80%>=0.75 and 95%>=0.90 coverage",
        "grid_results": results,
    }


def current_prior_draws(
    current: list[dict[str, Any]], models: dict[str, dict[str, Any]],
    allocation: dict[str, dict[str, float]], decomposition: dict[str, Any],
    draws: int, seed: int, structural_fit: dict[str, Any] | None = None,
) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    global_draw = rng.multivariate_normal(np.zeros(2), decomposition["global"], size=draws)
    office_draw = {
        office: rng.multivariate_normal(np.zeros(2), decomposition["office"][office], size=draws)
        for office in OFFICES
    }
    state_draw = {
        state: rng.multivariate_normal(np.zeros(2), decomposition["state"], size=draws)
        for state in sorted({item["race"]["state"] for item in current})
    }
    output = {}
    for item in current:
        race = item["race"]
        office = race["office"]
        mean = stage3.current_predict(models[office], item["prior_shares"], item["candidates"])
        race_error = rng.multivariate_normal(np.zeros(2), decomposition["race"][office], size=draws)
        race_error *= float(item["fundamental"]["uncertainty_multiplier"])
        groups = {stage3.party_group(candidate["party"]) for candidate in item["candidates"]}
        ballot = structural.ballot_class(groups, float(item["prior_shares"][2]))
        if structural_fit is not None and ballot == "other_debut":
            for coordinate in (0, 1):
                race_error[:, coordinate] *= structural_fit["other_debut"][str(coordinate)]["local_sd_multiplier"]
        normalization = decomposition["office_coordinate_normalization"][office]
        latent = mean + (
            global_draw + office_draw[office] + state_draw[race["state"]] + race_error
        )*normalization
        other_target = stage3.current_other_share_target(
            models[office], item["prior_shares"], item["candidates"]
        )
        if other_target is not None:
            latent = stage3.calibrate_other_share(latent, other_target)
        if structural_fit is not None and ballot == "one_major_plus_other":
            # The old D/R transition cannot identify the share of a newly
            # prominent independent when a major party is absent. Use the
            # historical one-major-plus-other likelihood and its full error.
            one_major = structural_fit["one_major_plus_other"]
            latent[:, 1] = (structural.one_major_log_odds(item, structural_fit, stage3)
                            + rng.normal(0.0, one_major["residual_sd"], draws))
        output[race["race_id"]] = stage3.simulate_candidates(
            latent, item["candidates"], allocation[office]["incumbent_log_utility"],
            allocation[office]["within_group_sigma"], rng,
            allocation[office]["write_in_share_samples"],
        )
    return output


def distribution(values: np.ndarray) -> dict[str, float]:
    counts = Counter(int(value) for value in values)
    return {str(value): count/len(values) for value, count in sorted(counts.items())}


def simulate_current(
    current: list[dict[str, Any]], questions: list[PollQuestion], bias_model: BiasModel,
    prior_draws: dict[str, np.ndarray], stage3_draws: dict[str, np.ndarray], cutoff: datetime,
    posterior_inflation: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_race = defaultdict(list)
    for question in questions:
        if question.available_date <= cutoff:
            by_race[question.race_key].append(question)
    results = []
    seat_counts = {office: {group: np.zeros(len(next(iter(prior_draws.values()))), dtype=np.int16) for group in stage3.GROUPS} for office in OFFICES}
    for item in current:
        race = item["race"]
        candidates = item["candidates"]
        keys = [candidate["ballot_entry_id"] for candidate in candidates]
        groups = [stage3.party_group(candidate["party"]) for candidate in candidates]
        rows, values, variances, diagnostics = poll_contrasts(
            by_race.get(race["race_id"], []), keys, groups, bias_model, cutoff,
        )
        prior = prior_draws[race["race_id"]]
        original_stage3 = stage3_draws[race["race_id"]]
        posterior = affine_update_draws(prior, rows, values, variances, posterior_inflation)
        posterior = preserve_unpolled_candidate_mass(
            prior, posterior, keys, diagnostics["polled_candidate_keys"]
        )
        leaders = np.argmax(posterior, axis=1)
        stage3_leaders = np.argmax(original_stage3, axis=1)
        candidate_output = []
        for index, candidate in enumerate(candidates):
            probability = float(np.mean(leaders == index))
            prior_probability = float(np.mean(stage3_leaders == index))
            summary = stage3.quantile_summary(posterior[:, index])
            prior_summary = stage3.quantile_summary(original_stage3[:, index])
            direct = race["counting_rule"] == "plurality" or len(candidates) == 1
            candidate_output.append({
                **candidate, "party_group": groups[index], "share": summary,
                "stage3_share": prior_summary,
                "first_stage_leader_probability": probability,
                "stage3_first_stage_leader_probability": prior_probability,
                "eventual_win_probability": probability if direct else None,
                "monte_carlo_standard_error": math.sqrt(probability*(1-probability)/len(posterior)),
            })
        for draw_index, candidate_index in enumerate(leaders):
            seat_counts[race["office"]][groups[int(candidate_index)]][draw_index] += 1
        results.append({
            "race_id": race["race_id"], "office": race["office"], "state": race["state"],
            "district_code": race["district_code"], "counting_rule": race["counting_rule"],
            "ballot_status": race["ballot_status"], "baseline_source": item["fundamental"]["baseline_source_race_id"],
            "uncertainty_multiplier": item["fundamental"]["uncertainty_multiplier"],
            "poll_diagnostics": diagnostics,
            "update_status": "race_polls_and_national_signals" if rows else "national_signals_only",
            "winner_interpretation": (
                "eventual winner under plurality" if race["counting_rule"] == "plurality" or len(candidates) == 1
                else "first-stage leader only; Stage 5 must apply transfers or later-round rules"
            ),
            "candidates": candidate_output,
        })
    summaries = {}
    for office in OFFICES:
        values = seat_counts[office]
        joint = Counter(
            f"{int(values['D'][i])}-{int(values['R'][i])}-{int(values['O'][i])}"
            for i in range(len(values["D"]))
        )
        summaries[office] = {
            "seat_universe": int(sum(values[group][0] for group in stage3.GROUPS)),
            "marginal_distributions": {group: distribution(counts) for group, counts in values.items()},
            "joint_D_R_O_distribution": {key: count/len(values["D"]) for key, count in sorted(joint.items())},
            "interpretation": "first-stage leaders; nonplurality final rules remain deferred to Stage 5",
        }
    return results, summaries


def serialize_bias_model(model: BiasModel, historically_selected_half_life: float) -> dict[str, Any]:
    names = model.vectorizer.get_feature_names_out().tolist()
    return {
        "feature_names": names,
        "coordinates": {
            str(index): {
                "selected_ridge": model.selected_alpha[index],
                "training_observations": model.training_rows[index],
                "intercept": float(model.models[index].intercept_),
                "coefficients": {
                    name: float(value) for name, value in zip(names, model.models[index].coef_)
                    if abs(value) >= 1e-10
                },
            }
            for index in range(2)
        },
        "residual_variance": model.residual_variance,
        "shared_race_error_variance": model.shared_variance,
        "same_party_candidate_logratio_variance": model.same_group_variance,
        "selected_poll_half_life_days": historically_selected_half_life,
        "senate_D_R_correction": (
            senate_bias.serialize(model.senate_bias_model)
            if model.senate_bias_model is not None else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--stage1-database", type=Path, default=Path("data/processed/stage1.sqlite"))
    parser.add_argument("--stage3-artifact", type=Path, default=Path("artifacts/stage3/forecast_2026.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/stage4"))
    parser.add_argument("--draws", type=int, default=75000)
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument(
        "--current-poll-half-life-days",
        type=float,
        default=CURRENT_POLL_HALF_LIFE_DAYS,
        help="Recency half-life for 2026 race polls; historical backtests retain their fitted value.",
    )
    args = parser.parse_args()
    if args.draws < 1000:
        raise ValueError("At least 1,000 draws are required")
    if args.current_poll_half_life_days <= 0:
        raise ValueError("Current poll half-life must be positive")
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        historical_races = stage3.load_historical_races(connection)
        races_by_id = {race.source_race_id: race for race in historical_races}
        transitions = stage3.build_transitions(historical_races)
        historical_questions = load_historical_questions(connection)
        bias_model = fit_bias_model(
            historical_questions, races_by_id, senate_training_through=2016
        )
        senate_rows, senate_inventory = senate_bias.load_observations(historical_races, CUTOFF_DAYS)
        historically_selected_half_life = bias_model.half_life_days
        posterior_inflation, posterior_inflation_cv = select_posterior_inflation(
            historical_races, transitions, historical_questions, bias_model, args.seed+3
        )
        bias_model.senate_bias_model, senate_2018_training = senate_bias.fit_through_cycle(
            senate_rows, 2018
        )
        backtest_result = backtest(
            historical_races, transitions, historical_questions, bias_model, args.seed+4,
            holdout_cycle=2020, posterior_inflation=posterior_inflation,
        )
        if not backtest_result["gate"]["passed"]:
            raise RuntimeError(f"Stage 4 holdout gate failed: {backtest_result['gate']}")
        senate_2020, _ = senate_bias.fit_through_cycle(senate_rows, 2020)
        senate_2022_holdout = senate_bias.score(
            senate_2020, [row for row in senate_rows if row.cycle == 2022]
        )
        bias_model.senate_bias_model, _ = senate_bias.fit_through_cycle(senate_rows, 2022)
        senate_2024_questions = senate_archive_questions(senate_rows, races_by_id, 2024)
        senate_2024_full_backtest = backtest(
            historical_races, transitions, senate_2024_questions, bias_model,
            args.seed+6, holdout_cycle=2024, posterior_inflation=posterior_inflation,
        )
        major_party_coverage = {
            str(cycle): {
                group: result["by_office_candidate_group"].get(
                    f"senate:{group}", {}
                ).get("combined", {}).get("coverage95", 0.0)
                for group in ("D", "R")
            }
            for cycle, result in ((2020, backtest_result), (2024, senate_2024_full_backtest))
        }
        senate_major_party_gate = all(
            coverage >= 0.90
            for cycle in major_party_coverage.values() for coverage in cycle.values()
        )
        if not senate_major_party_gate:
            raise RuntimeError(f"Senate D/R interval coverage gate failed: {major_party_coverage}")
        bias_model.senate_bias_model, senate_bias_report = senate_bias.select_and_validate(senate_rows)
        senate_bias_report["held_out_2022"] = senate_2022_holdout
        senate_bias_report["2020_backtest_training"] = senate_2018_training
        senate_bias_report["inventory"] = senate_inventory
        senate_bias_report["full_model_2024_holdout"] = senate_2024_full_backtest
        senate_bias_report["major_party_coverage95_by_cycle"] = major_party_coverage
        senate_bias_report["major_party_interval_gate_passed"] = senate_major_party_gate
        senate_bias_report["held_out_2024"]["gate_passed"] = (
            senate_bias_report["held_out_2024"]["selected"]["races"] >= 10
            and senate_bias_report["held_out_2024"]["selected"]["rmse_margin_points_approx"]
            < senate_bias_report["held_out_2024"]["no_correction"]["rmse_margin_points_approx"]
        )
        if not senate_bias_report["held_out_2024"]["gate_passed"]:
            raise RuntimeError("Senate poll-bias correction failed the held-out 2024 gate")
        # Keep the fitted half-life for historical evaluation, then apply the
        # explicit late-cycle recency policy only to the live 2026 forecast.
        bias_model.half_life_days = float(args.current_poll_half_life_days)
        current_questions = load_current_questions(connection, args.stage1_database)
        source_eligible_questions = connection.execute(
            "SELECT COUNT(*) FROM current_question_map WHERE model_eligible=1"
        ).fetchone()[0]
        current = stage3.load_current_races(connection)
        models = stage3.fit_office_models(transitions)
        allocation = stage3.fit_candidate_allocation(historical_races)
        decomposition = stage3.decompose_covariance(transitions, models)
        structural_fit = structural.fit(transitions, models, stage3)
        cutoff_text = "2026-09-21T20:45:24Z"
        cutoff = datetime.fromisoformat(cutoff_text.replace("Z", "+00:00")).replace(tzinfo=None)
        stage3_priors = current_prior_draws(
            current, models, allocation, decomposition, args.draws, args.seed, structural_fit,
        )
        national_priors, national_signals = fit_national_signal_update(
            connection, args.stage1_database, historical_races, current, stage3_priors, cutoff
        )
        race_forecasts, joint = simulate_current(
            current, current_questions, bias_model, national_priors, stage3_priors, cutoff,
            posterior_inflation,
        )
        accepted_stage3 = json.loads(args.stage3_artifact.read_text(encoding="utf-8"))
        accepted_by_race = {race["race_id"]: race for race in accepted_stage3["races"]}
        for race in race_forecasts:
            accepted_candidates = {
                candidate["ballot_entry_id"]: candidate
                for candidate in accepted_by_race[race["race_id"]]["candidates"]
            }
            for candidate in race["candidates"]:
                accepted = accepted_candidates[candidate["ballot_entry_id"]]
                candidate["stage3_share"] = accepted["share"]
                candidate["stage3_first_stage_leader_probability"] = accepted["first_stage_leader_probability"]
        build_metadata = dict(connection.execute("SELECT key,value FROM build_metadata"))
    finally:
        connection.close()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_version": MODEL_VERSION, "stage": 4,
        "estimand": "candidate share at the next listed voting stage",
        "information_cutoff_utc": cutoff_text, "data_sha256": sha256(args.database),
        "stage1_data_sha256": sha256(args.stage1_database), "model_code_sha256": sha256(Path(__file__)),
        "national_model_code_sha256": sha256(NATIONAL_PATH),
        "national_source_manifest_sha256": sha256(national_env.REFERENCE / "source_manifest.json"),
        "senate_local_code_sha256": sha256(LOCAL_PATH),
        "senate_local_source_manifest_sha256": sha256(local_lean.SOURCE / "source_manifest.json"),
        "senate_poll_bias_code_sha256": sha256(SENATE_BIAS_PATH),
        "senate_poll_bias_source_manifest_sha256": sha256(senate_bias.SOURCE / "source_manifest.json"),
        "stage3_code_sha256": sha256(STAGE3_PATH), "random_seed": args.seed,
        "stage3_forecast_sha256": sha256(args.stage3_artifact),
        "simulation_draws": args.draws,
        "current_source_eligible_questions": source_eligible_questions,
        "current_selected_questions_after_poll_race_deduplication": len(current_questions),
        "historical_questions": len(historical_questions), "input_snapshot_ids": {
            "live_source_snapshot": build_metadata["source_snapshot_id"],
            "historical_snapshot": build_metadata["historical_snapshot"],
        },
    }
    parameters = {
        "metadata": metadata, "poll_error_model": serialize_bias_model(
            bias_model, historically_selected_half_life
        ),
        "backtest": backtest_result,
        "posterior_covariance_inflation": {
            "selected": posterior_inflation, "calibration": posterior_inflation_cv,
        },
        "current_poll_recency": {
            "half_life_days": float(args.current_poll_half_life_days),
            "historically_selected_half_life_days": historically_selected_half_life,
            "scope": "Live 2026 race polls only; historical calibration and holdout retain the fitted half-life.",
        },
        "national_signal_update": national_signals,
        "senate_poll_bias_calibration": senate_bias_report,
        "signals": {
            "race_polls": "admitted after holdout gate",
            "generic_ballot": "admitted for 2026 as a national House vote observation; historical error has only one populated cycle",
            "presidential_approval": "admitted through a fitted 1948-2024 historical national House vote model, evaluated on later election cycles",
        },
    }
    forecast = {
        "metadata": metadata, "publication_status": "internal_stage4_not_for_publication",
        "national_signal_note": "Fitted postwar national fundamentals replace the aggregate Stage 3 center; generic ballot then updates the shared D/R environment before race polls. Sensitivities are in model_parameters.json.",
        "nonplurality_limitation": "First-stage shares only; Stage 5 must model transfers and later rounds.",
        "race_count": len(race_forecasts), "races": race_forecasts, "joint_summaries": joint,
    }
    (args.output_dir/"model_parameters.json").write_text(json.dumps(parameters, indent=2)+"\n", encoding="utf-8")
    (args.output_dir/"forecast_2026.json").write_text(json.dumps(forecast, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({
        "status": "complete", "metadata": metadata, "backtest": backtest_result["overall"],
        "gate": backtest_result["gate"], "outputs": [
            str(args.output_dir/"model_parameters.json"), str(args.output_dir/"forecast_2026.json")
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
