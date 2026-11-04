
"""Frozen Forecast v2 — recent-form challenger projection engine.

Preserves the v1 shot-volume / goalie formula, but blends
season-long team performance with recent five-game form.

This is an experimental model, not a replacement for v1.
"""

import pandas as pd

from engine import (
    API,
    STATS,
    ET,
    get_json,
    norm,
    season_for,
    fetch_schedule,
    fetch_team_stats,
    fetch_goalie_stats,
    fetch_starters,
    verify_rosters,
)


MODEL_VERSION = "v2_recent5_w20"

RECENT_GAMES = 5
RECENT_WEIGHT = 0.20


def fetch_recent_team_stats(season, through_date, games=5):
    """Fetch completed regular-season game-level team stats.

    Only games strictly before the target game date are eligible.
    This prevents using target-day results in pregame projections.
    """

    data = get_json(
        f"{STATS}/team/summary",
        {
            "isAggregate": "false",
            "isGame": "true",
            "cayenneExp": (
                f"gameTypeId=2 and seasonId={season}"
            ),
            "limit": -1,
        },
    ).get("data", [])

    if not data:
        raise RuntimeError(
            "No game-level NHL team statistics were returned."
        )

    records = []

    for item in data:
        team = item.get("teamFullName")

        from engine import TEAM_CODES

        code = TEAM_CODES.get(team)

        if not code:
            continue

        date = str(
            item.get("gameDate")
            or item.get("date")
            or ""
        )[:10]

        if not date or date >= through_date:
            continue

        shots_for = item.get("shotsFor")
        shots_against = item.get("shotsAgainst")
        goals_for = item.get("goalsFor")

        if (
            shots_for is None
            or shots_against is None
            or goals_for is None
        ):
            continue

        records.append({
            "team": code,
            "date": date,
            "game_id": str(item.get("gameId") or ""),
            "shots_for": float(shots_for),
            "shots_against": float(shots_against),
            "goals_for": float(goals_for),
        })

    if not records:
        raise RuntimeError(
            "No valid recent team-game statistics were returned."
        )

    df = pd.DataFrame(records)

    df = df.sort_values(
        ["team", "date", "game_id"],
        ascending=[True, False, False],
    )

    df = df.drop_duplicates(
        ["team", "game_id"]
    )

    df = df.groupby(
        "team",
        group_keys=False
    ).head(games)

    recent = {}

    for code, group in df.groupby("team"):
        total_shots = group["shots_for"].sum()

        if total_shots <= 0:
            continue

        recent[code] = {
            "sf": group["shots_for"].mean(),
            "sa": group["shots_against"].mean(),
            "shoot": (
                group["goals_for"].sum() / total_shots
            ),
            "games": len(group),
        }

    return recent


def blend_team_stats(season_stats, recent_stats):
    """Blend season averages with recent performance."""

    blended = {}

    for code, season in season_stats.items():
        recent = recent_stats.get(code)

        if not recent:
            blended[code] = season.copy()
            continue

        # Reduce the weight if fewer than five games exist.
        weight = RECENT_WEIGHT * min(
            recent["games"] / RECENT_GAMES,
            1.0
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


def build_projections(date, verify=True):
    """Return the same projection schema as engine.py."""

    games = fetch_schedule(date)

    if not games:
        return pd.DataFrame(), {
            "scheduled": 0,
            "projected": 0,
            "rosters": {},
            "model_version": MODEL_VERSION,
        }

    season = season_for(date)

    teams = fetch_team_stats(season)

    recent = fetch_recent_team_stats(
        season,
        date,
        games=RECENT_GAMES,
    )

    teams = blend_team_stats(
        teams,
        recent,
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
                f"{away} @ {home}: missing team/starter data"
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
                f"{away} @ {home}: goalie stats missing"
            )
            continue

        away_team = teams[away]
        home_team = teams[home]

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
                away_goals + home_goals,
                4,
            ),
            "Goalie Reliability": reliability,
            "Start ET": start.tz_convert(ET).strftime(
                "%I:%M %p ET"
            ),
            "Start UTC": start.isoformat(),
            "Calculated At UTC": now.isoformat(),
        })

    projections = (
        pd.DataFrame(rows)
        .sort_values(
            "Projected Total",
            ascending=False
        )
        .reset_index(drop=True)
        if rows
        else pd.DataFrame()
    )

    metadata = {
        "scheduled": len(games),
        "projected": len(rows),
        "skipped": skipped,
        "rosters": roster,
        "team_count": len(teams),
        "goalie_count": len(goalies),
        "recent_team_count": len(recent),
        "model_version": MODEL_VERSION,
    }

    return projections, metadata
