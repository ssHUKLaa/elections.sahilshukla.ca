"""Compare one NYT snapshot with the source-labeled 2026 race universe."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


SOURCES = ("senate", "house", "governor")
NONCANDIDATE_PARTIES = {"NONE"}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def race_key(office: str, row: dict[str, str]) -> tuple[str, ...]:
    if office == "house":
        return row["state"], row["seat_number"]
    return (row["state"],)


def expected_key(race: dict) -> tuple[str, ...]:
    if race["office"] == "house":
        # NYT calls an at-large seat district 1; Census encodes it as 00.
        code = race["district_code"]
        return race["state"], "1" if code == "00" else str(int(code))
    return (race["state"],)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument(
        "--registry", type=Path, default=Path("data/reference/races_2026.json")
    )
    parser.add_argument("--output", type=Path, default=Path("docs/nyt_data_inventory.md"))
    args = parser.parse_args()
    snapshot = args.snapshot or max(
        path
        for path in Path("data/raw/nyt").iterdir()
        if path.is_dir() and (path / "manifest.json").exists() and not path.name.endswith(".incomplete")
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    lines = [
        "# NYT data inventory and initial race coverage",
        "",
        f"Snapshot: `{snapshot.as_posix()}`; retrieved `{manifest['retrieved_at_utc']}` UTC.",
        f"Race registry: `{args.registry.as_posix()}` version `{registry['version']}`.",
        "These are **poll mentions**, not verified ballot entries. Poll questions can name withdrawn, primary, hypothetical, or generic candidates.",
        "",
        "## Files and schema",
        "",
        "| Feed | Rows | Columns | SHA-256 |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, meta in manifest["files"].items():
        lines.append(
            f"| {name} | {meta['rows']:,} | {len(meta['columns'])} | `{meta['sha256']}` |"
        )
    lines += [
        "",
        "The three race feeds and `other.csv` share a 50-column row-level schema. The approval poll file has 38 columns; the approval-average file has only `topic`, `date`, `answer`, and `pct`. The race files are **one row per answer option**, not one row per survey; group by `poll_id` and `question_id` before modeling.",
        "",
        "Race-feed identifiers and dimensions: `poll_id`, `question_id`, `race_id`, `candidate_id`, `state`, `seat_name`, `seat_number`, `election_date`, `stage`, `party`, `answer`, `candidate_name`, `pct`, plus field dates, sample, population, pollster, and source metadata. The meaning of `created_at` has not yet been established as publication time; do not use it for historical as-of cutoffs without verification.",
        "",
        "## November race-stage poll coverage",
        "",
        "Filter: the registry's November election date and stage, with `state != US`. NYT's `primary` label is accepted for Louisiana's November House open primary; elsewhere the stage is `general`. Race-key matching is by state and seat number, with Census `00` at-large districts mapped to NYT district `1`. This matches poll **races**, not candidates.",
        "",
        "| Office | Registry races | Races with matching NYT polls | Races without matching NYT polls | Poll questions |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    all_rows: dict[str, list[dict[str, str]]] = {}
    all_general: dict[str, list[dict[str, str]]] = {}
    missing_by_office: dict[str, list[str]] = {}
    for office in SOURCES:
        rows = read_rows(snapshot / f"{office}.csv")
        all_rows[office] = rows
        office_races = [race for race in registry["races"] if race["office"] == office]
        expected = {expected_key(race): race for race in office_races}
        if len(expected) != len(office_races):
            raise ValueError(
                f"{office} has multiple races with one state/seat key; "
                "add an official seat-class mapping before comparing NYT coverage"
            )
        november = [
            row
            for row in rows
            if row["election_date"] == "2026-11-03" and row["state"] != "US"
        ]
        unknown = sorted({race_key(office, row) for row in november} - set(expected))
        if unknown:
            raise ValueError(f"{office} has NYT races missing from registry: {unknown}")
        general = [
            row for row in november
            if row["election_date"] == expected[race_key(office, row)]["election_date"]
            and (
                row["stage"] == expected[race_key(office, row)]["stage"]
                or (
                    expected[race_key(office, row)]["stage"] == "open_primary"
                    and row["stage"] == "primary"
                )
            )
        ]
        all_general[office] = general
        observed = {race_key(office, row) for row in general}
        missing = sorted(set(expected) - observed)
        missing_by_office[office] = [expected[key]["race_id"] for key in missing]
        questions = len({row["question_id"] for row in general})
        lines.append(
            f"| {office.title()} | {len(expected)} | {len(observed)} | {len(missing)} | {questions} |"
        )

    house_rows = all_rows["house"]
    national_generic = [
        row
        for row in house_rows
        if row["state"] == "US" and row["stage"] == "general"
    ]
    lines += [
        "",
        f"The House CSV also contains **{len(national_generic):,} national `US` general-election answer rows** (generic ballot), which must be routed to a national-signal pipeline rather than a House district. The three office files also include primary and special-stage observations; a `stage` filter is mandatory.",
        "Louisiana's six House districts have a November 3 open primary and a December 12 general election if no candidate wins a majority. The historical May 16 Louisiana primary question in this snapshot is outside the November coverage count. A chamber-control simulation must continue through any December runoff.",
        "",
        "### Unpolled race IDs in this snapshot",
        "",
    ]
    for office in SOURCES:
        missing = missing_by_office[office]
        if office == "house":
            lines.append(
                f"- House: {len(missing)} missing districts (the full list is generated by the script; a published model must still forecast all 435)."
            )
        else:
            lines.append(f"- {office.title()}: {', '.join(missing) or 'none'}.")

    senate_questions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in all_general["senate"]:
        senate_questions[row["question_id"]].append(row)
    signatures: dict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
    for rows in senate_questions.values():
        parties = tuple(sorted({row["party"] for row in rows if row["party"] not in NONCANDIDATE_PARTIES}))
        signatures[rows[0]["state"]][parties] += 1
    ri = sorted(
        state for state, patterns in signatures.items()
        if any("REP" in pattern and "IND" in pattern and "DEM" not in pattern for pattern in patterns)
    )
    rid = sorted(
        state for state, patterns in signatures.items()
        if any("REP" in pattern and "IND" in pattern and "DEM" in pattern for pattern in patterns)
    )
    lines += [
        "",
        "## Candidate and option mapping warnings",
        "",
        f"Senate polls contain at least one R–I question without a D option in: {', '.join(ri) or 'none'}. They contain at least one R–I–D question in: {', '.join(rid) or 'none'}. These are **question configurations**, not claims about the final ballot. Some polls within one race ask different candidate configurations; match each question to a dated verified ballot scenario before using it.",
        "",
        "Responses with party `NONE` include answers such as `Don't know`, `Someone else`, and `Would not vote`. They must remain response categories, not candidate records. `IND` is a candidate party label where a named person is supplied; an answer such as `Independent` without an identity needs manual review. `candidate_id` in NYT is a source identifier and cannot replace a project-wide ballot entry ID.",
        "",
        "The NYT snapshot alone cannot establish ballot qualification, withdrawals, endorsements, or Senate caucus plans. The separate ballot registry covers all races and labels state-reviewed versus secondary-source entries. The [Census warns](https://www.census.gov/programs-surveys/decennial-census/about/rdo/congressional-districts.html) that its Missouri 120th-district geography may not match the November 2026 election plan; verify Missouri with state authorities before mapping or building district baselines.",
        "",
        "## Immediate parser rules",
        "",
        "1. Read all answer rows for a (`poll_id`, `question_id`) together. Preserve the original options and percentages; do not pivot to fixed D/R columns.",
        "2. Separate national generic ballot (`house.csv`, `state=US`), office races, approval, primary, special, and general stages.",
        "3. Join a question to the project race key and a dated candidate-set scenario. Quarantine unknown candidates or ambiguous response options.",
        "4. Confirm what `created_at` means and obtain a trustworthy publication timestamp before using historical as-of cutoffs.",
        "5. Match independent winners to caucus assumptions only in the Senate-control calculation, never in raw race data.",
        "6. The project owner confirmed direct NYT permission on 21 September 2026, so these rows may enter the model pipeline. Keep raw snapshots outside Git, retain attribution and provenance, and verify the permission's raw-redistribution scope before publishing downloadable rows.",
        "",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
