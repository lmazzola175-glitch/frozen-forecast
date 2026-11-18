"""Read-only matched-snapshot sensitivity test for a home-ice goal shift."""
import math
import os
from collections import defaultdict
from supabase import create_client
from win_probability import calculate_win_probabilities

SHIFT = 0.05
PAGE = 500


def read_all(client, table, columns):
    rows = []
    start = 0
    while True:
        batch = (client.table(table).select(columns)
                 .range(start, start + PAGE - 1).execute().data or [])
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE
    return rows


def score(predictions, results):
    n = len(predictions)
    if not n:
        return None
    brier = sum((p - y) ** 2 for p, y in zip(predictions, results)) / n
    correct = sum((p > 0.5 and y == 1) or (p < 0.5 and y == 0) for p, y in zip(predictions, results))
    ties = sum(p == 0.5 for p in predictions)
    return n, correct, ties, correct / n, brier


def main():
    url = os.environ['SUPABASE_URL']
    key = os.environ['SUPABASE_KEY']
    client = create_client(url, key)
    preds = read_all(client, 'predictions', 'game_id,model_version,snapshot_type,away_projected_goals,home_projected_goals,away_win_probability,home_win_probability,scheduled_start,saved_at')
    finals = read_all(client, 'game_results', 'game_id,away_goals,home_goals')
    actual = {str(r['game_id']): r for r in finals if r.get('game_id') is not None}
    by_game = defaultdict(list)
    for r in preds:
        if r.get('model_version') == 'v2_recent5_w20' and r.get('snapshot_type') == 'FINAL PREGAME':
            by_game[str(r['game_id'])].append(r)

    base, adjusted, outcomes = [], [], []
    skipped = defaultdict(int)
    for gid, rows in by_game.items():
        if gid not in actual:
            skipped['no final result'] += 1
            continue
        # Prefer earliest saved frozen snapshot if duplicates exist.
        r = sorted(rows, key=lambda x: str(x.get('saved_at') or ''))[0]
        try:
            a = float(r['away_projected_goals'])
            h = float(r['home_projected_goals'])
            p = float(r['home_win_probability'])
            ag = int(actual[gid]['away_goals'])
            hg = int(actual[gid]['home_goals'])
            if not all(math.isfinite(v) for v in (a, h, p)) or min(a, h) < 0 or not 0 <= p <= 1:
                raise ValueError('invalid inputs')
            if hg == ag:
                skipped['tied final score'] += 1
                continue
            if r.get('saved_at') and r.get('scheduled_start') and str(r['saved_at']) >= str(r['scheduled_start']):
                skipped['not pregame'] += 1
                continue
            adjusted_probs = calculate_win_probabilities(max(0, a - SHIFT), h + SHIFT, 'AWAY', 'HOME')
            base.append(p)
            adjusted.append(adjusted_probs['home_win_probability'])
            outcomes.append(int(hg > ag))
        except (TypeError, ValueError, KeyError):
            skipped['invalid row'] += 1

    print('Matched FINAL PREGAME V2 games:', len(outcomes))
    print('Skipped:', dict(skipped))
    if not outcomes:
        raise RuntimeError('No matched predictions and results found')
    for label, values in [('Frozen V2', base), ('Home-ice shift (+0.05 home, -0.05 away)', adjusted)]:
        n, correct, ties, accuracy, brier = score(values, outcomes)
        print(f'{label}: games={n}, correct={correct}, tossups={ties}, accuracy={accuracy:.2%}, Brier={brier:.6f}')
    print('Brier change (adjusted minus baseline):', f'{score(adjusted, outcomes)[4] - score(base, outcomes)[4]:+.6f}')
    print('READ-ONLY SENSITIVITY TEST COMPLETE; NO SUPABASE WRITES')


if __name__ == '__main__':
    main()
