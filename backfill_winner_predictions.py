
"""Frozen Forecast — Historical Winner Prediction Backfill.

Reconstructs win probabilities from original frozen goal projections.

Safety:
- Dry run by default
- Only updates winner-related columns
- Never recalculates goal projections
- Never changes saved_at or snapshot timestamps
- Skips existing winner predictions
- Targets November 5, 2026 EARLY snapshots by default
"""

import argparse
import math
import os
from collections import Counter

from supabase import create_client

from win_probability import calculate_win_probabilities


WINNER_COLUMNS = (
    "projected_winner",
    "away_win_probability",
    "home_win_probability",
    "winner_confidence",
)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        default="2026-11-05",
        help="Game date to backfill",
    )

    parser.add_argument(
        "--snapshot",
        default="EARLY",
        choices=["EARLY", "FINAL PREGAME"],
    )

    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually update Supabase; otherwise dry run",
    )

    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY are required."
        )

    client = create_client(url, key)

    print("=" * 65)
    print("FROZEN FORECAST — WINNER BACKFILL")
    print("=" * 65)
    print("Date:", args.date)
    print("Snapshot:", args.snapshot)
    print("Mode:", "WRITE" if args.write else "DRY RUN")

    response = (
        client.table("predictions")
        .select(
            "game_id,game_date,model_version,snapshot_type,"
            "away_team,home_team,"
            "away_projected_goals,home_projected_goals,"
            "projected_winner,away_win_probability,"
            "home_win_probability,winner_confidence"
        )
        .eq("game_date", args.date)
        .eq("snapshot_type", args.snapshot)
        .execute()
    )

    rows = response.data or []

    print("Rows found:", len(rows))

    if not rows:
        print("Nothing to backfill.")
        return

    counts = Counter()
    prepared = []

    for row in rows:
        model = row["model_version"]

        existing = [
            row.get(column)
            for column in WINNER_COLUMNS
        ]

        # Do not overwrite any existing winner data.
        if any(value is not None for value in existing):
            counts[(model, "already populated")] += 1
            continue

        away_goals = row.get("away_projected_goals")
        home_goals = row.get("home_projected_goals")

        if away_goals is None or home_goals is None:
            counts[(model, "missing goal projections")] += 1
            continue

        away_goals = float(away_goals)
        home_goals = float(home_goals)

        if not (
            math.isfinite(away_goals)
            and math.isfinite(home_goals)
            and away_goals >= 0
            and home_goals >= 0
        ):
            counts[(model, "invalid goal projections")] += 1
            continue

        result = calculate_win_probabilities(
            away_expected_goals=away_goals,
            home_expected_goals=home_goals,
            away_team=row["away_team"],
            home_team=row["home_team"],
        )

        update = {
            column: result[column]
            for column in WINNER_COLUMNS
        }

        prepared.append((row, update))
        counts[(model, "prepared")] += 1

        print(
            f"{model} | "
            f"{row['away_team']} @ {row['home_team']} | "
            f"Winner: {update['projected_winner']} | "
            f"Away: {update['away_win_probability']:.1%} | "
            f"Home: {update['home_win_probability']:.1%}"
        )

    print("\nPrepared updates:", len(prepared))

    if not args.write:
        print("DRY RUN COMPLETE — no database changes.")
        return

    saved = 0

    for row, update in prepared:
        # Match the exact original frozen snapshot.
        # NULL filters ensure existing winner data is not overwritten.
        query = (
            client.table("predictions")
            .update(update)
            .eq("game_id", row["game_id"])
            .eq("model_version", row["model_version"])
            .eq("snapshot_type", row["snapshot_type"])
            .eq("game_date", row["game_date"])
            .is_("projected_winner", "null")
            .is_("away_win_probability", "null")
            .is_("home_win_probability", "null")
            .is_("winner_confidence", "null")
        )

        result = query.execute()

        changed = len(result.data or [])

        if changed > 1:
            raise RuntimeError(
                "Unexpected multiple rows updated for "
                f"{row['game_id']} / {row['model_version']}"
            )

        saved += changed

    print("=" * 65)
    print("BACKFILL COMPLETE")
    print("Updated rows:", saved)
    print("Prepared rows:", len(prepared))
    print("=" * 65)


if __name__ == "__main__":
    main()
