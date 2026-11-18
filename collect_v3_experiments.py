"""Frozen Forecast V3 challenger snapshot preparation (READ ONLY).

Runs V3 baseline, fatigue, and scaled-totals engines independently.
Uses the production collector's exact pregame eligibility and winner checks.
Prints proposed records but NEVER writes to Supabase. Next phase will verify
Supabase schema and design versioned probability storage before enabling writes.
"""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

from collect_predictions import collect_eligible_predictions
from engine_v3 import build_projections as baseline
from engine_v3_fatigue_experiment import build_projections as fatigue
from engine_v3_totals_experiment import build_projections as scaled

ET = ZoneInfo('America/New_York')
BUILDERS = {
    'v3_dual_market_baseline': baseline,
    'v3_fatigue_experiment': fatigue,
    'v3_totals_scaled105_experiment': scaled,
}
LINES = (5.5, 6.0, 6.5)


def validate_totals(row):
    """Check challenger probabilities, including push handling."""
    for line in LINES:
        values = [float(row[f'{side} {line} Probability']) for side in ('Over', 'Under', 'Push')]
        if any(not (0 <= v <= 1) for v in values):
            raise ValueError(f'Invalid probabilities at {line}: {values}')
        if abs(sum(values) - 1) > 0.00001:
            raise ValueError(f'Probabilities do not sum to one at {line}: {values}')
        if line != 6.0 and values[2] > 0.000001:
            raise ValueError(f'Unexpected push at {line}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('early', 'final'), default='early')
    parser.add_argument('--date', help='Eastern date YYYY-MM-DD; default today')
    args = parser.parse_args()
    game_date = args.date or datetime.now(ET).date().isoformat()
    snapshot = 'EARLY' if args.mode == 'early' else 'FINAL PREGAME'
    print(f'V3 CHALLENGER DRY RUN | {game_date} ET | {snapshot}')
    failures = []
    for name, build in BUILDERS.items():
        print(f'\nMODEL: {name}')
        try:
            df, metadata = build(game_date, verify=True)
            print(f'Projected games: {len(df)} | scheduled: {metadata.get("scheduled", "unknown")}')
            for _, row in df.iterrows():
                validate_totals(row)
            eligible = collect_eligible_predictions(df, name, game_date, snapshot, args.mode)
            print(f'Eligible frozen snapshots: {len(eligible)}')
            by_id = {str(row['Game ID']): row for _, row in df.iterrows()}
            for record in eligible:
                row = by_id[record['game_id']]
                probabilities = ' | '.join(
                    f'{line}: O={float(row[f"Over {line} Probability"]):.1%} '
                    f'U={float(row[f"Under {line} Probability"]):.1%} '
                    f'P={float(row[f"Push {line} Probability"]):.1%}'
                    for line in LINES
                )
                print(f'{record["away_team"]} @ {record["home_team"]} | '
                      f'total={record["projected_total"]:.2f} | '
                      f'winner={record["projected_winner"]} | {probabilities}')
            print('DRY RUN ONLY: no Supabase writes')
        except Exception as exc:
            failures.append(name)
            print(f'ERROR: {type(exc).__name__}: {exc}')
    if failures:
        raise RuntimeError(f'Failed challenger engines: {failures}')
    print('\nALL V3 CHALLENGER CHECKS PASSED — NO DATABASE WRITES')


if __name__ == '__main__':
    main()
