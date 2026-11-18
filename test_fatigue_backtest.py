"""Read-only sensitivity test of NHL back-to-back adjustments on frozen V2 picks.

This is exploratory, in-sample analysis; it does not establish a betting edge.
"""
import math
import os
from collections import defaultdict
from datetime import date

from supabase import create_client
from engine import STATS, TEAM_CODES, get_json, season_for
from win_probability import calculate_win_probabilities
from over_under_probability import calculate_total_probabilities

MODEL = 'v2_recent5_w20'
SNAPSHOT = 'FINAL PREGAME'
LINES = (5.5, 6.0, 6.5)
# Fixed candidate shifts in expected goals; no adjustment if neither team is on B2B.
# Fatigued team loses 'attack' goals and allows 'defense' goals to its opponent.
CANDIDATES = [(0.0, 0.0), (0.05, 0.05), (0.10, 0.10), (0.10, 0.05)]


def fetch_all(table, columns, filters=()):
    client = fetch_all.client
    output = []
    offset = 0
    while True:
        query = client.table(table).select(columns)
        for field, value in filters:
            query = query.eq(field, value)
        batch = query.range(offset, offset + 999).execute().data or []
        output.extend(batch)
        if len(batch) < 1000:
            return output
        offset += len(batch)


def fetch_team_game_records(season):
    output, offset = [], 0
    while True:
        response = get_json(f'{STATS}/team/summary', {
            'isAggregate': 'false', 'isGame': 'true',
            'cayenneExp': f'gameTypeId=2 and seasonId={season}',
            'start': offset, 'limit': 100,
        })
        batch = response.get('data', [])
        if not batch:
            break
        output.extend(batch)
        offset += len(batch)
        if offset >= int(response.get('total') or 0):
            break
    return output


def rest_by_game(records):
    """Rest for each team/game, calculated only from earlier game dates."""
    by_team = defaultdict(list)
    for r in records:
        team = TEAM_CODES.get(r.get('teamFullName'))
        game_id = r.get('gameId')
        day = str(r.get('gameDate') or '')[:10]
        if not team or not game_id or len(day) != 10:
            continue
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        by_team[team].append((d, str(game_id)))
    lookup = {}
    for team, entries in by_team.items():
        # A team cannot legitimately play twice on the same calendar date.
        entries = sorted(set(entries))
        previous = None
        for d, gid in entries:
            rest = (d - previous).days - 1 if previous is not None else None
            lookup[(gid, team)] = rest
            previous = d
    return lookup


def brier(prob, outcome):
    return (prob - outcome) ** 2


def summarize(rows):
    n = len(rows)
    if not n:
        return 'n=0'
    return (f'n={n}, winner_accuracy={sum(r["correct"] for r in rows)/n:.2%}, '
            f'Brier={sum(r["brier"] for r in rows)/n:.6f}, '
            f'total_MAE={sum(r["mae"] for r in rows)/n:.4f}, '
            f'avg_total_bias={sum(r["bias"] for r in rows)/n:+.4f}')


def main():
    url = os.environ['SUPABASE_URL']
    key = os.environ['SUPABASE_KEY']
    fetch_all.client = create_client(url, key)
    predictions = fetch_all('predictions',
        'game_id,game_date,away_team,home_team,away_projected_goals,home_projected_goals,saved_at',
        [('model_version', MODEL), ('snapshot_type', SNAPSHOT)])
    results = fetch_all('game_results', 'game_id,away_goals,home_goals,actual_total')
    results_by_id = {str(r['game_id']): r for r in results}
    seasons = {season_for(str(p['game_date'])) for p in predictions if p.get('game_date')}
    records = []
    for season in sorted(seasons):
        records.extend(fetch_team_game_records(season))
    rest = rest_by_game(records)
    evaluated = {c: [] for c in CANDIDATES}
    buckets = defaultdict(lambda: {c: [] for c in CANDIDATES})
    excluded = defaultdict(int)
    for p in predictions:
        gid = str(p['game_id'])
        actual = results_by_id.get(gid)
        if not actual:
            excluded['no final result'] += 1
            continue
        away, home = p['away_team'], p['home_team']
        ar, hr = rest.get((gid, away)), rest.get((gid, home))
        if ar is None or hr is None:
            excluded['rest unknown (e.g. first season game)'] += 1
            continue
        try:
            ag, hg = float(p['away_projected_goals']), float(p['home_projected_goals'])
            a_actual, h_actual = int(actual['away_goals']), int(actual['home_goals'])
            if min(ag, hg) < 0 or not all(map(math.isfinite, (ag, hg))):
                raise ValueError('invalid xG')
        except (TypeError, ValueError):
            excluded['invalid goals'] += 1
            continue
        # NHL official final scores include OT winner, and shootout result as +1 goal.
        # For totals this may differ from sportsbook grading in shootouts; total MAE is diagnostic only.
        actual_total = a_actual + h_actual
        actual_home_win = int(h_actual > a_actual)
        if a_actual == h_actual:
            excluded['tied final score'] += 1
            continue
        away_b2b, home_b2b = ar == 0, hr == 0
        bucket = ('away B2B only' if away_b2b and not home_b2b else
                  'home B2B only' if home_b2b and not away_b2b else
                  'both B2B' if home_b2b and away_b2b else 'neither B2B')
        for candidate in CANDIDATES:
            attack, defense = candidate
            adjusted_away = max(0.01, ag - attack * away_b2b + defense * home_b2b)
            adjusted_home = max(0.01, hg - attack * home_b2b + defense * away_b2b)
            probs = calculate_win_probabilities(adjusted_away, adjusted_home, away, home)
            home_prob = probs['home_win_probability']
            record = {
                'correct': int((home_prob > 0.5) == bool(actual_home_win)) if home_prob != 0.5 else 0.5,
                'brier': brier(home_prob, actual_home_win),
                'mae': abs(adjusted_away + adjusted_home - actual_total),
                'bias': adjusted_away + adjusted_home - actual_total,
            }
            evaluated[candidate].append(record)
            buckets[bucket][candidate].append(record)
    print(f'Frozen {MODEL} / {SNAPSHOT}: {len(predictions)} rows')
    print(f'Eligible matched games with known rest: {len(evaluated[CANDIDATES[0]])}')
    print('Excluded:', dict(excluded))
    print('Adjustment units: (fatigued attack reduction, opponent scoring increase)')
    print('NOTE: exploratory same-sample comparison, not an out-of-sample validation.')
    print('NOTE: this tests winner Brier and total MAE, NOT market-line betting profitability.')
    for c in CANDIDATES:
        print(f'Candidate {c}: {summarize(evaluated[c])}')
    for bucket in ('away B2B only', 'home B2B only', 'both B2B', 'neither B2B'):
        print(f'\n{bucket}:')
        for c in CANDIDATES:
            print(f'  {c}: {summarize(buckets[bucket][c])}')
    if not evaluated[CANDIDATES[0]]:
        raise RuntimeError('No eligible matched games: inspect team code mapping, API and database data')
    print('\nREAD-ONLY FATIGUE BACKTEST COMPLETE; NO SUPABASE WRITES')


if __name__ == '__main__':
    main()
