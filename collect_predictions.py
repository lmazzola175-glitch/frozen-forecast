"""Frozen Forecast pregame snapshot collector. Defaults to dry-run."""
import argparse
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from engine import build_projections

MODEL = 'v1_goalie_adjusted'
ET = ZoneInfo('America/New_York')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true', help='Actually insert new snapshots')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    game_date = now.astimezone(ET).date().isoformat()
    print(f'Frozen Forecast collector | {game_date} ET | {"WRITE" if args.write else "DRY RUN"}', flush=True)
    df, meta = build_projections(game_date, verify=True)
    print(f'Scheduled: {meta.get("scheduled", 0)} | Projected: {len(df)}')
    eligible = []
    for _, game in df.iterrows():
        game_id = str(game['Game ID'])
        start = pd.to_datetime(game['Start UTC'], utc=True).to_pydatetime()
        calculated = pd.to_datetime(game['Calculated At UTC'], utc=True).to_pydatetime()
        current = datetime.now(timezone.utc)
        reason = None
        if start <= current:
            reason = 'game already started'
        elif calculated > current or (current - calculated).total_seconds() > 900:
            reason = 'stale/future calculation'
        elif calculated >= start:
            reason = 'not a pregame calculation'
        elif str(game['Goalie Reliability']).upper() == 'BLOCKED':
            reason = 'goalie roster verification blocked'
        if reason:
            print(f'SKIP {game_id}: {reason}')
            continue
        eligible.append({
            'game_id': game_id,
            'game_date': game_date,
            'model_version': MODEL,
            'snapshot_type': 'EARLY',
            'saved_at': calculated.isoformat(),
            'scheduled_start': start.isoformat(),
            'away_team': str(game['Away Code']),
            'home_team': str(game['Home Code']),
            'away_projected_goals': float(game['Away xG']),
            'home_projected_goals': float(game['Home xG']),
            'projected_total': float(game['Projected Total']),
            'away_goalie': str(game['Away Goalie']),
            'home_goalie': str(game['Home Goalie']),
            'goalie_reliability': str(game['Goalie Reliability']),
        })
    print(f'Eligible pregame snapshots: {len(eligible)}')
    for item in eligible:
        print(f"  {item['away_team']} @ {item['home_team']} | {item['projected_total']:.2f} | {item['game_id']}")
    if not args.write:
        print('DRY RUN COMPLETE: no database writes performed.')
        return
    if not eligible:
        print('Nothing to save.')
        return
    from supabase import create_client
    url = os.environ.get('SUPABASE_URL')
    key = os.environ.get('SUPABASE_KEY')
    if not url or not key:
        raise RuntimeError('Missing SUPABASE_URL or SUPABASE_KEY GitHub Actions secrets')
    client = create_client(url, key)
    ids = [r['game_id'] for r in eligible]
    response = (client.table('predictions').select('game_id')
                .eq('model_version', MODEL).eq('snapshot_type', 'EARLY')
                .in_('game_id', ids).execute())
    existing = {str(r['game_id']) for r in (response.data or [])}
    saved = skipped = 0
    for record in eligible:
        if record['game_id'] in existing:
            skipped += 1
            continue
        # Recheck start immediately before the write.
        if pd.to_datetime(record['scheduled_start'], utc=True).to_pydatetime() <= datetime.now(timezone.utc):
            print(f"SKIP {record['game_id']}: puck drop reached before insertion")
            skipped += 1
            continue
        try:
            client.table('predictions').insert(record).execute()
            saved += 1
        except Exception as exc:
            if '23505' in str(exc) or 'duplicate key' in str(exc).lower():
                skipped += 1
            else:
                raise RuntimeError(f"Database insert failed for game {record['game_id']}") from exc
    print(f'WRITE COMPLETE: saved={saved}, already present/skipped={skipped}')


if __name__ == '__main__':
    main()
