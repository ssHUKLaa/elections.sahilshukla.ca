"""Build the fixed, one-tile-per-district House cartogram layout.

Run from the repository root with ``python pipeline/build_us_house_cartogram.py``.
The forecast is deliberately absent here: a district keeps its position as the
date slider changes. Shapely is needed only when rebuilding this static file.
"""

import json
import math
import re
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Polygon, box
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
DISTRICTS = json.loads((ROOT / 'static/data/us_house_2026_paths.json').read_text())['districts']
STATES = json.loads((ROOT / 'static/data/us_states_2024_paths.json').read_text())['states']
OUTPUT = ROOT / 'static/data/us_house_2026_cartogram.json'
COLS, ROWS = 51, 34
TILE, PITCH = 15, 16
SHAPE_DIMS = {
    'CA': (6, 13), 'TX': (9, 7), 'FL': (8, 8), 'NY': (8, 5),
    'PA': (6, 4), 'MI': (5, 5), 'IL': (4, 5), 'OH': (4, 4),
    'NC': (7, 3), 'VA': (6, 3), 'TN': (6, 3), 'MD': (4, 3),
    'AL': (2, 4), 'NJ': (3, 5), 'MA': (4, 3),
}


def polygon_from_svg(path):
    """The source SVG contains absolute M/L coordinates and closed rings."""
    polygons = []
    for ring in re.findall(r'M([^Z]+)Z', path):
        points = [(float(x), float(y)) for x, y in re.findall(r'([0-9.]+),([0-9.]+)', ring)]
        if len(points) >= 3:
            polygon = Polygon(points)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if not polygon.is_empty:
                polygons.append(polygon)
    return unary_union(polygons)


def footprint(state, count):
    """Rasterize the state outline into exactly `count` district squares."""
    if count == 1:
        return [(0, 0)], 1, 1
    shape = polygon_from_svg(state['path'])
    minx, miny, maxx, maxy = shape.bounds
    aspect = max(0.42, min(2.8, ((maxx - minx) / (maxy - miny)) ** 0.8))
    fill = max(0.36, min(0.90, shape.area / ((maxx - minx) * (maxy - miny))))
    width = max(1, round(math.sqrt(count / fill * aspect)))
    height = max(1, math.ceil(count / fill / width))
    if state['abbr'] in SHAPE_DIMS:
        width, height = SHAPE_DIMS[state['abbr']]
    width = max(width, math.ceil(count / height))
    scores = []
    dx, dy = (maxx - minx) / width, (maxy - miny) / height
    for y in range(height):
        for x in range(width):
            cell = box(minx + x * dx, miny + y * dy,
                       minx + (x + 1) * dx, miny + (y + 1) * dy)
            coverage = shape.intersection(cell).area / cell.area
            # Prefer occupied cells near the outline's center in exact ties.
            scores.append((coverage, -abs(x - (width - 1) / 2) - abs(y - (height - 1) / 2), x, y))
    coverage = {(x, y): value for value, _, x, y in scores}
    start = max(scores)[2:]
    selected = {start}
    while len(selected) < count:
        frontier = {(x + dx, y + dy)
                    for x, y in selected for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < width and 0 <= y + dy < height}
        frontier -= selected
        next_cell = max(frontier, key=lambda p: (coverage[p],
                                                 sum((p[0] + dx, p[1] + dy) in selected
                                                     for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))),
                                                 -abs(p[0] - (width - 1) / 2) - abs(p[1] - (height - 1) / 2)))
        selected.add(next_cell)
    slots = list(selected)
    left, top = min(x for x, _ in slots), min(y for _, y in slots)
    slots = [(x - left, y - top) for x, y in slots]
    return slots, max(x for x, _ in slots) + 1, max(y for _, y in slots) + 1


def target(state):
    # Compress the geographic map into a tile map, with room for the Northeast.
    x = (state['label_x'] - 130) / 770 * 45 + 2
    y = (state['label_y'] - 50) / 450 * 26 + 2
    return x, y


def path_center(path):
    coords = [(float(x), float(y)) for x, y in re.findall(r'([0-9.]+),([0-9.]+)', path)]
    return (sum(x for x, _ in coords) / len(coords),
            sum(y for _, y in coords) / len(coords))


def outline_path(col, row, slots):
    shape = unary_union([box((col + x) * PITCH, (row + y) * PITCH,
                             (col + x + 1) * PITCH, (row + y + 1) * PITCH)
                         for x, y in slots])
    polygons = [shape] if shape.geom_type == 'Polygon' else shape.geoms
    rings = []
    for polygon in polygons:
        for ring in (polygon.exterior, *polygon.interiors):
            coords = list(ring.coords)
            rings.append('M' + 'L'.join(f'{int(x)},{int(y)}' for x, y in coords) + 'Z')
    return ''.join(rings)


def label_positions(placements, occupied):
    labels = []
    used_boxes = []
    tile_boxes = [(x * PITCH, y * PITCH, (x + 1) * PITCH, (y + 1) * PITCH)
                  for x, y in occupied]

    def overlaps(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    for abbr in sorted(placements, key=lambda s: (-len(placements[s][2]), s)):
        col, row, slots, width, height = placements[abbr]
        left, right = col * PITCH, (col + width) * PITCH
        top, bottom = row * PITCH, (row + height) * PITCH
        xs = [left + width * PITCH * fraction for fraction in (0.5, 0.25, 0.75)]
        candidates = [(x, top - 4) for x in xs]
        candidates += [(x, bottom + 13) for x in xs]
        candidates += [(left - 13, (top + bottom) / 2),
                       (right + 13, (top + bottom) / 2)]
        best = None
        for index, (x, y) in enumerate(candidates):
            bbox = (x - 10, y - 12, x + 10, y + 2)
            collisions = sum(overlaps(bbox, tile) for tile in tile_boxes)
            collisions += 2 * sum(overlaps(bbox, other) for other in used_boxes)
            outside = x < 10 or x > (COLS + 1) * PITCH - 10 or y < 12 or y > (ROWS + 1) * PITCH - 2
            score = collisions * 100 + outside * 1000 + index
            if best is None or score < best[0]:
                best = (score, x, y, bbox)
        _, x, y, bbox = best
        used_boxes.append(bbox)
        labels.append({'abbr': abbr, 'x': x, 'y': y})
    return labels


def main():
    by_state = defaultdict(list)
    for district in DISTRICTS:
        by_state[district['state']].append(district)
    state_info = {state['abbr']: state for state in STATES if state['abbr'] in by_state}
    assert set(state_info) == set(by_state)

    occupied = set()
    placements = {}
    # Large states anchor the layout; smaller states fit into nearby gaps.
    for abbr in sorted(by_state, key=lambda s: (-len(by_state[s]), s)):
        slots, width, height = footprint(state_info[abbr], len(by_state[abbr]))
        tx, ty = target(state_info[abbr])
        best = None
        for row in range(1, ROWS - height):
            for col in range(1, COLS - width):
                shifted = {(col + x, row + y) for x, y in slots}
                if shifted & occupied:
                    continue
                cx = col + sum(x for x, _ in slots) / len(slots)
                cy = row + sum(y for _, y in slots) / len(slots)
                neighbors = sum((x + dx, y + dy) in occupied
                                for x, y in shifted for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                if neighbors:
                    continue
                score = (cx - tx) ** 2 + 1.2 * (cy - ty) ** 2
                if best is None or score < best[0]:
                    best = (score, col, row, shifted)
        if best is None:
            raise ValueError(f'Could not place {abbr}')
        _, col, row, shifted = best
        occupied.update(shifted)
        placements[abbr] = col, row, slots, width, height

    tiles, outlines = [], []
    for abbr, (col, row, slots, width, height) in placements.items():
        districts = by_state[abbr]
        centers = {d['id']: path_center(d['path']) for d in districts}
        xs, ys = zip(*centers.values())
        xspan, yspan = max(xs) - min(xs), max(ys) - min(ys)
        remaining = set(slots)
        for district in sorted(districts, key=lambda d: (centers[d['id']][1], centers[d['id']][0])):
            x, y = centers[district['id']]
            nx = (x - min(xs)) / xspan * max(width - 1, 1) if xspan else (width - 1) / 2
            ny = (y - min(ys)) / yspan * max(height - 1, 1) if yspan else (height - 1) / 2
            sx, sy = min(remaining, key=lambda p: ((p[0] - nx) ** 2 + (p[1] - ny) ** 2, p[1], p[0]))
            remaining.remove((sx, sy))
            tiles.append({'id': district['id'], 'x': (col + sx) * PITCH,
                          'y': (row + sy) * PITCH})
        outlines.append({'abbr': abbr, 'path': outline_path(col, row, slots)})

    assert len(tiles) == 435 and len({t['id'] for t in tiles}) == 435
    assert len({(t['x'], t['y']) for t in tiles}) == 435
    labels = label_positions(placements, occupied)
    result = {'view_box': [0, 0, (COLS + 1) * PITCH, (ROWS + 1) * PITCH],
              'tile_size': TILE, 'tiles': sorted(tiles, key=lambda t: t['id']),
              'labels': sorted(labels, key=lambda l: l['abbr']),
              'outlines': sorted(outlines, key=lambda o: o['abbr'])}
    OUTPUT.write_text(json.dumps(result, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'Wrote {len(tiles)} tiles across {len(labels)} states to {OUTPUT}')


if __name__ == '__main__':
    main()
