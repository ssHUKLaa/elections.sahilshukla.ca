"""Build secondary-source ballot entries from snapshot Wikipedia summaries.

Reviewed state-source races are excluded so official/manual catalogs always win.
The result is an inventory input, not a claim of state certification.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

sys.path.insert(0, "data/raw/.vendor")
import pandas as pd  # noqa: E402

from build_official_ballot_subset import add_entry  # noqa: E402


STATE_NAMES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

PARTY_ALIASES = {
    "Democratic": "Democratic", "Republican": "Republican", "Independent": "Independent",
    "Libertarian": "Libertarian", "Green": "Green", "Constitution": "Other Candidates",
    "DFL": "Democratic", "U.S. Taxpayers": "Other Candidates",
    "Legal Marijuana Now": "Other Candidates", "No Labels": "Other Candidates",
    "Unity": "Other Candidates", "American Constitution": "Other Candidates",
    "Working Class": "Working Class Party", "Freedom and Unity": "Other Candidates",
    "United Citizens": "Other Candidates", "American Center": "Other Candidates",
    "Alaskan": "Other Candidates",
}

CANDIDATE_RE = re.compile(r"^(.+?)\s+\(([^()]+)\)$")


def flat_columns(frame: pd.DataFrame) -> list[str]:
    return [str(col[-1] if isinstance(col, tuple) else col) for col in frame.columns]


def parse_candidates(value: object) -> list[tuple[str, str, bool]]:
    text = str(value).replace("\\u258c", "▌").replace("\xa0", " ").strip()
    if text in {"", "TBD", "nan"}:
        return []
    found = []
    if "▌" not in text:
        return []
    for segment in text.split("▌"):
        segment = re.sub(r"\[[^\]]+\]", "", segment).strip()
        if not segment:
            continue
        match = CANDIDATE_RE.fullmatch(segment)
        if not match:
            raise ValueError(f"Could not parse candidate segment: {segment!r} from {text!r}")
        name, label = match.groups()
        write_in = "write-in" in label.lower()
        party = re.sub(r",?\s*write-in", "", label, flags=re.I).strip()
        found.append((name.strip(), party, write_in))
    if not found:
        raise ValueError(f"Could not parse candidate cell: {text}")
    return found


def state_from_location(location: str) -> tuple[str, str]:
    normalized = location.replace("\xa0", " ").strip()
    for state_name in sorted(STATE_NAMES, key=len, reverse=True):
        if normalized == state_name or normalized.startswith(state_name + " "):
            return STATE_NAMES[state_name], normalized[len(state_name):].strip()
    raise ValueError(f"Unknown state location: {location}")


def existing_races() -> set[str]:
    paths = [
        "data/reference/ballot_entries_official_subset_2026.json",
        "data/reference/ballot_entries_reviewed_2026.json",
        "data/reference/ballot_entries_wa_reviewed_2026.json",
        "data/reference/ballot_entries_il_2026.json",
        "data/reference/ballot_entries_al_2026.json",
    ]
    result = set()
    for path in paths:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        result.update(entry["race_id"] for entry in doc["entries"])
    return result


def add_rows(entries: list[dict], race_id: str, candidates: list[tuple[str, str, bool]],
             source_record: str, excluded: set[str]) -> None:
    if race_id in excluded:
        return
    for name, source_party, write_in in candidates:
        normalized_party = PARTY_ALIASES.get(source_party, "Other Candidates")
        add_entry(entries, race_id, name, normalized_party, "wikipedia_2026_summaries",
                  "secondary_source_general_list", source_record,
                  "Wikipedia aggregation; requires final state-source verification.")
        entries[-1]["source_party_label"] = source_party
        entries[-1]["write_in_only"] = write_in


def main() -> None:
    snapshot = max(
        path for path in Path("data/raw/wikipedia").iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    universe = json.loads(Path("data/reference/races_2026.json").read_text(encoding="utf-8"))
    races = universe["races"]
    by_office_state = {}
    for race in races:
        by_office_state.setdefault((race["office"], race["state"]), []).append(race["race_id"])
    excluded = existing_races()
    entries: list[dict] = []

    # The 50 state tables are the consecutive 7-column tables whose final column is Candidates.
    house_tables = pd.read_html(StringIO((snapshot / "house.html").read_text(encoding="utf-8")))
    house_cells = {}
    for frame in house_tables:
        cols = flat_columns(frame)
        if len(cols) != 7 or not cols[-1].startswith("Candidates") or cols[0] != "Location":
            continue
        frame.columns = cols
        for _, row in frame.iterrows():
            if pd.isna(row["Location"]):
                continue
            state, district = state_from_location(str(row["Location"]))
            code = "00" if district.lower() in {"at-large", "at large"} else f"{int(district):02d}"
            race_id = f"H-2026-{state}-{code}"
            parsed = parse_candidates(row[cols[-1]])
            if race_id in house_cells and house_cells[race_id] != parsed:
                raise ValueError(f"Conflicting duplicate House rows for {race_id}")
            house_cells[race_id] = parsed
    if len(house_cells) != 435:
        raise ValueError(f"Expected 435 Wikipedia House rows, got {len(house_cells)}")
    for race_id, candidates in house_cells.items():
        add_rows(entries, race_id, candidates, f"House summary row {race_id}", excluded)

    senate_tables = pd.read_html(StringIO((snapshot / "senate.html").read_text(encoding="utf-8")))
    senate_cells = {}
    for frame in senate_tables:
        cols = flat_columns(frame)
        if not cols or cols[0] != "State" or cols[-1] != "Candidates" or len(frame) not in {2, 33}:
            continue
        frame.columns = cols
        for _, row in frame.iterrows():
            state, remainder = state_from_location(str(row["State"]))
            if remainder and not re.fullmatch(r"\(Class [123]\)", remainder):
                raise ValueError(f"Unexpected Senate location suffix: {row['State']}")
            ids = by_office_state[("senate", state)]
            if len(ids) != 1:
                raise ValueError(f"Senate state not unique: {state} -> {ids}")
            senate_cells[ids[0]] = parse_candidates(row["Candidates"])
    if len(senate_cells) != 35:
        raise ValueError(f"Expected 35 Wikipedia Senate rows, got {len(senate_cells)}")
    for race_id, candidates in senate_cells.items():
        add_rows(entries, race_id, candidates, f"Senate summary row {race_id}", excluded)

    governor_tables = pd.read_html(StringIO((snapshot / "governor.html").read_text(encoding="utf-8")))
    governor_cells = {}
    for frame in governor_tables:
        cols = flat_columns(frame)
        if cols == ["State", "Governor", "Party", "First elected", "Last race", "Status", "Candidates"] and len(frame) == 36:
            frame.columns = cols
            for _, row in frame.iterrows():
                state, remainder = state_from_location(str(row["State"]))
                if remainder:
                    raise ValueError(f"Unexpected governor location suffix: {row['State']}")
                governor_cells[f"G-2026-{state}"] = parse_candidates(row["Candidates"])
    if len(governor_cells) != 36:
        raise ValueError(f"Expected 36 Wikipedia governor rows, got {len(governor_cells)}")
    for race_id, candidates in governor_cells.items():
        add_rows(entries, race_id, candidates, f"Governor summary row {race_id}", excluded)

    covered = {entry["race_id"] for entry in entries}
    expected = {race["race_id"] for race in races} - excluded
    empty = sorted(race_id for race_id in expected if race_id not in covered)
    if empty:
        raise ValueError(f"Wikipedia rows have no parsed candidates for: {empty}")
    document = {
        "version": "0.1-secondary-snapshot",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": snapshot.as_posix(),
        "source_manifest": manifest,
        "scope_note": "Secondary-source fill for races lacking a reviewed state-source catalog.",
        "excluded_state_reviewed_races": len(excluded),
        "entries": sorted(entries, key=lambda item: item["ballot_entry_id"]),
    }
    output = Path("data/reference/ballot_entries_wikipedia_2026.json")
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output}: {len(entries)} entries across {len(covered)} races")


if __name__ == "__main__":
    main()
