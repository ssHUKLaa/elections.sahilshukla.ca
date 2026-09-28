"""List 2024 House seats unavailable for historical vote-share calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "artifacts/calibration/stage6_house_result_gaps.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        expected = {(row["state"], row["district_code"]) for row in connection.execute(
            "SELECT state, district_code FROM races WHERE office='house'"
        )}
        reconciled = {(row["state"], row["district"]) for row in connection.execute(
            "SELECT state, district FROM result_reconciliation "
            "WHERE cycle=2024 AND office='house' AND status IN ('exact','within_tolerance')"
        )}
        resolved = {(row["state"], row["district"]) for row in connection.execute(
            "SELECT DISTINCT state,district FROM historical_result_resolutions WHERE cycle=2024 AND office='house'"
        )}
        gaps = []
        for state, district in sorted(expected - reconciled):
            status = connection.execute(
                "SELECT status, reason, official_votes, archive_votes FROM result_reconciliation "
                "WHERE cycle=2024 AND office='house' AND state=? AND district=?",
                (state, district),
            ).fetchone()
            official = [dict(row) for row in connection.execute(
                "SELECT candidate_label, party, votes, included_in_valid_total, page "
                "FROM clerk_2024_candidate_results WHERE office='house' AND state=? AND district=? "
                "ORDER BY row_index",
                (state, district),
            )]
            archive = [dict(row) for row in connection.execute(
                "SELECT candidate_name, ballot_party, votes, result_round, source_race_id "
                "FROM historical_results WHERE cycle=2024 AND office='house' AND state=? "
                "AND district=? AND stage='general' AND special=0 ORDER BY source_result_id",
                (state, district),
            )]
            gap_type = "unopposed_no_reported_vote_total" if (
                not status and len(archive) == 1 and archive[0]["votes"] is None
            ) else "resolved_with_reviewed_official_candidate_rows" if (state, district) in resolved else "unreconciled_official_archive_totals"
            gaps.append({
                "state": state,
                "district": district,
                "gap_type": gap_type,
                "reconciliation": dict(status) if status else None,
                "official_candidate_rows": official,
                "archive_result_rows": archive,
            })
    report = {
        "design": "Compare the 2024 House map with exact/tolerant Clerk-to-archive result reconciliations. Source rows remain visible; no votes are imputed.",
        "source_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "expected_house_seats": len(expected),
        "reconciled_house_seats": len(expected & reconciled),
        "resolved_from_official_candidate_rows": len(expected & resolved),
        "unresolved_vote_share_seats": len(expected - reconciled - resolved),
        "gap_count": len(gaps),
        "gaps": gaps,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "expected_house_seats", "reconciled_house_seats",
        "resolved_from_official_candidate_rows", "unresolved_vote_share_seats",
        "gap_count"
    )}, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
