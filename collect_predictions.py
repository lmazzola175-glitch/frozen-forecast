
"""Frozen Forecast automated pregame snapshot collector.

Defaults to a dry run. Supports EARLY and FINAL PREGAME snapshots.
"""

import argparse
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from engine import build_projections

MODEL = "v1_goalie_adjusted"
ET = ZoneInfo("America/New_York")

FINAL_WINDOW_MINUTES = 60
MAX_CALCULATION_AGE_SECONDS = 900


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Save eligible snapshots to Supabase",
    )
    parser.add_argument(
        "--mode",
        choices=["early", "final"],
        default="early",
        help="Snapshot collection mode",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    game_date = now.astimezone(ET).date().isoformat()

    snapshot_type = (
        "EARLY" if args.mode == "early" else "FINAL PREGAME"
    )

    print("=" * 60)
    print("FROZEN FORECAST — PREGAME COLLECTOR")
    print("=" * 60)
    print(f"Date: {game_date} ET")
    print(f"Mode: {snapshot_type}")
    print(f"Operation: {'WRITE' if args.write else 'DRY RUN'}")

    df, meta = build_projections(game_date, verify=True)

    print(f"Scheduled games: {meta.get('scheduled', 0)}")
    print(f"Projected games: {len(df)}")

    eligible = []

    for _, game in df.iterrows():
        game_id = str(game["Game ID"])

        start = pd.to_datetime(
            game["Start UTC"], utc=True
        ).to_pydatetime()

        calculated = pd.to_datetime(
            game["Calculated At UTC"], utc=True
        ).to_pydatetime()

        current = datetime.now(timezone.utc)

        minutes_until_start = (
            start - current
        ).total_seconds() / 60

        calculation_age = (
            current - calculated
        ).total_seconds()

        reason = None

        if start <= current:
            reason = "game already started"

        elif calculation_age < 0 or calculation_age > MAX_CALCULATION_AGE_SECONDS:
            reason = "stale or future calculation"

        elif calculated >= start:
            reason = "calculation not pregame"

        elif str(game["Goalie Reliability"]).upper() == "BLOCKED":
            reason = "goalie verification blocked"

        elif args.mode == "early" and minutes_until_start <= FINAL_WINDOW_MINUTES:
            reason = "outside EARLY collection window"

        elif args.mode == "final" and not (
            0 < minutes_until_start <= FINAL_WINDOW_MINUTES
        ):
            reason = "outside FINAL PREGAME window"

        if reason:
            print(f"SKIP {game_id}: {reason}")
            continue

        eligible.append({
            "game_id": game_id,
            "game_date": game_date,
            "model_version": MODEL,
            "snapshot_type": snapshot_type,
            "saved_at": calculated.isoformat(),
            "scheduled_start": start.isoformat(),
            "away_team": str(game["Away Code"]),
            "home_team": str(game["Home Code"]),
            "away_projected_goals": float(game["Away xG"]),
            "home_projected_goals": float(game["Home xG"]),
            "projected_total": float(game["Projected Total"]),
            "away_goalie": str(game["Away Goalie"]),
            "home_goalie": str(game["Home Goalie"]),
            "goalie_reliability": str(game["Goalie Reliability"]),
        })

    print(f"Eligible {snapshot_type} snapshots: {len(eligible)}")

    for item in eligible:
        print(
            f"{item['away_team']} @ {item['home_team']} "
            f"| {item['projected_total']:.2f} "
            f"| {item['game_id']}"
        )

    if not args.write:
        print("DRY RUN COMPLETE: no database writes performed.")
        return

    if not eligible:
        print("Nothing to save.")
        return

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_KEY secrets"
        )

    client = create_client(url, key)

    ids = [record["game_id"] for record in eligible]

    response = (
        client.table("predictions")
        .select("game_id")
        .eq("model_version", MODEL)
        .eq("snapshot_type", snapshot_type)
        .in_("game_id", ids)
        .execute()
    )

    existing = {
        str(record["game_id"])
        for record in (response.data or [])
    }

    saved = 0
    skipped = 0

    for record in eligible:
        if record["game_id"] in existing:
            skipped += 1
            continue

        current = datetime.now(timezone.utc)

        start = pd.to_datetime(
            record["scheduled_start"], utc=True
        ).to_pydatetime()

        minutes_until_start = (
            start - current
        ).total_seconds() / 60

        if minutes_until_start <= 0:
            print(
                f"SKIP {record['game_id']}: "
                "puck drop reached before insertion"
            )
            skipped += 1
            continue

        if args.mode == "early" and minutes_until_start <= FINAL_WINDOW_MINUTES:
            print(
                f"SKIP {record['game_id']}: "
                "EARLY window closed before insertion"
            )
            skipped += 1
            continue

        if args.mode == "final" and minutes_until_start > FINAL_WINDOW_MINUTES:
            print(
                f"SKIP {record['game_id']}: "
                "FINAL window not yet open"
            )
            skipped += 1
            continue

        try:
            client.table("predictions").insert(record).execute()
            saved += 1

        except Exception as exc:
            message = str(exc).lower()

            if "23505" in message or "duplicate key" in message:
                skipped += 1
            else:
                raise RuntimeError(
                    f"Database insert failed for game "
                    f"{record['game_id']}"
                ) from exc

    print("=" * 60)
    print(
        f"WRITE COMPLETE: saved={saved}, "
        f"already present/skipped={skipped}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()

