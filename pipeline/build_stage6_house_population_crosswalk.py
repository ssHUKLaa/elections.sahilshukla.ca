"""Estimate district overlap using 2020 Census block-group population centers."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely import points
from shapely.geometry import shape
from shapely.strtree import STRtree

from build_stage6_house_crosswalk import read_districts

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/census_districts"
CENTERS = SOURCE / "CenPop2020_Mean_BG.txt"
BOUNDARIES = ROOT / "data/reference/stage6_house_crosswalk_sources.json"
NC_2020_SOURCE = ROOT / "data/reference/stage6_nc_2020_map_source.json"
OUTPUT = ROOT / "data/reference/stage6_house_population_crosswalk.json"
CENTERS_URL = "https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG.txt"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_centers() -> dict[str, tuple[np.ndarray, np.ndarray]]:
    by_state = defaultdict(lambda: ([], []))
    with CENTERS.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            population = int(row["POPULATION"])
            if population <= 0:
                continue
            state = row["STATEFP"]
            coordinates, populations = by_state[state]
            coordinates.append((float(row["LONGITUDE"]), float(row["LATITUDE"])))
            populations.append(population)
    return {state: (np.asarray(xy), np.asarray(pop, dtype=np.int64))
            for state, (xy, pop) in by_state.items()}


def districts_at_centers(geographies, centers):
    by_state = defaultdict(list)
    for (state, district), geometry in geographies.items():
        if district not in {"98", "ZZ"}:
            by_state[state].append((district, geometry))
    result = {}
    fallback = {}
    for state, (xy, population) in centers.items():
        districts = sorted(by_state.get(state, []))
        if not districts:
            continue
        geometries = [geometry for _, geometry in districts]
        tree = STRtree(geometries)
        values = np.full(len(xy), -1, dtype=np.int16)
        locations = points(xy[:, 0], xy[:, 1])
        matches = tree.query(locations, predicate="intersects")
        for center_index, geometry_index in zip(*matches):
            if values[center_index] == -1 or geometry_index < values[center_index]:
                values[center_index] = geometry_index
        missing = np.flatnonzero(values < 0)
        for index in missing:
            values[index] = tree.nearest(locations[index])
        result[state] = np.asarray([districts[index][0] for index in values])
        fallback[state] = {"block_groups": int(len(missing)),
                           "population": int(population[missing].sum())}
    return result, fallback


def build_transition(prior, target, centers, prior_cycle):
    rows = []
    for state, (_, population) in centers.items():
        if state not in prior or state not in target:
            continue
        by_target = defaultdict(lambda: defaultdict(int))
        for old, new, people in zip(prior[state], target[state], population):
            by_target[new][old] += int(people)
        for district, overlaps in sorted(by_target.items()):
            total = sum(overlaps.values())
            ranked = sorted(overlaps.items(), key=lambda item: (-item[1], item[0]))
            rows.append({
                "state_fips": state, "target_district": district,
                "population_2020": total,
                "dominant_prior_district": ranked[0][0],
                "dominant_population_fraction": round(ranked[0][1] / total, 6),
                "overlaps": [{"prior_district": old, "population": count,
                              "population_fraction": round(count / total, 6)}
                             for old, count in ranked],
            })
    return rows


def main() -> None:
    manifest = json.loads(BOUNDARIES.read_text(encoding="utf-8"))
    for entry in manifest.values():
        path = SOURCE / entry["filename"]
        if digest(path) != entry["sha256"]:
            raise ValueError(f"Census boundary hash mismatch: {path}")
    centers = load_centers()
    geographies = {int(cycle): read_districts(SOURCE / entry["filename"])
                   for cycle, entry in manifest.items()}
    nc_source = json.loads(NC_2020_SOURCE.read_text(encoding="utf-8"))
    nc_path = SOURCE / nc_source["filename"]
    if digest(nc_path) != nc_source["sha256"]:
        raise ValueError("North Carolina 2020 official map hash mismatch")
    nc_map = json.loads(nc_path.read_text(encoding="utf-8"))
    if len(nc_map["features"]) != nc_source["district_count"]:
        raise ValueError("North Carolina 2020 district count changed")
    for feature in nc_map["features"]:
        district = f"{int(feature['properties']['District']):02d}"
        geographies[2020]["37", district] = shape(feature["geometry"])
    # Remove the 116th boundaries for North Carolina; they were not the map
    # used in its 2020 congressional election.
    for key in list(geographies[2020]):
        if key[0] == "37" and key[1] not in {f"{i:02d}" for i in range(1, 14)}:
            del geographies[2020][key]
    assignments = {}
    fallbacks = {}
    for cycle, geography in geographies.items():
        assignments[cycle], fallbacks[cycle] = districts_at_centers(geography, centers)
    transitions = {
        "2020_to_2022": build_transition(assignments[2020], assignments[2022], centers, 2020),
        "2022_to_2024": build_transition(assignments[2022], assignments[2024], centers, 2022),
    }
    report = {
        "method": "Assign each 2020 Census block-group mean population center to a district polygon; sum its 2020 population by old and new district.",
        "limitations": [
            "Each block group's population is assigned to one point; district lines can split block groups.",
            "The district boundary files are generalized 1:500,000 cartographic polygons; point assignment near boundaries can be inaccurate.",
            "Unmatched population centers are assigned to the nearest district in the same state and quantified below.",
            "North Carolina 2020 uses the state legislature's official 2019 enacted map rather than the national 116th Congress file.",
            "Population overlap is a geographic prior only; it is not a retabulation of election votes or turnout.",
        ],
        "sources": {
            "centers": {"url": CENTERS_URL, "sha256": digest(CENTERS), "bytes": CENTERS.stat().st_size},
            "boundaries": {cycle: {"url": item["url"], "sha256": item["sha256"]}
                           for cycle, item in manifest.items()},
            "north_carolina_2020": {"url": nc_source["query_url"],
                                    "sha256": nc_source["sha256"]},
        },
        "fallback_assignment": fallbacks,
        "transitions": transitions,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print({key: len(rows) for key, rows in transitions.items()})
    print({cycle: sum(item["population"] for item in states.values())
           for cycle, states in fallbacks.items()})
    print(OUTPUT)


if __name__ == "__main__":
    main()
