"""Generate compact SVG state paths from the pinned Census 2024 boundary file.

Build-time dependencies: geopandas and shapely. The website only reads the JSON.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import MultiPolygon, Polygon


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/census/cb_2024_us_state_5m.zip"
OUTPUT = ROOT / "static/data/us_states_2024_paths.json"
URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_5m.zip"
SOURCE_SHA256 = "c9db0e395c11a1f94a8017fde4f4c7cbee1dca6eb37ba8f1ccaab927df70885f"
TERRITORIES = {"AS", "GU", "MP", "PR", "VI"}
SMALL_LABELS = {"CT", "DC", "DE", "MA", "MD", "NH", "NJ", "RI", "VT"}


def fit(bounds, rectangle):
    xmin, ymin, xmax, ymax = bounds
    left, top, width, height = rectangle
    scale = min(width / (xmax - xmin), height / (ymax - ymin))
    xoffset = left + (width - (xmax - xmin) * scale) / 2
    yoffset = top + (height - (ymax - ymin) * scale) / 2

    def project(x, y):
        return xoffset + (x - xmin) * scale, yoffset + (ymax - y) * scale

    return project


def svg_path(geometry, project):
    polygons = geometry.geoms if isinstance(geometry, MultiPolygon) else (geometry,)
    parts = []
    for polygon in polygons:
        if not isinstance(polygon, Polygon):
            continue
        for ring in (polygon.exterior, *polygon.interiors):
            points = [project(x, y) for x, y in ring.coords]
            if len(points) < 4:
                continue
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in points) + "Z")
    return "".join(parts)


def main():
    if not SOURCE.exists():
        response = requests.get(URL, timeout=60)
        response.raise_for_status()
        SOURCE.parent.mkdir(parents=True, exist_ok=True)
        SOURCE.write_bytes(response.content)
    actual_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if actual_sha != SOURCE_SHA256:
        raise ValueError(f"Unexpected Census boundary hash: {actual_sha}")
    frame = gpd.read_file(f"zip://{SOURCE}")
    frame = frame[~frame["STUSPS"].isin(TERRITORIES)]
    if len(frame) != 51:
        raise ValueError(f"Expected 50 states and DC, found {len(frame)}")
    conus = frame[~frame["STUSPS"].isin({"AK", "HI"})].to_crs(5070)
    alaska = frame[frame["STUSPS"] == "AK"].to_crs(3338)
    hawaii = frame[frame["STUSPS"] == "HI"].to_crs(26904)
    layouts = (
        (conus, fit(conus.total_bounds, (110, 15, 820, 510)), 3000),
        (alaska, fit(alaska.total_bounds, (30, 447, 225, 143)), 8000),
        (hawaii, fit(hawaii.total_bounds, (263, 529, 115, 63)), 2000),
    )
    states = []
    for subset, project, tolerance in layouts:
        for _, row in subset.iterrows():
            geometry = row.geometry.simplify(tolerance, preserve_topology=True)
            point = geometry.representative_point()
            label_x, label_y = project(point.x, point.y)
            xmin, ymin, xmax, ymax = geometry.bounds
            projected_width = project(xmax, ymin)[0] - project(xmin, ymin)[0]
            projected_height = project(xmin, ymin)[1] - project(xmin, ymax)[1]
            states.append({
                "abbr": row["STUSPS"],
                "name": row["NAME"],
                "path": svg_path(geometry, project),
                "label_x": round(label_x, 1),
                "label_y": round(label_y, 1),
                "show_label": bool(row["STUSPS"] not in SMALL_LABELS
                                   and projected_width >= 24 and projected_height >= 20),
            })
    report = {
        "source_url": URL,
        "source_sha256": actual_sha,
        "view_box": "0 0 1000 610",
        "states": sorted(states, key=lambda state: state["abbr"]),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(states)} states to {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
