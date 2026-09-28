"""Cycle-blocked poll-level test of generic-ballot and approval information.

The 538 ratings archive has median field dates but no publication dates for
pre-2020 cycles. These tests are provisional and never alter live forecasts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests

import national_environment as national
from test_national_signals import predict, predict_current_generic, score, score_generic

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/reference/national_signals/raw_polls.csv"
MANIFEST = SOURCE.parent / "source_manifest.json"
CREATION_SOURCE = ROOT / "data/raw/historical/20260921T204524Z/538_archive_generic_ballot_polls.csv"
OUTPUT = ROOT / "artifacts/joint_national_signal_test.json"


def source_rows() -> list[dict]:
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["sha256"]
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != expected:
        raise ValueError("FiveThirtyEight poll archive differs from frozen manifest")
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def restore_source() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if SOURCE.exists() and hashlib.sha256(SOURCE.read_bytes()).hexdigest() == manifest["sha256"]:
        return manifest
    response = requests.get(manifest["url"], timeout=45)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != manifest["sha256"]:
        raise ValueError("Historical source no longer matches frozen snapshot")
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE.write_bytes(response.content)
    return manifest


def poll_averages(rows: list[dict], lag: int) -> list[dict]:
    by_cycle = defaultdict(list)
    for row in rows:
        if row["type_simple"] != "House-G-US" or row["location"] != "US":
            continue
        if row["partisan"] not in ("", "NA"):
            continue
        if row["cand1_party"] != "DEM" or row["cand2_party"] != "REP":
            continue
        try:
            year = int(row["cycle"])
            day = date.fromisoformat(row["polldate"])
            dem, rep = float(row["cand1_pct"]), float(row["cand2_pct"])
            sample = float(row["samplesize"])
        except (ValueError, TypeError):
            continue
        cutoff = national.election_date(year) - timedelta(days=43)
        age = (cutoff-day).days
        if age < lag or age > 60 or dem <= 0 or rep <= 0 or sample <= 0:
            continue
        margin = 100*(dem-rep)/(dem+rep)
        weight = math.exp(-math.log(2)*age/30)*math.sqrt(min(sample, 3000)/1000)
        by_cycle[year].append({"poll_id": row["poll_id"], "date": day.isoformat(),
                               "margin": margin, "weight": weight})
    result = []
    for year, polls in sorted(by_cycle.items()):
        unique = {p["poll_id"]: p for p in polls}
        polls = list(unique.values())
        weights = np.array([p["weight"] for p in polls])
        values = np.array([p["margin"] for p in polls])
        result.append({"year": year, "generic_margin": float(np.average(values, weights=weights)),
                       "poll_count": len(polls), "poll_ids": [p["poll_id"] for p in polls],
                       "earliest_poll_date": min(p["date"] for p in polls),
                       "latest_poll_date": max(p["date"] for p in polls)})
    return result


def joined_rows(raw: list[dict], lag: int) -> list[dict]:
    house = national.parse_house()
    approval = {r["year"]: r for r in national.cycle_rows(
        house, national.parse_approval(), cutoff_days=43)}
    result = []
    for poll in poll_averages(raw, lag):
        year = poll["year"]
        if year not in approval:
            continue
        a = approval[year]
        result.append({**poll, "actual_margin": 100*house[year],
                       "previous_house_margin": 100*a["previous_margin"],
                       "signed_approval_net": 100*a["signed_approval_net"],
                       "approval_age_days": a["approval_age_days"]})
    return result


def rolling(rows: list[dict]) -> dict:
    predictions = []
    for index, row in enumerate(rows):
        if index < 5:
            continue
        train = rows[:index]
        predictions.append({**row,
            "generic_calibrated": predict(train, row, False),
            "generic_plus_approval": predict(train, row, True),
            "current_generic_from_previous_house": predict_current_generic(train, row, False),
            "current_generic_from_previous_house_and_approval": predict_current_generic(train, row, True)})
    if not predictions:
        raise ValueError("Too few generic poll cycles for rolling test")
    eventual_a = score(predictions, "generic_calibrated")
    eventual_b = score(predictions, "generic_plus_approval")
    current_a = score_generic(predictions, "current_generic_from_previous_house")
    current_b = score_generic(predictions, "current_generic_from_previous_house_and_approval")
    g_error = np.array([p["generic_calibrated"]-p["actual_margin"] for p in predictions])
    a_error = np.array([p["generic_plus_approval"]-p["actual_margin"] for p in predictions])
    return {"cycles": [r["year"] for r in rows], "predictions": predictions,
            "eventual_house_vote": {"generic_calibrated": eventual_a,
                                    "generic_plus_approval": eventual_b,
                                    "approval_better_absolute_error_count": sum(
                                        abs(p["generic_plus_approval"]-p["actual_margin"])
                                        < abs(p["generic_calibrated"]-p["actual_margin"])
                                        for p in predictions)},
            "contemporaneous_generic_proxy": {"previous_house": current_a,
                "previous_house_plus_approval": current_b},
            "eventual_outcome_error_correlation": float(np.corrcoef(g_error, a_error)[0, 1]),
            "correlation_warning": "Both predictions share the generic signal and eventual-outcome target; this is NOT approval-prior/generic measurement-error covariance."}


def creation_audit(rows: list[dict], included_ids: list[str]) -> dict:
    created = {}
    with CREATION_SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["cycle"] != "2020" or not row["created_at"]:
                continue
            when = datetime.strptime(row["created_at"], "%m/%d/%y %H:%M").date()
            old = created.get(row["poll_id"])
            if old is None or when < old:
                created[row["poll_id"]] = when
    cutoff = national.election_date(2020)-timedelta(days=43)
    known = [pid for pid in included_ids if pid in created]
    late = [pid for pid in known if created[pid] > cutoff]
    eligible = []
    for row in rows:
        if (row["cycle"] != "2020" or row["type_simple"] != "House-G-US"
                or row["poll_id"] not in known or row["poll_id"] in late):
            continue
        dem, rep = float(row["cand1_pct"]), float(row["cand2_pct"])
        age = (cutoff-date.fromisoformat(row["polldate"])).days
        sample = float(row["samplesize"])
        eligible.append((100*(dem-rep)/(dem+rep),
                         math.exp(-math.log(2)*age/30)*math.sqrt(min(sample, 3000)/1000)))
    return {"cycle": 2020, "cutoff": cutoff.isoformat(), "included_polls": len(included_ids),
            "matched_creation_dates": len(known), "created_after_cutoff": len(late),
            "creation_filtered_poll_count": len(eligible),
            "creation_filtered_generic_margin": float(np.average(
                [x[0] for x in eligible], weights=[x[1] for x in eligible])) if eligible else None,
            "late_poll_ids": late,
            "warning": "Created_at is the 538 database timestamp, not necessarily first public release; a post-cutoff timestamp prevents treating that archived row as demonstrably available as of cutoff."}


def report() -> dict:
    national.verify_sources()
    raw = source_rows()
    runs = {str(lag): rolling(joined_rows(raw, lag)) for lag in (0, 7, 14)}
    main = runs["7"]
    example = next(r for r in joined_rows(raw, 7) if r["year"] == 2020)
    return {"source": json.loads(MANIFEST.read_text(encoding="utf-8")),
            "design": {"cutoff_days_before_election": 43, "poll_window_days": 60,
                       "main_field_date_embargo_days": 7,
                       "weight": "exp(-ln(2)*poll_age/30) * sqrt(min(sample_size,3000)/1000)",
                       "filters": "US House generic D/R, nonpartisan, valid two-party marginals; one question per poll_id",
                       "validation": "expanding election-cycle holdouts after five training cycles",
                       "availability_limitation": "polldate is median field date; release dates absent pre-2020; main test is not strictly as-of"},
            "main": main, "field_date_embargo_sensitivity": {
                lag: {"cycles": value["cycles"],
                      "eventual_house_vote": value["eventual_house_vote"],
                      "contemporaneous_generic_proxy": value["contemporaneous_generic_proxy"]}
                for lag, value in runs.items()},
            "creation_timestamp_audit": creation_audit(raw, example["poll_ids"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true", help="restore archived CSV against its frozen SHA-256")
    args = parser.parse_args()
    if args.restore:
        restore_source()
    result = report()
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"main_eventual": result["main"]["eventual_house_vote"],
                      "main_current_proxy": result["main"]["contemporaneous_generic_proxy"],
                      "creation_audit": result["creation_timestamp_audit"],
                      "lag_sensitivity": result["field_date_embargo_sensitivity"]}, indent=2))
