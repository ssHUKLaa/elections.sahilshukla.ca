"""Validate the Stage 2 normalization and fundamentals acceptance gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def validate(database: Path, stage1: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise AssertionError(f"SQLite integrity check failed: {integrity}")
        metadata = dict(connection.execute("SELECT key,value FROM build_metadata"))
        if metadata["stage1_database_sha256"] != sha256(stage1):
            raise AssertionError("Stage 2 is stale relative to the Stage 1 database")
        alias_path = Path(__file__).resolve().parents[1] / "data/reference/prior_winner_alias_reviewed_2026.json"
        if metadata.get("prior_winner_alias_sha256") != sha256(alias_path):
            raise AssertionError("Stage 2 is stale relative to reviewed prior-winner aliases")
        aliases = json.loads(alias_path.read_text(encoding="utf-8"))
        for ballot_entry_id, alias in aliases.items():
            row = connection.execute("""SELECT prior_winner_match,match_method,evidence_source_race_id
                FROM candidate_features WHERE ballot_entry_id=?""", (ballot_entry_id,)).fetchone()
            if row != (1, "reviewed_official_winner_alias", alias["official_source_race_id"]):
                raise AssertionError(f"Reviewed prior winner not matched: {ballot_entry_id}")
        other_sullivan = connection.execute("""SELECT prior_winner_match FROM candidate_features
            WHERE ballot_entry_id='S-2026-AK-II-regular:DAN-J-SULLIVAN'""").fetchone()
        if other_sullivan != (0,):
            raise AssertionError("The other Dan Sullivan was incorrectly marked as prior winner")
        timmons = connection.execute("""SELECT f.prior_winner_match,f.match_method
            FROM candidates c JOIN candidate_features f USING(ballot_entry_id)
            WHERE c.race_id='H-2026-SC-04' AND c.name='William Timmons'""").fetchone()
        if timmons != (1, "official_unique_first_last"):
            raise AssertionError("The official middle initial prevented a verified incumbent match")
        registry = json.loads((Path(__file__).resolve().parents[1] /
                               "data/reference/ballot_registry_2026.json").read_text(encoding="utf-8"))
        candidate_count = len(registry["entries"])
        expectations = {"races": 506, "candidates": candidate_count,
                        "race_fundamentals": 506, "candidate_features": candidate_count}
        for table, expected in expectations.items():
            actual = scalar(connection, f"SELECT COUNT(*) FROM {table}")
            if actual != expected:
                raise AssertionError(f"{table}: expected {expected}, found {actual}")
        if scalar(connection, "SELECT COUNT(*) FROM candidates WHERE name LIKE '%▌%'"):
            raise AssertionError("A candidate stripe leaked into the Stage 2 database")
        if scalar(connection, """SELECT COUNT(*) FROM current_option_map
            WHERE mapping_status='mapped_candidate' AND (candidate_id IS NULL OR ballot_entry_id IS NULL)"""):
            raise AssertionError("mapped option lacks a stable candidate key")
        if scalar(connection, """SELECT COUNT(*) FROM current_question_map q WHERE model_eligible=1
            AND (mapping_status!='mapped' OR EXISTS (SELECT 1 FROM quarantine z
            WHERE z.snapshot_id=q.snapshot_id AND z.question_key=q.question_key))"""):
            raise AssertionError("an eligible question contains a quarantine or invalid status")
        if scalar(connection, """SELECT COUNT(*) FROM (SELECT source_candidate_id FROM current_option_map
            WHERE mapping_status='mapped_candidate' AND source_candidate_id IS NOT NULL AND source_candidate_id!=''
            GROUP BY source_candidate_id HAVING COUNT(DISTINCT candidate_id)>1)"""):
            raise AssertionError("a source candidate ID maps to multiple project candidates")
        if scalar(connection, """SELECT COUNT(*) FROM current_question_map q
            JOIN current_option_map o USING(snapshot_id,question_key)
            WHERE q.model_eligible=1 AND o.mapping_status='unmapped_candidate'"""):
            raise AssertionError("an unmapped candidate entered an eligible question")
        if scalar(connection, """SELECT COUNT(*) FROM current_question_map q
            WHERE q.model_eligible=1 AND (SELECT COUNT(*) FROM current_option_map o
            WHERE o.snapshot_id=q.snapshot_id AND o.question_key=q.question_key
            AND o.mapping_status='mapped_candidate') < 2"""):
            raise AssertionError("a question without a candidate contrast was marked eligible")
        if scalar(connection, """SELECT COUNT(*) FROM current_option_map o
            JOIN current_question_map q USING(snapshot_id,question_key)
            WHERE q.mapping_status IN ('mapped','quarantined_options')
            AND o.source_party='NONE' AND o.mapping_status!='noncandidate_response'"""):
            raise AssertionError("a party=NONE response bucket was treated as a candidate")
        alaska_sullivans = dict(connection.execute("""SELECT source_candidate_id,candidate_id
            FROM current_option_map WHERE source_candidate_id IN
            ('2b1d0cbf-bfeb-4358-80e4-0fadc1ba901b','cbe57fdb-832c-4d33-b7d7-ccd8ee1312a6')
            AND mapping_status='mapped_candidate' GROUP BY source_candidate_id,candidate_id"""))
        if alaska_sullivans != {
            "2b1d0cbf-bfeb-4358-80e4-0fadc1ba901b": "PERSON-AK-DAN-J-SULLIVAN",
            "cbe57fdb-832c-4d33-b7d7-ccd8ee1312a6": "PERSON-AK-DAN-S-SULLIVAN",
        }:
            raise AssertionError(f"Alaska Sullivan source IDs are not distinct: {alaska_sullivans}")
        if scalar(connection, "SELECT COUNT(*) FROM result_reconciliation WHERE status='mismatch'") < 1:
            raise AssertionError("result mismatch quarantine was not exercised")
        osborn = connection.execute(
            """SELECT ballot_party FROM historical_result_resolutions
            WHERE cycle=2024 AND office='senate' AND state='NE'
            AND candidate_name='Dan Osborn'""").fetchone()
        if osborn is None or osborn[0] != "":
            raise AssertionError("Nebraska's independent Senate candidate differs from the Clerk ballot label")
        if scalar(connection, """SELECT COUNT(*) FROM race_fundamentals f JOIN races r USING(race_id)
            WHERE r.office='house' AND r.state='MO'
            AND (f.geography_status!='missouri_2022_plan_current'
                 OR f.uncertainty_multiplier!=1.5)"""):
            raise AssertionError("Missouri House priors still use the superseded 2025 map assumption")
        for cycle, office, state, district, official, regular in connection.execute(
            """SELECT cycle,office,state,district,official_votes,archive_votes FROM result_reconciliation
            WHERE status='regular_special_split_verified'"""):
            special = connection.execute(
                """SELECT COALESCE(SUM(r.votes),0) FROM historical_results r
                JOIN historical_races h ON h.source_race_id=r.source_race_id
                WHERE h.cycle=? AND h.office=? AND h.state=? AND h.district=?
                AND h.stage='general' AND h.special=1 AND r.votes IS NOT NULL
                AND COALESCE(r.result_round,'') IN ('','1')""",
                (cycle, office, state, district)).fetchone()[0]
            if regular is None or official != regular + special or special <= 0:
                raise AssertionError(f"regular/special FEC partition changed: {cycle} {state}-{district}")
        if scalar(connection, """SELECT COUNT(*) FROM race_fundamentals
            WHERE evidence_status='quarantined_result_reconciliation'
            AND (dem_share IS NOT NULL OR rep_share IS NOT NULL OR other_share IS NOT NULL)"""):
            raise AssertionError("an unreconciled result supplied numerical fundamentals")
        house_unvalidated = scalar(connection, """SELECT COUNT(*) FROM race_fundamentals f JOIN races r USING(race_id)
            WHERE r.office='house' AND f.geography_status!='unresolved' AND f.uncertainty_multiplier<=1""")
        if house_unvalidated:
            raise AssertionError("an unvalidated House boundary baseline lacks widened uncertainty")
        if scalar(connection, """SELECT COUNT(*) FROM race_fundamentals f JOIN races r USING(race_id)
            WHERE r.office IN ('house','senate') AND
            (f.dem_share IS NULL OR f.rep_share IS NULL OR
             (f.baseline_source_race_id NOT LIKE 'official:%'
              AND f.evidence_status!='structured_same_seat_result_official_row_unavailable'))"""):
            raise AssertionError("a federal race lacks an accepted numerical baseline")
        if scalar(connection, """SELECT COUNT(*) FROM race_fundamentals f JOIN races r USING(race_id)
            WHERE r.office='senate' AND
            ((r.seat_class='II' AND f.baseline_cycle!=2020)
             OR (r.seat_class='III' AND f.baseline_cycle!=2022))"""):
            raise AssertionError("a Senate baseline came from the other seat class")
        if scalar(connection, """SELECT COUNT(*) FROM race_fundamentals f JOIN races r USING(race_id)
            WHERE r.office='senate' AND (f.dem_share<0.01 OR f.rep_share<0.01)
            AND f.evidence_status!='official_other_seat_statewide_fallback_for_structural_zero'"""):
            raise AssertionError("a structural major-party absence entered the Senate prior as zero support")
        if scalar(connection, """SELECT COUNT(*) FROM race_fundamentals f JOIN races r USING(race_id)
            WHERE r.office='house' AND (f.dem_share<0.01 OR f.rep_share<0.01)
            AND f.evidence_status!='official_same_district_contested_fallback_for_structural_zero'"""):
            raise AssertionError("a structural major-party absence entered the House prior as zero support")
        if scalar(connection, "SELECT COUNT(*) FROM fec_candidate_results") < 10000:
            raise AssertionError("official federal candidate result normalization is unexpectedly sparse")
        for cycle, office, state, district, total, winners, source_count, official, regular, status in connection.execute(
            """SELECT r.cycle,r.office,r.state,r.district,SUM(r.votes),SUM(r.winner),
            COUNT(DISTINCT r.source_race_id),q.official_votes,q.archive_votes,q.status
            FROM historical_result_resolutions r JOIN result_reconciliation q
            ON (r.cycle,r.office,r.state,r.district)=(q.cycle,q.office,q.state,q.district)
            GROUP BY r.cycle,r.office,r.state,r.district"""
        ):
            expected = regular if status == "regular_special_split_verified" else official
            if total != expected or winners != 1 or source_count != 1:
                raise AssertionError(f"official candidate resolution is incomplete: {cycle} {office} {state}-{district}")
        source = sqlite3.connect(stage1)
        try:
            latest = source.execute("SELECT snapshot_id FROM source_snapshots ORDER BY retrieved_at_utc DESC LIMIT 1").fetchone()[0]
            source_options = source.execute("SELECT COUNT(*) FROM poll_options WHERE snapshot_id=?", (latest,)).fetchone()[0]
        finally:
            source.close()
        normalized_options = scalar(connection, "SELECT COUNT(*) FROM current_option_map")
        if source_options != normalized_options:
            raise AssertionError("Stage 2 dropped source poll options")
        return {
            "status": "passed",
            "database_integrity": "ok",
            "race_and_candidate_keys_unique": True,
            "all_live_options_preserved": normalized_options,
            "unmapped_options_quarantined": scalar(connection, "SELECT COUNT(*) FROM quarantine"),
            "eligible_questions": scalar(connection, "SELECT COUNT(*) FROM current_question_map WHERE model_eligible=1"),
            "historical_poll_questions": scalar(connection, "SELECT COUNT(*) FROM historical_poll_questions"),
            "historical_result_rows": scalar(connection, "SELECT COUNT(*) FROM historical_results"),
            "fec_race_totals": scalar(connection, "SELECT COUNT(*) FROM fec_race_totals"),
            "official_federal_candidate_rows": scalar(connection, "SELECT COUNT(*) FROM fec_candidate_results"),
            "official_candidate_resolved_races": scalar(connection, """SELECT COUNT(*) FROM
                (SELECT DISTINCT cycle,office,state,district FROM historical_result_resolutions)"""),
            "federal_exact_or_tolerant_reconciliations": scalar(connection, "SELECT COUNT(*) FROM result_reconciliation WHERE status IN ('exact','within_tolerance')"),
            "verified_regular_special_splits": scalar(connection, "SELECT COUNT(*) FROM result_reconciliation WHERE status='regular_special_split_verified'"),
            "unreconciled_results_withheld": True,
            "house_boundary_uncertainty_widened": True,
            "all_federal_races_have_accepted_baselines": True,
            "reviewed_prior_winner_aliases_verified": len(aliases),
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--stage1-database", type=Path, default=Path("data/processed/stage1.sqlite"))
    args = parser.parse_args()
    print(json.dumps(validate(args.database, args.stage1_database), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
