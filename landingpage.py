import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, redirect, render_template, request
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from datavisualize import server as us2024server

# Initialize Flask app
server = Flask(__name__)
STATE_MAP_PATH = Path(__file__).resolve().parent / 'static/data/us_states_2024_paths.json'
STATE_MAP = json.loads(STATE_MAP_PATH.read_text(encoding='utf-8'))
HOUSE_MAP_PATH = Path(__file__).resolve().parent / 'static/data/us_house_2026_paths.json'
HOUSE_MAP = json.loads(HOUSE_MAP_PATH.read_text(encoding='utf-8'))
HOUSE_CARTOGRAM_PATH = Path(__file__).resolve().parent / 'static/data/us_house_2026_cartogram.json'
US2026_CSS_PATH = Path(__file__).resolve().parent / 'static/css/us2026.css'
SENATE_BASELINES_PATH = Path(__file__).resolve().parent / 'data/reference/senate_seat_baselines_2026.json'
SENATE_BASELINES = json.loads(SENATE_BASELINES_PATH.read_text(encoding='utf-8'))['seats']
HOUSE_BASELINES_PATH = Path(__file__).resolve().parent / 'data/reference/house_seat_baselines_2026.json'
HOUSE_BASELINES = json.loads(HOUSE_BASELINES_PATH.read_text(encoding='utf-8'))['seats']
GOVERNOR_BASELINES_PATH = Path(__file__).resolve().parent / 'data/reference/governor_seat_baselines_2026.json'
GOVERNOR_BASELINES = json.loads(GOVERNOR_BASELINES_PATH.read_text(encoding='utf-8'))['seats']
GOVERNOR_CLOSE_THRESHOLD = 0.70
PARTISAN_PALETTE = (
    (-1.0, (125, 16, 40)),
    (-0.6, (167, 23, 50)),
    (-0.3, (211, 41, 66)),
    (0.0, (128, 87, 170)),
    (0.3, (39, 123, 205)),
    (0.6, (22, 85, 171)),
    (1.0, (11, 44, 136)),
)


def partisan_color(score):
    score = max(-1.0, min(1.0, score))
    for (low, start), (high, end) in zip(PARTISAN_PALETTE, PARTISAN_PALETTE[1:]):
        if score <= high:
            fraction = (score - low) / (high - low)
            rgb = tuple(round(a + (b - a) * fraction) for a, b in zip(start, end))
            return '#{:02x}{:02x}{:02x}'.format(*rgb)
    return '#0b2c88'


def race_color_score(race):
    winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
    group = winner['party_group']
    if group == 'O':
        return 0.0, winner, '#78808c'
    strength = max(0.08, 2 * winner['eventual_win_probability'] - 1)
    score = strength if group == 'D' else -strength
    return score, winner, partisan_color(score)


MAP_TOOLTIP_PARTY_LABELS = {
    'D': 'Dem.', 'DEM': 'Dem.', 'DEMOCRAT': 'Dem.', 'DEMOCRATIC': 'Dem.',
    'R': 'Rep.', 'REP': 'Rep.', 'REPUBLICAN': 'Rep.', 'GOP': 'Rep.',
    'LIB': 'Lib.', 'LIBERTARIAN': 'Lib.',
    'IND': 'Ind.', 'IND.': 'Ind.', 'INDP': 'Ind.', 'INDEPENDENT': 'Ind.',
}
MAP_TOOLTIP_PARTY_COLORS = {
    'D': '#397fc9', 'R': '#c82336', 'O': '#78808c',
}


def map_race_tooltip(title, race, winner):
    rows = []
    for candidate in sorted(race['candidates'],
                            key=lambda item: item['first_stage_share']['mean'], reverse=True):
        group = candidate['party_group']
        party_code = str(candidate.get('party', '')).strip()
        rows.append({
            'name': candidate['name'] + ('*' if candidate.get('incumbent') else ''),
            'party': MAP_TOOLTIP_PARTY_LABELS.get(
                party_code.upper(), MAP_TOOLTIP_PARTY_LABELS.get(group, party_code or 'Other')),
            'pct': f"{100 * candidate['first_stage_share']['mean']:.1f}%",
            'color': MAP_TOOLTIP_PARTY_COLORS.get(group, MAP_TOOLTIP_PARTY_COLORS['O']),
            'winner': candidate['candidate_id'] == winner['candidate_id'],
        })
    return {
        'title': title,
        'rows': rows,
        'has_incumbent': any(candidate.get('incumbent') for candidate in race['candidates']),
    }


KEY_BAR_COLORS = {
    'D': ('#0b2c88', '#6888c0'),
    'R': ('#7d1028', '#bb6577'),
    'O': ('#66707e', '#929ba8'),
}


def key_bar_gradient(candidate, range_at_right):
    dark, range_color = KEY_BAR_COLORS[candidate['party_group']]
    share = candidate['first_stage_share']
    mean = share['mean']
    margin = max(mean - share['interval95_low'], share['interval95_high'] - mean)
    range_width = min(100, 100 * margin / mean) if mean > 0 else 100
    if range_at_right:
        return (f'linear-gradient(to right, {dark} 0%, '
                f'{dark} {100 - range_width:.1f}%, '
                f'{range_color} {100 - range_width:.1f}%, {range_color} 100%)')
    return (f'linear-gradient(to right, {range_color} 0%, '
            f'{range_color} {range_width:.1f}%, '
            f'{dark} {range_width:.1f}%, {dark} 100%)')


def senate_hemicycle(forecast):
    state_names = {state['abbr']: state['name'] for state in STATE_MAP['states']}
    races = []
    for race in forecast['races']:
        if race['office'] != 'senate':
            continue
        score, winner, color = race_color_score(race)
        races.append({
            'state': race['state'],
            'race_id': race['race_id'],
            'score': score,
            'winner': winner,
            'color': color,
            'tooltip': map_race_tooltip(state_names[race['state']], race, winner),
        })
    races.sort(key=lambda race: (-race['score'], race['state'], race['race_id']))

    # Concentric rows fill the center while keeping the outer semicircle fixed.
    row_counts = (15, 12, 8)
    row_radii = (230, 175, 120)
    if len(races) != sum(row_counts):
        raise ValueError(f"Expected 35 Senate contests, found {len(races)}")
    positions = []
    for count, radius in zip(row_counts, row_radii):
        for index in range(count):
            angle = math.pi * (1 - index / (count - 1)) if count > 1 else math.pi / 2
            positions.append((300 + 0.98 * radius * math.cos(angle),
                              200.5 - 0.774 * radius * math.sin(angle)))
    positions.sort(key=lambda point: (point[0], point[1]))

    return [
        {
            'state': race['state'],
            'x': round(x, 2), 'y': round(y, 2), 'fill': race['color'],
            'title': (f"{race['state']} Senate: {race['winner']['name']} "
                      f"({race['winner']['party_group']}), "
                      f"{race['winner']['eventual_win_probability']:.0%} chance to win"),
            'tooltip': race['tooltip'],
        }
        for race, (x, y) in zip(races, positions)
    ]


def senate_tipping_marker(forecast, seats):
    full_chamber = forecast['joint_summaries']['senate']['full_chamber']
    control = full_chamber['caucus_scenarios']['all_other_winners_caucus_D']
    baseline = full_chamber['not_up_baseline']
    coalition = ('D' if control['D_control_probability'] >= control['R_control_probability'] else 'R')
    needed = (51 - baseline['D_caucus'] if coalition == 'D' else
              50 - baseline['R_caucus'])
    races = [race for race in forecast['races'] if race['office'] == 'senate']

    def coalition_probability(race):
        groups = ('D', 'O') if coalition == 'D' else ('R',)
        return sum(candidate['eventual_win_probability'] for candidate in race['candidates']
                   if candidate['party_group'] in groups)

    ranked = sorted(races, key=lambda race: (-coalition_probability(race), race['state']))
    tipping_race = ranked[needed - 1]
    tipping_seat = next(seat for seat in seats if seat['state'] == tipping_race['state'])

    hub_x, hub_y = 300, 205
    dx, dy = tipping_seat['x'] - hub_x, tipping_seat['y'] - hub_y
    distance = math.hypot(dx, dy)
    perp_x, perp_y = -dy / distance, dx / distance
    half_width = 8
    tip_x = tipping_seat['x'] - 13 * dx / distance
    tip_y = tipping_seat['y'] - 13 * dy / distance
    arrow_path = (f'M {hub_x + perp_x * half_width:.2f} {hub_y + perp_y * half_width:.2f} '
                  f'L {tip_x:.2f} {tip_y:.2f} '
                  f'L {hub_x - perp_x * half_width:.2f} {hub_y - perp_y * half_width:.2f} Z')
    return {
        'state': tipping_race['state'],
        'state_name': next(state['name'] for state in STATE_MAP['states']
                           if state['abbr'] == tipping_race['state']),
        'arrow_path': arrow_path,
        'arrow_color': '#4b70b6' if coalition == 'D' else '#c45263',
        'party': coalition,
        'party_adjective': 'Democratic' if coalition == 'D' else 'Republican',
        'coalition_name': 'Democrats and independents' if coalition == 'D' else 'Republicans',
        'seats_needed': needed,
    }


def majority_control_gauge(d_probability, r_probability):
    favored = 'D' if d_probability >= r_probability else 'R'
    bands = (
        (0.00, 0.15, 'VERY LIKELY', '#f0d6d9', '#a84c58'),
        (0.15, 0.35, 'LIKELY', '#f7e4e6', '#b45d67'),
        (0.35, 0.45, 'LEANING', '#fcf0f1', '#ad7880'),
        (0.45, 0.55, 'TOSSUP', '#f7f7f7', '#7c8490'),
        (0.55, 0.65, 'LEANING', '#f0f5fb', '#6d8daf'),
        (0.65, 0.85, 'LIKELY', '#e1ecf8', '#4c7eae'),
        (0.85, 1.00, 'VERY LIKELY', '#d4e3f5', '#426fa9'),
    )

    def ellipse_point(probability, radius_x, radius_y):
        angle = math.pi * probability
        return 300 + radius_x * math.cos(angle), 205 - radius_y * math.sin(angle)

    sectors = []
    for low, high, label, fill, text_color in bands:
        outer_low = ellipse_point(low, 240, 195)
        outer_high = ellipse_point(high, 240, 195)
        inner_high = ellipse_point(high, 95, 80)
        inner_low = ellipse_point(low, 95, 80)
        label_x, label_y = ellipse_point((low + high) / 2, 165, 137)
        path = (f'M{outer_low[0]:.2f} {outer_low[1]:.2f} '
                f'A240 195 0 0 0 {outer_high[0]:.2f} {outer_high[1]:.2f} '
                f'L{inner_high[0]:.2f} {inner_high[1]:.2f} '
                f'A95 80 0 0 1 {inner_low[0]:.2f} {inner_low[1]:.2f} Z')
        if high <= 0.5:
            range_label = (f"Republican chance: {100 * (1 - high):.0f}%–"
                           f"{100 * (1 - low):.0f}%")
        elif low >= 0.5:
            range_label = f"Democratic chance: {100 * low:.0f}%–{100 * high:.0f}%"
        else:
            range_label = (f"Tossup: Democratic chance {100 * low:.0f}%–"
                           f"{100 * high:.0f}%")
        sectors.append({'path': path, 'label': label, 'fill': fill,
                        'text_color': text_color, 'label_x': round(label_x, 2),
                        'label_y': round(label_y, 2), 'range_label': range_label})

    tip_x, tip_y = ellipse_point(d_probability, 228, 186)
    dx, dy = tip_x - 300, tip_y - 205
    distance = math.hypot(dx, dy)
    perp_x, perp_y = -dy / distance, dx / distance
    needle_path = (f'M{300 + 8 * perp_x:.2f} {205 + 8 * perp_y:.2f} '
                   f'L{tip_x:.2f} {tip_y:.2f} '
                   f'L{300 - 8 * perp_x:.2f} {205 - 8 * perp_y:.2f} Z')
    return {
        'sectors': sectors,
        'needle_path': needle_path,
        'needle_color': '#4b70b6' if favored == 'D' else '#c45263',
        'favored_party': favored,
        'favored_probability': round(100 * max(d_probability, r_probability), 1),
        'd_probability': round(100 * d_probability, 1),
        'r_probability': round(100 * r_probability, 1),
    }


def senate_control_gauge(forecast):
    control = forecast['joint_summaries']['senate']['full_chamber']['caucus_scenarios']['all_other_winners_caucus_D']
    return majority_control_gauge(control['D_control_probability'], control['R_control_probability'])


def house_control_gauge(forecast):
    control = forecast['joint_summaries']['house']['control']
    gauge = majority_control_gauge(control['D_control_probability'], control['R_control_probability'])
    gauge['neither_probability'] = round(100 * control['neither_probability'], 1)
    return gauge


def house_popular_vote_gauge(parameters):
    posterior = parameters['national_signal_update']['posterior']
    mean_logratio = posterior['national_D_R_logratio_mean']
    sd_logratio = posterior['national_D_R_logratio_sd']
    margin = lambda value: 100 * math.tanh(value / 2)
    mean = margin(mean_logratio)
    low = margin(mean_logratio - 1.96 * sd_logratio)
    high = margin(mean_logratio + 1.96 * sd_logratio)
    scale = max(20, 5 * math.ceil(max(abs(low), abs(high), abs(mean)) / 5))

    def point(value, radius_x, radius_y):
        angle = math.pi / 2 + math.pi * max(-scale, min(scale, value)) / (2 * scale)
        return 300 + radius_x * math.cos(angle), 205 - radius_y * math.sin(angle)

    def band_path(lower, upper):
        outer_low = point(lower, 240, 195)
        outer_high = point(upper, 240, 195)
        inner_high = point(upper, 95, 80)
        inner_low = point(lower, 95, 80)
        return (f'M{outer_low[0]:.2f} {outer_low[1]:.2f} '
                f'A240 195 0 0 0 {outer_high[0]:.2f} {outer_high[1]:.2f} '
                f'L{inner_high[0]:.2f} {inner_high[1]:.2f} '
                f'A95 80 0 0 1 {inner_low[0]:.2f} {inner_low[1]:.2f} Z')

    bands = []
    if low < 0:
        bands.append({'path': band_path(low, min(high, 0)), 'fill': '#e6a3aa'})
    if high > 0:
        bands.append({'path': band_path(max(low, 0), high), 'fill': '#a7c6ed'})
    ticks = []
    labels = []
    for value in range(-scale, scale + 1):
        outer = point(value, 240, 195)
        inner = point(value, 233 if value % 5 == 0 else 236,
                      189 if value % 5 == 0 else 192)
        ticks.append({'x1': round(inner[0], 2), 'y1': round(inner[1], 2),
                      'x2': round(outer[0], 2), 'y2': round(outer[1], 2)})
        if value % 5 == 0 and abs(value) < scale:
            x, y = point(value, 205, 164)
            text = '0' if value == 0 else f'D+{value}' if value > 0 else f'R+{-value}'
            rotation = (math.copysign(90 * (1 - abs(value) / scale), value)
                        if value else 0)
            labels.append({'x': round(x, 2), 'y': round(y, 2),
                           'text': text, 'rotation': round(rotation, 2),
                           'party': 'D' if value > 0 else 'R' if value < 0 else 'center'})
    tip_x, tip_y = point(mean, 230, 188)
    dx, dy = tip_x - 300, tip_y - 205
    distance = math.hypot(dx, dy)
    perp_x, perp_y = -dy / distance, dx / distance
    needle_path = (f'M{300 + 8 * perp_x:.2f} {205 + 8 * perp_y:.2f} '
                   f'L{tip_x:.2f} {tip_y:.2f} '
                   f'L{300 - 8 * perp_x:.2f} {205 - 8 * perp_y:.2f} Z')

    def margin_text(value):
        return f'D+{value:.1f}' if value >= 0 else f'R+{-value:.1f}'

    return {'bands': bands, 'ticks': ticks, 'labels': labels,
            'needle_path': needle_path, 'needle_color': '#4b86ce' if mean >= 0 else '#c45263',
            'party': 'D' if mean >= 0 else 'R',
            'mean': mean, 'low': low, 'high': high,
            'mean_display': f'Dem. +{mean:.1f}' if mean >= 0 else f'Rep. +{-mean:.1f}',
            'mean_text': margin_text(mean), 'low_text': margin_text(low),
            'high_text': margin_text(high)}


def senate_projected_seats(forecast):
    baseline = forecast['joint_summaries']['senate']['full_chamber']['not_up_baseline']
    d_seats = baseline['D_caucus']
    r_seats = baseline['R_caucus']
    for race in forecast['races']:
        if race['office'] != 'senate':
            continue
        winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
        if winner['party_group'] in ('D', 'O'):
            d_seats += 1
        else:
            r_seats += 1
    return {
        'd_seats': d_seats,
        'r_seats': r_seats,
        'd_not_up': baseline['D_caucus'],
        'r_not_up': baseline['R_caucus'],
    }


def senate_map_states(forecast):
    races = {race['state']: race for race in forecast['races'] if race['office'] == 'senate'}
    states = []
    for geometry in STATE_MAP['states']:
        state = dict(geometry)
        race = races.get(state['abbr'])
        if race is None:
            state.update(fill='#edf0f3', label_fill='#657180', winner_group='none', flip=False,
                         title=f"{state['name']}: no Senate election")
        else:
            _, winner, fill = race_color_score(race)
            prior = SENATE_BASELINES[race['race_id']]['prior_winner_group']
            group = winner['party_group']
            flip = group != prior
            state.update(
                fill=fill,
                label_fill='#ffffff',
                winner_group=group,
                flip=flip,
                tooltip=map_race_tooltip(state['name'], race, winner),
                title=(f"{state['name']} Senate: {winner['name']} "
                       f"({winner['party']}), {winner['eventual_win_probability']:.0%} chance to win"
                       + (f"; projected flip from {prior}" if flip else "")),
            )
        states.append(state)
    return states


def senate_extreme_maps(extremes):
    maps = []
    for key, heading in (("best_democratic", "Best Democratic simulation"),
                         ("best_republican", "Best Republican simulation")):
        scenario = extremes[key]
        states = []
        for geometry in STATE_MAP['states']:
            state = dict(geometry)
            winner = scenario['winners'].get(state['abbr'])
            if winner is None:
                state.update(fill='#edf0f3', label_fill='#657180',
                             title=f"{state['name']}: no Senate election")
            else:
                group = winner['party_group']
                fill = {'D': '#0b2c88', 'R': '#7d1028', 'O': '#78808c'}[group]
                state.update(fill=fill, label_fill='#ffffff',
                             title=f"{state['name']} Senate: {winner['name']} ({winner['party']})")
            states.append(state)
        maps.append({'heading': heading,
                     'd_seats': scenario['D_and_independent_seats'],
                     'r_seats': scenario['R_seats'],
                     'states': states})
    return maps


def seat_distribution_interval(counts, draws, left, step, max_d):
    cumulative = 0
    quantiles = {}
    thresholds = {1: (draws + 9) // 10,
                  5: (5 * draws + 9) // 10,
                  9: (9 * draws + 9) // 10}
    for seats, count in sorted(counts.items()):
        cumulative += count
        for numerator, threshold in thresholds.items():
            if numerator not in quantiles and cumulative >= threshold:
                quantiles[numerator] = seats
    def x(seats):
        return round(left + (max_d - seats) * step, 2)
    return {'median': quantiles[5], 'low': quantiles[1], 'high': quantiles[9],
            'median_x': x(quantiles[5]), 'left_x': x(quantiles[9]),
            'right_x': x(quantiles[1]),
            'center_x': round((x(quantiles[9]) + x(quantiles[1])) / 2, 2)}


def distribution_range_stops(interval, control_counts):
    palette = {'D': (11, 44, 136), 'R': (167, 23, 50), 'O': (120, 128, 140)}
    high, low = interval['high'], interval['low']
    stops = []
    for seats in range(high, low - 1, -1):
        groups = control_counts.get(seats, {})
        total = sum(groups.values())
        if not total:
            nearest = min((seat for seat, outcome in control_counts.items() if sum(outcome.values())),
                          key=lambda seat: abs(seat - seats))
            groups = control_counts[nearest]
            total = sum(groups.values())
        # An opaque pastel keeps the dots legible while using the actual
        # majority mix beneath each seat total to choose the hue.
        rgb = tuple(round(0.86 * 255 + 0.14 *
                          sum(groups.get(party, 0) * palette[party][channel]
                              for party in palette) / total)
                    for channel in range(3))
        stops.append({'offset': round(100 * (high - seats) / max(1, high - low), 3),
                      'color': '#{:02x}{:02x}{:02x}'.format(*rgb)})
    if len(stops) == 1:
        stops.append({'offset': 100, 'color': stops[0]['color']})
    return stops


def senate_seat_dotplot(forecast):
    draws = forecast['metadata']['simulation_draws']
    joint = forecast['joint_summaries']['senate']['joint_D_R_O_distribution']
    baseline = forecast['joint_summaries']['senate']['full_chamber']['not_up_baseline']
    counts = {}
    for result, probability in joint.items():
        d_elected, r_elected, other_elected = map(int, result.split('-'))
        d_seats = baseline['D_caucus'] + d_elected + other_elected
        r_seats = baseline['R_caucus'] + r_elected
        if d_seats + r_seats != 100:
            raise ValueError(f'Invalid Senate seat total: {result}')
        counts[d_seats] = counts.get(d_seats, 0) + round(probability * draws)
    if sum(counts.values()) != draws:
        raise ValueError('Senate seat distribution does not sum to the simulation count')

    dot_unit = max(200, 50 * math.ceil(max(counts.values()) / 48 / 50))
    left, right, bottom, pitch = 66, 950, 385, 7.2
    max_d, min_d = max(counts), min(counts)
    step = (right - left) / (max_d - min_d) if max_d > min_d else 0
    columns = []
    for d_seats in range(max_d, min_d - 1, -1):
        count = counts.get(d_seats, 0)
        dots = []
        for index in range(math.ceil(count / dot_unit)):
            represented = min(dot_unit, count - index * dot_unit)
            dots.append({'y': round(bottom - (index + 0.5) * pitch, 2),
                         'opacity': round(0.35 + 0.65 * represented / dot_unit, 3),
                         'tooltip': {
                             'title': f'{d_seats} D+I seats · {100 - d_seats} R seats',
                             'detail': ('Democratic caucus majority' if d_seats >= 51
                                        else 'Republican majority'),
                             'represented': represented,
                             'share': round(100 * represented / draws, 2),
                             'dot_color': '#0b2c88' if d_seats >= 51 else '#a71732',
                         }})
        columns.append({'x': round(left + (max_d - d_seats) * step, 2),
                        'd_seats': d_seats, 'r_seats': 100 - d_seats,
                        'count': count, 'fill': '#0b2c88' if d_seats >= 51 else '#a71732',
                        'dots': dots})

    tick_seats = {max_d, min_d}
    if min_d <= 50 <= max_d:
        tick_seats.add(50)
    tick_seats.update(seats for seats in range(min_d, max_d + 1) if seats % 5 == 0)
    ticks = []
    for d_seats in sorted(tick_seats, reverse=True):
        label = ('50–50' if d_seats == 50 else
                 f'{d_seats} D+I' if d_seats > 50 else f'{100 - d_seats} R')
        ticks.append({'x': round(left + (max_d - d_seats) * step, 2), 'label': label})
    grid_max = max(2000, 2000 * math.ceil(max(counts.values()) / 2000))
    interval = seat_distribution_interval(counts, draws, left, step, max_d)
    interval['gradient_stops'] = distribution_range_stops(
        interval, {seats: {'D': count} if seats >= 51 else {'R': count}
                   for seats, count in counts.items()})
    return {'draws': draws, 'dot_unit': dot_unit, 'columns': columns, 'ticks': ticks,
            'interval': interval,
            'grid': [{'count': count, 'y': round(bottom - count / dot_unit * pitch, 2)}
                     for count in range(0, grid_max + 1, 2000)],
            'majority_x': (round(left + (max_d - 50.5) * step, 2)
                           if min_d <= 50 < max_d else None)}


def house_seat_dotplot(forecast):
    draws = forecast['metadata']['simulation_draws']
    joint = forecast['joint_summaries']['house']['joint_D_R_O_distribution']
    counts = {}
    seat_ranges_by_group = {}
    for result, probability in joint.items():
        d_seats, r_seats, other_seats = map(int, result.split('-'))
        if d_seats + r_seats + other_seats != 435:
            raise ValueError(f'Invalid House seat total: {result}')
        control = 'D' if d_seats >= 218 else 'R' if r_seats >= 218 else 'O'
        by_control = counts.setdefault(d_seats, {'D': 0, 'R': 0, 'O': 0})
        represented = round(probability * draws)
        by_control[control] += represented
        group = seat_ranges_by_group.setdefault(
            (d_seats, control),
            {'count': 0, 'r_min': 436, 'r_max': -1, 'o_min': 436, 'o_max': -1})
        group['count'] += represented
        if represented:
            group['r_min'] = min(group['r_min'], r_seats)
            group['r_max'] = max(group['r_max'], r_seats)
            group['o_min'] = min(group['o_min'], other_seats)
            group['o_max'] = max(group['o_max'], other_seats)
    if sum(sum(groups.values()) for groups in counts.values()) != draws:
        raise ValueError('House seat distribution does not sum to the simulation count')

    max_count = max(sum(groups.values()) for groups in counts.values())
    dot_unit = max(25, 5 * math.ceil(max_count / 48 / 5))
    left, right, bottom, pitch = 66, 950, 385, 7.2
    max_d, min_d = max(counts), min(counts)
    step = (right - left) / (max_d - min_d) if max_d > min_d else 0
    colors = {'D': '#0b2c88', 'R': '#a71732', 'O': '#78808c'}
    columns = []
    for d_seats in range(max_d, min_d - 1, -1):
        groups = counts.get(d_seats, {'D': 0, 'R': 0, 'O': 0})
        dots = []
        for control in ('R', 'O', 'D'):
            count = groups[control]
            for index in range(math.ceil(count / dot_unit)):
                represented = min(dot_unit, count - index * dot_unit)
                control_label = {'D': 'Democratic majority', 'R': 'Republican majority',
                                 'O': 'Neither party has a majority'}[control]
                seat_ranges = seat_ranges_by_group[(d_seats, control)]
                r_range = (str(seat_ranges['r_min']) if seat_ranges['r_min'] == seat_ranges['r_max']
                           else f"{seat_ranges['r_min']}-{seat_ranges['r_max']}")
                o_range = (str(seat_ranges['o_min']) if seat_ranges['o_min'] == seat_ranges['o_max']
                           else f"{seat_ranges['o_min']}-{seat_ranges['o_max']}")
                dots.append({'y': round(bottom - (len(dots) + 0.5) * pitch, 2),
                             'opacity': round(0.35 + 0.65 * represented / dot_unit, 3),
                             'fill': colors[control],
                             'tooltip': {
                                 'title': f'{d_seats} D · {r_range} R · {o_range} Ind./Other',
                                 'detail': control_label,
                                 'represented': represented,
                                 'share': round(100 * represented / draws, 2),
                                 'dot_color': colors[control],
                             }})
        columns.append({'x': round(left + (max_d - d_seats) * step, 2),
                        'd_seats': d_seats, 'count': sum(groups.values()),
                        'd_control': groups['D'], 'r_control': groups['R'],
                        'neither': groups['O'], 'dots': dots})

    tick_seats = {max_d, min_d}
    if min_d <= 218 <= max_d:
        tick_seats.add(218)
    tick_seats.update(seats for seats in range(min_d, max_d + 1)
                      if seats % 20 == 0 and abs(seats - 218) >= 8
                      and abs(seats - min_d) >= 6 and abs(seats - max_d) >= 6)
    ticks = [{'x': round(left + (max_d - seats) * step, 2), 'label': str(seats)}
             for seats in sorted(tick_seats, reverse=True)]
    grid_max = max(500, 500 * math.ceil(max_count / 500))
    seat_counts = {seats: sum(groups.values()) for seats, groups in counts.items()}
    interval = seat_distribution_interval(seat_counts, draws, left, step, max_d)
    interval['gradient_stops'] = distribution_range_stops(interval, counts)
    return {'draws': draws, 'dot_unit': dot_unit, 'columns': columns, 'ticks': ticks,
            'interval': interval,
            'grid': [{'count': count, 'y': round(bottom - count / dot_unit * pitch, 2)}
                     for count in range(0, grid_max + 1, 500)],
            'majority_x': (round(left + (max_d - 217.5) * step, 2)
                           if min_d <= 217 < max_d else None)}


def senate_key_states(forecast, map_states):
    by_state = {state['abbr']: state for state in map_states}
    key_races = []
    for race in forecast['races']:
        if race['office'] != 'senate':
            continue
        winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
        if winner['eventual_win_probability'] >= 0.90:
            continue
        vote_order = sorted(race['candidates'],
                            key=lambda candidate: (-candidate['first_stage_share']['mean'], candidate['name']))
        segments = [
            {
                'name': candidate['name'],
                'label': (candidate['name'].split()[-1].title()
                          if candidate['first_stage_share']['mean'] > 0.15 else None),
                'share': round(100 * candidate['first_stage_share']['mean'], 2),
                'display_share': round(100 * candidate['first_stage_share']['mean'], 1),
                'gradient': key_bar_gradient(candidate, index == 0),
                'css_class': ('key-race-fill' if index == 0 else
                              'key-race-remainder' if index == 1 else 'key-race-other'),
            }
            for index, candidate in enumerate(vote_order)
        ]
        key_races.append({
            'state': race['state'],
            'state_name': by_state[race['state']]['name'],
            'winner_probability': round(100 * winner['eventual_win_probability'], 1),
            'segments': segments,
            'vote_aria_label': (f"{by_state[race['state']]['name']} expected vote: " +
                                ', '.join(f"{segment['name']} {segment['display_share']} percent"
                                          for segment in segments)),
            'flip': by_state[race['state']]['flip'],
            'tooltip': by_state[race['state']]['tooltip'],
        })
    return sorted(key_races, key=lambda race: (race['winner_probability'], race['state']))


def house_projected_seats(forecast):
    counts = {'D': 0, 'R': 0, 'O': 0}
    for race in forecast['races']:
        if race['office'] == 'house':
            winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
            counts[winner['party_group']] += 1
    if sum(counts.values()) != 435:
        raise ValueError('Expected 435 projected House seats')
    return {'d_seats': counts['D'], 'r_seats': counts['R'], 'other_seats': counts['O'],
            'd_percent': round(100 * counts['D'] / 435, 3),
            'other_percent': round(100 * counts['O'] / 435, 3),
            'majority_percent': round(100 * 218 / 435, 3)}


def house_map_districts(forecast, cartogram_tiles):
    races = {f"{race['state']}-{race['district_code']}": race
             for race in forecast['races'] if race['office'] == 'house'}
    if set(races) != {district['id'] for district in HOUSE_MAP['districts']}:
        raise ValueError('House district geometry does not match the forecast race universe')
    if set(races) != set(cartogram_tiles):
        raise ValueError('House cartogram tiles do not match the forecast race universe')
    districts = []
    for geometry in HOUSE_MAP['districts']:
        race = races[geometry['id']]
        _, winner, fill = race_color_score(race)
        prior = HOUSE_BASELINES[race['race_id']]['prior_winner_group']
        flip = winner['party_group'] != prior
        district = dict(geometry)
        district.update(tile_x=cartogram_tiles[geometry['id']]['x'],
                        tile_y=cartogram_tiles[geometry['id']]['y'])
        state_name = next((state['name'] for state in STATE_MAP['states']
                           if state['abbr'] == race['state']), race['state'])
        district_number = int(race['district_code']) if race['district_code'].isdigit() else None
        district_name = (f"District {district_number}" if district_number
                         else "At-large district")
        district.update(fill=fill, flip=flip, winner_group=winner['party_group'],
                        tooltip=map_race_tooltip(
                            f"{state_name} · {district_name}", race, winner),
                        title=(f"{geometry['id']} House: {winner['name']} ({winner['party']}), "
                               f"{winner['eventual_win_probability']:.0%} chance to win"
                               + (f"; projected flip from 2024 same-numbered seat ({prior})"
                                  if flip else "")))
        districts.append(district)
    return districts


def house_district_view_box(path):
    points = [(float(x), float(y)) for x, y in re.findall(r'([0-9.]+),([0-9.]+)', path)]
    xs, ys = zip(*points)
    left, top = min(xs), min(ys)
    width, height = max(xs) - left, max(ys) - top
    padding = max(width, height) * 0.06
    return (f'{left - padding:.2f} {top - padding:.2f} '
            f'{width + 2 * padding:.2f} {height + 2 * padding:.2f}',
            round(max(width, height) / 9, 2))


def house_close_races(forecast):
    close = []
    state_names = {state['abbr']: state['name'] for state in STATE_MAP['states']}
    for race in forecast['races']:
        if race['office'] != 'house':
            continue
        winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
        if winner['eventual_win_probability'] >= 0.60:
            continue
        vote_order = sorted(race['candidates'],
                            key=lambda candidate: (-candidate['first_stage_share']['mean'], candidate['name']))
        segments = [
            {'name': candidate['name'],
             'label': (candidate['name'].split()[-1].title()
                       if candidate['first_stage_share']['mean'] > 0.15 else None),
             'share': round(100 * candidate['first_stage_share']['mean'], 2),
             'display_share': round(100 * candidate['first_stage_share']['mean'], 1),
             'gradient': key_bar_gradient(candidate, index == 0),
             'css_class': ('key-race-fill' if index == 0 else
                           'key-race-remainder' if index == 1 else 'key-race-other')}
            for index, candidate in enumerate(vote_order)
        ]
        district = f"{race['state']}-{'AL' if race['district_code'] == '00' else race['district_code']}"
        district_number = int(race['district_code']) if race['district_code'].isdigit() else None
        district_name = (f"District {district_number}" if district_number
                         else "At-large district")
        close.append({
            'id': f"{race['state']}-{race['district_code']}",
            'district': district,
            'winner_probability': round(100 * winner['eventual_win_probability'], 1),
            'segments': segments,
            'vote_aria_label': (f"{district} expected vote: " +
                                ', '.join(f"{segment['name']} {segment['display_share']} percent"
                                          for segment in segments)),
            'tooltip': map_race_tooltip(
                f"{state_names.get(race['state'], race['state'])} · {district_name}", race, winner),
        })
    return sorted(close, key=lambda race: (race['winner_probability'], race['district']))


def governor_projected_seats(forecast):
    races = [race for race in forecast['races'] if race['office'] == 'governor']
    if {race['race_id'] for race in races} != set(GOVERNOR_BASELINES):
        raise ValueError('Governor baseline does not match the forecast race universe')
    counts = {'D': 0, 'R': 0, 'O': 0}
    for race in races:
        winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
        counts[winner['party_group']] += 1
    total = sum(counts.values())
    return {'total': total, 'd_seats': counts['D'], 'r_seats': counts['R'],
            'other_seats': counts['O'], 'd_percent': round(100 * counts['D'] / total, 3),
            'other_percent': round(100 * counts['O'] / total, 3),
            'not_up': 50 - total}


def governor_map_states(forecast):
    races = {race['state']: race for race in forecast['races'] if race['office'] == 'governor'}
    states = []
    for geometry in STATE_MAP['states']:
        state = dict(geometry)
        race = races.get(state['abbr'])
        if race is None:
            state.update(fill='#edf0f3', label_fill='#657180', winner_group='none', flip=False,
                         title=f"{state['name']}: no governor election")
        else:
            _, winner, fill = race_color_score(race)
            prior = GOVERNOR_BASELINES[race['race_id']]['prior_winner_group']
            flip = winner['party_group'] != prior
            state.update(fill=fill, label_fill='#ffffff', winner_group=winner['party_group'],
                         flip=flip, tooltip=map_race_tooltip(state['name'], race, winner),
                         title=(f"{state['name']} governor: {winner['name']} ({winner['party']}), "
                                f"{winner['eventual_win_probability']:.0%} chance to win"
                                + (f'; projected flip from {prior}' if flip else '')))
        states.append(state)
    return states


def governor_close_races(forecast, map_states):
    by_state = {state['abbr']: state for state in map_states}
    close = []
    for race in forecast['races']:
        if race['office'] != 'governor':
            continue
        winner = max(race['candidates'], key=lambda candidate: candidate['eventual_win_probability'])
        if winner['eventual_win_probability'] >= GOVERNOR_CLOSE_THRESHOLD:
            continue
        vote_order = sorted(race['candidates'],
                            key=lambda candidate: (-candidate['first_stage_share']['mean'], candidate['name']))
        segments = [
            {'name': candidate['name'],
             'label': (candidate['name'].split()[-1].title()
                       if candidate['first_stage_share']['mean'] > 0.15 else None),
             'share': round(100 * candidate['first_stage_share']['mean'], 2),
             'display_share': round(100 * candidate['first_stage_share']['mean'], 1),
             'gradient': key_bar_gradient(candidate, index == 0),
             'css_class': ('key-race-fill' if index == 0 else
                           'key-race-remainder' if index == 1 else 'key-race-other')}
            for index, candidate in enumerate(vote_order)
        ]
        state = by_state[race['state']]
        close.append({'state': race['state'], 'state_name': state['name'],
                      'winner_probability': round(100 * winner['eventual_win_probability'], 1),
                      'segments': segments,
                      'vote_aria_label': (f"{state['name']} governor expected vote: " +
                                          ', '.join(f"{segment['name']} {segment['display_share']} percent"
                                                    for segment in segments)),
                      'tooltip': state['tooltip']})
    return sorted(close, key=lambda race: (race['winner_probability'], race['state']))

# Main route with button to redirect
@server.route('/')
def home():
    return render_template('index.html')

@server.route('/us2026')
def us2026():
    artifact_root = Path(__file__).resolve().parent / 'artifacts'
    parameters = artifact_root / 'nowcast/model_parameters.json'
    updated_at = None
    updated_iso = None
    history_dates = []
    selected_index = 0
    forecast_path = artifact_root / 'nowcast/forecast_2026.json'
    if parameters.is_file():
        metadata = json.loads(parameters.read_text(encoding='utf-8'))['metadata']
        updated_iso = metadata['information_cutoff_utc']
        history_path = artifact_root / 'nowcast_history/index.json'
        if history_path.is_file():
            history = json.loads(history_path.read_text(encoding='utf-8'))
            if history.get('entries'):
                history_dates = []
                for entry in history['entries']:
                    day = date.fromisoformat(entry['date'])
                    history_dates.append({
                        'date': entry['date'],
                        'label': f'{day:%B} {day.day}, {day:%Y}',
                        'cutoff': entry['information_cutoff_utc'],
                        'kind': entry['kind'],
                    })
                requested = request.args.get('date')
                selected_index = next((index for index, entry in enumerate(history_dates)
                                       if entry['date'] == requested), len(history_dates) - 1)
                updated_iso = history_dates[selected_index]['cutoff']
                forecast_path = (artifact_root / 'nowcast_history' /
                                 history_dates[selected_index]['date'] / 'forecast_2026.json')
        cutoff = datetime.fromisoformat(updated_iso.replace('Z', '+00:00')).astimezone(ZoneInfo('America/New_York'))
        updated_at = f'{cutoff:%B} {cutoff.day}, {cutoff:%Y at %H:%M ET}'
    forecast = json.loads(forecast_path.read_text(encoding='utf-8')) if forecast_path.is_file() else None
    senate_seats = senate_hemicycle(forecast) if forecast else []
    senate_tipping = senate_tipping_marker(forecast, senate_seats) if forecast else None
    if senate_tipping:
        for seat in senate_seats:
            if seat['state'] == senate_tipping['state']:
                seat['tooltip'] = {**seat['tooltip'], 'signifier': 'Senate tipping point'}
    senate_control = senate_control_gauge(forecast) if forecast else None
    senate_seat_projection = senate_projected_seats(forecast) if forecast else None
    senate_states = senate_map_states(forecast) if forecast else []
    senate_keys = senate_key_states(forecast, senate_states) if forecast else []
    extremes_path = forecast_path.with_name('senate_extremes_2026.json')
    extremes = json.loads(extremes_path.read_text(encoding='utf-8')) if extremes_path.is_file() else None
    if extremes and forecast and (extremes['information_cutoff_utc'] != forecast['metadata']['information_cutoff_utc'] or
                                  extremes['simulation_draws'] != forecast['metadata']['simulation_draws']):
        extremes = None
    senate_extremes = senate_extreme_maps(extremes) if extremes else []
    senate_distribution = senate_seat_dotplot(forecast) if forecast else None
    house_control = house_control_gauge(forecast) if forecast else None
    house_distribution = house_seat_dotplot(forecast) if forecast else None
    house_seat_projection = house_projected_seats(forecast) if forecast else None
    # The cartogram is tiny; read it per request so an updated static layout is
    # reflected by the date slider and development server without a restart.
    house_cartogram = json.loads(HOUSE_CARTOGRAM_PATH.read_text(encoding='utf-8'))
    cartogram_tiles = {tile['id']: tile for tile in house_cartogram['tiles']}
    house_districts = house_map_districts(forecast, cartogram_tiles) if forecast else []
    house_close = house_close_races(forecast) if forecast else []
    districts_by_id = {district['id']: district for district in house_districts}
    house_competitive = [dict(districts_by_id[race['id']], label=race['district'])
                         for race in house_close]
    for district in house_competitive:
        district['view_box'], district['hatch_pitch'] = house_district_view_box(district['path'])
    house_parameters_path = forecast_path.with_name('model_parameters.json')
    house_parameters = (json.loads(house_parameters_path.read_text(encoding='utf-8'))
                        if house_parameters_path.is_file() else None)
    house_vote = (house_popular_vote_gauge(house_parameters)
                  if house_parameters and forecast and
                  house_parameters['metadata']['information_cutoff_utc'] ==
                  forecast['metadata']['information_cutoff_utc'] else None)
    governor_seats = governor_projected_seats(forecast) if forecast else None
    governor_states = governor_map_states(forecast) if forecast else []
    governor_close = governor_close_races(forecast, governor_states) if forecast else []
    return render_template('us2026.html', updated_at=updated_at, updated_iso=updated_iso,
                           css_version=US2026_CSS_PATH.stat().st_mtime_ns,
                           history_dates=history_dates, selected_index=selected_index,
                           senate_seats=senate_seats, senate_tipping=senate_tipping,
                           senate_control=senate_control,
                           senate_seat_projection=senate_seat_projection,
                           senate_states=senate_states,
                           senate_keys=senate_keys, senate_extremes=senate_extremes,
                           senate_distribution=senate_distribution,
                           house_control=house_control, house_vote=house_vote,
                           house_distribution=house_distribution,
                           house_seat_projection=house_seat_projection,
                           house_districts=house_districts, house_close=house_close,
                           house_competitive=house_competitive,
                           house_state_outlines=STATE_MAP['states'],
                           house_cartogram=house_cartogram,
                           governor_seats=governor_seats, governor_states=governor_states,
                           governor_close=governor_close)

@server.route('/redirect-to-us2024')
def redirect_to_us2024():
    return redirect('/old/us2024')

server.wsgi_app = DispatcherMiddleware(server.wsgi_app, {
    "/old/us2024": us2024server 
})
