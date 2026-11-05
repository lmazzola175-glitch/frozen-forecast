
"""Frozen Forecast v2 — Recent Form Challenger Engine.

Model: v2_recent5_w20

Uses the original v1 goalie-adjusted projection formula,
blending season team statistics with the previous five
completed games at a maximum weight of 20%.

Adds Poisson-based game winner probabilities using
the shared win_probability.py module.

Does not modify v1 or write predictions to Supabase.
"""

import pandas as pd

from engine import (
    API,
    STATS,
    ET,
    TEAM_CODES,
    get_json,
    norm,
    season_for,
    fetch_schedule,
    fetch_team_stats,
    fetch_goalie_stats,
    fetch_starters,
    verify_rosters,
)

from win_probability import calculate_win_probabilities


MODEL_VERSION = "v2_recent5_w20"

RECENT_GAMES = 5
RECENT_WEIGHT = 0.20

PAGE_SIZE = 100


# ============================================================
# RECENT TEAM STATISTICS
# ============================================================

def fetch_recent_team_stats(season, through_date, games=RECENT_GAMES):
    """Retrieve the previous N games for each NHL team.

    Uses game-level statistics strictly before through_date.
    Handles NHL API pagination.
    """

    records = []
    start = 0
    total = None

    while True:
        response = get_json(
            f"{STATS}/team/summary",
            {
                "isAggregate": "false",
                "isGame": "true",
                "cayenneExp": (
                    f"gameTypeId=2 and seasonId={season}"
                ),
                "start": start,
                "limit": PAGE_SIZE,
            },
        )

        rows = response.get("data", [])

        if total is None:
            total = int(response.get("total") or 0)

        if not rows:
            break

        records.extend(rows)
        start += len(rows)

        if total and start >= total:
            break

        if len(rows) < PAGE_SIZE:
            break

    if not records:
        raise RuntimeError(
            "NHL API returned no game-level team statistics."
        )

    parsed = []

    for item in records:
        code = TEAM_CODES.get(item.get("teamFullName"))

        if not code:
            continue

        game_date = str(
            item.get("gameDate") or ""
        )[:10]

        if not game_date or game_date >= through_date:
            continue

        shots_for = item.get("shotsForPerGame")
        shots_against = item.get("shotsAgainstPerGame")
        goals_for = item.get("goalsFor")

        if (
            shots_for is None
            or shots_against is None
            or goals_for is None
        ):
            continue

        parsed.append({
            "team": code,
            "date": game_date,
            "game_id": str(item.get("gameId") or ""),
            "shots_for": float(shots_for),
            "shots_against": float(shots_against),
            "goals_for": float(goals_for),
        })

    if not parsed:
        raise RuntimeError(
            "No valid completed team-game statistics "
            "were available before the target date."
        )

    df = pd.DataFrame(parsed)

    df = df.drop_duplicates(
        subset=["team", "game_id"]
    )

    df = df.sort_values(
        ["team", "date", "game_id"],
        ascending=[True, False, False],
    )

    df = (
        df.groupby("team", group_keys=False)
        .head(games)
        .copy()
    )

    recent = {}

    for code, group in df.groupby("team"):
        total_shots = group["shots_for"].sum()

        if total_shots <= 0:
            continue

        recent[code] = {
            "sf": float(group["shots_for"].mean()),
            "sa": float(group["shots_against"].mean()),
            "shoot": float(
                group["goals_for"].sum() / total_shots
            ),
            "games": int(len(group)),
        }

    return recent


# ============================================================
# BLEND SEASON AND RECENT FORM
# ============================================================

def blend_team_stats(season_stats, recent_stats):
    """Blend season averages with recent five-game form."""

    blended = {}

    for code, season in season_stats.items():
        recent = recent_stats.get(code)

        if recent is None:
            blended[code] = season.copy()
            continue

        weight = RECENT_WEIGHT * min(
            recent["games"] / RECENT_GAMES,
            1.0,
        )

        blended[code] = {
            "sf": (
                (1 - weight) * season["sf"]
                + weight * recent["sf"]
            ),
            "sa": (
                (1 - weight) * season["sa"]
                + weight * recent["sa"]
            ),
            "shoot": (
                (1 - weight) * season["shoot"]
                + weight * recent["shoot"]
            ),
        }

    return blended


# ============================================================
# V2 PROJECTIONS + WIN PROBABILITIES
# ============================================================

def build_projections(date, verify=True):
    """Generate v2 projections using the v1 output schema.

    Adds projected winner, home/away win probabilities,
    winner confidence, and regulation tie probability.
    """

    games = fetch_schedule(date)

    if not games:
        return pd.DataFrame(), {
            "scheduled": 0,
            "projected": 0,
            "rosters": {},
            "model_version": MODEL_VERSION,
            "recent_team_count": 0,
        }

    season = season_for(date)

    season_teams = fetch_team_stats(season)

    recent_teams = fetch_recent_team_stats(
        season,
        date,
        games=RECENT_GAMES,
    )

    teams = blend_team_stats(
        season_teams,
        recent_teams,
    )

    goalies = fetch_goalie_stats(season)
    starters = fetch_starters(date)

    roster = (
        verify_rosters(starters)
        if verify
        else {
            code: "NOT CHECKED"
            for code in starters
        }
    )

    now = pd.Timestamp.now(tz="UTC")

    rows = []
    skipped = []

    for game in games:

        away = (
            game.get("awayTeam", {})
            .get("abbrev")
        )

        home = (
            game.get("homeTeam", {})
            .get("abbrev")
        )

        start = pd.to_datetime(
            game.get("startTimeUTC"),
            utc=True,
            errors="coerce",
        )

        if (
            pd.isna(start)
            or start <= now
            or game.get("gameState") in (
                "LIVE",
                "CRIT",
                "FINAL",
                "OFF",
            )
        ):
            continue

        if (
            away not in teams
            or home not in teams
            or away not in starters
            or home not in starters
        ):
            skipped.append(
                f"{away} @ {home}: "
                "team or starter data unavailable"
            )
            continue

        away_starter = starters[away]
        home_starter = starters[home]

        away_sv = goalies.get(
            (away, norm(away_starter["name"]))
        )

        home_sv = goalies.get(
            (home, norm(home_starter["name"]))
        )

        if away_sv is None or home_sv is None:
            skipped.append(
                f"{away} @ {home}: "
                "goalie statistics missing"
            )
            continue

        away_team = teams[away]
        home_team = teams[home]

        # ----------------------------------------
        # ORIGINAL V2 GOAL FORMULA — UNCHANGED
        # ----------------------------------------

        away_shots = (
            away_team["sf"]
            + home_team["sa"]
        ) / 2

        home_shots = (
            home_team["sf"]
            + away_team["sa"]
        ) / 2

        away_goals = away_shots * (
            away_team["shoot"]
            + (1 - home_sv)
        ) / 2

        home_goals = home_shots * (
            home_team["shoot"]
            + (1 - away_sv)
        ) / 2

        projected_total = away_goals + home_goals

        # ----------------------------------------
        # NEW: WIN PROBABILITY CALCULATION
        # ----------------------------------------

        win_prediction = calculate_win_probabilities(
            away_expected_goals=away_goals,
            home_expected_goals=home_goals,
            away_team=away,
            home_team=home,
        )

        # ----------------------------------------
        # GOALIE RELIABILITY — UNCHANGED
        # ----------------------------------------

        statuses = {
            away_starter["status"],
            home_starter["status"],
        }

        if verify and (
            roster.get(away) != "MATCH"
            or roster.get(home) != "MATCH"
        ):
            reliability = "BLOCKED"

        elif "Unconfirmed" in statuses:
            reliability = "LOW"

        elif "Likely" in statuses:
            reliability = "MEDIUM"

        else:
            reliability = "HIGH"

        # ----------------------------------------
        # BUILD GAME RECORD
        # ----------------------------------------

        rows.append({
            "Game ID": str(game["id"]),
            "Game Date": date,

            "Away Code": away,
            "Home Code": home,

            "Away Goalie": away_starter["name"],
            "Home Goalie": home_starter["name"],

            "Away Status": away_starter["status"],
            "Home Status": home_starter["status"],

            "Away xG": round(away_goals, 4),
            "Home xG": round(home_goals, 4),

            "Projected Total": round(
                projected_total, 4
            ),

            # NEW WINNER FIELDS
            "Projected Winner": (
                win_prediction["projected_winner"]
            ),

            "Away Win Probability": (
                win_prediction["away_win_probability"]
            ),

            "Home Win Probability": (
                win_prediction["home_win_probability"]
            ),

            "Winner Confidence": (
                win_prediction["winner_confidence"]
            ),

            "Regulation Tie Probability": (
                win_prediction["regulation_tie_probability"]
            ),

            "Goalie Reliability": reliability,

            "Start ET": start.tz_convert(
                ET
            ).strftime("%I:%M %p ET"),

            "Start UTC": start.isoformat(),

            "Calculated At UTC": now.isoformat(),
        })

    if rows:
        projections = (
            pd.DataFrame(rows)
            .sort_values(
                "Projected Total",
                ascending=False,
            )
            .reset_index(drop=True)
        )
    else:
        projections = pd.DataFrame()

    metadata = {
        "scheduled": len(games),
        "projected": len(rows),
        "skipped": skipped,
        "rosters": roster,
        "team_count": len(teams),
        "goalie_count": len(goalies),
        "recent_team_count": len(recent_teams),
        "model_version": MODEL_VERSION,
    }

    return projections, metadata


