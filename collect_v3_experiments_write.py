"""Frozen Forecast V3 experimental snapshot collector.

Dry-run by default. --write enables insert-only saving, capped by --max-inserts.
Never updates existing snapshots. Run from a manual workflow before scheduling.
"""
import argparse
import math
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from collect_predictions import collect_eligible_predictions, FINAL_WINDOW_MINUTES
from engine_v3 import build_projections as baseline
from engine_v3_fatigue_experiment import build_projections as fatigue
from engine_v3_totals_experiment import build_projections as scaled

ET = ZoneInfo("America/New_York")
BUILDERS = {
    "v3_dual_market_baseline": baseline,
    "v3_fatigue_experiment": fatigue,
    "v3_totals_scaled105_experiment": scaled,
}
LINES = (5.5, 6.0, 6.5)
PROBABILITY_COLUMNS = {
    ("Over", 5.5): "over_5_5_probability",
    ("Under", 5.5): "under_5_5_probability",
    ("Over", 6.0): "over_6_0_probability",
    ("Under", 6.0): "under_6_0_probability",
    ("Push", 6.0): "push_6_0_probability",
    ("Over", 6.5): "over_6_5_probability",
    ("Under", 6.5): "under_6_5_probability",
}


def probabilities_for(row):
    output = {}
    for line in LINES:
        vals = {}
        for side in ("Over", "Under", "Push"):
            value = float(row[f"{side} {line} Probability"])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Invalid {side} probability at {line}: {value}")
            vals[side] = value
            if (side, line) in PROBABILITY_COLUMNS:
                output[PROBABILITY_COLUMNS[(side, line)]] = value
        if abs(sum(vals.values()) - 1) > 1e-5:
            raise ValueError(f"Probabilities at {line} do not sum to one")
        if line != 6.0 and vals["Push"] > 1e-6:
            raise ValueError(f"Unexpected push at {line}")
    # A full-game total >=7 is the same event at 6.0 and 6.5.
    if abs(output["over_6_0_probability"] - output["over_6_5_probability"]) > 1e-5:
        raise ValueError("Over 6.0 and Over 6.5 probabilities disagree")
    return output


def eligible_now(record, mode):
    """Recheck pregame timing immediately before inserting."""
    start = datetime.fromisoformat(record["scheduled_start"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    minutes = (start - now).total_seconds() / 60
    if mode == "early":
        return minutes > FINAL_WINDOW_MINUTES
    return 0 < minutes <= FINAL_WINDOW_MINUTES


def fetch_existing(client, record):
    response = (client.table("predictions")
                .select("game_id,model_version,snapshot_type")
                .eq("game_id", record["game_id"])
                .eq("model_version", record["model_version"])
                .eq("snapshot_type", record["snapshot_type"])
                .limit(1).execute())
    return bool(response.data)


def insert_and_verify(client, record):
    try:
        client.table("predictions").insert(record).execute()
    except Exception as exc:
        if "23505" in str(exc).lower() or "duplicate key" in str(exc).lower():
            print("SKIP: concurrent collector inserted the same snapshot")
            return False
        raise

    response = (client.table("predictions")
                .select("game_id,model_version,snapshot_type,projected_total,"
                        + ",".join(PROBABILITY_COLUMNS.values()))
                .eq("game_id", record["game_id"])
                .eq("model_version", record["model_version"])
                .eq("snapshot_type", record["snapshot_type"])
                .limit(1).execute())
    if not response.data:
        raise RuntimeError("Insert completed but record could not be read back")
    saved = response.data[0]
    for key in ("projected_total", *PROBABILITY_COLUMNS.values()):
        if saved.get(key) is None or not math.isclose(float(saved[key]), float(record[key]), abs_tol=1e-8):
            raise RuntimeError(f"Readback mismatch for {key}")
    print(f"SAVED AND VERIFIED {record['model_version']} | {record['snapshot_type']} | "
          f"{record['away_team']} @ {record['home_team']} | game {record['game_id']}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("early", "final"), default="early")
    parser.add_argument("--date", help="Eastern game date YYYY-MM-DD (default today)")
    parser.add_argument("--write", action="store_true", help="Enable insert-only Supabase writes")
    parser.add_argument("--max-inserts", type=int, default=1,
                        help="Maximum new records per invocation (default 1)")
    args = parser.parse_args()
    if args.max_inserts < 1:
        parser.error("--max-inserts must be at least 1")
    today = datetime.now(ET).date().isoformat()
    game_date = args.date or today
    datetime.strptime(game_date, "%Y-%m-%d")
    if args.write and game_date != today:
        parser.error("Writes are restricted to today's Eastern game date")

    snapshot = "EARLY" if args.mode == "early" else "FINAL PREGAME"
    print(f"V3 COLLECTOR | {game_date} ET | {snapshot} | "
          f"{'WRITE' if args.write else 'DRY RUN'}")
    client = None
    if args.write:
        from supabase import create_client
        client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    candidates = []
    for model, build in BUILDERS.items():
        print(f"\nMODEL: {model}")
        df, metadata = build(game_date, verify=True)
        print(f"Projected games: {len(df)} | scheduled: {metadata.get('scheduled', 'unknown')}")
        by_id = {}
        for _, row in df.iterrows():
            # Validate every model output, not only eligible games.
            probabilities_for(row)
            game_id = str(row["Game ID"])
            if game_id in by_id:
                raise ValueError(f"Duplicate game ID in {model}: {game_id}")
            by_id[game_id] = row
        eligible = collect_eligible_predictions(df, model, game_date, snapshot, args.mode)
        print(f"Eligible snapshots: {len(eligible)}")
        for record in eligible:
            record.update(probabilities_for(by_id[record["game_id"]]))
            candidates.append(record)

    print(f"\nTOTAL ELIGIBLE: {len(candidates)}")
    if not args.write:
        for record in candidates:
            print(f"WOULD SAVE {record['model_version']} | {record['snapshot_type']} | "
                  f"{record['away_team']} @ {record['home_team']} | "
                  f"Over 5.5={record['over_5_5_probability']:.1%}, "
                  f"Over 6.5={record['over_6_5_probability']:.1%}")
        print("DRY RUN COMPLETE — NO DATABASE WRITES")
        return

    saved_count = 0
    for record in candidates:
        if saved_count >= args.max_inserts:
            break
        if not eligible_now(record, args.mode):
            print(f"SKIP {record['game_id']}: collection window closed")
            continue
        if fetch_existing(client, record):
            print(f"SKIP {record['game_id']} / {record['model_version']}: already saved")
            continue
        if insert_and_verify(client, record):
            saved_count += 1
    print(f"WRITE COMPLETE: {saved_count} inserted and verified; cap={args.max_inserts}")
    if not candidates:
        print("No eligible games right now; retry during an eligible collection window")


if __name__ == "__main__":
    main()
