"""Frozen Forecast: read-only diagnostic for NHL full-game total probabilities.

Uses frozen V2 FINAL PREGAME snapshots. Excludes games whose official scoring
period cannot be verified, and corrects shootout deciding goals for totals.
This is exploratory IN-SAMPLE analysis, not a betting profitability test.
"""
import math
import os
from collections import defaultdict
from datetime import datetime

import requests
from supabase import create_client
from over_under_probability import calculate_total_probabilities

MODEL = 'v2_recent5_w20'
SNAPSHOT = 'FINAL PREGAME'
LINES = (5.5, 6.0, 6.5)
NHL_SCORE = 'https://api-web.nhle.com/v1/score/'


def fetch_all(client, table, fields, filters=()):
    rows = []
    offset = 0
    while True:
        query = client.table(table).select(fields)
        for field, value in filters:
            query = query.eq(field, value)
        batch = query.range(offset, offset + 999).execute().data or []
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += len(batch)


def outcome_types(dates):
    """Read official period type from NHL scoreboard, grouped by game date."""
    outcomes = {}
    for day in sorted(dates):
        try:
            response = requests.get(NHL_SCORE + day, timeout=30)
            response.raise_for_status()
            for game in response.json().get('games', []):
                if game.get('gameState') != 'OFF':
                    continue
                game_outcome = game.get('gameOutcome') or {}
                kind = game_outcome.get('lastPeriodType')
                if kind in ('REG', 'OT', 'SO'):
                    outcomes[str(game['id'])] = kind
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f'WARNING: unable to verify outcome types for {day}: {exc}')
    return outcomes


def metrics(values):
    if not values:
        return 'n=0'
    n = len(values)
    avg = lambda field: sum(v[field] for v in values) / n
    return (f'n={n}, predicted={avg("pred"):.3%}, observed={avg("obs"):.3%}, '
            f'gap={avg("pred") - avg("obs"):+.3%}, '
            f'Brier={avg("brier"):.5f}')


def main():
    client = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
    predictions = fetch_all(client, 'predictions',
        'game_id,game_date,away_projected_goals,home_projected_goals,saved_at',
        [('model_version', MODEL), ('snapshot_type', SNAPSHOT)])
    results = fetch_all(client, 'game_results',
        'game_id,away_goals,home_goals,actual_total')
    results_by_id = {str(row['game_id']): row for row in results}
    completed = [p for p in predictions if str(p['game_id']) in results_by_id]
    kinds = outcome_types({str(p['game_date'])[:10] for p in completed})

    data = defaultdict(list)
    diagnostics = defaultdict(list)
    exclusions = defaultdict(int)
    included = 0
    for p in completed:
        gid = str(p['game_id'])
        actual = results_by_id[gid]
        kind = kinds.get(gid)
        if kind is None:
            exclusions['unverified period type / not OFF'] += 1
            continue
        try:
            away_xg = float(p['away_projected_goals'])
            home_xg = float(p['home_projected_goals'])
            away_goals = int(actual['away_goals'])
            home_goals = int(actual['home_goals'])
            if not all(math.isfinite(x) and x >= 0 for x in (away_xg, home_xg)):
                raise ValueError('invalid xG')
        except (ValueError, TypeError):
            exclusions['invalid data'] += 1
            continue
        # NHL scoreboard final scores include a deciding shootout goal, but
        # sportsbooks do not count that goal toward full-game totals.
        total = away_goals + home_goals - (1 if kind == 'SO' else 0)
        if total < 0:
            exclusions['invalid final total'] += 1
            continue
        lam = away_xg + home_xg
        probs = calculate_total_probabilities(away_xg, home_xg, LINES)
        diagnostics['total'].append({'bias': lam - total, 'ae': abs(lam - total)})
        diagnostics['period_' + kind].append({'bias': lam - total, 'ae': abs(lam - total)})
        included += 1
        for line in LINES:
            values = probs[line]
            outcome = ('over' if total > line else 'under' if total < line else 'push')
            # Three-category multiclass Brier for 6.0, binary for half-lines.
            multi_brier = sum((values[k + '_probability'] - int(outcome == k)) ** 2
                              for k in ('over', 'under', 'push'))
            diagnostics[f'{line}_multibrier'].append(multi_brier)
            for side in ('over', 'under', 'push'):
                if side == 'push' and not float(line).is_integer():
                    continue
                pred = values[side + '_probability']
                obs = int(outcome == side)
                data[(line, side)].append({
                    'pred': pred, 'obs': obs, 'brier': (pred - obs) ** 2,
                })

    print(f'Frozen {MODEL} / {SNAPSHOT}: {len(predictions)} rows')
    print(f'Completed matched games: {len(completed)}')
    print(f'Officially verified and graded: {included}')
    print(f'Excluded: {dict(exclusions)}')
    if not included:
        raise RuntimeError('No verified games; inspect NHL outcome type and Supabase rows')
    for category in ('total', 'period_REG', 'period_OT', 'period_SO'):
        rows = diagnostics[category]
        if rows:
            print(f'{category}: n={len(rows)}, MAE={sum(r["ae"] for r in rows)/len(rows):.4f}, '
                  f'bias={sum(r["bias"] for r in rows)/len(rows):+.4f}')
    for line in LINES:
        print(f'\nLINE {line:.1f}')
        for side in ('over', 'under', 'push'):
            if side == 'push' and not line.is_integer():
                continue
            print(f'  {side.upper()}: {metrics(data[(line, side)])}')
        mb = diagnostics[f'{line}_multibrier']
        print(f'  multiclass Brier (sum of squared class errors): {sum(mb)/len(mb):.5f}')
    print('\nNOTES: Same completed games used for all lines. Pushes at 6.0 are a separate outcome.')
    print('No odds/market lines were stored: these are hypothetical fixed-line calibration diagnostics, NOT ROI.')
    print('Poisson uses regulation xG; full-game totals include overtime, exclude shootout deciding goal.')
    print('Do not fit and claim validation on this same sample. Future frozen games are needed.')
    print('READ-ONLY CALIBRATION DIAGNOSTIC COMPLETE; NO SUPABASE WRITES')


if __name__ == '__main__':
    main()
