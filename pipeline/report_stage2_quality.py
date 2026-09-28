"""Write machine-readable and human-readable Stage 2 coverage reports."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def rows(connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, parameters)]


def build_report(database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        report = {
            "stage": 2,
            "database": str(database),
            "metadata": {row["key"]: row["value"] for row in connection.execute("SELECT * FROM build_metadata")},
            "race_inventory": rows(connection, "SELECT office,ballot_status,count(*) AS races FROM races GROUP BY office,ballot_status ORDER BY office,ballot_status"),
            "counting_rules": rows(connection, "SELECT office,counting_rule,count(*) AS races FROM races GROUP BY office,counting_rule ORDER BY office,counting_rule"),
            "question_status": rows(connection, "SELECT feed,mapping_status,count(*) AS questions FROM current_question_map GROUP BY feed,mapping_status ORDER BY feed,mapping_status"),
            "eligible_race_coverage": rows(connection, """SELECT r.office,count(DISTINCT q.project_race_id) AS races_with_eligible_questions,
                count(*) AS eligible_questions FROM current_question_map q JOIN races r ON r.race_id=q.project_race_id
                WHERE q.model_eligible=1 GROUP BY r.office ORDER BY r.office"""),
            "option_status": rows(connection, "SELECT mapping_status,count(*) AS options FROM current_option_map GROUP BY mapping_status ORDER BY options DESC"),
            "candidate_match_methods": rows(connection, """SELECT mapping_method,count(*) AS options FROM current_option_map
                WHERE mapping_status='mapped_candidate' GROUP BY mapping_method ORDER BY options DESC"""),
            "quarantine_reasons": rows(connection, "SELECT reason_code,count(*) AS records FROM quarantine GROUP BY reason_code ORDER BY records DESC"),
            "top_unmapped_candidates": rows(connection, """SELECT source_candidate_name,source_party,count(*) AS appearances,
                count(DISTINCT project_race_id) AS races FROM current_option_map
                WHERE mapping_status='unmapped_candidate' GROUP BY source_candidate_name,source_party
                ORDER BY appearances DESC,source_candidate_name LIMIT 100"""),
            "historical_poll_coverage": rows(connection, """SELECT source_key,office,min(cycle) AS first_cycle,max(cycle) AS last_cycle,
                count(*) AS questions FROM historical_poll_questions GROUP BY source_key,office ORDER BY source_key"""),
            "result_reconciliation": rows(connection, "SELECT cycle,office,status,count(*) AS races FROM result_reconciliation GROUP BY cycle,office,status ORDER BY cycle,office,status"),
            "fundamentals_status": rows(connection, """SELECT r.office,f.geography_status,f.evidence_status,count(*) AS races
                FROM race_fundamentals f JOIN races r USING(race_id)
                GROUP BY r.office,f.geography_status,f.evidence_status ORDER BY r.office,races DESC"""),
            "state_coverage": rows(connection, """SELECT r.office,r.state,count(*) AS races,
                sum(CASE WHEN f.dem_share IS NOT NULL OR f.rep_share IS NOT NULL THEN 1 ELSE 0 END) AS usable_baselines,
                sum(CASE WHEN f.evidence_status LIKE 'quarantined%' OR f.evidence_status='missing' THEN 1 ELSE 0 END) AS quarantined_or_missing
                FROM races r JOIN race_fundamentals f USING(race_id)
                GROUP BY r.office,r.state ORDER BY r.office,r.state"""),
        }
        return report
    finally:
        connection.close()


def markdown(report: dict[str, Any]) -> str:
    eligible = {row["office"]: row for row in report["eligible_race_coverage"]}
    options = {row["mapping_status"]: row["options"] for row in report["option_status"]}
    quarantine = sum(row["records"] for row in report["quarantine_reasons"])
    reconciliation: dict[str, int] = {}
    for row in report["result_reconciliation"]:
        reconciliation[row["status"]] = reconciliation.get(row["status"], 0) + row["races"]
    lines = [
        "# Stage 2 data-quality report",
        "",
        f"Source snapshot: `{report['metadata']['source_snapshot_id']}`.",
        "",
        "## Live poll mapping",
        "",
        "| Office | Races with eligible polls | Eligible questions |",
        "| --- | ---: | ---: |",
    ]
    for office in ("house", "senate", "governor"):
        row = eligible.get(office, {})
        lines.append(f"| {office.title()} | {row.get('races_with_eligible_questions', 0)} | {row.get('eligible_questions', 0)} |")
    lines += [
        "",
        f"Mapped candidate option rows: **{options.get('mapped_candidate', 0):,}**. Quarantined option rows: **{quarantine:,}**. A quarantined option makes its question ineligible; it is never silently dropped from an otherwise eligible vector.",
        "",
        "Most quarantined rows are candidates appearing in hypothetical general-election combinations who are not in the current ballot registry. They remain available for review and future dated ballot scenarios.",
        "",
        "## Historical inputs",
        "",
        f"Normalized historical poll questions: **{sum(row['questions'] for row in report['historical_poll_coverage']):,}**.",
        "",
        f"Federal result cross-checks: **{reconciliation.get('exact', 0):,} exact**, **{reconciliation.get('within_tolerance', 0):,} within 0.1%**, **{reconciliation.get('mismatch', 0):,} quarantined mismatches**, **{reconciliation.get('missing_archive', 0) + reconciliation.get('missing_official_parse', 0):,} missing on one side**.",
        "",
        "The numerical federal baselines come directly from normalized FEC workbooks and the official 2024 House Clerk publication. The FiveThirtyEight archive is a cross-check: mismatched comparisons remain quarantined and do not replace the official values.",
        "",
        "## Geography and baseline policy",
        "",
        "Every one of the 506 races has a fundamentals record. All 435 House and 35 Senate records use an official prior federal result. Governor baselines use the latest comparable statewide result, retain upstream state-result links, and remain pending final official reconciliation. House results are never labeled as a validated 2026-boundary lean: same-number district results carry a 1.5 uncertainty multiplier and Missouri carries 2.0.",
        "",
        "The companion JSON contains state, ballot-status, counting-rule, source-cycle, reconciliation, and top-unmapped-candidate detail.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--json", type=Path, default=Path("data/reference/stage2_quality_report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("docs/stage2_quality_report.md"))
    args = parser.parse_args()
    report = build_report(args.database)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(args.json), "markdown": str(args.markdown)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
