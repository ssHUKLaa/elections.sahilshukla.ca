"""Build compact SVG paths for the 2026 House map from official Census districts.

The 120th Congress TIGERweb layer supplies the 2026 boundaries. Missouri uses
the pinned 119th Congress cartographic file because the model's reviewed 2026
race map retains that plan. This is a build-time script; Flask reads only JSON.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import shape

from build_us_state_map import fit, svg_path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/census_districts/cd120_tigerweb_2026.geojson"
MISSOURI_SOURCE = ROOT / "data/raw/census_districts/cb_2024_us_cd119_500k.zip"
STATE_SOURCE = ROOT / "data/raw/census/cb_2024_us_state_5m.zip"
OUTPUT = ROOT / "static/data/us_house_2026_paths.json"
URL = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Legislative/MapServer/0/query"
SOURCE_SHA256 = "05636800b5146d54916611d1a09a8d6c0b390e412315ce60d892bf17388beb6a"
MISSOURI_SHA256 = "2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a"
STATE_SHA256 = "c9db0e395c11a1f94a8017fde4f4c7cbee1dca6eb37ba8f1ccaab927df70885f"
EXCLUDED_STATES = {"AS", "DC", "GU", "MP", "PR", "VI"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download() -> None:
    features = []
    offset = 0
    while True:
        response = requests.get(URL, params={
            "where": "1=1", "outFields": "GEOID,STATE,CD120",
            "returnGeometry": "true", "outSR": "4326",
            "maxAllowableOffset": "0.005", "geometryPrecision": "4",
            "resultOffset": offset, "resultRecordCount": 100,
            "orderByFields": "OBJECTID", "f": "geojson",
        }, timeout=90)
        response.raise_for_status()
        batch = response.json().get("features", [])
        features.extend(batch)
        print(f"Fetched {len(features)} Census district geometries", flush=True)
        if len(batch) < 100:
            break
        offset += len(batch)
    if len(features) != 444:
        raise ValueError(f"Expected 444 Census layer features, found {len(features)}")
    if len({item["properties"]["GEOID"] for item in features}) != len(features):
        raise ValueError("Duplicate Census district GEOID")
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    SOURCE.write_text(json.dumps({"type": "FeatureCollection", "features": sorted(
        features, key=lambda item: item["properties"]["GEOID"]
    )}, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> None:
    if not SOURCE.is_file():
        download()
    actual_sha = digest(SOURCE)
    if SOURCE_SHA256 is not None and actual_sha != SOURCE_SHA256:
        raise ValueError(f"Unexpected 120th Congress geometry hash: {actual_sha}")
    if digest(MISSOURI_SOURCE) != MISSOURI_SHA256:
        raise ValueError("Missouri cartographic source hash mismatch")
    if digest(STATE_SOURCE) != STATE_SHA256:
        raise ValueError("State cartographic source hash mismatch")

    state_frame = gpd.read_file(f"zip://{STATE_SOURCE}")
    state_fips = dict(zip(state_frame["STATEFP"], state_frame["STUSPS"]))
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))["features"]
    records = []
    for feature in raw:
        properties = feature["properties"]
        state = state_fips.get(properties["STATE"])
        district = properties["CD120"]
        if state in EXCLUDED_STATES or district == "ZZ":
            continue
        records.append({"state": state, "district": district,
                        "geometry": shape(feature["geometry"])})
    if len(records) != 435:
        raise ValueError(f"Expected 435 voting districts, found {len(records)}")

    # The model's Missouri review retains the 2024 numbered district plan.
    missouri = gpd.read_file(f"zip://{MISSOURI_SOURCE}")
    missouri = missouri[missouri["STATEFP"] == "29"]
    if len(missouri) != 8:
        raise ValueError(f"Expected eight Missouri districts, found {len(missouri)}")
    records = [item for item in records if item["state"] != "MO"]
    records.extend({"state": "MO", "district": row["CD119FP"],
                    "geometry": row.geometry}
                   for _, row in missouri.to_crs(4326).iterrows())
    districts = gpd.GeoDataFrame(records, crs=4326)
    districts["id"] = districts["state"] + "-" + districts["district"]
    if len(districts) != 435 or districts["id"].nunique() != 435:
        raise ValueError("House map must cover 435 unique district IDs")

    layouts = (
        ("CONUS", 5070, (110, 15, 820, 510), 1500),
        ("AK", 3338, (30, 447, 225, 143), 5000),
        ("HI", 26904, (263, 529, 115, 63), 1000),
    )
    output = []
    for region, crs, rectangle, tolerance in layouts:
        if region == "CONUS":
            subset = districts[~districts["state"].isin({"AK", "HI"})].to_crs(crs)
            state_subset = state_frame[~state_frame["STUSPS"].isin(EXCLUDED_STATES | {"AK", "HI"})].to_crs(crs)
        else:
            subset = districts[districts["state"] == region].to_crs(crs)
            state_subset = state_frame[state_frame["STUSPS"] == region].to_crs(crs)
        project = fit(state_subset.total_bounds, rectangle)
        for _, row in subset.iterrows():
            geometry = row.geometry.simplify(tolerance, preserve_topology=True)
            output.append({"id": row["id"], "state": row["state"],
                           "district": row["district"], "path": svg_path(geometry, project)})
    if len(output) != 435 or any(not item["path"] for item in output):
        raise ValueError("Missing district SVG paths")
    report = {"source_url": URL, "source_sha256": actual_sha,
              "missouri_source_sha256": MISSOURI_SHA256,
              "missouri_note": "Uses the reviewed operative plan matching the model, rather than the Census 120th layer.",
              "view_box": "0 0 1000 610", "districts": sorted(output, key=lambda item: item["id"])}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(output)} districts to {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
    print(f"Pinned TIGERweb SHA-256: {actual_sha}")


if __name__ == "__main__":
    main()
