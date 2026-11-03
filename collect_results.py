
"""Frozen Forecast — Official NHL Results Collector."""

import argparse
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
API = "https://api-web.nhle.com/v1"


def fetch_final_games(game_date):
    url = f"{API}/score/{game_date}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    games = response.json().get("games", [])
    results = []

    for game in games:
        if game.get("gameState") != "OFF":
            continue

        away = game.get("awayTeam", {})
        home = game.get("homeTeam", {})

        away_goals = away.get("score")
        home_goals = home.get("score")

        if away_goals is None or home_goals is None:
            continue

        results.append({
            "game_id": str(game["id"]),
            "game_date": game_date,
            "away_team": away["abbrev"],
            "home_team": home["abbrev"],
            "away_goals": int(away_goals),
            "home_goals": int(home_goals),
            "actual_total": int(away_goals) + int(home_goals),
            "completed_at": datetime.now(
                timezone.utc
            ).isoformat(),
        })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Save results to Supabase",
    )
    parser.add_argument(
        "--date",
        help="Optional Eastern game date YYYY-MM-DD",
    )
    args = parser.parse_args()

    today = datetime.now(ET).date()

    dates = (
        [args.date]
        if args.date
        else [
            (today - timedelta(days=1)).isoformat(),
            today.isoformat(),
        ]
    )

    print("======================================")
    print("FROZEN FORECAST — NHL RESULTS COLLECTOR")
    print("======================================")
    print("Mode:", "WRITE" if args.write else "DRY RUN")

    all_results = []

    for date in dates:
        results = fetch_final_games(date)
        print(f"{date}: {len(results)} completed games")
        all_results.extend(results)

    for game in all_results:
        print(
            f"{game['away_team']} "
            f"{game['away_goals']} @ "
            f"{game['home_team']} "
            f"{game['home_goals']} "
            f"| Total: {game['actual_total']}"
        )

    if not args.write:
        print("DRY RUN COMPLETE — no database writes.")
        return

    if not all_results:
        print("No completed games to save.")
        return

    from supabase import create_client

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]

    client = create_client(url, key)

    saved = 0

    for game in all_results:
        existing = (
            client.table("game_results")
            .select("game_id")
            .eq("game_id", game["game_id"])
            .execute()
        )

        if existing.data:
            continue

        client.table("game_results").insert(game).execute()
        saved += 1

    print(f"RESULTS SAVED: {saved}")


if __name__ == "__main__":
    main()
