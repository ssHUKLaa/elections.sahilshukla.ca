"""Reproducible postwar House national-environment research.

Sources: Brookings Vital Statistics table 2-2 and the American Presidency
Project's dated presidential job approval tables.  This module deliberately
keeps the historical fit separate from the live race forecast until its
validation and signal-combination rules are reviewed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import numpy as np
import requests
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data" / "reference" / "national_environment"
BROOKINGS = "https://www.brookings.edu/wp-content/uploads/2026/04/2-2.csv"
APP = "https://www.presidency.ucsb.edu/statistics/data/presidential-job-approval-all-data"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.links = []
        self.href = None
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag == "a":
            self.href = attrs.get("href")
            self.anchor = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.anchor is not None:
            self.anchor.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "a" and self.anchor is not None:
            self.links.append((" ".join("".join(self.anchor).split()), self.href))
            self.anchor = None
            self.href = None


def download_sources() -> dict:
    REFERENCE.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    urls = {"house_votes.csv": BROOKINGS, "approval_index.html": APP}
    index = session.get(APP, timeout=45)
    index.raise_for_status()
    parser = TableParser()
    parser.feed(index.text)
    for label, href in parser.links:
        if not href or "approval" not in href.lower():
            continue
        if not any(name in label.lower() for name in (
            "truman", "eisenhower", "kennedy", "johnson", "nixon", "ford",
            "carter", "reagan", "bush", "clinton", "obama", "trump", "biden",
        )):
            continue
        slug = href.rstrip("/").split("/")[-1]
        urls[f"approval_{slug}.html"] = urljoin(APP, href)
    if len(urls) < 15:
        raise ValueError(f"Approval index exposed too few presidential tables: {len(urls)}")
    manifest = {}
    for name, url in urls.items():
        content = index.content if name == "approval_index.html" else session.get(url, timeout=45).content
        path = REFERENCE / name
        path.write_bytes(content)
        manifest[name] = {"url": url, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    (REFERENCE / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_sources() -> dict:
    manifest = json.loads((REFERENCE / "source_manifest.json").read_text(encoding="utf-8"))
    for name, item in manifest.items():
        content = (REFERENCE / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise ValueError(f"Historical national source changed after snapshot: {name}")
    return manifest


def restore_sources() -> dict:
    manifest = json.loads((REFERENCE / "source_manifest.json").read_text(encoding="utf-8"))
    for name, item in manifest.items():
        path = REFERENCE / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
            continue
        response = requests.get(item["url"], timeout=45)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != item["sha256"]:
            raise ValueError(f"Historical source no longer matches frozen snapshot: {name}")
        path.write_bytes(response.content)
    return manifest


def parse_house() -> dict[int, float]:
    text = (REFERENCE / "house_votes.csv").read_text(encoding="utf-8-sig")
    rows = csv.DictReader(io.StringIO(text.replace("\r\r\n", "\n")))
    result = {}
    for row in rows:
        year = int(row["Year"])
        d, r = float(row["DemPctVotes"]), float(row["RepPctVotes"])
        if d <= 0 or r <= 0 or d + r > 101:
            raise ValueError(f"Invalid Brookings House vote shares for {year}: {d}, {r}")
        result[year] = (d-r)/(d+r)
    if sorted(result) != list(range(1946, 2025, 2)):
        raise ValueError("Brookings House table does not cover every cycle from 1946 to 2024")
    return result


def parse_approval() -> list[dict]:
    observations = []
    for path in sorted(REFERENCE.glob("approval_*.html")):
        if path.name == "approval_index.html":
            continue
        parser = TableParser()
        parser.feed(path.read_text(encoding="utf-8"))
        for row in parser.rows:
            if len(row) < 4 or not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", row[0]):
                continue
            if "interpolat" in " ".join(row).lower():
                continue
            try:
                start = date.fromisoformat(f"{row[0][-4:]}-{int(row[0].split('/')[0]):02d}-{int(row[0].split('/')[1]):02d}")
                end = date.fromisoformat(f"{row[1][-4:]}-{int(row[1].split('/')[0]):02d}-{int(row[1].split('/')[1]):02d}")
                approve, disapprove = float(row[2]), float(row[3])
            except (ValueError, IndexError):
                continue
            if end < start or not (0 <= approve <= 100 and 0 <= disapprove <= 100) or approve + disapprove > 101:
                continue
            observations.append({"source": path.name, "start": start, "end": end,
                                 "approve": approve, "disapprove": disapprove})
    return observations


def election_date(year: int) -> date:
    first = date(year, 11, 1)
    return first + timedelta(days=(1-first.weekday()) % 7 + (7 if first.day + (1-first.weekday()) % 7 == 1 else 0))


def president(year: int) -> tuple[str, int]:
    # President in office on the general-election date; +1 Democrat, -1 Republican.
    intervals = [(1952, "truman", 1), (1960, "eisenhower", -1),
                 (1962, "kennedy", 1), (1968, "johnson", 1),
                 (1972, "nixon", -1), (1974, "ford", -1), (1976, "ford", -1),
                 (1980, "carter", 1), (1988, "reagan", -1),
                 (1992, "george-bush", -1), (2000, "clinton", 1),
                 (2008, "george-w-bush", -1), (2016, "obama", 1),
                 (2020, "donald-j-trump", -1), (2024, "joseph-r-biden", 1),
                 (2026, "donald-j-trump", -1)]
    return next((slug, party) for last, slug, party in intervals if year <= last)


def cycle_rows(house: dict[int, float], approval: list[dict], cutoff_days: int = 43) -> list[dict]:
    rows = []
    for year in range(1948, 2025, 2):
        slug, party = president(year)
        cutoff = election_date(year) - timedelta(days=cutoff_days)
        relevant = [r for r in approval if slug in r["source"] and r["end"] <= cutoff]
        relevant.sort(key=lambda r: r["end"], reverse=True)
        if not relevant:
            continue
        newest = relevant[0]["end"]
        window = [r for r in relevant if (newest-r["end"]).days <= 45]
        net = float(np.mean([r["approve"]-r["disapprove"] for r in window]))/100
        rows.append({"year": year, "margin": house[year], "previous_margin": house[year-2],
                     "president_party": party, "approval_net": net,
                     "signed_approval_net": party*net, "midterm": int(year % 4 == 2),
                     "approval_age_days": (cutoff-newest).days, "approval_poll_count": len(window),
                     "approval_last_end": newest.isoformat(), "cutoff": cutoff.isoformat()})
    return rows


def features(rows: list[dict]) -> np.ndarray:
    # Modest model size for 39 elections.  The midterm term learns the
    # president's party penalty; the approval term learns its interaction with
    # current public opinion.  Previous House vote anchors partisan baseline.
    return np.asarray([[r["previous_margin"], r["president_party"]*r["midterm"],
                        r["signed_approval_net"], r["president_party"]] for r in rows])


def fit(rows: list[dict], half_life_years: float, alpha: float, target_year: int):
    years = np.asarray([r["year"] for r in rows])
    weights = 2.0 ** (-(target_year-years)/half_life_years)
    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit(features(rows), [r["margin"] for r in rows], sample_weight=weights)
    return model


def evaluate(rows: list[dict]) -> dict:
    # Tune on rolling predictions through 2016. Keep 2018-24 untouched for a
    # genuine later-cycle check of the selected specification.
    candidates = [(hl, alpha) for hl in (16, 24, 40, 80) for alpha in (0.001, 0.01, 0.1)]
    scores = []
    for hl, alpha in candidates:
        predictions = []
        for test in rows:
            train = [r for r in rows if r["year"] < test["year"]]
            if len(train) < 12:
                continue
            model = fit(train, hl, alpha, test["year"])
            prediction = float(model.predict(features([test]))[0])
            predictions.append({"year": test["year"], "predicted": prediction,
                                "actual": test["margin"], "error": prediction-test["margin"]})
        tuning = [p for p in predictions if p["year"] <= 2016]
        rmse = math.sqrt(float(np.mean([p["error"]**2 for p in tuning])))
        scores.append({"half_life_years": hl, "ridge_alpha": alpha, "rolling_rmse": rmse,
                       "predictions": predictions})
    chosen = min(scores, key=lambda s: s["rolling_rmse"])
    later = [p for p in chosen["predictions"] if p["year"] >= 2018]
    holdout_rmse = math.sqrt(float(np.mean([p["error"]**2 for p in later])))
    return {"chosen": chosen, "later_cycle_rmse": holdout_rmse,
            "later_cycle_predictions": later,
            "grid": [{k: v for k, v in s.items() if k != "predictions"} for s in scores]}


def current_estimate(stage1_path: Path, cutoff: date, snapshot_id: str | None = None) -> dict:
    verify_sources()
    house = parse_house()
    approval = parse_approval()
    rows = cycle_rows(house, approval)
    validation = evaluate(rows)
    chosen = validation["chosen"]
    model = fit(rows, chosen["half_life_years"], chosen["ridge_alpha"], 2026)
    connection = sqlite3.connect(stage1_path)
    try:
        result = connection.execute(
            """SELECT date,
            MAX(CASE WHEN answer='Approve' THEN CAST(pct AS REAL) END),
            MAX(CASE WHEN answer='Disapprove' THEN CAST(pct AS REAL) END)
            FROM approval_averages WHERE date<=? AND (? IS NULL OR snapshot_id=?)
            GROUP BY date ORDER BY date DESC LIMIT 1""",
            (cutoff.isoformat(), snapshot_id, snapshot_id),
        ).fetchone()
    finally:
        connection.close()
    if not result or result[1] is None or result[2] is None:
        raise ValueError("Missing current NYT approval average")
    approval_net = (result[1]-result[2])/100
    current = {"year": 2026, "previous_margin": house[2024], "president_party": -1,
               "signed_approval_net": -approval_net, "midterm": 1}
    prediction = float(model.predict(features([current]))[0])
    error_sd = validation["chosen"]["rolling_rmse"]
    return {"margin": prediction, "margin_sd": error_sd,
            "approval_date": result[0], "approve": result[1], "disapprove": result[2],
            "previous_house_margin": house[2024], "training_cycles": len(rows),
            "approval_observations": len(approval),
            "half_life_years": chosen["half_life_years"], "ridge_alpha": chosen["ridge_alpha"],
            "rolling_tuning_rmse": chosen["rolling_rmse"],
            "later_cycle_rmse": validation["later_cycle_rmse"],
            "later_cycle_predictions": validation["later_cycle_predictions"],
            "coefficients": {"intercept": float(model.intercept_),
                             "previous_margin": float(model.coef_[0]),
                             "president_party_midterm": float(model.coef_[1]),
                             "signed_approval_net": float(model.coef_[2]),
                             "president_party": float(model.coef_[3])}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--restore", action="store_true", help="Restore and verify frozen source files")
    args = parser.parse_args()
    if args.download:
        download_sources()
    if args.restore:
        restore_sources()
    house = parse_house()
    approval = parse_approval()
    rows = cycle_rows(house, approval)
    if len(rows) < 35:
        raise ValueError(f"Too few matched historical election cycles: {len(rows)}")
    validation = evaluate(rows)
    chosen = validation["chosen"]
    model = fit(rows, chosen["half_life_years"], chosen["ridge_alpha"], 2026)
    result = {"source_manifest": json.loads((REFERENCE / "source_manifest.json").read_text()),
              "training_rows": rows, "approval_observations": len(approval),
              "validation": validation, "current": current_estimate(ROOT / "data" / "processed" / "stage1.sqlite", date(2026, 9, 21)), "coefficients": {"intercept": float(model.intercept_),
               "previous_margin": float(model.coef_[0]), "president_party_midterm": float(model.coef_[1]),
               "signed_approval_net": float(model.coef_[2]), "president_party": float(model.coef_[3])}}
    out = ROOT / "artifacts" / "national_environment_research.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cycles": len(rows), "approval_observations": len(approval),
                      "chosen": {k: v for k, v in chosen.items() if k != "predictions"},
                      "coefficients": result["coefficients"], "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
