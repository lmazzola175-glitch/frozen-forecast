"""Frozen Forecast V3 fatigue challenger (live, read-only, experimental).

Wraps the current V3 baseline. Applies a +/-0.10 xG shift only for a
team on the second night of a back-to-back, then recalculates winners and
5.5/6/6.5 totals. Does NOT write snapshots or change baseline engines.
The shift was selected on historical data and is NOT independently validated.
"""
from collections import defaultdict
from datetime import date as Date
import math

from engine import STATS, TEAM_CODES, get_json, season_for
from engine_v3 import build_projections as build_baseline
from win_probability import calculate_win_probabilities
from over_under_probability import calculate_total_probabilities

MODEL_VERSION = 'v3_fatigue_experiment'
ATTACK_PENALTY = 0.10
OPPONENT_BONUS = 0.10
LINES = (5.5, 6.0, 6.5)


def previous_game_dates(target_date):
    """Latest known completed regular-season game before target date per team."""
    target = Date.fromisoformat(str(target_date)[:10])
    season = season_for(target.isoformat())
    last = {}
    offset = 0
    while True:
        response = get_json(f'{STATS}/team/summary', {
            'isAggregate': 'false', 'isGame': 'true',
            'cayenneExp': f'gameTypeId=2 and seasonId={season}',
            'start': offset, 'limit': 100,
        })
        batch = response.get('data', [])
        if not batch:
            break
        for record in batch:
            code = TEAM_CODES.get(record.get('teamFullName'))
            raw_day = str(record.get('gameDate') or '')[:10]
            if not code or not raw_day or record.get('goalsFor') is None:
                continue
            try:
                day = Date.fromisoformat(raw_day)
            except ValueError:
                continue
            if day < target and (code not in last or day > last[code]):
                last[code] = day
        offset += len(batch)
        if offset >= int(response.get('total') or 0):
            break
    return last


def build_projections(date, verify=True):
    baseline, metadata = build_baseline(date, verify=verify)
    df = baseline.copy()
    metadata = dict(metadata)
    metadata['model_version'] = MODEL_VERSION
    metadata['experiment_note'] = ('In-sample-selected +/-0.10 xG back-to-back '
                                    'shift; NOT validated betting probabilities')
    if df.empty:
        return df, metadata

    last = previous_game_dates(date)
    target = Date.fromisoformat(str(date)[:10])
    missing = set()
    for index, row in df.iterrows():
        away, home = str(row['Away Code']), str(row['Home Code'])
        away_prev, home_prev = last.get(away), last.get(home)
        # Unknown history means no adjustment; never assume back-to-back.
        away_b2b = away_prev is not None and (target-away_prev).days == 1
        home_b2b = home_prev is not None and (target-home_prev).days == 1
        if away_prev is None: missing.add(away)
        if home_prev is None: missing.add(home)
        ag, hg = float(row['Away xG']), float(row['Home xG'])
        if not all(math.isfinite(x) and x >= 0 for x in (ag, hg)):
            raise ValueError('Invalid baseline projected goals')
        adj_away = max(0.01, ag - ATTACK_PENALTY*away_b2b + OPPONENT_BONUS*home_b2b)
        adj_home = max(0.01, hg - ATTACK_PENALTY*home_b2b + OPPONENT_BONUS*away_b2b)
        win = calculate_win_probabilities(adj_away, adj_home, away, home)
        totals = calculate_total_probabilities(adj_away, adj_home, lines=LINES)
        df.at[index, 'Baseline Away xG'] = ag
        df.at[index, 'Baseline Home xG'] = hg
        df.at[index, 'Away Back-to-Back'] = bool(away_b2b)
        df.at[index, 'Home Back-to-Back'] = bool(home_b2b)
        df.at[index, 'Away Rest Days'] = (target-away_prev).days-1 if away_prev else None
        df.at[index, 'Home Rest Days'] = (target-home_prev).days-1 if home_prev else None
        df.at[index, 'Away xG'] = round(adj_away, 4)
        df.at[index, 'Home xG'] = round(adj_home, 4)
        df.at[index, 'Projected Total'] = round(adj_away+adj_home, 4)
        df.at[index, 'Away Win Probability'] = win['away_win_probability']
        df.at[index, 'Home Win Probability'] = win['home_win_probability']
        df.at[index, 'Projected Winner'] = win['projected_winner']
        df.at[index, 'Winner Confidence'] = win['winner_confidence']
        df.at[index, 'Regulation Tie Probability'] = win['regulation_tie_probability']
        for line, values in totals.items():
            for kind in ('Over', 'Under', 'Push'):
                df.at[index, f'{kind} {line} Probability'] = round(values[f'{kind.lower()}_probability'], 6)
    metadata['unknown_prior_game_teams'] = sorted(missing)
    metadata['fatigue_adjusted_games'] = int((df['Away Back-to-Back'] | df['Home Back-to-Back']).sum())
    return df, metadata
