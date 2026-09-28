"""Fit Senate race lean relative to the national House vote, without future data."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge

from national_environment import parse_house

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "reference" / "local_lean"


def verify_sources():
    manifest = json.loads((SOURCE / "source_manifest.json").read_text(encoding="utf-8"))
    for name, item in manifest.items():
        if hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Local-lean source changed after snapshot: {name}")


def group(party: str) -> str | None:
    p = (party or "").upper().strip()
    if p in {"DEM", "D", "DFL"}:
        return "D"
    if p in {"REP", "R", "R*"}:
        return "R"
    return None


def name_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z]+", value.lower().replace("jr", "")))


def load_presidential() -> dict[int, dict[str, float]]:
    source_rows = defaultdict(list)
    with (SOURCE / "presidential_results.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["stage"] != "general" or not row["state_abbrev"] or not row["votes"]:
                continue
            source_rows[(int(row["cycle"]), row["state_abbrev"])].append(row)
    races = defaultdict(lambda: defaultdict(float))
    for key, rows in source_rows.items():
        nominees = {name_key(row["candidate_name"]): group(row["ballot_party"])
                    for row in rows if group(row["ballot_party"]) and row["candidate_name"]}
        for row in rows:
            party = nominees.get(name_key(row["candidate_name"]))
            if party:
                races[key][party] += int(row["votes"])
    years = defaultdict(dict)
    for (cycle, state), votes in races.items():
        if votes["D"] > 0 and votes["R"] > 0:
            years[cycle][state] = votes
    result = {}
    for year, states in years.items():
        national_d = sum(v["D"] for v in states.values())
        national_r = sum(v["R"] for v in states.values())
        national_margin = (national_d-national_r)/(national_d+national_r)
        result[year] = {state: (v["D"]-v["R"])/(v["D"]+v["R"])-national_margin
                        for state, v in states.items()}
    return result


def load_senate() -> dict[tuple[int, str, str], dict]:
    source_rows = defaultdict(list)
    with (SOURCE / "senate_results.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row["stage"] != "general" or row["special"] != "false"
                    or not row["state_abbrev"] or not row["votes"]):
                continue
            key = (int(row["cycle"]), row["state_abbrev"], row["office_seat_name"])
            source_rows[key].append(row)
    races = defaultdict(lambda: {"votes": defaultdict(float), "candidates": defaultdict(float)})
    for key, rows in source_rows.items():
        nominees = {name_key(row["candidate_name"]): group(row["ballot_party"])
                    for row in rows if group(row["ballot_party"]) and row["candidate_name"]}
        for row in rows:
            candidate_name = name_key(row["candidate_name"])
            party = nominees.get(candidate_name)
            if party:
                races[key]["votes"][party] += int(row["votes"])
                races[key]["candidates"][(party, candidate_name)] += int(row["votes"])
    result = {}
    for key, item in races.items():
        d, r = item["votes"]["D"], item["votes"]["R"]
        if d <= 0 or r <= 0 or key[2] not in {"Class I", "Class II", "Class III"}:
            continue
        item["margin"] = (d-r)/(d+r)
        result[key] = item
    return result


def prior_presidential_lean(presidential: dict, year: int, state: str) -> tuple[int, float] | None:
    eligible = [cycle for cycle in presidential if cycle < year and state in presidential[cycle]]
    if not eligible:
        return None
    cycle = max(eligible)
    return cycle, presidential[cycle][state]


def recurring_candidate(prior: dict, target: dict) -> int:
    previous = {key for key, votes in prior["candidates"].items() if votes > 0}
    current = {key for key, votes in target["candidates"].items() if votes > 0}
    for group_name in ("D", "R"):
        if any(key[0] == group_name for key in previous & current):
            return 1 if group_name == "D" else -1
    return 0


def training_rows() -> list[dict]:
    verify_sources()
    presidential = load_presidential()
    senate = load_senate()
    house = parse_house()
    rows = []
    for (year, state, seat), target in sorted(senate.items()):
        if year not in house or year-6 not in house:
            continue
        prior = senate.get((year-6, state, seat))
        pres = prior_presidential_lean(presidential, year, state)
        if not prior or not pres:
            continue
        rows.append({"year": year, "state": state, "seat": seat,
                     "presidential_year": pres[0], "presidential_lean": pres[1],
                     "previous_senate_margin": prior["margin"],
                     "previous_senate_lean": prior["margin"]-house[year-6],
                     "recurring_candidate": recurring_candidate(prior, target),
                     "target_lean": target["margin"]-house[year],
                     "target_margin": target["margin"]})
    return rows


def features(rows: list[dict], specification: str) -> np.ndarray:
    columns = {
        "previous": ("previous_senate_lean",),
        "presidential": ("presidential_lean",),
        "combined": ("previous_senate_lean", "presidential_lean", "recurring_candidate"),
    }[specification]
    return np.asarray([[row[key] for key in columns] for row in rows], dtype=float)


def fit(rows: list[dict], specification: str, alpha: float) -> Ridge:
    model = Ridge(alpha=alpha)
    model.fit(features(rows, specification), [row["target_lean"] for row in rows])
    return model


def assess(rows: list[dict]) -> dict:
    grid = []
    for spec in ("previous", "presidential", "combined"):
        for alpha in (0.01, 0.1, 1.0, 10.0):
            errors = []
            for year in sorted({row["year"] for row in rows}):
                train = [row for row in rows if row["year"] < year]
                test = [row for row in rows if row["year"] == year]
                if len(train) < 60 or not test:
                    continue
                model = fit(train, spec, alpha)
                predicted = model.predict(features(test, spec))
                errors.extend({"year": year, "state": row["state"], "seat": row["seat"],
                               "error": float(p-row["target_lean"]),
                               "predicted_lean": float(p), "actual_lean": row["target_lean"]}
                              for row, p in zip(test, predicted))
            tune = [row["error"] for row in errors if row["year"] <= 2018]
            later = [row["error"] for row in errors if row["year"] >= 2020]
            grid.append({"specification": spec, "alpha": alpha,
                         "tuning_rmse": math.sqrt(float(np.mean(np.square(tune)))) if tune else None,
                         "later_rmse": math.sqrt(float(np.mean(np.square(later)))) if later else None,
                         "errors": errors})
    selected = min(grid, key=lambda row: row["tuning_rmse"] or math.inf)
    return {"selected": selected,
            "grid": [{key: value for key, value in row.items() if key != "errors"} for row in grid]}


def current_lean(race: dict, candidates: list[dict], senate: dict, presidential: dict,
                 house: dict, model: Ridge, specification: str) -> dict | None:
    year, state = 2026, race["state"]
    if race.get("election_type") != "regular":
        return None
    seat = {"II": "Class II"}.get(race.get("seat_class"))
    if seat is None:
        return None
    prior = senate.get((2020, state, seat))
    pres = prior_presidential_lean(presidential, year, state)
    if not prior or not pres:
        return None
    current_names = {(group(c["party"]), name_key(c["name"])) for c in candidates}
    prior_names = {key for key in prior["candidates"]}
    recurring = 0
    for party in ("D", "R"):
        if any(key[0] == party for key in current_names & prior_names):
            recurring = 1 if party == "D" else -1
    row = {"previous_senate_lean": prior["margin"]-house[2020],
           "presidential_lean": pres[1], "recurring_candidate": recurring}
    return {"predicted_lean": float(model.predict(features([row], specification))[0]),
            "inputs": {**row, "presidential_year": pres[0], "prior_senate_year": 2020}}


def build_current(current: list[dict]) -> tuple[dict, dict]:
    rows = training_rows()
    assessment = assess(rows)
    chosen = assessment["selected"]
    model = fit(rows, chosen["specification"], chosen["alpha"])
    senate = load_senate()
    pres = load_presidential()
    house = parse_house()
    predictions = {}
    for item in current:
        if item["race"]["office"] != "senate":
            continue
        prediction = current_lean(item["race"], item["candidates"], senate, pres,
                                  house, model, chosen["specification"])
        if prediction:
            predictions[item["race"]["race_id"]] = prediction
    report = {"training_races": len(rows), "selected": {k: v for k, v in chosen.items() if k != "errors"},
              "grid": assessment["grid"], "coefficients": {"intercept": float(model.intercept_),
              "features": dict(zip({"previous": ("previous_senate_lean",),
                                    "presidential": ("presidential_lean",),
                                    "combined": ("previous_senate_lean", "presidential_lean", "recurring_candidate")}[chosen["specification"]],
                                    (float(x) for x in model.coef_)))},
              "current_predictions": predictions}
    return predictions, report


if __name__ == "__main__":
    import sqlite3
    import sys
    sys.path.insert(0, str(ROOT / "modeling"))
    import stage3_results_baseline as stage3
    connection = sqlite3.connect(ROOT / "data" / "processed" / "stage2.sqlite")
    connection.row_factory = sqlite3.Row
    predictions, report = build_current(stage3.load_current_races(connection))
    path = ROOT / "artifacts" / "senate_local_lean_research.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"training_races": report["training_races"], "selected": report["selected"],
                      "coefficients": report["coefficients"], "current_races": len(predictions)}, indent=2))
