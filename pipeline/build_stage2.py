"""Build the Stage 2 normalized mapping, results, and fundamentals database."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from pypdf import PdfReader


RACE_POLL_SOURCES = {
    "538_archive_senate_polls": "senate",
    "538_archive_house_polls": "house",
    "538_archive_governor_polls": "governor",
}
RESULT_SOURCES = {
    "538_results_senate": "senate",
    "538_results_house": "house",
    "538_results_governor": "governor",
}
AT_LARGE_STATES = {"AK", "DE", "ND", "SD", "VT", "WY"}
STATE_NAMES = {
    "ALABAMA":"AL", "ALASKA":"AK", "ARIZONA":"AZ", "ARKANSAS":"AR", "CALIFORNIA":"CA",
    "COLORADO":"CO", "CONNECTICUT":"CT", "DELAWARE":"DE", "FLORIDA":"FL", "GEORGIA":"GA",
    "HAWAII":"HI", "IDAHO":"ID", "ILLINOIS":"IL", "INDIANA":"IN", "IOWA":"IA",
    "KANSAS":"KS", "KENTUCKY":"KY", "LOUISIANA":"LA", "MAINE":"ME", "MARYLAND":"MD",
    "MASSACHUSETTS":"MA", "MICHIGAN":"MI", "MINNESOTA":"MN", "MISSISSIPPI":"MS", "MISSOURI":"MO",
    "MONTANA":"MT", "NEBRASKA":"NE", "NEVADA":"NV", "NEW HAMPSHIRE":"NH", "NEW JERSEY":"NJ",
    "NEW MEXICO":"NM", "NEW YORK":"NY", "NORTH CAROLINA":"NC", "NORTH DAKOTA":"ND", "OHIO":"OH",
    "OKLAHOMA":"OK", "OREGON":"OR", "PENNSYLVANIA":"PA", "RHODE ISLAND":"RI", "SOUTH CAROLINA":"SC",
    "SOUTH DAKOTA":"SD", "TENNESSEE":"TN", "TEXAS":"TX", "UTAH":"UT", "VERMONT":"VT",
    "VIRGINIA":"VA", "WASHINGTON":"WA", "WEST VIRGINIA":"WV", "WISCONSIN":"WI", "WYOMING":"WY",
}


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE races (
  race_id TEXT PRIMARY KEY, office TEXT NOT NULL, state TEXT NOT NULL,
  district_code TEXT, seat_class TEXT, election_type TEXT NOT NULL,
  stage TEXT NOT NULL, election_date TEXT NOT NULL, counting_rule TEXT NOT NULL,
  ballot_status TEXT NOT NULL, raw_json TEXT NOT NULL
);
CREATE TABLE candidates (
  ballot_entry_id TEXT PRIMARY KEY, race_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
  name TEXT NOT NULL, ballot_party TEXT, status TEXT NOT NULL, source_key TEXT,
  source_candidate_id TEXT, write_in_only INTEGER NOT NULL, raw_json TEXT NOT NULL,
  FOREIGN KEY(race_id) REFERENCES races(race_id)
);
CREATE TABLE current_question_map (
  snapshot_id TEXT NOT NULL, question_key TEXT NOT NULL, feed TEXT NOT NULL,
  project_race_id TEXT, observation_type TEXT NOT NULL, mapping_status TEXT NOT NULL,
  mapping_reason TEXT NOT NULL, model_eligible INTEGER NOT NULL,
  PRIMARY KEY(snapshot_id, question_key)
);
CREATE TABLE current_option_map (
  snapshot_id TEXT NOT NULL, question_key TEXT NOT NULL, option_index INTEGER NOT NULL,
  project_race_id TEXT, ballot_entry_id TEXT, candidate_id TEXT,
  response_kind TEXT NOT NULL, mapping_status TEXT NOT NULL, mapping_method TEXT,
  source_answer TEXT, source_candidate_name TEXT, source_candidate_id TEXT,
  source_party TEXT, pct REAL, PRIMARY KEY(snapshot_id,question_key,option_index)
);
CREATE TABLE quarantine (
  snapshot_id TEXT NOT NULL, question_key TEXT NOT NULL, option_index INTEGER,
  reason_code TEXT NOT NULL, detail TEXT NOT NULL,
  PRIMARY KEY(snapshot_id,question_key,option_index,reason_code)
);
CREATE TABLE historical_poll_questions (
  source_key TEXT NOT NULL, question_key TEXT NOT NULL, source_poll_id TEXT NOT NULL,
  source_question_id TEXT NOT NULL, cycle INTEGER, office TEXT NOT NULL, state TEXT,
  district TEXT, stage TEXT, election_date TEXT, start_date TEXT, end_date TEXT,
  source_created_at TEXT, availability_status TEXT NOT NULL, pollster TEXT,
  sample_size REAL, population TEXT, methodology TEXT, source_race_id TEXT,
  raw_json TEXT NOT NULL, PRIMARY KEY(source_key,question_key)
);
CREATE TABLE historical_poll_options (
  source_key TEXT NOT NULL, question_key TEXT NOT NULL, option_index INTEGER NOT NULL,
  answer TEXT, candidate_name TEXT, source_candidate_id TEXT, party TEXT, pct REAL,
  response_kind TEXT NOT NULL, raw_json TEXT NOT NULL,
  PRIMARY KEY(source_key,question_key,option_index)
);
CREATE TABLE historical_races (
  source_race_id TEXT PRIMARY KEY, cycle INTEGER, office TEXT, state TEXT,
  district TEXT, stage TEXT, special INTEGER, election_date TEXT,
  incumbent_party TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE historical_results (
  source_result_id TEXT PRIMARY KEY, source_race_id TEXT NOT NULL, cycle INTEGER,
  office TEXT NOT NULL, state TEXT, district TEXT, stage TEXT, special INTEGER,
  candidate_name TEXT, source_candidate_id TEXT, ballot_party TEXT,
  votes INTEGER, percent REAL, winner INTEGER, unopposed INTEGER,
  result_round TEXT, upstream_source TEXT, raw_json TEXT NOT NULL
);
CREATE TABLE fec_race_totals (
  cycle INTEGER NOT NULL, office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL,
  candidate_rows INTEGER NOT NULL, official_votes INTEGER NOT NULL,
  workbook_source_id TEXT NOT NULL, sheet_name TEXT NOT NULL,
  PRIMARY KEY(cycle,office,state,district)
);
CREATE TABLE fec_candidate_results (
  cycle INTEGER NOT NULL, office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL,
  row_index INTEGER NOT NULL, candidate_name TEXT NOT NULL, party TEXT,
  votes INTEGER NOT NULL, winner INTEGER NOT NULL, incumbent INTEGER NOT NULL,
  workbook_source_id TEXT NOT NULL, sheet_name TEXT NOT NULL,
  PRIMARY KEY(cycle,office,state,district,row_index)
);
CREATE TABLE clerk_2024_candidate_results (
  office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL,
  row_index INTEGER NOT NULL, candidate_label TEXT NOT NULL, party TEXT,
  votes INTEGER NOT NULL, included_in_valid_total INTEGER NOT NULL, page INTEGER NOT NULL,
  PRIMARY KEY(office,state,district,row_index)
);
CREATE TABLE result_reconciliation (
  cycle INTEGER NOT NULL, office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL,
  official_votes INTEGER, archive_votes INTEGER, absolute_difference INTEGER,
  relative_difference REAL, archive_race_count INTEGER NOT NULL,
  status TEXT NOT NULL, reason TEXT NOT NULL,
  PRIMARY KEY(cycle,office,state,district)
);
CREATE TABLE historical_result_resolutions (
  cycle INTEGER NOT NULL, office TEXT NOT NULL, state TEXT NOT NULL, district TEXT NOT NULL,
  source_race_id TEXT NOT NULL, source_candidate_id TEXT NOT NULL,
  candidate_name TEXT NOT NULL, ballot_party TEXT NOT NULL, votes INTEGER NOT NULL,
  winner INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
  PRIMARY KEY(cycle,office,state,district,source_candidate_id)
);
CREATE TABLE race_fundamentals (
  race_id TEXT PRIMARY KEY, baseline_cycle INTEGER, baseline_source_race_id TEXT,
  baseline_kind TEXT NOT NULL, dem_share REAL, rep_share REAL, other_share REAL,
  prior_winner_party TEXT, prior_incumbent_party TEXT,
  geography_status TEXT NOT NULL, uncertainty_multiplier REAL NOT NULL,
  evidence_status TEXT NOT NULL, note TEXT NOT NULL
);
CREATE TABLE candidate_features (
  ballot_entry_id TEXT PRIMARY KEY, race_id TEXT NOT NULL, prior_winner_match INTEGER NOT NULL,
  incumbent_status TEXT NOT NULL, evidence_source_race_id TEXT, match_method TEXT
);
"""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def number(value: Any) -> float | None:
    value = text(value).replace(",", "")
    if not value or value.lower() in {"nan", "unopposed"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def integer(value: Any) -> int | None:
    value_number = number(value)
    return None if value_number is None else int(round(value_number))


def truth(value: Any) -> int:
    return int(text(value).lower() in {"1", "true", "t", "yes", "y", "w", "(i)"})


def normalized_name(value: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    ascii_name = re.sub(r"\([^)]*\)", " ", ascii_name)
    ascii_name = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_name).lower().strip()
    tokens = [token for token in ascii_name.split() if token not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(tokens)


def excluded_result_name(value: str) -> bool:
    return normalized_name(value).startswith((
        "blank", "under vote", "undervote", "over vote", "overvote", "void",
        "continuing ballot", "exhausted ballot",
    ))


def federal_party_group(value: str | None) -> str:
    party = text(value).upper()
    tokens = {token for token in re.split(r"[^A-Z]+", party) if token}
    if tokens & {"D", "DEM", "DFL"} or party == "N(D)/D":
        return "D"
    if tokens & {"R", "REP"}:
        return "R"
    return "O"


def first_last_name(value: str) -> str:
    tokens = normalized_name(value).split()
    return " ".join((tokens[0], tokens[-1])) if len(tokens) >= 2 else " ".join(tokens)


def official_person_name(value: str) -> str:
    """Convert Clerk/FEC display forms to a conservative first/last match key."""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    party_words = {"republican", "democrat", "democratic", "libertarian", "independent",
                   "green", "constitution", "conservative", "working families"}
    if len(parts) >= 2 and normalized_name(parts[-1]) in party_words:
        parts = parts[:-1]
    if len(parts) == 2 and len(parts[0].split()) <= 3 and len(parts[1].split()) <= 4:
        value = f"{parts[1]} {parts[0]}"
    else:
        value = " ".join(parts) if parts else value
    return normalized_name(value)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def district_from_seat(office: str, seat: str) -> str:
    if office == "house":
        match = re.search(r"(\d+)", seat or "")
        return f"{int(match.group(1)):02d}" if match else "00"
    return "S" if office == "senate" else "G"


def office_from_name(value: str) -> str:
    value = value.lower()
    if "senate" in value:
        return "senate"
    if "house" in value or "representative" in value:
        return "house"
    if "governor" in value:
        return "governor"
    return value


def latest_historical_snapshot(root: Path) -> tuple[Path, dict[str, Any]]:
    snapshots = sorted(path for path in root.iterdir() if path.is_dir())
    if not snapshots:
        raise FileNotFoundError(f"No historical snapshot under {root}")
    snapshot = snapshots[-1]
    return snapshot, json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))


def insert_registry(connection: sqlite3.Connection, registry: dict[str, Any]) -> None:
    for race in registry["races"]:
        connection.execute(
            "INSERT INTO races VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                race["race_id"], race["office"], race["state"], race.get("district_code"),
                race.get("seat_class"), race["election_type"], race["stage"],
                race["election_date"], race["counting_rule"], race["ballot_status"],
                canonical(race),
            ),
        )
    for entry in registry["entries"]:
        connection.execute(
            "INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                entry["ballot_entry_id"], entry["race_id"], entry["candidate_id"],
                entry["name"], entry.get("ballot_party"), entry["status"],
                entry.get("source_key"), entry.get("source_candidate_id"),
                int(entry.get("write_in_only", False)), canonical(entry),
            ),
        )


def build_race_lookup(registry: dict[str, Any]) -> dict[tuple[str, str, str], list[str]]:
    lookup: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for race in registry["races"]:
        district = race.get("district_code") or ""
        lookup[(race["office"], race["state"], district)].append(race["race_id"])
    return lookup


def map_question(row: sqlite3.Row, race_lookup: dict[tuple[str, str, str], list[str]]) -> tuple[str | None, str, str, str]:
    if row["feed"] == "president_approval_polls":
        return None, "approval", "signal", "presidential approval question"
    if row["feed"] == "other":
        return None, "other_office", "out_of_scope", "other-office feed is contextual"
    if row["feed"] == "house" and row["state"] == "US":
        return None, "generic_ballot", "signal", "national generic ballot"
    if row["cycle"] != "2026":
        return None, "historical_or_future", "out_of_scope", f"cycle={row['cycle']}"
    office = row["feed"]
    district = ""
    if office == "house":
        if not text(row["seat_number"]).isdigit():
            return None, "race_poll", "unmapped_race", "missing House district number"
        district = f"{int(row['seat_number']):02d}"
        matches = race_lookup.get((office, row["state"], district), [])
        if not matches:
            state_matches = [
                race_ids for (o, state, _), race_ids in race_lookup.items()
                if o == office and state == row["state"]
            ]
            flattened = [race_id for group in state_matches for race_id in group]
            if len(flattened) == 1:
                matches = flattened
    else:
        matches = [
            race_id for (o, state, _), ids in race_lookup.items()
            if o == office and state == row["state"] for race_id in ids
        ]
    if len(matches) != 1:
        return None, "race_poll", "unmapped_race", f"race candidates={matches}"
    project_race = matches[0]
    target_stage = row["stage"] == "general" or (
        office == "house" and row["state"] == "LA" and row["stage"] == "primary"
    )
    if row["election_date"] != "2026-11-03" or not target_stage:
        return project_race, "race_poll", "out_of_scope_stage", (
            f"stage={row['stage']} election_date={row['election_date']}"
        )
    return project_race, "race_poll", "mapped", "unique office/state/seat and target stage"


def build_current_mapping(
    output: sqlite3.Connection, source: sqlite3.Connection, registry: dict[str, Any], aliases: dict[str, Any]
) -> str:
    source.row_factory = sqlite3.Row
    snapshot_id = source.execute(
        "SELECT snapshot_id FROM source_snapshots ORDER BY retrieved_at_utc DESC LIMIT 1"
    ).fetchone()[0]
    race_lookup = build_race_lookup(registry)
    entries_by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in registry["entries"]:
        entries_by_race[entry["race_id"]].append(entry)
    alias_lookup = {
        (match["state"], match["source_candidate_id"]): match["ballot_entry_id"]
        for match in aliases.get("matches", [])
    }
    entry_by_id = {entry["ballot_entry_id"]: entry for entry in registry["entries"]}

    questions = source.execute(
        "SELECT * FROM questions WHERE snapshot_id=? ORDER BY feed,question_key", (snapshot_id,)
    ).fetchall()
    for question in questions:
        race_id, observation_type, status, reason = map_question(question, race_lookup)
        options = source.execute(
            "SELECT * FROM poll_options WHERE snapshot_id=? AND question_key=? ORDER BY option_index",
            (snapshot_id, question["question_key"]),
        ).fetchall()
        all_candidate_options_mapped = True
        mapped_candidate_options = 0
        for option in options:
            option_status = "noncandidate_response"
            method = None
            ballot_entry = None
            candidate_id = None
            kind = option["response_kind"]
            # Some NYT response buckets have candidate-shaped IDs and names.  The
            # Stage 1 response kind, derived from party=NONE, prevents them from
            # invalidating an otherwise mapped candidate question.
            candidate_like = kind != "noncandidate_response" and bool(
                option["source_candidate_id"] or option["candidate_name"]
            )
            if status == "mapped" and candidate_like:
                candidates = entries_by_race[race_id]
                alias_id = alias_lookup.get((question["state"], option["source_candidate_id"]))
                if alias_id and alias_id in entry_by_id and entry_by_id[alias_id]["race_id"] == race_id:
                    matches = [entry_by_id[alias_id]]
                    method = "reviewed_source_id"
                else:
                    exact = [e for e in candidates if normalized_name(e["name"]) == normalized_name(option["candidate_name"])]
                    if len(exact) == 1:
                        matches = exact
                        method = "exact_normalized_name"
                    else:
                        loose = [e for e in candidates if first_last_name(e["name"]) == first_last_name(option["candidate_name"])]
                        matches = loose if len(loose) == 1 else []
                        method = "unique_first_last_name" if matches else None
                if len(matches) == 1:
                    ballot_entry = matches[0]["ballot_entry_id"]
                    candidate_id = matches[0]["candidate_id"]
                    option_status = "mapped_candidate"
                    mapped_candidate_options += 1
                    kind = "candidate"
                else:
                    option_status = "unmapped_candidate"
                    all_candidate_options_mapped = False
                    output.execute(
                        "INSERT INTO quarantine VALUES (?,?,?,?,?)",
                        (snapshot_id, question["question_key"], option["option_index"],
                         "unmapped_candidate", f"{option['candidate_name']} [{option['source_candidate_id']}]"),
                    )
            elif status == "mapped" and option["party"] not in (None, "", "NONE"):
                option_status = "unresolved_party_response"
                all_candidate_options_mapped = False
                output.execute(
                    "INSERT INTO quarantine VALUES (?,?,?,?,?)",
                    (snapshot_id, question["question_key"], option["option_index"],
                     "party_without_candidate_identity", f"{option['answer']} [{option['party']}]"),
                )
            elif status != "mapped":
                option_status = "not_applicable_to_target_race"
            output.execute(
                "INSERT INTO current_option_map VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    snapshot_id, question["question_key"], option["option_index"], race_id,
                    ballot_entry, candidate_id, kind, option_status, method,
                    option["answer"], option["candidate_name"], option["source_candidate_id"],
                    option["party"], number(option["pct"]),
                ),
            )
        hypothetical = text(question["hypothetical"]).lower() == "true"
        eligible = (
            status == "mapped" and all_candidate_options_mapped
            and mapped_candidate_options >= 2 and not hypothetical
        )
        if status == "mapped" and hypothetical:
            status = "scenario_only"
            reason = "source marks question hypothetical"
        if status == "mapped" and not all_candidate_options_mapped:
            status = "quarantined_options"
            reason = "one or more candidate-like options do not map uniquely"
        elif status == "mapped" and mapped_candidate_options < 2:
            status = "insufficient_candidate_contrast"
            reason = "fewer than two mapped candidates"
        output.execute(
            "INSERT INTO current_question_map VALUES (?,?,?,?,?,?,?,?)",
            (snapshot_id, question["question_key"], question["feed"], race_id,
             observation_type, status, reason, int(eligible)),
        )
    return snapshot_id


def insert_historical_question(
    connection: sqlite3.Connection, source_key: str, office: str, row: dict[str, str]
) -> str:
    key = f"{source_key}:{row['question_id']}"
    connection.execute(
        "INSERT INTO historical_poll_questions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            source_key, key, row["poll_id"], row["question_id"], integer(row.get("cycle")), office,
            row.get("state"), text(row.get("seat_number")), row.get("stage"), row.get("election_date"),
            row.get("start_date"), row.get("end_date"), row.get("created_at"),
            "source_database_created_at_timezone_unverified", row.get("pollster"),
            number(row.get("sample_size")), row.get("population"), row.get("methodology"),
            row.get("race_id"), canonical(row),
        ),
    )
    return key


def normalize_historical_polls(connection: sqlite3.Connection, root: Path, manifest: dict[str, Any]) -> None:
    for source_key, office in RACE_POLL_SOURCES.items():
        _, rows = read_csv(root / manifest["files"][source_key]["filename"])
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row["question_id"]].append(row)
        for question_id, question_rows in grouped.items():
            key = insert_historical_question(connection, source_key, office, question_rows[0])
            for index, row in enumerate(question_rows):
                connection.execute(
                    "INSERT INTO historical_poll_options VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (source_key, key, index, row.get("answer"), row.get("candidate_name"),
                     row.get("candidate_id"), row.get("candidate_party"), number(row.get("pct")),
                     "candidate" if row.get("candidate_id") or row.get("candidate_name") else "response",
                     canonical(row)),
                )

    source_key = "538_archive_generic_ballot_polls"
    _, rows = read_csv(root / manifest["files"][source_key]["filename"])
    for row in rows:
        key = insert_historical_question(connection, source_key, "generic_ballot", row)
        for index, party in enumerate(("dem", "rep", "ind")):
            if text(row.get(party)):
                connection.execute(
                    "INSERT INTO historical_poll_options VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (source_key, key, index, party.upper(), None, None, party.upper(),
                     number(row[party]), "party", canonical({"answer": party, "pct": row[party]})),
                )

    source_key = "538_archive_president_approval_polls"
    _, rows = read_csv(root / manifest["files"][source_key]["filename"])
    for row in rows:
        row = {**row, "cycle": "", "stage": "approval", "election_date": "", "race_id": "", "seat_number": ""}
        key = insert_historical_question(connection, source_key, "president_approval", row)
        for index, answer in enumerate(("yes", "no")):
            connection.execute(
                "INSERT INTO historical_poll_options VALUES (?,?,?,?,?,?,?,?,?,?)",
                (source_key, key, index, answer, None, None, None, number(row[answer]),
                 "approval_response", canonical({"answer": answer, "pct": row[answer]})),
            )


def normalize_historical_results(connection: sqlite3.Connection, root: Path, manifest: dict[str, Any]) -> None:
    _, race_rows = read_csv(root / manifest["files"]["538_results_races"]["filename"])
    for row in race_rows:
        office = office_from_name(row.get("office_name", ""))
        district = district_from_seat(office, row.get("office_seat_name", ""))
        connection.execute(
            "INSERT OR REPLACE INTO historical_races VALUES (?,?,?,?,?,?,?,?,?,?)",
            (row["id"], integer(row.get("cycle")), office, row.get("state_abbrev"), district,
             row.get("stage"), truth(row.get("special")), row.get("date"),
             row.get("incumbent_party"), canonical(row)),
        )
    for source_key, office in RESULT_SOURCES.items():
        _, rows = read_csv(root / manifest["files"][source_key]["filename"])
        for row in rows:
            district = district_from_seat(office, row.get("office_seat_name", ""))
            if office == "house" and row.get("state_abbrev") in AT_LARGE_STATES and district == "01":
                district = "00"
            connection.execute(
                "INSERT INTO historical_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["id"], row["race_id"], integer(row.get("cycle")), office,
                 row.get("state_abbrev"), district, row.get("stage"), truth(row.get("special")),
                 row.get("candidate_name") or row.get("alt_result_text"), row.get("candidate_id"),
                 row.get("ballot_party"), integer(row.get("votes")), number(row.get("percent")),
                 truth(row.get("winner")), truth(row.get("unopposed")), row.get("ranked_choice_round"),
                 row.get("source"), canonical(row)),
            )


def find_column(columns: Iterable[Any], required: tuple[str, ...], exact: str | None = None) -> Any:
    normalized = {column: re.sub(r"\s+", " ", text(column).upper()) for column in columns}
    if exact:
        for column, value in normalized.items():
            if value == exact:
                return column
    for column, value in normalized.items():
        if all(token in value for token in required):
            return column
    return None


def normalize_fec(connection: sqlite3.Connection, root: Path, manifest: dict[str, Any]) -> None:
    for cycle in range(2010, 2024, 2):
        source_id = f"fec_federal_elections_{cycle}"
        path = root / manifest["files"][source_id]["filename"]
        workbook = pd.ExcelFile(path)
        candidate_sheets = [
            sheet for sheet in workbook.sheet_names
            if ("Results by State" in sheet or "House & Senate Res" in sheet)
            and ("US " in sheet or cycle <= 2012)
        ]
        totals: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {"votes": 0, "rows": 0, "sheets": set()})
        row_indexes: dict[tuple[str, str, str], int] = defaultdict(int)
        for sheet in candidate_sheets:
            frame = pd.read_excel(path, sheet_name=sheet, header=0)
            state_col = find_column(frame.columns, ("STATE", "ABBREVIATION"))
            district_col = find_column(frame.columns, ("DISTRICT",), exact="D")
            if district_col is None:
                district_col = find_column(frame.columns, tuple(), exact="D")
            candidate_columns = [column for column in frame.columns if "CANDIDATE NAME" in text(column).upper()]
            candidate_col = next((column for column in candidate_columns if text(column).upper().strip() == "CANDIDATE NAME"), None)
            if candidate_col is None:
                candidate_col = next((column for column in candidate_columns if "LAST, FIRST" in text(column).upper()), None)
            if candidate_col is None and candidate_columns:
                candidate_col = candidate_columns[-1]
            party_col = find_column(frame.columns, tuple(), exact="PARTY")
            winner_col = find_column(frame.columns, ("GE", "WINNER"))
            incumbent_col = find_column(frame.columns, ("INCUMBENT",))
            if incumbent_col is None:
                incumbent_col = find_column(frame.columns, tuple(), exact="(I)")
            votes_col = find_column(frame.columns, ("GENERAL", "VOTES"))
            if votes_col is None:
                votes_col = find_column(frame.columns, tuple(), exact="GENERAL")
            if votes_col is None:
                continue
            for _, row in frame.iterrows():
                state = text(row.get(state_col)).upper()
                district_raw = text(row.get(district_col)).upper()
                votes = integer(row.get(votes_col))
                candidate = text(row.get(candidate_col))
                if not re.fullmatch(r"[A-Z]{2}", state) or votes is None or not candidate:
                    continue
                if any(marker in candidate.lower() for marker in ("votes:", "district ", "total state")):
                    continue
                # FEC sheets for years with both a regular and special Senate
                # election label the regular rows S-FULL TERM (with varying
                # spaces/parentheses). Keep that race and exclude the separate
                # unexpired-term contest from this regular-seat table.
                if district_raw.startswith("S") and "UNEXPIRED" in district_raw:
                    continue
                office = "senate" if district_raw == "S" or (
                    district_raw.startswith("S") and "FULL" in district_raw
                ) else "house"
                if office == "senate":
                    district = "S"
                else:
                    match = re.search(r"\d+", district_raw)
                    if not match:
                        continue
                    district = f"{int(match.group()):02d}"
                item = totals[(office, state, district)]
                item["votes"] += votes
                item["rows"] += 1
                item["sheets"].add(sheet)
                row_index = row_indexes[(office, state, district)]
                row_indexes[(office, state, district)] += 1
                connection.execute(
                    "INSERT INTO fec_candidate_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cycle, office, state, district, row_index, candidate,
                     text(row.get(party_col)).upper(), votes, truth(row.get(winner_col)),
                     truth(row.get(incumbent_col)), source_id, sheet),
                )
        for (office, state, district), item in totals.items():
            connection.execute(
                "INSERT INTO fec_race_totals VALUES (?,?,?,?,?,?,?,?)",
                (cycle, office, state, district, item["rows"], item["votes"], source_id,
                 "; ".join(sorted(item["sheets"]))),
            )


def clerk_party(label: str) -> str | None:
    lowered = label.lower()
    party_names = (
        ("republican", "REP"), ("democrat", "DEM"), ("libertarian", "LIB"),
        ("green", "GRN"), ("constitution", "CON"), ("independent", "IND"),
        ("conservative", "CONSERVATIVE"), ("working families", "WORKING_FAMILIES"),
        ("write-in", "W"), ("scattering", "W"),
    )
    for name, code in party_names:
        if name in lowered:
            return code
    return None


def normalize_clerk_2024(connection: sqlite3.Connection, root: Path, manifest: dict[str, Any]) -> None:
    record = manifest["files"].get("house_clerk_federal_elections_2024")
    if not record:
        raise ValueError("Historical snapshot lacks the official 2024 House Clerk PDF")
    reader = PdfReader(str(root / record["filename"]))
    parsed: list[tuple[str, str, str, str, int, int]] = []
    state = office = district = None
    line_pattern = re.compile(r"^\s*(?:(\d+)\.\s+)?(.+?)\.{5,}\s+([\d,]+)\s*$")
    for page_number, page in enumerate(reader.pages, 1):
        try:
            page_text = page.extract_text(extraction_mode="layout") or ""
        except KeyError:
            continue
        for line in page_text.splitlines():
            stripped = line.strip().replace("�Continued", "").replace("—Continued", "").strip()
            if stripped.upper() in STATE_NAMES:
                state = STATE_NAMES[stripped.upper()]
            if "Recapitulation of Votes Cast" in stripped:
                office = None
            if stripped.startswith("FOR UNITED STATES SENATOR"):
                office, district = "senate", "S"
                continue
            if stripped.startswith("FOR UNITED STATES REPRESENTATIVE"):
                office, district = "house", None
                continue
            if stripped.startswith("FOR PRESIDENTIAL"):
                office = None
                continue
            if office and stripped == "AT LARGE":
                district = "00"
                continue
            if not office or not state:
                continue
            match = line_pattern.match(line.replace("�", ""))
            if not match:
                continue
            if match.group(1):
                district = f"{int(match.group(1)):02d}"
            if office == "house" and district is None:
                continue
            parsed.append((office, state, district, match.group(2).strip(),
                           int(match.group(3).replace(",", "")), page_number))
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    row_indexes: dict[tuple[str, str, str], int] = defaultdict(int)
    excluded_prefixes = ("blank", "under vote", "undervote", "over vote", "overvote",
                         "void", "continuing ballot", "exhausted ballot")
    for office, state, district, label, votes, page in parsed:
        key = (office, state, district)
        included = not normalized_name(label).startswith(excluded_prefixes)
        row_index = row_indexes[key]
        row_indexes[key] += 1
        connection.execute(
            "INSERT INTO clerk_2024_candidate_results VALUES (?,?,?,?,?,?,?,?,?)",
            (office, state, district, row_index, label, clerk_party(label), votes, int(included), page),
        )
        if included:
            totals[key] += votes
            counts[key] += 1
            connection.execute(
                "INSERT INTO fec_candidate_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (2024, office, state, district, row_index, label, clerk_party(label), votes,
                 0, 0, "house_clerk_federal_elections_2024", "candidate detail pages"),
            )
    for (office, state, district), votes in totals.items():
        connection.execute(
            "INSERT INTO fec_race_totals VALUES (?,?,?,?,?,?,?,?)",
            (2024, office, state, district, counts[(office,state,district)], votes,
             "house_clerk_federal_elections_2024", "candidate detail pages"),
        )


def reconcile_results(connection: sqlite3.Connection) -> None:
    archive_rows: dict[tuple[int, str, str, str], list[tuple[int, str]]] = defaultdict(list)
    for row in connection.execute(
        """SELECT cycle,office,state,district,source_race_id,candidate_name,votes
        FROM historical_results WHERE cycle BETWEEN 2010 AND 2024
        AND cycle % 2 = 0 AND office IN ('house','senate')
        AND stage IN ('general','jungle primary')
        AND special=0 AND votes IS NOT NULL
        AND (result_round IS NULL OR result_round='' OR result_round='1')"""
    ):
        if excluded_result_name(row[5] or ""):
            continue
        district = ("00" if row[1] == "house" and
                    (row[2] in AT_LARGE_STATES or (row[2] == "MT" and row[0] <= 2020))
                    else row[3])
        archive_rows[(row[0], row[1], row[2], district)].append((row[6], row[4]))
    archive = {key: (sum(votes for votes, _ in rows), len({race_id for _, race_id in rows}))
               for key, rows in archive_rows.items()}
    official = {
        (row[0], row[1], row[2], row[3]): row[4]
        for row in connection.execute(
            "SELECT cycle,office,state,district,official_votes FROM fec_race_totals"
        )
    }
    for key in sorted(set(archive) | set(official)):
        official_votes = official.get(key)
        archive_data = archive.get(key)
        archive_votes = archive_data[0] if archive_data else None
        race_count = archive_data[1] if archive_data else 0
        if official_votes is None:
            status, reason = "missing_official_parse", "archive race lacks a parsed FEC total"
        elif archive_votes is None:
            status, reason = "missing_archive", "FEC race lacks a structured archive result"
        elif race_count != 1:
            status, reason = "ambiguous_archive_races", f"{race_count} archive races share this key"
        else:
            difference = abs(official_votes - archive_votes)
            relative = difference / official_votes if official_votes else None
            if difference == 0:
                status, reason = "exact", "totals match"
            elif relative is not None and relative <= 0.001:
                status, reason = "within_tolerance", "difference is at most 0.1%"
            else:
                status, reason = "mismatch", "requires row-level reconciliation before modeling"
                # Some official totals combine regular and special elections.
                # Accept the regular archived race only if candidate-vote
                # multisets exactly partition the official total.
                cycle, office, state, district = key
                if office in ("house", "senate"):
                    official_rows = sorted(row[0] for row in connection.execute(
                        "SELECT votes FROM fec_candidate_results WHERE cycle=? AND office=? AND state=? AND district=?", key))
                    official_source = "FEC"
                    if not official_rows and cycle == 2024:
                        official_rows = sorted(row[0] for row in connection.execute(
                            """SELECT votes FROM clerk_2024_candidate_results
                            WHERE office=? AND state=? AND district=? AND included_in_valid_total=1""",
                            (office, state, district)))
                        official_source = "House Clerk"
                    archive_by_special = {}
                    for special in (0, 1):
                        archive_by_special[special] = [row[0] for row in connection.execute(
                            """SELECT r.votes FROM historical_results r JOIN historical_races h
                            ON h.source_race_id=r.source_race_id
                            WHERE h.cycle=? AND h.office=? AND h.state=?
                            AND h.district IN (?,?) AND h.stage='general' AND h.special=?
                            AND r.votes IS NOT NULL AND COALESCE(r.result_round,'') IN ('','1')""",
                            (cycle, office, state, district,
                             "01" if state in AT_LARGE_STATES else district, special))]
                    combined_rows = sorted(archive_by_special[0] + archive_by_special[1])
                    if (archive_by_special[0] and archive_by_special[1]
                            and official_rows == combined_rows
                            and sum(archive_by_special[0]) == archive_votes
                            and sum(combined_rows) == official_votes):
                        status = "regular_special_split_verified"
                        reason = (f"{official_source} candidate votes exactly partition into "
                                  "archived regular and special general elections")
        difference = None if official_votes is None or archive_votes is None else abs(official_votes - archive_votes)
        relative = None if difference is None or not official_votes else difference / official_votes
        connection.execute(
            "INSERT INTO result_reconciliation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (*key, official_votes, archive_votes, difference, relative, race_count, status, reason),
        )


def load_reviewed_2024_house_resolutions(connection: sqlite3.Connection, root: Path, manifest: dict[str, Any]) -> None:
    review_path = Path(__file__).resolve().parents[1] / "data/reference/stage6_house_2024_official_resolutions.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    pdf_record = manifest["files"]["house_clerk_federal_elections_2024"]
    if review["source_sha256"] != pdf_record["sha256"] or sha256(root / pdf_record["filename"]) != review["source_sha256"]:
        raise ValueError("Reviewed 2024 House resolutions do not match the pinned Clerk PDF")
    for race in review["races"]:
        key = (2024, "house", race["state"], race["district"])
        row = connection.execute(
            "SELECT official_votes,status FROM result_reconciliation WHERE cycle=? AND office=? AND state=? AND district=?", key
        ).fetchone()
        if row is None or row[0] != race["official_total"] or row[1] != "mismatch":
            raise ValueError(f"Official resolution no longer matches a discrepant race: {key}")
        source_ids = {item[0] for item in connection.execute(
            "SELECT DISTINCT source_candidate_id FROM historical_results WHERE source_race_id=? AND source_candidate_id!=''",
            (race["source_race_id"],),
        )}
        if sum(candidate["votes"] for candidate in race["candidates"]) != race["official_total"]:
            raise ValueError(f"Reviewed candidate votes do not match official total: {key}")
        if sum(bool(candidate["winner"]) for candidate in race["candidates"]) != 1:
            raise ValueError(f"Reviewed race must have one winner: {key}")
        for candidate in race["candidates"]:
            if not candidate["candidate_id"].startswith("official:") and candidate["candidate_id"] not in source_ids:
                raise ValueError(f"Reviewed candidate ID absent from archive: {key} {candidate['candidate_id']}")
            connection.execute(
                "INSERT INTO historical_result_resolutions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*key, race["source_race_id"], candidate["candidate_id"], candidate["name"],
                 candidate["party"], candidate["votes"], int(candidate["winner"]), review["source_sha256"]),
            )


def load_fec_candidate_resolutions(connection: sqlite3.Connection, root: Path,
                                   manifest: dict[str, Any]) -> None:
    """Resolve federal total mismatches when FEC rows map uniquely or are new.

    FEC scattered/write-in rows may be absent in the polling archive. Preserve
    source candidate IDs for named candidates and add synthetic IDs only for
    the official unnamed vote rows. Ambiguous names remain withheld.
    """
    aliases = {
        (2020, "NY", "24", "steven williams"): "steve williams",
        (2020, "PA", "08", "matthew cartwright"): "matt cartwright",
        (2020, "PA", "10", "eugenio depasquale"): "eugene depasquale",
        (2020, "PA", "12", "fred keller"): "frederick keller",
        (2020, "PA", "14", "bill marx"): "william marx",
        (2022, "NJ", "08", "robert menendez"): "rob menendez",
        (2022, "NJ", "09", "pascrell bill"): "bill pascrell",
        (2022, "NJ", "10", "payne m"): "donald payne",
        (2022, "NJ", "10", "childress howard"): "clenard childress",
        (2022, "PA", "15", "mike molesevich"): "michael molesevich",
    }
    unnamed = {"scattered", "write in", "write ins", "all others", "other", "no name"}
    for cycle, office, state, district, official_total in connection.execute(
        """SELECT cycle,office,state,district,official_votes FROM result_reconciliation
        WHERE ((cycle IN (2020,2022) AND office='house')
            OR (cycle BETWEEN 2010 AND 2022 AND office='senate'))
        AND status='mismatch'
        ORDER BY cycle,state,district"""
    ).fetchall():
        key = (cycle, office, state, district)
        race_ids = [row[0] for row in connection.execute(
            """SELECT source_race_id FROM historical_races WHERE cycle=? AND office=?
            AND state=? AND district=? AND stage='general' AND special=0""", key
        )]
        if len(race_ids) != 1:
            continue
        source_race_id = race_ids[0]
        source_rows = connection.execute(
            """SELECT source_candidate_id,candidate_name,ballot_party FROM historical_results
            WHERE source_race_id=? AND votes IS NOT NULL
            AND COALESCE(result_round,'') IN ('','1')""", (source_race_id,)
        ).fetchall()
        archive: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        for candidate_id, name, party in source_rows:
            archive[first_last_name(name)].add((candidate_id or "", name, party or ""))
        official_rows = connection.execute(
            """SELECT row_index,candidate_name,party,votes,winner FROM fec_candidate_results
            WHERE cycle=? AND office=? AND state=? AND district=? ORDER BY row_index""", key
        ).fetchall()
        if not official_rows or sum(row[3] for row in official_rows) != official_total:
            continue
        replacement = []
        for row_index, name, party, votes, winner in official_rows:
            name_key = first_last_name(official_person_name(name))
            name_key = aliases.get((cycle, state, district, name_key), name_key)
            if name_key in unnamed or name_key not in archive:
                candidate_id = f"official:fec:{cycle}:{state}:{district}:{row_index}"
                display_name = official_person_name(name)
            else:
                matches = archive.get(name_key, set())
                matched_ids = {item[0] for item in matches}
                if len(matched_ids) != 1:
                    replacement = []
                    break
                candidate_id = next(iter(matched_ids))
                display_name = sorted(item[1] for item in matches)[0]
                if not candidate_id:
                    replacement = []
                    break
            replacement.append((candidate_id, display_name, party or "", votes, winner))
        if not replacement or len({row[0] for row in replacement if row[4]}) != 1:
            continue
        combined: dict[str, list[Any]] = {}
        for candidate_id, name, party, votes, winner in replacement:
            item = combined.setdefault(candidate_id, [name, party, 0, 0])
            if federal_party_group(item[1]) == "O" and federal_party_group(party) in {"D", "R"}:
                item[1] = party
            item[2] += votes
            item[3] = int(bool(item[3] or winner))
        source_record = manifest["files"][f"fec_federal_elections_{cycle}"]
        source_sha = source_record["sha256"]
        if sha256(root / source_record["filename"]) != source_sha:
            raise ValueError(f"FEC {cycle} source hash changed during resolution")
        for candidate_id, (name, party, votes, winner) in combined.items():
            connection.execute(
                "INSERT INTO historical_result_resolutions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*key, source_race_id, candidate_id, name, party, votes, int(bool(winner)), source_sha),
            )


def load_reviewed_earlier_house_resolutions(connection: sqlite3.Connection, root: Path,
                                            manifest: dict[str, Any]) -> None:
    review = json.loads((Path(__file__).resolve().parents[1] /
                         "data/reference/stage6_house_2018_2022_official_resolutions.json")
                        .read_text(encoding="utf-8"))
    for race in review["races"]:
        cycle, state, district = race["cycle"], race["state"], race["district"]
        key = (cycle, "house", state, district)
        source = manifest["files"][f"fec_federal_elections_{cycle}"]
        if race["source_sha256"] != source["sha256"] or sha256(root / source["filename"]) != race["source_sha256"]:
            raise ValueError(f"Reviewed FEC source changed: {key}")
        reconciliation = connection.execute(
            "SELECT official_votes,status FROM result_reconciliation WHERE cycle=? AND office=? AND state=? AND district=?",
            key).fetchone()
        if reconciliation is None or reconciliation[0] != race["official_total"] or reconciliation[1] != "mismatch":
            raise ValueError(f"Reviewed FEC race no longer needs resolution: {key}")
        official = sorted((int(row[0]), federal_party_group(row[1])) for row in connection.execute(
            "SELECT votes,party FROM fec_candidate_results WHERE cycle=? AND office=? AND state=? AND district=?", key))
        reviewed = sorted((item["votes"], federal_party_group(item["party"])) for item in race["candidates"])
        if official != reviewed or sum(item["votes"] for item in race["candidates"]) != race["official_total"]:
            raise ValueError(f"Reviewed candidate votes differ from FEC rows: {key}")
        if sum(bool(item["winner"]) for item in race["candidates"]) != 1:
            raise ValueError(f"Reviewed FEC race needs one winner: {key}")
        archived_ids = {row[0] for row in connection.execute(
            "SELECT DISTINCT source_candidate_id FROM historical_results WHERE source_race_id=?", (race["source_race_id"],))}
        for item in race["candidates"]:
            if not item["candidate_id"].startswith("official:fec:") and item["candidate_id"] not in archived_ids:
                raise ValueError(f"Reviewed candidate is absent from archive: {key} {item['candidate_id']}")
            connection.execute(
                "INSERT INTO historical_result_resolutions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (*key, race["source_race_id"], item["candidate_id"], item["name"], item["party"],
                 item["votes"], int(item["winner"]), race["source_sha256"]),
            )


def load_clerk_senate_regular_splits(connection: sqlite3.Connection, root: Path,
                                    manifest: dict[str, Any]) -> None:
    """Carry official ballot labels into Senate races split from specials."""
    source = manifest["files"]["house_clerk_federal_elections_2024"]
    source_sha = source["sha256"]
    if sha256(root / source["filename"]) != source_sha:
        raise ValueError("House Clerk source hash changed")
    for state, district in connection.execute(
        """SELECT state,district FROM result_reconciliation WHERE cycle=2024
        AND office='senate' AND status='regular_special_split_verified'"""
    ).fetchall():
        races = connection.execute(
            """SELECT source_race_id FROM historical_races WHERE cycle=2024
            AND office='senate' AND state=? AND district=?
            AND stage='general' AND special=0""", (state, district)
        ).fetchall()
        if len(races) != 1:
            raise ValueError(f"Regular Senate source race missing: {state}")
        race_id = races[0][0]
        archived = connection.execute(
            """SELECT source_candidate_id,candidate_name,votes,winner
            FROM historical_results WHERE source_race_id=? AND votes IS NOT NULL""",
            (race_id,)).fetchall()
        official = connection.execute(
            """SELECT candidate_label,party,votes FROM clerk_2024_candidate_results
            WHERE office='senate' AND state=? AND district=?
            AND included_in_valid_total=1""", (state, district)
        ).fetchall()
        by_votes = defaultdict(list)
        for label, party, votes in official:
            by_votes[votes].append((label, party))
        for candidate_id, name, votes, winner in archived:
            matches = by_votes[votes]
            if len(matches) != 1:
                raise ValueError(f"Ambiguous Clerk vote-row match: {state} {name}")
            label, party = matches[0]
            official_name = label.split(",", 1)[0].strip()
            if not name.lower().startswith("write-") and first_last_name(name) != first_last_name(official_name):
                raise ValueError(f"Clerk name mismatch: {state} {name} vs {label}")
            connection.execute(
                "INSERT INTO historical_result_resolutions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (2024, "senate", state, district, race_id, candidate_id,
                 name, party or "", votes, int(winner), source_sha),
            )


def build_fundamentals(connection: sqlite3.Connection, registry: dict[str, Any]) -> None:
    reviewed_aliases = json.loads((Path(__file__).resolve().parents[1] / "data/reference/prior_winner_alias_reviewed_2026.json").read_text(encoding="utf-8"))
    used_aliases: set[str] = set()
    result_rows = connection.execute(
        """SELECT h.source_race_id,h.cycle,h.office,h.state,h.district,h.incumbent_party,
        r.candidate_name,r.ballot_party,r.votes,r.winner
        FROM historical_races h JOIN historical_results r ON r.source_race_id=h.source_race_id
        WHERE h.stage IN ('general','runoff') AND h.cycle<=2024 AND r.votes IS NOT NULL
        AND (r.result_round IS NULL OR r.result_round='' OR r.result_round='1')"""
    ).fetchall()
    by_race: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    race_meta: dict[str, tuple[Any, ...]] = {}
    for row in result_rows:
        if excluded_result_name(row[6] or ""):
            continue
        by_race[row[0]].append(row)
        race_meta[row[0]] = row[:6]
    candidates_by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in registry["entries"]:
        candidates_by_race[entry["race_id"]].append(entry)

    for race in registry["races"]:
        office, state = race["office"], race["state"]
        district = race.get("district_code") or ("S" if office == "senate" else "G")
        if office in {"house", "senate"}:
            desired_senate_cycle = None
            if office == "senate":
                desired_senate_cycle = 2020 if race.get("seat_class") == "II" else 2022
            official_cycle_row = connection.execute(
                """SELECT MAX(cycle) FROM fec_candidate_results
                WHERE cycle<2026 AND office=? AND state=? AND district=?
                AND (? IS NULL OR cycle=?)""",
                (office, state, district, desired_senate_cycle, desired_senate_cycle),
            ).fetchone()
            official_cycle = official_cycle_row[0] if official_cycle_row else None
            if official_cycle is not None:
                official_rows = connection.execute(
                    """SELECT candidate_name,party,votes,winner,incumbent FROM fec_candidate_results
                    WHERE cycle=? AND office=? AND state=? AND district=?""",
                    (official_cycle, office, state, district),
                ).fetchall()
                total = sum(row[2] for row in official_rows)
                dem_votes = sum(row[2] for row in official_rows if federal_party_group(row[1]) == "D")
                rep_votes = sum(row[2] for row in official_rows if federal_party_group(row[1]) == "R")
                share_total, share_dem, share_rep = total, dem_votes, rep_votes
                structural_fallback_cycle = None
                if total and (dem_votes == 0 or rep_votes == 0):
                    fallback_cycles = [
                        row[0] for row in connection.execute(
                            """SELECT DISTINCT cycle FROM fec_candidate_results
                            WHERE cycle<2026 AND cycle!=? AND office=?
                            AND state=? AND district=? ORDER BY cycle DESC""",
                            (official_cycle, office, state, district),
                        )
                    ]
                    for fallback_cycle in fallback_cycles:
                        fallback_rows = connection.execute(
                            """SELECT party,votes FROM fec_candidate_results
                            WHERE cycle=? AND office=? AND state=? AND district=?""",
                            (fallback_cycle, office, state, district),
                        ).fetchall()
                        fallback_dem = sum(row[1] for row in fallback_rows if federal_party_group(row[0]) == "D")
                        fallback_rep = sum(row[1] for row in fallback_rows if federal_party_group(row[0]) == "R")
                        if fallback_dem and fallback_rep:
                            structural_fallback_cycle = fallback_cycle
                            share_total = sum(row[1] for row in fallback_rows)
                            share_dem, share_rep = fallback_dem, fallback_rep
                            break
                winners = [row for row in official_rows if row[3]]
                if not winners and official_rows:
                    winners = [max(official_rows, key=lambda row: row[2])]
                winner = winners[0] if winners else None
                winner_party = text(winner[1]).upper() if winner else None
                prior_names = {official_person_name(row[0]) for row in winners}
                candidate_name_counts = Counter(first_last_name(entry["name"]) for entry in candidates_by_race[race["race_id"]])
                prior_first_last_counts = Counter(first_last_name(name) for name in prior_names)
                if office == "house":
                    geography_status = "missouri_2022_plan_current" if state == "MO" else "same_district_label_boundaries_not_yet_validated"
                    multiplier = 1.5
                    evidence = (
                        "official_same_district_contested_fallback_for_structural_zero"
                        if structural_fallback_cycle is not None
                        else "official_result_with_widened_boundary_uncertainty"
                    )
                    note = (
                        f"Latest result lacked a major-party nominee; shares use the {structural_fallback_cycle} same-district result with widened boundary uncertainty"
                        if structural_fallback_cycle is not None
                        else "Official prior result; not treated as a validated 2026-boundary partisan lean"
                    )
                    kind = "official_prior_same_district_result"
                else:
                    geography_status = "statewide_comparable"
                    multiplier = 1.25 if structural_fallback_cycle is not None else 1.0
                    evidence = (
                        "official_other_seat_statewide_fallback_for_structural_zero"
                        if structural_fallback_cycle is not None else "official_statewide_result"
                    )
                    note = (
                        f"Same-seat result had a structurally absent major party; shares use the {structural_fallback_cycle} statewide Senate result"
                        if structural_fallback_cycle is not None else "Official House Clerk or FEC statewide result"
                    )
                    kind = "official_prior_statewide_office_result"
                source_id = f"official:{official_cycle}:{office}:{state}:{district}"
                connection.execute(
                    "INSERT INTO race_fundamentals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (race["race_id"], official_cycle, source_id, kind,
                     share_dem / share_total if share_total else None, share_rep / share_total if share_total else None,
                     (share_total-share_dem-share_rep) / share_total if share_total else None,
                     winner_party, None, geography_status, multiplier, evidence, note),
                )
                for entry in candidates_by_race[race["race_id"]]:
                    matched = normalized_name(entry["name"]) in prior_names
                    match_method = "official_normalized_name" if matched else None
                    first_last = first_last_name(entry["name"])
                    if (not matched and candidate_name_counts[first_last] == 1
                            and prior_first_last_counts[first_last] == 1):
                        matched = True
                        match_method = "official_unique_first_last"
                    alias = reviewed_aliases.get(entry["ballot_entry_id"])
                    if alias is not None:
                        expected_name = official_person_name(alias["official_winner_name"])
                        if (alias["official_source_race_id"] != source_id
                                or expected_name not in prior_names):
                            raise ValueError(f"Reviewed prior-winner alias has no matching official winner: {entry['ballot_entry_id']}")
                        matched = True
                        match_method = "reviewed_official_winner_alias"
                        used_aliases.add(entry["ballot_entry_id"])
                    connection.execute(
                        "INSERT INTO candidate_features VALUES (?,?,?,?,?,?)",
                        (entry["ballot_entry_id"], race["race_id"], int(matched),
                         "prior_general_winner" if matched else "not_established",
                         source_id if matched else None, match_method),
                    )
                continue
        possible = []
        for source_race_id, meta in race_meta.items():
            _, cycle, hist_office, hist_state, hist_district, _ = meta
            location_match = hist_state == state and hist_office == office
            if office == "house":
                location_match = location_match and hist_district == district
            if (
                location_match and cycle and cycle < 2026
                and (office != "senate" or cycle == desired_senate_cycle)
            ):
                possible.append((cycle, source_race_id))
        if not possible:
            connection.execute(
                "INSERT INTO race_fundamentals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (race["race_id"], None, None, "no_comparable_result", None, None, None,
                 None, None, "unresolved", 2.0, "missing", "No prior comparable general result in archive"),
            )
            prior_names: set[str] = set()
            prior_race_id = None
        else:
            cycle, prior_race_id = max(possible)
            rows = by_race[prior_race_id]
            party_votes: dict[str, int] = defaultdict(int)
            total = 0
            winner_party = None
            prior_names = set()
            for row in rows:
                votes = row[8]
                party = text(row[7]).upper()
                total += votes
                party_votes[party] += votes
                if row[9]:
                    winner_party = party
                    prior_names.add(normalized_name(text(row[6])))
            dem = sum(v for p, v in party_votes.items() if p in {"DEM", "D"}) / total if total else None
            rep = sum(v for p, v in party_votes.items() if p in {"REP", "R"}) / total if total else None
            other = None if total == 0 else max(0.0, 1.0 - (dem or 0) - (rep or 0))
            if office == "house":
                geography_status = "missouri_2022_plan_current" if state == "MO" else "same_district_label_boundaries_not_yet_validated"
                multiplier = 1.5
                evidence = "fallback_with_widened_uncertainty"
                note = "Prior House result is not treated as a validated 2026-boundary partisan lean"
            else:
                geography_status = "statewide_comparable"
                multiplier = 1.0
                evidence = "structured_result_pending_final_official_reconciliation"
                note = "Latest prior statewide general result"
            incumbent_party = race_meta[prior_race_id][5]
            reconciliation_status = None
            if office in {"house", "senate"}:
                reconciliation_row = connection.execute(
                    """SELECT status FROM result_reconciliation
                    WHERE cycle=? AND office=? AND state=? AND district=?""",
                    (cycle, office, state, district),
                ).fetchone()
                reconciliation_status = reconciliation_row[0] if reconciliation_row else "missing"
            same_seat_senate_fallback = office == "senate" and cycle == desired_senate_cycle
            if same_seat_senate_fallback:
                multiplier = max(multiplier, 1.25)
                evidence = "structured_same_seat_result_official_row_unavailable"
                note = "Same-seat Senate result from structured archive; official normalized row unavailable"
            elif office in {"house", "senate"} and reconciliation_status not in {"exact", "within_tolerance", "regular_special_split_verified"}:
                dem = rep = other = None
                winner_party = None
                prior_names = set()
                multiplier = max(multiplier, 2.0)
                evidence = "quarantined_result_reconciliation"
                note += f"; FEC cross-check status={reconciliation_status}, so vote shares are withheld"
            elif office == "governor":
                multiplier = max(multiplier, 1.25)
                evidence = "state_source_link_present_pending_official_reconciliation"
                note += "; candidate rows retain upstream state-result links"
            connection.execute(
                "INSERT INTO race_fundamentals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (race["race_id"], cycle, prior_race_id,
                 "prior_same_district_result" if office == "house" else "prior_statewide_office_result",
                 dem, rep, other, winner_party, incumbent_party, geography_status,
                 multiplier, evidence, note),
            )
        candidate_name_counts = Counter(first_last_name(row["name"]) for row in candidates_by_race[race["race_id"]])
        prior_first_last_counts = Counter(first_last_name(name) for name in prior_names)
        for entry in candidates_by_race[race["race_id"]]:
            if entry["ballot_entry_id"] in reviewed_aliases:
                raise ValueError(f"Reviewed official prior-winner alias did not use official result: {entry['ballot_entry_id']}")
            matched = normalized_name(entry["name"]) in prior_names
            first_last = first_last_name(entry["name"])
            if (not matched and candidate_name_counts[first_last] == 1
                    and prior_first_last_counts[first_last] == 1):
                matched = True
            connection.execute(
                "INSERT INTO candidate_features VALUES (?,?,?,?,?,?)",
                (entry["ballot_entry_id"], race["race_id"], int(matched),
                 "prior_general_winner" if matched else "not_established",
                 prior_race_id if matched else None,
                 ("exact_normalized_name" if normalized_name(entry["name"]) in prior_names else "unique_first_last") if matched else None),
            )
    if used_aliases != set(reviewed_aliases):
        raise ValueError(f"Unused prior-winner aliases: {sorted(set(reviewed_aliases)-used_aliases)}")


def build(args: argparse.Namespace) -> dict[str, Any]:
    registry_path = Path("data/reference/ballot_registry_2026.json")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    aliases = json.loads(Path("data/reference/nyt_alias_reviewed_2026.json").read_text(encoding="utf-8"))
    historical_root, historical_manifest = latest_historical_snapshot(args.historical_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".building.sqlite")
    temp.unlink(missing_ok=True)
    output = sqlite3.connect(temp)
    source = sqlite3.connect(args.stage1_database)
    try:
        output.executescript(SCHEMA)
        with output:
            insert_registry(output, registry)
            snapshot_id = build_current_mapping(output, source, registry, aliases)
            normalize_historical_polls(output, historical_root, historical_manifest)
            normalize_historical_results(output, historical_root, historical_manifest)
            normalize_fec(output, historical_root, historical_manifest)
            normalize_clerk_2024(output, historical_root, historical_manifest)
            reconcile_results(output)
            load_reviewed_2024_house_resolutions(output, historical_root, historical_manifest)
            load_fec_candidate_resolutions(output, historical_root, historical_manifest)
            load_reviewed_earlier_house_resolutions(output, historical_root, historical_manifest)
            load_clerk_senate_regular_splits(output, historical_root, historical_manifest)
            build_fundamentals(output, registry)
            metadata = {
                "stage2_version": "1.9",
                "source_snapshot_id": snapshot_id,
                "stage1_database_sha256": sha256(args.stage1_database),
                "race_registry_sha256": sha256(registry_path),
                "prior_winner_alias_sha256": sha256(Path(__file__).resolve().parents[1] / "data/reference/prior_winner_alias_reviewed_2026.json"),
                "historical_snapshot": historical_root.name,
                "historical_manifest_sha256": sha256(historical_root / "manifest.json"),
            }
            output.executemany("INSERT INTO build_metadata VALUES (?,?)", metadata.items())
        output.execute("PRAGMA integrity_check").fetchone()
    finally:
        source.close()
        output.close()
    args.output.unlink(missing_ok=True)
    temp.replace(args.output)
    connection = sqlite3.connect(args.output)
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("races", "candidates", "current_question_map", "current_option_map",
                          "quarantine", "historical_poll_questions", "historical_poll_options",
                          "historical_results", "fec_race_totals", "result_reconciliation",
                          "fec_candidate_results", "clerk_2024_candidate_results",
                          "race_fundamentals", "candidate_features")
        }
    finally:
        connection.close()
    return {"status": "built", "database": str(args.output), "counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-database", type=Path, default=Path("data/processed/stage1.sqlite"))
    parser.add_argument("--historical-root", type=Path, default=Path("data/raw/historical"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/stage2.sqlite"))
    args = parser.parse_args()
    print(json.dumps(build(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
