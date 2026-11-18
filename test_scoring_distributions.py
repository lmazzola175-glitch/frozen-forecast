"""Frozen Forecast: read-only, chronological scoring-distribution experiment.

Compare the existing Poisson proxy, a training-fitted Poisson mean scale,
and a training-fitted negative-binomial dispersion. All observations are
frozen V2 FINAL PREGAME predictions joined to verified NHL final results.
No sportsbook prices are available; these are hypothetical fixed lines.
"""
import math
import os
from collections import Counter
from datetime import datetime

import requests
from supabase import create_client

MODEL = 'v2_recent5_w20'
SNAPSHOT = 'FINAL PREGAME'
SCORE_API = 'https://api-web.nhle.com/v1/score/'
TRAIN_FRACTION = 0.70
MIN_GAMES = 40
# Small, deliberately prespecified candidate grids to limit overfitting.
SCALES = (0.90, 0.95, 1.00, 1.05, 1.10, 1.15)
NB_DISPERSIONS = (4.0, 8.0, 16.0, 32.0, 64.0, 128.0)


def fetch_all(client, table, fields, filters=()):
    rows = []
    start = 0
    while True:
        q = client.table(table).select(fields)
        for key, value in filters:
            q = q.eq(key, value)
        batch = q.range(start, start + 999).execute().data or []
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        start += len(batch)


def fetch_outcome_types(dates):
    types = {}
    for day in sorted(dates):
        response = requests.get(SCORE_API + day, timeout=30)
        response.raise_for_status()
        for game in response.json().get('games', []):
            if game.get('gameState') != 'OFF':
                continue
            kind = (game.get('gameOutcome') or {}).get('lastPeriodType')
            if kind in ('REG', 'OT', 'SO'):
                types[str(game['id'])] = kind
    return types


def total_distribution(mean, kind='poisson', dispersion=None, max_goals=6):
    """Probabilities for 0..6 goals; remaining probability is the >=7 tail."""
    if not math.isfinite(mean) or mean < 0:
        raise ValueError('Invalid mean')
    if kind == 'poisson':
        p = math.exp(-mean)
        values = [p]
        for k in range(1, max_goals + 1):
            p = p * mean / k
            values.append(p)
    elif kind == 'negative_binomial':
        r = float(dispersion)
        if not math.isfinite(r) or r <= 0:
            raise ValueError('Invalid dispersion')
        p = (r / (r + mean)) ** r
        values = [p]
        for k in range(1, max_goals + 1):
            p = p * (k - 1 + r) / k * mean / (r + mean)
            values.append(p)
    else:
        raise ValueError('Unknown distribution')
    tail = max(0.0, 1.0 - sum(values))
    return values + [tail]


def probabilities(lam, model, parameter=None):
    if model == 'Baseline Poisson':
        p = total_distribution(lam)
    elif model == 'Scaled Poisson':
        p = total_distribution(lam * parameter)
    elif model == 'Negative binomial':
        p = total_distribution(lam, 'negative_binomial', parameter)
    else:
        raise ValueError('Unknown model')
    # 5.5: <=5 or >=6; 6.0: <=5, exactly 6, >=7; 6.5: <=6 or >=7.
    under5 = sum(p[:6])
    six = p[6]
    over6 = p[7]
    return {
        '5.5': (under5, six + over6),
        '6.0': (under5, six, over6),
        '6.5': (under5 + six, over6),
    }


def outcome_index(total, line):
    if line == '5.5':
        return int(total >= 6)
    if line == '6.0':
        return 0 if total <= 5 else 1 if total == 6 else 2
    return int(total >= 7)


def evaluate(rows, model, parameter=None):
    scores = {'5.5': [], '6.0': [], '6.5': []}
    frequency = {'5.5': [0.0, 0.0], '6.0': [0.0, 0.0, 0.0], '6.5': [0.0, 0.0]}
    observed = {key: [0.0] * len(vals) for key, vals in frequency.items()}
    for row in rows:
        pp = probabilities(row['lambda'], model, parameter)
        for line, vector in pp.items():
            idx = outcome_index(row['total'], line)
            scores[line].append(sum((p - (i == idx)) ** 2 for i, p in enumerate(vector)))
            for i, p in enumerate(vector):
                frequency[line][i] += p
            observed[line][idx] += 1
    n = len(rows)
    return {
        'score': sum(sum(scores[line]) for line in scores) / n / 3,
        'brier': {line: sum(scores[line]) / n for line in scores},
        'predicted': {line: [v / n for v in frequency[line]] for line in frequency},
        'observed': {line: [v / n for v in observed[line]] for line in observed},
    }


def load_games():
    client = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
    predictions = fetch_all(client, 'predictions',
        'game_id,game_date,away_projected_goals,home_projected_goals,saved_at',
        [('model_version', MODEL), ('snapshot_type', SNAPSHOT)])
    results = fetch_all(client, 'game_results',
        'game_id,away_goals,home_goals,actual_total')
    results_by_id = {str(row['game_id']): row for row in results}
    # If duplicate snapshot rows exist, retain earliest saved frozen projection.
    predictions.sort(key=lambda x: (str(x.get('saved_at') or ''), str(x.get('game_id'))))
    unique = {}
    for p in predictions:
        unique.setdefault(str(p['game_id']), p)
    matched = [p for p in unique.values() if str(p['game_id']) in results_by_id]
    kinds = fetch_outcome_types({str(p['game_date'])[:10] for p in matched})
    exclusions = Counter()
    games = []
    for p in matched:
        gid = str(p['game_id'])
        kind = kinds.get(gid)
        if kind is None:
            exclusions['unverified final period'] += 1
            continue
        try:
            lam = float(p['away_projected_goals']) + float(p['home_projected_goals'])
            actual = results_by_id[gid]
            total = int(actual['away_goals']) + int(actual['home_goals']) - int(kind == 'SO')
            day = str(p['game_date'])[:10]
            datetime.strptime(day, '%Y-%m-%d')
            if not math.isfinite(lam) or lam < 0 or total < 0:
                raise ValueError('invalid values')
        except (TypeError, ValueError, KeyError):
            exclusions['invalid record'] += 1
            continue
        games.append({'game_id': gid, 'date': day, 'lambda': lam, 'total': total, 'period': kind})
    games.sort(key=lambda x: (x['date'], x['game_id']))
    print(f'Frozen {MODEL} / {SNAPSHOT}: {len(predictions)} rows, '
          f'{len(unique)} unique game IDs, {len(matched)} matched completed games')
    print('Verified usable games:', len(games), 'Excluded:', dict(exclusions))
    return games


def main():
    games = load_games()
    if len(games) < MIN_GAMES:
        raise RuntimeError(f'Need at least {MIN_GAMES} games for chronological comparison')
    # Keep all games on the same date in the same partition.
    cutoff_idx = int(len(games) * TRAIN_FRACTION)
    cutoff_day = games[cutoff_idx]['date']
    train = [g for g in games if g['date'] < cutoff_day]
    test = [g for g in games if g['date'] >= cutoff_day]
    if len(train) < 20 or len(test) < 10:
        raise RuntimeError('Not enough games on both sides of chronological split')
    print(f'TRAIN: {len(train)} games, {train[0]["date"]} to {train[-1]["date"]}')
    print(f'TEST:  {len(test)} games, {test[0]["date"]} to {test[-1]["date"]}')
    print('No test outcomes used to select parameters.')

    candidates = [('Baseline Poisson', None)]
    for model, grid in [('Scaled Poisson', SCALES), ('Negative binomial', NB_DISPERSIONS)]:
        best = min(grid, key=lambda p: evaluate(train, model, p)['score'])
        candidates.append((model, best))
    print('\nMean multiclass Brier across 5.5, 6.0, 6.5 (LOWER IS BETTER).')
    print('Note: 5.5 and 6.5 are binary Brier; 6.0 is three-class Brier.')
    print('Lines overlap; this composite is a diagnostic, not three independent markets.')
    for model, param in candidates:
        training = evaluate(train, model, param)
        heldout = evaluate(test, model, param)
        print(f'\n{model}: parameter={param}, TRAIN score={training["score"]:.5f}, '
              f'TEST score={heldout["score"]:.5f}')
        for line in ('5.5', '6.0', '6.5'):
            labels = ('UNDER', 'OVER') if line != '6.0' else ('UNDER', 'PUSH', 'OVER')
            pred = heldout['predicted'][line]
            obs = heldout['observed'][line]
            print(f'  TEST line {line}: Brier={heldout["brier"][line]:.5f} | ' +
                  ' | '.join(f'{label} predicted={p:.1%}, observed={o:.1%}'
                           for label, p, o in zip(labels, pred, obs)))
    print('\nREAD-ONLY DISTRIBUTION COMPARISON COMPLETE — NO SUPABASE WRITES')
    print('WARNING: 89 games is a small sample; this split is exploratory and noisy.')
    print('Historical market odds/lines were not saved. No ROI or betting edge is measured.')
    print('Baseline xG is regulation-oriented; outcomes are full game incl. OT, excluding SO deciding goal.')
    print('Do not deploy a fitted distribution without additional future frozen-game validation.')


if __name__ == '__main__':
    main()
