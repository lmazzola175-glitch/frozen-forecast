
"""Frozen Forecast — Automated Pregame Prediction Collector.

Supports:
    v1_goalie_adjusted
    v2_recent5_w20

Features:
- EARLY and FINAL PREGAME snapshots
- Independent model execution
- Dry-run mode by default
- Duplicate prevention
- Freshness and pregame validation
- No overwriting existing predictions
"""

import argparse
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from engine import build_projections as build_v1
from engine_v2 import build_projections as build_v2


ET = ZoneInfo("America/New_York")

FINAL_WINDOW_MINUTES = 60
MAX_CALCULATION_AGE_SECONDS = 900

MODELS = {
    "v1_goalie_adjusted": build_v1,
    "v2_recent5_w20": build_v2,
}


def collect_eligible_predictions(
    df,
    model_version,
    game_date,
    snapshot_type,
    mode,
):
    """Validate and prepare pregame predictions."""

    eligible = []

    for _, game in df.iterrows():
        game_id = str(game["Game ID"])

        start = pd.to_datetime(
            game["Start UTC"],
            utc=True,
        ).to_pydatetime()

        calculated = pd.to_datetime(
            game["Calculated At UTC"],
            utc=True,
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

        elif (
            calculation_age < 0
            or calculation_age > MAX_CALCULATION_AGE_SECONDS
        ):
            reason = "stale or future calculation"

        elif calculated >= start:
            reason = "calculation not pregame"

        elif (
            str(game["Goalie Reliability"]).upper()
            == "BLOCKED"
        ):
            reason = "goalie verification blocked"

        elif (
            mode == "early"
            and minutes_until_start <= FINAL_WINDOW_MINUTES
        ):
            reason = "outside EARLY collection window"

        elif (
            mode == "final"
            and not (
                0 < minutes_until_start <= FINAL_WINDOW_MINUTES
            )
        ):
            reason = "outside FINAL PREGAME window"

        if reason:
            print(f"SKIP {game_id}: {reason}")
            continue

        eligible.append({
            "game_id": game_id,
            "game_date": game_date,
            "model_version": model_version,
            "snapshot_type": snapshot_type,
            "saved_at": calculated.isoformat(),
            "scheduled_start": start.isoformat(),
            "away_team": str(game["Away Code"]),
            "home_team": str(game["Home Code"]),
            "away_projected_goals": float(
                game["Away xG"]
            ),
            "home_projected_goals": float(
                game["Home xG"]
            ),
            "projected_total": float(
                game["Projected Total"]
            ),
            "away_goalie": str(
                game["Away Goalie"]
            ),
            "home_goalie": str(
                game["Home Goalie"]
            ),
            "goalie_reliability": str(
                game["Goalie Reliability"]
            ),
        })

    return eligible


def save_predictions(
    client,
    eligible,
    model_version,
    snapshot_type,
    mode,
):
    """Save new predictions without overwriting history."""

    if not eligible:
        print("Nothing to save.")
        return 0, 0

    ids = [
        record["game_id"]
        for record in eligible
    ]

    response = (
        client.table("predictions")
        .select("game_id")
        .eq("model_version", model_version)
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
        game_id = record["game_id"]

        if game_id in existing:
            skipped += 1
            continue

        current = datetime.now(timezone.utc)

        start = pd.to_datetime(
            record["scheduled_start"],
            utc=True,
        ).to_pydatetime()

        minutes_until_start = (
            start - current
        ).total_seconds() / 60

        if minutes_until_start <= 0:
            print(
                f"SKIP {game_id}: puck drop reached"
            )
            skipped += 1
            continue

        if (
            mode == "early"
            and minutes_until_start <= FINAL_WINDOW_MINUTES
        ):
            print(
                f"SKIP {game_id}: EARLY window closed"
            )
            skipped += 1
            continue

        if (
            mode == "final"
            and not (
                0 < minutes_until_start <= FINAL_WINDOW_MINUTES
            )
        ):
            print(
                f"SKIP {game_id}: outside FINAL window"
            )
            skipped += 1
            continue

        try:
            (
                client.table("predictions")
                .insert(record)
                .execute()
            )

            saved += 1

            print(
                f"SAVED {model_version} | "
                f"{snapshot_type} | "
                f"{record['away_team']} @ "
                f"{record['home_team']} | "
                f"{record['projected_total']:.2f}"
            )

        except Exception as exc:
            message = str(exc).lower()

            if (
                "23505" in message
                or "duplicate key" in message
            ):
                skipped += 1

            else:
                raise RuntimeError(
                    f"Database insert failed: "
                    f"{model_version} / {game_id}"
                ) from exc

    return saved, skipped


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--write",
        action="store_true",
        help="Save eligible predictions to Supabase",
    )

    parser.add_argument(
        "--mode",
        choices=["early", "final"],
        default="early",
        help="Snapshot collection mode",
    )

    parser.add_argument(
        "--model",
        choices=["all", "v1", "v2"],
        default="all",
        help="Which prediction model to run",
    )

    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    game_date = (
        now.astimezone(ET)
        .date()
        .isoformat()
    )

    snapshot_type = (
        "EARLY"
        if args.mode == "early"
        else "FINAL PREGAME"
    )

    print("=" * 65)
    print("FROZEN FORECAST — MULTI-MODEL COLLECTOR")
    print("=" * 65)

    print(f"Date: {game_date} ET")
    print(f"Snapshot: {snapshot_type}")
    print(
        f"Operation: "
        f"{'WRITE' if args.write else 'DRY RUN'}"
    )
    print(f"Model selection: {args.model}")

    if args.model == "v1":
        selected_models = {
            "v1_goalie_adjusted": build_v1
        }

    elif args.model == "v2":
        selected_models = {
            "v2_recent5_w20": build_v2
        }

    else:
        selected_models = MODELS

    client = None

    if args.write:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")

        if not url or not key:
            raise RuntimeError(
                "Missing SUPABASE_URL or SUPABASE_KEY"
            )

        client = create_client(url, key)

    total_saved = 0
    total_skipped = 0
    failed_models = []

    for model_version, builder in selected_models.items():
        print("\n" + "=" * 65)
        print(f"RUNNING MODEL: {model_version}")
        print("=" * 65)

        try:
            df, meta = builder(
                game_date,
                verify=True,
            )

            print(
                f"Scheduled games: "
                f"{meta.get('scheduled', 0)}"
            )

            print(
                f"Projected games: {len(df)}"
            )

            if "recent_team_count" in meta:
                print(
                    "Recent-form teams: "
                    f"{meta['recent_team_count']}"
                )

            eligible = collect_eligible_predictions(
                df,
                model_version,
                game_date,
                snapshot_type,
                args.mode,
            )

            print(
                f"Eligible {snapshot_type} "
                f"snapshots: {len(eligible)}"
            )

            for record in eligible:
                print(
                    f"{record['away_team']} @ "
                    f"{record['home_team']} | "
                    f"{record['projected_total']:.2f} | "
                    f"{record['game_id']}"
                )

            if not args.write:
                print(
                    "DRY RUN: no database writes."
                )
                continue

            saved, skipped = save_predictions(
                client,
                eligible,
                model_version,
                snapshot_type,
                args.mode,
            )

            total_saved += saved
            total_skipped += skipped

            print(
                f"{model_version}: "
                f"saved={saved}, skipped={skipped}"
            )

        except Exception as exc:
            failed_models.append(model_version)

            print(
                f"ERROR in {model_version}: "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                "Continuing with other models."
            )

    print("\n" + "=" * 65)
    print("FROZEN FORECAST — COLLECTION SUMMARY")
    print("=" * 65)

    print(f"Total saved: {total_saved}")
    print(f"Total skipped: {total_skipped}")
    print(f"Failed models: {failed_models}")

    if not args.write:
        print(
            "DRY RUN COMPLETE: "
            "no database writes performed."
        )

    if failed_models:
        raise RuntimeError(
            "One or more models failed: "
            + ", ".join(failed_models)
        )


if __name__ == "__main__":
    main()


