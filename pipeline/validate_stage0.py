"""Validate the Stage 0 race, candidate, provenance, and rule invariants."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    registry = load("data/reference/ballot_registry_2026.json")
    races = registry["races"]
    entries = registry["entries"]
    race_ids = {race["race_id"] for race in races}
    entry_ids = {entry["ballot_entry_id"] for entry in entries}

    assert Counter(race["office"] for race in races) == {
        "house": 435, "senate": 35, "governor": 36,
    }
    assert len(race_ids) == len(races) == 506
    assert len(entry_ids) == len(entries)
    assert all("▌" not in entry["name"] for entry in entries), "Candidate stripe leaked into a name"
    assert all("(Libertarian)" not in entry["name"] and "(Republican)" not in entry["name"]
               and "(Democratic)" not in entry["name"] for entry in entries), \
        "A party label leaked into a candidate name"
    assert all(entry["race_id"] in race_ids for entry in entries)
    assert all(race["candidate_count"] > 0 for race in races)
    assert all(race["counting_rule"] != "state_rule_pending" for race in races)
    assert registry["stage_0_gate_passed"] is True

    rules = Counter(race["counting_rule"] for race in races)
    assert rules == {
        "plurality": 477,
        "majority_then_top_two_runoff": 22,
        "ranked_choice": 6,
        "majority_then_legislative_selection": 1,
    }
    assert sum(entry["ballot_party"] == "IND" for entry in entries) > 0
    assert any(race["candidate_count"] >= 3 for race in races)

    wikipedia = load("data/reference/ballot_entries_wikipedia_2026.json")
    manifest = wikipedia["source_manifest"]
    assert manifest["license"].startswith("CC BY-SA")
    assert set(manifest["files"]) == {"house.html", "senate.html", "governor.html"}
    assert all(source["revision_id"] > 0 for source in manifest["files"].values())
    assert len({entry["race_id"] for entry in wikipedia["entries"]}) == 345

    print(
        f"Stage 0 valid: {len(races)} races, {len(entries)} candidate entries, "
        f"{len(wikipedia['entries'])} secondary-source entries"
    )


if __name__ == "__main__":
    main()
