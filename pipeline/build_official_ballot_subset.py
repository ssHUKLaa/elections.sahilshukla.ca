"""Extract a checked subset of 2026 candidates from official state documents.

The output deliberately covers only supported source formats/states. A listed
candidate is never silently promoted to certified status. Run after
``snapshot_state_ballots.py``; install pypdf for the California PDF.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


PARTIES = {
    "Democratic": "DEM", "Republican": "REP", "Green": "GRE",
    "Libertarian": "LIB", "Unaffiliated": "IND", "Independent": "IND",
    "Working Class Party": "WCP", "No Party Preference": "NPP",
    "Other Candidates": "OTH",
    "D": "DEM", "R": "REP", "GRE": "GRE", "DEM": "DEM",
    "REP": "REP", "LIB": "LIB", "IND": "IND", "I": "IND",
    "DEMOCRATIC": "DEM", "REPUBLICAN": "REP", "INDEPENDENT": "IND",
    "WORKING CLASS PARTY": "WCP", "AMERICAN CENTER PARTY": "ACP",
}


def slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "-", ascii_value.upper()).strip("-")


def xlsx_rows(path: Path) -> list[dict[str, str]]:
    """Read values from Maine's simple single-sheet XLSX without modifying it."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        strings_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = [
            "".join(element.text or "" for element in item.iter(f"{{{ns['m']}}}t"))
            for item in strings_xml
        ]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    matrix = []
    for row in sheet.findall(".//m:sheetData/m:row", ns):
        values = {}
        for cell in row.findall("m:c", ns):
            column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
            value = cell.find("m:v", ns)
            raw = value.text if value is not None else ""
            values[column] = strings[int(raw)] if cell.attrib.get("t") == "s" else raw
        matrix.append(values)
    columns = matrix[0]
    return [
        {label: row.get(column, "") for column, label in columns.items()}
        for row in matrix[1:]
    ]


def add_entry(entries: list[dict], race_id: str, name: str, party: str,
              source_key: str, status: str, source_label: str, note: str = "") -> None:
    if not name or not party:
        raise ValueError(f"Missing candidate name or party for {race_id}")
    code = PARTIES.get(party)
    if code is None:
        raise ValueError(f"Unreviewed party label {party!r} for {race_id}")
    entries.append({
        "ballot_entry_id": f"{race_id}:{slug(name)}",
        "race_id": race_id,
        "candidate_id": f"PERSON-{race_id.split('-')[2]}-{slug(name)}",
        "name": name,
        "ballot_party": code,
        "source_party_label": party,
        "status": status,
        "source_key": source_key,
        "source_record": source_label,
        "write_in_only": False,
        "senate_caucus": None,
        "note": note,
    })


def pdf_reader(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError("Install pypdf to read the official certified PDFs") from error
    return PdfReader(path)


def california(path: Path, entries: list[dict]) -> None:
    reader = pdf_reader(path)
    party_names = ("Democratic", "Republican", "No Party Preference", "Green", "Libertarian")
    pattern = re.compile(r"^(.+?) (" + "|".join(party_names) + r")\s*$")
    current = None
    for page_number, page in enumerate(reader.pages, 1):
        for raw_line in (page.extract_text() or "").splitlines():
            line = raw_line.strip()
            if line == "Governor":
                current = "G-2026-CA"
                continue
            match = re.fullmatch(r"United States Representative District (\d+)", line)
            if match:
                current = f"H-2026-CA-{int(match.group(1)):02d}"
                continue
            if line in {"Lieutenant Governor", "Secretary of State", "Board of Equalization Member District 1"} or line.startswith(("State Senate District ", "State Assembly District ")):
                current = None
            if current is None:
                continue
            candidate = pattern.match(line)
            if candidate:
                name = candidate.group(1).rstrip("*")
                add_entry(entries, current, name, candidate.group(2), "ca_certified",
                          "certified_general", f"PDF page {page_number}")
    counts = Counter(e["race_id"] for e in entries if e["source_key"] == "ca_certified")
    expected = {f"H-2026-CA-{number:02d}" for number in range(1, 53)} | {"G-2026-CA"}
    if set(counts) != expected or any(count != 2 for count in counts.values()):
        raise ValueError(f"California PDF extraction incomplete: {counts}")


def maryland(path: Path, entries: list[dict]) -> None:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 2):
            if row["Candidate Status"] != "Active":
                continue
            office = row["Office Name"]
            if office == "Governor / Lt. Governor":
                race_id = "G-2026-MD"
            elif office == "Representative in Congress":
                match = re.fullmatch(r"Congressional District (\d+)", row["Contest Run By District Name and Number"])
                if not match:
                    raise ValueError(f"Maryland district label at CSV row {row_number}")
                race_id = f"H-2026-MD-{int(match.group(1)):02d}"
            else:
                continue
            name = (row["Candidate First Name and Middle Name"] + " " + row["Candidate Ballot Last Name and Suffix"]).strip()
            add_entry(entries, race_id, name, row["Office Political Party"],
                      "md_general", "active_general_listed", f"CSV row {row_number}")


def north_carolina(path: Path, entries: list[dict]) -> None:
    unique = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream), 2):
            if row["election_dt"] != "11/03/2026" or row["party_contest"]:
                continue
            contest = row["contest_name"]
            if contest == "US SENATE":
                race_id = "S-2026-NC-II-regular"
            else:
                match = re.fullmatch(r"US HOUSE OF REPRESENTATIVES DISTRICT (\d+)", contest)
                if not match:
                    continue
                race_id = f"H-2026-NC-{int(match.group(1)):02d}"
            key = race_id, row["name_on_ballot"], row["party_candidate"]
            unique.setdefault(key, (row_number, row))
    for (race_id, name, party), (row_number, _) in unique.items():
        add_entry(entries, race_id, name, party, "nc_listing",
                  "listed_general_unfinalized", f"CSV first row {row_number}",
                  "State warns November list can change, including Green Party nominations.")
    covered = {entry["race_id"] for entry in entries if entry["source_key"] == "nc_listing"}
    expected = {f"H-2026-NC-{number:02d}" for number in range(1, 15)} | {"S-2026-NC-II-regular"}
    if covered != expected:
        raise ValueError(f"North Carolina missing contests: {sorted(expected - covered)}")


def maine(path: Path, entries: list[dict]) -> None:
    for row_number, row in enumerate(xlsx_rows(path), 2):
        office = row["Office"]
        if office == "US":
            race_id = "S-2026-ME-II-regular"
        elif office == "CG":
            race_id = f"H-2026-ME-{int(row['Dist']):02d}"
        elif office == "GOV":
            race_id = "G-2026-ME"
        else:
            continue
        name = " ".join(part for part in (row["First Name"], row["Middle Name"], row["Last Name"], row["Suffix"]) if part)
        add_entry(entries, race_id, name, row["Party"], "me_general",
                  "general_listed", f"XLSX row {row_number}")
    expected = {"S-2026-ME-II-regular", "H-2026-ME-01", "H-2026-ME-02", "G-2026-ME"}
    actual = {entry["race_id"] for entry in entries if entry["source_key"] == "me_general"}
    if actual != expected:
        raise ValueError(f"Maine missing contests: {sorted(expected - actual)}")


def texas(path: Path, entries: list[dict]) -> None:
    reader = pdf_reader(path)
    candidate_pattern = re.compile(r"^(.+?) (REP|DEM|LIB|GRE|IND)\s*$")
    unique = {}
    current = None
    block = []
    first_page = None

    def finish_block() -> None:
        nonlocal block
        if current is None or not block:
            block = []
            return
        inline = [candidate_pattern.match(line) for line in block]
        if all(inline):
            pairs = [(match.group(1), match.group(2)) for match in inline]
        else:
            parties = [line for line in block if line in {"REP", "DEM", "LIB", "GRE", "IND"}]
            names = [line for line in block if line not in {"REP", "DEM", "LIB", "GRE", "IND"}]
            if len(names) != len(parties) or any(candidate_pattern.match(line) for line in names):
                raise ValueError(f"Texas PDF ambiguous {current} page {first_page}: {block}")
            pairs = list(zip(names, parties))
        for name, party in pairs:
            unique.setdefault((current, name, party), first_page)
        block = []

    for page_number, page in enumerate(reader.pages, 1):
        if page_number == 1:
            continue
        for raw_line in (page.extract_text() or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("Texas Secretary of State", "Page ", "Ballot Certification Report", "2026 NOVEMBER", "November 03")):
                continue
            if line.startswith("County "):
                finish_block()
                current = None
                continue
            if line == "U. S. SENATOR":
                finish_block()
                current = "S-2026-TX-II-regular"
                first_page = page_number
                continue
            if line == "GOVERNOR":
                finish_block()
                current = "G-2026-TX"
                first_page = page_number
                continue
            match = re.fullmatch(r"U\. S\. REPRESENTATIVE DISTRICT (\d+)", line)
            if match:
                finish_block()
                current = f"H-2026-TX-{int(match.group(1)):02d}"
                first_page = page_number
                continue
            if line.startswith(("U. S. ", "LIEUTENANT GOVERNOR", "ATTORNEY GENERAL", "COMPTROLLER", "COMMISSIONER", "RAILROAD", "STATE ", "DISTRICT ", "JUDGE", "JUSTICE", "COUNTY ", "SHERIFF", "TAX ", "CONSTABLE", "MEMBER ")):
                finish_block()
                current = None
                continue
            if current is not None:
                block.append(line)
    finish_block()
    for (race_id, name, party), page_number in unique.items():
        add_entry(entries, race_id, name, party, "tx_certified",
                  "certified_general", f"PDF page {page_number}")
    covered = {entry["race_id"] for entry in entries if entry["source_key"] == "tx_certified"}
    expected = {f"H-2026-TX-{number:02d}" for number in range(1, 39)} | {
        "S-2026-TX-II-regular", "G-2026-TX"
    }
    if covered != expected:
        raise ValueError(f"Texas PDF missing contests: {sorted(expected - covered)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    snapshot = args.snapshot or max(
        path for path in Path("data/raw/state_ballots").iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    registry = json.loads(Path("data/reference/races_2026.json").read_text(encoding="utf-8"))
    entries: list[dict] = []
    california(snapshot / "CA_general_certified.pdf", entries)
    maryland(snapshot / "MD_general_statewide.csv", entries)
    north_carolina(snapshot / "NC_candidate_listing.csv", entries)
    maine(snapshot / "ME_general_candidates.xlsx", entries)
    texas(snapshot / "TX_general_certified.pdf", entries)
    by_id = {entry["ballot_entry_id"]: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ValueError("Duplicate ballot entry ID")
    race_ids = {race["race_id"] for race in registry["races"]}
    if {entry["race_id"] for entry in entries} - race_ids:
        raise ValueError("Official candidate maps to unknown race")
    counts = Counter(entry["race_id"].split("-")[0] for entry in entries)
    document = {
        "version": "0.1-official-subset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": snapshot.as_posix(),
        "sources": manifest["files"],
        "scope": "Official state-list extracts for CA, MD, NC, ME, TX; NC still warns list is not final. Does not certify absent candidates or cover other states.",
        "counts_by_office": dict(counts),
        "entries": sorted(entries, key=lambda entry: entry["ballot_entry_id"]),
    }
    output = Path("data/reference/ballot_entries_official_subset_2026.json")
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output}: {len(entries)} entries across {len({e['race_id'] for e in entries})} races")


if __name__ == "__main__":
    main()
