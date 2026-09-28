"""Cycle-held-out audit of the nowcast's 95/5 national House center."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m

SOURCE = ROOT / "data/raw/historical_wayback/20241129"
MANIFEST = ROOT / "data/reference/stage6_wayback_manifest.json"


def generic_rows():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = []
    for filename, spec in manifest["national_files"].items():
        if not filename.startswith("generic_ballot"):
            continue
        path = SOURCE / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
            raise RuntimeError(f"Historical national source hash changed: {filename}")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                try:
                    cycle = int(row["cycle"])
                    if cycle not in spec["cycle_use"]:
                        continue
                    dem, rep = float(row["dem"]), float(row["rep"])
                    end = m.parse_date(row["end_date"])
                    available = m.parse_date(row["created_at"]) + timedelta(days=1)
                    sample = float(row.get("sample_size") or 600)
                    if min(dem, rep) <= 0:
                        continue
                except (ValueError, TypeError):
                    continue
                output.append({"cycle": cycle, "poll_id": row["poll_id"],
                               "end": end, "available": available,
                               "sample": sample, "logratio": math.log(dem/rep)})
    return output


def approval_rows():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    output = []
    for filename, spec in manifest["national_files"].items():
        if not filename.startswith("president_approval"):
            continue
        path = SOURCE / filename
        if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
            raise RuntimeError(f"Historical approval source hash changed: {filename}")
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                try:
                    yes, no = float(row["yes"]), float(row["no"])
                    end = m.parse_date(row["end_date"])
                    available = m.parse_date(row["created_at"]) + timedelta(days=1)
                    sample = float(row.get("sample_size") or 600)
                    if min(yes, no) <= 0:
                        continue
                except (ValueError, TypeError):
                    continue
                output.append({"poll_id": row["poll_id"], "politician": row["politician"],
                               "end": end, "available": available,
                               "sample": sample, "net": (yes-no)/100})
    return output


def approval_at(rows, cycle, lead):
    cutoff = m.senate_bias.election_day(cycle)-timedelta(days=lead)
    politician = "Donald Trump" if cycle == 2020 else "Joe Biden"
    chosen = {}
    for row in rows:
        if row["politician"] != politician or row["end"] > cutoff or row["available"] > cutoff:
            continue
        if (cutoff-row["end"]).days > 90:
            continue
        old = chosen.get(row["poll_id"])
        if old is None or (row["sample"], row["available"]) > (old["sample"], old["available"]):
            chosen[row["poll_id"]] = row
    selected = list(chosen.values())
    if not selected:
        raise ValueError(f"Missing approval polls: {cycle}, {lead}")
    weights = [math.exp(-math.log(2)*max(0, (cutoff-r["end"]).days)/30)
               * math.sqrt(max(r["sample"], 100)/600) for r in selected]
    return float(np.average([r["net"] for r in selected], weights=weights)), len(selected)


def generic_at(rows, cycle, lead):
    cutoff = m.senate_bias.election_day(cycle)-timedelta(days=lead)
    chosen = {}
    for row in rows:
        if row["cycle"] != cycle or row["end"] > cutoff or row["available"] > cutoff:
            continue
        if (cutoff-row["end"]).days > 180:
            continue
        old = chosen.get(row["poll_id"])
        if old is None or (row["sample"], row["available"]) > (old["sample"], old["available"]):
            chosen[row["poll_id"]] = row
    selected = list(chosen.values())
    if not selected:
        raise ValueError(f"Missing generic ballot polls: {cycle}, {lead}")
    weights = [math.exp(-math.log(2)*max(0, (cutoff-r["end"]).days)/30)
               * math.sqrt(max(r["sample"], 100)/600) for r in selected]
    return float(np.average([r["logratio"] for r in selected], weights=weights)), len(selected)


def main():
    rows = generic_rows()
    approval_polls = approval_rows()
    house = m.national_env.parse_house()
    approval = m.national_env.parse_approval()
    validation = m.national_env.evaluate(m.national_env.cycle_rows(house, approval))
    chosen = validation["chosen"]
    report = []
    for cycle in (2020, 2022, 2024):
        for lead in (90, 30, 7):
            generic, count = generic_at(rows, cycle, lead)
            historical_rows = m.national_env.cycle_rows(house, approval, lead)
            target = next(row for row in historical_rows if row["year"] == cycle)
            training = [row for row in historical_rows if row["year"] < cycle]
            structural_model = m.national_env.fit(
                training, chosen["half_life_years"], chosen["ridge_alpha"], cycle)
            structural_margin = float(structural_model.predict(m.national_env.features([target]))[0])
            approval_net_538, approval_poll_count = approval_at(approval_polls, cycle, lead)
            alternate_target = {**target, "approval_net": approval_net_538,
                                "signed_approval_net": target["president_party"]*approval_net_538}
            structural_538 = float(structural_model.predict(
                m.national_env.features([alternate_target]))[0])
            structural_logratio = 2*math.atanh(max(-0.99, min(0.99, structural_margin)))
            structural_538_logratio = 2*math.atanh(max(-0.99, min(0.99, structural_538)))
            combined = 0.95*generic + 0.05*structural_logratio
            combined_538 = 0.95*generic + 0.05*structural_538_logratio
            actual = house[cycle]
            report.append({"cycle": cycle, "lead_days": lead, "generic_poll_count": count,
                           "approval_observations": target["approval_poll_count"],
                           "approval_538_poll_count": approval_poll_count,
                           "approval_538_net_points": round(100*approval_net_538, 3),
                           "generic_D_margin_points": round(100*math.tanh(generic/2), 3),
                           "approval_structural_D_margin_points": round(100*structural_margin, 3),
                           "approval_538_structural_D_margin_points": round(100*structural_538, 3),
                           "blend_D_margin_points": round(100*math.tanh(combined/2), 3),
                           "blend_with_538_approval_D_margin_points": round(100*math.tanh(combined_538/2), 3),
                           "result_D_margin_points": round(100*actual, 3),
                           "generic_minus_result_points": round(100*(math.tanh(generic/2)-actual), 3),
                           "blend_minus_result_points": round(100*(math.tanh(combined/2)-actual), 3)})
    output = {"design": "Cycle-held-out approval-structural fit with fixed pre-2016-selected hyperparameters; 538 generic ballot available at each cutoff; 95/5 blend in D/R log odds. Final House vote is a terminal proxy, not held-today truth. Main historic approval uses the frozen Gallup series fitted by national_environment.py; archived 538 approval is an alternate-source sensitivity, not a retroactive 2026 NYT series.",
              "generic_source_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
              "rows": report}
    path = ROOT / "artifacts/calibration/stage6_national_signals.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([row for row in report if row["lead_days"] == 7], indent=2))


if __name__ == "__main__":
    main()
