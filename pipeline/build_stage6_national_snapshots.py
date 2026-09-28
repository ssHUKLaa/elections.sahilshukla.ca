"""Reconstruct dated national poll snapshots from pinned 538 archive files.

These are observed inputs, not election-day estimates. The archive was captured
after the elections, so retrospective revisions cannot be excluded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import historical_pollster_quality as ratings
from modeling import national_environment as national

SOURCE = ROOT / "data/raw/historical_wayback/20241129"
MANIFEST = ROOT / "data/reference/stage6_wayback_manifest.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_national_snapshots.json"
PRIORITY = {"lv": 4, "rv": 3, "v": 2, "a": 1}


def parse_date(value: str) -> datetime:
    return datetime.strptime(value.split(" ")[0], "%m/%d/%y")


def read_sources() -> tuple[dict[str, list[dict]], dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = {"generic": [], "approval": []}
    for filename, spec in manifest["national_files"].items():
        path = SOURCE / filename
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        if observed != spec["sha256"]:
            raise ValueError(f"National archive hash mismatch: {filename}")
        kind = "generic" if filename.startswith("generic") else "approval"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            result[kind].extend({**row, "source_file": filename} for row in csv.DictReader(stream))
    return result, manifest


def summarize(rows: list[dict], cycle: int, lead: int, kind: str,
              quality_by_rating: dict[str, float]) -> dict:
    cutoff = datetime.combine(national.election_date(cycle) - timedelta(days=lead),
                              datetime.min.time())
    expected_president = "Donald Trump" if cycle in (2018, 2020) else "Joe Biden"
    selected: dict[str, dict] = {}
    exclusions: dict[str, int] = {}
    for row in rows:
        if kind == "generic" and row.get("cycle") != str(cycle):
            continue
        if kind == "approval" and row.get("politician") != expected_president:
            continue
        try:
            end = parse_date(row["end_date"])
            created = parse_date(row["created_at"])
            start = parse_date(row["start_date"])
            left = float(row["dem"] if kind == "generic" else row["yes"])
            right = float(row["rep"] if kind == "generic" else row["no"])
        except (ValueError, TypeError, KeyError):
            exclusions["invalid_row"] = exclusions.get("invalid_row", 0) + 1
            continue
        if not (start <= end < cutoff and created + timedelta(days=1) <= cutoff):
            continue
        if (cutoff - end).days > 180 or left <= 0 or right <= 0:
            continue
        if kind == "generic" and row.get("stage") != "general":
            continue
        poll_id = row["poll_id"]
        weight = quality_by_rating.get(row.get("pollster_rating_id", ""), 1.0)
        if weight <= 0:
            exclusions["banned_pollster"] = exclusions.get("banned_pollster", 0) + 1
            continue
        item = {"poll_id": poll_id, "source_file": row["source_file"],
                "end": end, "created": created, "left": left, "right": right,
                "sample_size": float(row.get("sample_size") or 600),
                "population": (row.get("population") or "").lower(),
                "quality": weight, "question_id": row.get("question_id", "")}
        old = selected.get(poll_id)
        rank = (PRIORITY.get(item["population"], 0), item["sample_size"], item["question_id"])
        old_rank = ((PRIORITY.get(old["population"], 0), old["sample_size"], old["question_id"])
                    if old else None)
        if old is None or rank > old_rank:
            selected[poll_id] = item
    chosen = list(selected.values())
    if not chosen:
        return {"status": "missing", "cutoff": cutoff.date().isoformat(),
                "poll_count": 0, "exclusions": exclusions}
    weights = [math.exp(-math.log(2) * (cutoff - r["end"]).days / 30)
               * math.sqrt(max(100, r["sample_size"]) / 600) * r["quality"] for r in chosen]
    values = ([math.log(r["left"] / r["right"]) for r in chosen] if kind == "generic"
              else [(r["left"] - r["right"]) / 100 for r in chosen])
    total = sum(weights)
    mean = sum(w * v for w, v in zip(weights, values)) / total
    n_eff = total * total / sum(w * w for w in weights)
    variance = sum(w * (v - mean) ** 2 for w, v in zip(weights, values)) / total
    return {"status": "available", "cutoff": cutoff.date().isoformat(),
            "poll_count": len(chosen), "effective_poll_count": n_eff,
            "mean": mean, "poll_dispersion_sd": math.sqrt(variance),
            "oldest_end": min(r["end"] for r in chosen).date().isoformat(),
            "newest_end": max(r["end"] for r in chosen).date().isoformat(),
            "latest_created": max(r["created"] for r in chosen).date().isoformat(),
            "source_files": sorted({r["source_file"] for r in chosen}),
            "exclusions": exclusions}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    rows, manifest = read_sources()
    house = national.parse_house()
    snapshots = []
    for cycle in (2018, 2020, 2022, 2024):
        if cycle == 2018:
            by_rating, rating_meta = {}, {"rating_edition": None}
        else:
            _, rating_meta = ratings.load(cycle)
            by_rating, _ = ratings.rating_weights(cycle)
        for lead in (90, 30, 7):
            generic = summarize(rows["generic"], cycle, lead, "generic", by_rating)
            approval = summarize(rows["approval"], cycle, lead, "approval", by_rating)
            actual = house[cycle]
            if generic["status"] == "available":
                generic["implied_D_two_party_margin"] = math.tanh(generic["mean"] / 2)
                generic["terminal_margin_error"] = generic["implied_D_two_party_margin"] - actual
            snapshots.append({"cycle": cycle, "lead_days": lead,
                              "generic_ballot": generic, "presidential_approval": approval,
                              "terminal_house_D_two_party_margin": actual,
                              "rating_edition": rating_meta["rating_edition"]})
    output = {"design": {"availability": "created_at calendar day plus one full day, with fieldwork ended",
                         "window_days": 180, "half_life_days": 30,
                         "deduplication": "one best population/sample question per poll ID",
                         "warning": "Archived files were captured after the elections and could contain retrospective revisions; terminal results do not directly identify cutoff support.",
                         "source_manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
                         "source_hashes": {k: v["sha256"] for k, v in manifest["national_files"].items()}},
              "snapshots": snapshots}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    for item in snapshots:
        print(item["cycle"], item["lead_days"],
              item["generic_ballot"]["poll_count"],
              item["presidential_approval"]["poll_count"])


if __name__ == "__main__":
    main()
