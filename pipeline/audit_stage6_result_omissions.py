"""Audit official-result mismatches caused by omitted structured archive rows."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling.stage3_results_baseline import is_excluded_name

DB = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "artifacts/calibration/stage6_result_omission_audit.json"


def main() -> None:
    with sqlite3.connect(DB) as connection:
        connection.row_factory = sqlite3.Row
        official = {(row["cycle"], row["office"], row["state"], row["district"]): row
                    for row in connection.execute(
                        "SELECT * FROM result_reconciliation WHERE cycle IN (2020,2022,2024)"
                        " AND office IN ('house','senate')")}
        grouped = defaultdict(list)
        for row in connection.execute(
            "SELECT cycle,office,state,district,source_race_id,candidate_name,ballot_party,"
            "source_candidate_id,votes,result_round FROM historical_results"
            " WHERE cycle IN (2020,2022,2024) AND office IN ('house','senate')"
            " AND stage='general' AND special=0 AND votes IS NOT NULL"
            " AND (result_round IS NULL OR result_round='' OR result_round='1')"
        ):
            grouped[(row["cycle"], row["office"], row["state"], row["district"])].append(row)
    rows = []
    counts = Counter()
    for key, record in sorted(official.items()):
        if record["status"] != "mismatch" or record["archive_race_count"] != 1:
            continue
        observed = grouped.get(key, [])
        if not observed:
            continue
        old_total = sum(row["votes"] for row in observed
                        if row["source_candidate_id"] or row["ballot_party"])
        omitted = [row for row in observed if not (row["source_candidate_id"] or row["ballot_party"])
                   and not is_excluded_name(row["candidate_name"] or "")]
        revised_total = old_total + sum(row["votes"] for row in omitted)
        official_total = record["official_votes"]
        relative_difference = (abs(revised_total - official_total) / official_total
                               if official_total else None)
        class_name = ("recovered_exact" if revised_total == official_total else
                      "recovered_within_tolerance" if relative_difference is not None and relative_difference <= .001
                      else "still_mismatch")
        counts[(key[0], key[1], class_name)] += 1
        rows.append({"cycle": key[0], "office": key[1], "state": key[2], "district": key[3],
                     "official_votes": official_total, "previous_archive_votes": old_total,
                     "revised_archive_votes": revised_total, "classification": class_name,
                     "omitted_rows": [{"name": row["candidate_name"], "votes": row["votes"]}
                                      for row in omitted]})
    report = {"design": "Audit only previously mismatched, unique structured general-result races. Test whether adding positive-vote named rows lacking both source candidate ID and party reconciles the official total; exclude explicit noncandidate labels.",
              "counts": {f"{cycle}:{office}:{status}": n
                         for (cycle, office, status), n in sorted(counts.items())},
              "races": rows}
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(report["counts"], flush=True)
    print(OUTPUT, flush=True)


if __name__ == "__main__":
    main()
