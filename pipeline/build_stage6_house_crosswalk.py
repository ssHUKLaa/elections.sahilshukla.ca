"""Build exploratory district-area overlaps from Census cartographic boundaries.

The overlap identifies candidate prior districts; it is not a population or
vote-weighted retabulation. North Carolina 2020 is excluded because the Census
116th Congress file does not represent its 117th Congress election map.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import shapefile
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/census_districts"
OUTPUT = ROOT / "data/reference/stage6_house_area_crosswalk.json"
MANIFEST = ROOT / "data/reference/stage6_house_crosswalk_sources.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_districts(path: Path):
    reader = shapefile.Reader(str(path))
    names = [field[0] for field in reader.fields[1:]]
    output = {}
    for record in reader.iterShapeRecords():
        values = dict(zip(names, record.record))
        state = values["STATEFP"]
        district = values["GEOID"][2:]
        geometry = shape(record.shape.__geo_interface__)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        if geometry.is_empty:
            raise ValueError(f"Empty district geometry {state}-{district} in {path}")
        output[(state, district)] = geometry
    return output


def crosswalk(prior, target, *, excluded_states=frozenset()):
    result = []
    by_state = {}
    for (state, district), geometry in prior.items():
        by_state.setdefault(state, []).append((district, geometry))
    for (state, district), geometry in sorted(target.items()):
        if state in excluded_states:
            continue
        overlaps = []
        for previous_district, previous_geometry in by_state.get(state, []):
            if not geometry.intersects(previous_geometry):
                continue
            area = geometry.intersection(previous_geometry).area
            if area > 0:
                overlaps.append((previous_district, area))
        total = sum(area for _, area in overlaps)
        if not total:
            continue
        ranked = sorted(overlaps, key=lambda value: (-value[1], value[0]))
        result.append({
            "state_fips": state, "target_district": district,
            "dominant_prior_district": ranked[0][0],
            "dominant_area_fraction": round(ranked[0][1] / total, 6),
            "overlaps": [{"prior_district": old, "area_fraction": round(area / total, 6)}
                         for old, area in ranked],
        })
    return result


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest.values():
        path = SOURCE / entry["filename"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ValueError(f"Missing or mismatched official Census boundary source: {path}")
    geographies = {int(cycle): read_districts(SOURCE / entry["filename"])
                   for cycle, entry in manifest.items()}
    transitions = {
        "2020_to_2022": crosswalk(geographies[2020], geographies[2022], excluded_states={"37"}),
        "2022_to_2024": crosswalk(geographies[2022], geographies[2024]),
    }
    report = {
        "method": "fraction of target cartographic polygon area overlapping each prior polygon",
        "limitations": [
            "Area fractions are not population or vote fractions; do not use to retabulate vote shares.",
            "The 1:500,000 cartographic files generalize boundaries and may distort small overlaps.",
            "North Carolina 2020 is excluded: its election used 117th Congress boundaries, absent from the national 116th Congress source.",
        ],
        "sources": {cycle: {"url": entry["url"], "sha256": entry["sha256"]}
                    for cycle, entry in manifest.items()},
        "transitions": transitions,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print({name: len(rows) for name, rows in transitions.items()}, flush=True)
    print(OUTPUT, flush=True)


if __name__ == "__main__":
    main()
