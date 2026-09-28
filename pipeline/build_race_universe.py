"""Build a source-labeled 2026 race universe, without asserting ballot candidates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests


CENSUS_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2026_Gazetteer/2026_Gaz_120CDs_national.zip"
)
GOVERNOR_HISTORY_URL = (
    "https://raw.githubusercontent.com/fivethirtyeight/election-results/"
    "main/election_results_gubernatorial.csv"
)
SENATE_CLASS_II_URL = "https://www.senate.gov/senators/Class_II.htm"
NGA_URL = "https://www.nga.org/governors/elections/"
OHIO_SPECIAL_URL = "https://www.ohiosos.gov/assets/directive-2025-54-writ-of-special-election-for-united-states-senate-election.pdf"
FLORIDA_SENATE_URL = "https://dos.fl.gov/elections/candidates-committees/offices-up-for-election"
CENSUS_EXCEPTION_URL = "https://www.census.gov/programs-surveys/decennial-census/about/rdo/congressional-districts.html"
LOUISIANA_RULE_URL = "https://www.sos.la.gov/elections-voting/types-of-elections"
ALASKA_RULE_URL = "https://www.elections.alaska.gov/election-information/"
MAINE_RULE_URL = "https://www.maine.gov/sos/elections-voting/upcoming-elections"
GEORGIA_RULE_URL = "https://georgia.gov/vote-runoff-elections"
GEORGIA_DATE_URL = "https://georgia.gov/events/2026-11-23/general-election-runoff-early-voting"
CALIFORNIA_RULE_URL = "https://www.sos.ca.gov/administration/news-releases-and-advisories/2026-news-releases-and-advisories/california-secretary-state-shirley-n-weber-phd-certifies-candidate-list-june-2-2026-primary-election"
WASHINGTON_RULE_URL = "https://www.sos.wa.gov/elections/voters/helpful-information/top-two-primary-faqs-voters"
VERMONT_RULE_URL = "https://sos.vermont.gov/vsara/learn/elections/majority-election"
NCSL_RCV_URL = "https://www.ncsl.org/elections-and-campaigns/ranked-choice-voting"

# Transcribed from the U.S. Senate's Class II list. These are seat states, not nominees.
CLASS_II_STATES = (
    "AL AR CO DE GA IA ID IL KS KY LA MA ME MI MN MS MT NC NE NH NJ NM "
    "OK OR RI SC SD TN TX VA WV WY AK"
).split()
STATE_ABBREVIATIONS = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI "
    "MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX "
    "UT VT VA WA WV WI WY".split()
)


def election_rule(state: str, office: str) -> dict:
    if state == "LA" and office == "house":
        return {
            "stage": "open_primary", "counting_rule": "majority_then_top_two_runoff",
            "contingent_runoff_date": "2026-12-12", "nomination_rule": "open_primary",
            "rule_source_key": "louisiana_house_rule",
        }
    if state == "GA":
        return {
            "stage": "general", "counting_rule": "majority_then_top_two_runoff",
            "contingent_runoff_date": "2026-12-01", "nomination_rule": "party_primary",
            "rule_source_key": "georgia_runoff_rule",
        }
    if state == "AK":
        return {
            "stage": "general", "counting_rule": "ranked_choice",
            "contingent_runoff_date": None, "nomination_rule": "top_four_primary",
            "rule_source_key": "alaska_rcv_rule",
        }
    if state == "ME":
        return {
            "stage": "general", "counting_rule": "plurality" if office == "governor" else "ranked_choice",
            "contingent_runoff_date": None, "nomination_rule": "party_primary",
            "rule_source_key": "maine_2026_rule",
        }
    if state == "CA" and office in {"house", "governor"}:
        return {
            "stage": "general", "counting_rule": "plurality",
            "contingent_runoff_date": None, "nomination_rule": "top_two_primary",
            "rule_source_key": "california_top_two_rule",
        }
    if state == "WA" and office == "house":
        return {
            "stage": "general", "counting_rule": "plurality",
            "contingent_runoff_date": None, "nomination_rule": "top_two_primary",
            "rule_source_key": "washington_top_two_rule",
        }
    if state == "VT" and office == "governor":
        return {
            "stage": "general", "counting_rule": "majority_then_legislative_selection",
            "contingent_runoff_date": None, "nomination_rule": "party_primary",
            "rule_source_key": "vermont_governor_majority_rule",
        }
    return {
        "stage": "general", "counting_rule": "plurality",
        "contingent_runoff_date": None, "nomination_rule": "state_qualification",
        "rule_source_key": "general_plurality_inventory",
    }


def fetch(session: requests.Session, url: str, path: Path) -> dict:
    response = session.get(url, timeout=45)
    response.raise_for_status()
    payload = response.content
    path.write_bytes(payload)
    return {
        "url": url,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "path": str(path).replace("\\", "/"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", type=Path,
        help="Reuse an existing raw source directory without a network request",
    )
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    raw_dir = args.source_dir or Path("data/raw/reference") / now.strftime("%Y%m%dT%H%M%SZ")
    if args.source_dir:
        census_path = raw_dir / "census_2026_cd120.zip"
        governor_path = raw_dir / "governor_results_history.csv"
        if not census_path.is_file() or not governor_path.is_file():
            raise FileNotFoundError(f"Missing raw source in {raw_dir}")
        source_timestamp = datetime.strptime(raw_dir.name, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        ).isoformat()
        census_meta = {
            "url": CENSUS_URL, "sha256": hashlib.sha256(census_path.read_bytes()).hexdigest(),
            "bytes": census_path.stat().st_size, "path": census_path.as_posix(),
            "retrieved_at_utc": source_timestamp,
        }
        governor_meta = {
            "url": GOVERNOR_HISTORY_URL, "sha256": hashlib.sha256(governor_path.read_bytes()).hexdigest(),
            "bytes": governor_path.stat().st_size, "path": governor_path.as_posix(),
            "retrieved_at_utc": source_timestamp,
        }
    else:
        raw_dir.mkdir(parents=True, exist_ok=False)
        session = requests.Session()
        session.headers.update({"User-Agent": "us2026forecast-race-inventory/0.1"})
        census_meta = fetch(session, CENSUS_URL, raw_dir / "census_2026_cd120.zip")
        governor_meta = fetch(
            session, GOVERNOR_HISTORY_URL, raw_dir / "governor_results_history.csv"
        )

    with zipfile.ZipFile(raw_dir / "census_2026_cd120.zip") as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise ValueError(f"Unexpected Census archive members: {names}")
        districts = list(
            csv.DictReader(
                io.TextIOWrapper(archive.open(names[0]), encoding="utf-8"),
                delimiter="|",
            )
        )
    house = []
    for district in districts:
        state = district["USPS"]
        code = district["GEOID"][-2:]
        if state not in STATE_ABBREVIATIONS or not code.isdigit():
            continue  # Census also includes DC/PR delegates and ZZ pseudo-geography.
        house.append(
            {
                "race_id": f"H-2026-{state}-{code}",
                "office": "house",
                "state": state,
                "district_code": code,
                "census_geoid": district["GEOID"],
                "seat_class": None,
                "election_type": "regular",
                "stage": election_rule(state, "house")["stage"],
                "election_date": "2026-11-03",
                **{key: value for key, value in election_rule(state, "house").items() if key != "stage"},
                "universe_status": "geometry_needs_state_review" if state == "MO" else "census_listed",
                "source_keys": ["census_cd120"],
            }
        )
    if len(house) != 435 or len({r["race_id"] for r in house}) != 435:
        raise ValueError(f"Expected 435 distinct voting House districts, got {len(house)}")

    if len(CLASS_II_STATES) != 33 or len(set(CLASS_II_STATES)) != 33:
        raise ValueError("Class II list should contain 33 unique states")
    senate = [
        {
            "race_id": f"S-2026-{state}-II-regular",
            "office": "senate",
            "state": state,
            "district_code": None,
            "seat_class": "II",
            "election_type": "regular",
            "stage": "general",
            "election_date": "2026-11-03",
            **{key: value for key, value in election_rule(state, "senate").items() if key != "stage"},
            "universe_status": "senate_class_listed",
            "source_keys": ["senate_class_ii"],
        }
        for state in CLASS_II_STATES
    ]
    for state, source_key, status in (
        ("OH", "ohio_special", "official_special_notice"),
        ("FL", "florida_senate", "state_office_listed_special_class_to_verify"),
    ):
        senate.append(
            {
                "race_id": f"S-2026-{state}-III-special",
                "office": "senate",
                "state": state,
                "district_code": None,
                "seat_class": "III",
                "election_type": "special",
                "stage": "general",
                "election_date": "2026-11-03",
                **{key: value for key, value in election_rule(state, "senate").items() if key != "stage"},
                "universe_status": status,
                "source_keys": [source_key],
            }
        )

    with (raw_dir / "governor_results_history.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        history = csv.DictReader(file)
        governor_states = sorted(
            {
                row["state_abbrev"]
                for row in history
                if row["cycle"] == "2022"
                and row["stage"] == "general"
                and row["state_abbrev"] in STATE_ABBREVIATIONS
            }
        )
    if len(governor_states) != 36:
        raise ValueError(f"Expected 36 historical 2022 state races, got {len(governor_states)}")
    governor = [
        {
            "race_id": f"G-2026-{state}",
            "office": "governor",
            "state": state,
            "district_code": None,
            "seat_class": None,
            "election_type": "regular",
            "stage": "general",
            "election_date": "2026-11-03",
            **{key: value for key, value in election_rule(state, "governor").items() if key != "stage"},
            "universe_status": "cycle_list_crosschecked",
            "source_keys": ["governor_2022", "nga_2026_total"],
        }
        for state in governor_states
    ]

    races = sorted(house + senate + governor, key=lambda r: r["race_id"])
    ids = [r["race_id"] for r in races]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate race IDs")
    document = {
        "version": "1.0-stage0",
        "generated_at_utc": now.isoformat(),
        "notes": [
            "Universe only; no candidate is asserted to be ballot-qualified.",
            "Governor state list follows the four-year cycle from 2022 and is cross-checked against the 36-state 2026 Wikipedia summary; NGA reports 39 elections when three territories are included.",
            "Census warns its Missouri 120th-district geography may not match the November 2026 election plan; review Missouri before using geometry or baselines.",
            "Louisiana House candidates face a November 3 open primary; if no majority winner, the top two advance to a December 12 general election.",
            "Alaska uses top-four primaries and ranked-choice general elections; Maine uses ranked choice for federal general elections but plurality for governor.",
            "Georgia may have a December 1 general runoff; California and Washington use top-two primary nomination for the listed offices.",
            "Vermont governor requires a popular-vote majority; otherwise the General Assembly selects among the top three.",
            "All remaining listed general elections use the plurality branch. The rule inventory should still be monitored for litigation or statutory changes.",
            "Recheck later special elections and election notices before publication.",
        ],
        "sources": {
            "census_cd120": census_meta,
            "governor_2022": governor_meta,
            "senate_class_ii": {"url": SENATE_CLASS_II_URL, "method": "transcribed"},
            "nga_2026_total": {"url": NGA_URL, "method": "summary cross-check"},
            "ohio_special": {"url": OHIO_SPECIAL_URL, "method": "official notice"},
            "florida_senate": {"url": FLORIDA_SENATE_URL, "method": "official office list"},
            "census_missouri_exception": {"url": CENSUS_EXCEPTION_URL},
            "louisiana_house_rule": {"url": LOUISIANA_RULE_URL, "method": "official election guidance"},
            "alaska_rcv_rule": {"url": ALASKA_RULE_URL, "method": "official election guidance"},
            "maine_2026_rule": {"url": MAINE_RULE_URL, "method": "official 2026 election guidance"},
            "georgia_runoff_rule": {"url": GEORGIA_RULE_URL, "date_url": GEORGIA_DATE_URL, "method": "official election guidance"},
            "california_top_two_rule": {"url": CALIFORNIA_RULE_URL, "method": "official primary guidance"},
            "washington_top_two_rule": {"url": WASHINGTON_RULE_URL, "method": "official primary guidance"},
            "vermont_governor_majority_rule": {"url": VERMONT_RULE_URL, "method": "official constitutional summary"},
            "general_plurality_inventory": {"url": NCSL_RCV_URL, "method": "default after enumerating RCV and general-runoff exceptions"},
        },
        "counts": dict(Counter(r["office"] for r in races)),
        "races": races,
    }
    output = Path("data/reference/races_2026.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Wrote {output}: {document['counts']}, {len(races)} races")
    print(f"Raw sources: {raw_dir}")


if __name__ == "__main__":
    main()
