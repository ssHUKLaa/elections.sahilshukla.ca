"""Audit whether discrepant 2020/22 federal archive rows can be resolved from FEC candidate rows."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as model
DB = ROOT / "data/processed/stage2.sqlite"
OUT = ROOT / "artifacts/calibration/stage6_fec_resolution_audit.json"


def main() -> None:
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    records = []
    for race in connection.execute("""SELECT * FROM result_reconciliation
        WHERE cycle IN (2020,2022) AND office='house' AND status='mismatch'
        ORDER BY cycle,state,district"""):
        key = (race["cycle"], race["office"], race["state"], race["district"])
        ids = [r[0] for r in connection.execute("""SELECT source_race_id FROM historical_races
            WHERE cycle=? AND office=? AND state=? AND district=? AND stage='general' AND special=0""", key)]
        official = [dict(row) for row in connection.execute("""SELECT candidate_name,party,votes,winner FROM fec_candidate_results
            WHERE cycle=? AND office=? AND state=? AND district=? ORDER BY row_index""", key)]
        archive = [dict(row) for row in connection.execute("""SELECT source_race_id,source_candidate_id,candidate_name,ballot_party,votes
            FROM historical_results WHERE cycle=? AND office=? AND state=? AND district=? AND stage='general'
            AND special=0 AND votes IS NOT NULL AND COALESCE(result_round,'') IN ('','1')""", key)]
        names = defaultdict(set)
        for item in archive:
            names[model.first_last_key(item["candidate_name"])].add(item["source_candidate_id"] or "")
        mismatches = []
        for item in official:
            key_name = model.official_name_key(item["candidate_name"])
            if key_name in {"scattered", "write ins", "write in", "all others", "other"}:
                continue
            if len(names.get(key_name, set())) != 1:
                mismatches.append({"candidate": item["candidate_name"], "key": key_name,
                                   "archive_ids": sorted(names.get(key_name, set()))})
        records.append({"cycle":race["cycle"],"state":race["state"],"district":race["district"],
                        "source_race_ids": ids,"official_total":race["official_votes"],
                        "official_sum":sum(row["votes"] for row in official),
                        "archive_total":race["archive_votes"],"official_candidate_count":len(official),
                        "archive_candidate_count":len(archive),"name_mismatches":mismatches,
                        "official":official,"archive":archive})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"races":records},indent=2)+"\n",encoding="utf-8")
    print("races",len(records),"fully_matched",sum(not r["name_mismatches"] for r in records))
    print("2022 PA",[(r["district"],len(r["name_mismatches"])) for r in records
                     if r["cycle"]==2022 and r["state"]=="PA"])


if __name__ == "__main__":
    main()
