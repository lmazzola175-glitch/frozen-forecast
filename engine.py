"""Frozen Forecast — V1 NHL Projection Engine.

Uses the original goalie-adjusted goal projection formula
and adds Poisson-based game winner probabilities.

The existing goal projection calculations remain unchanged.
"""

import json
import re
import unicodedata

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from bs4 import BeautifulSoup

from win_probability import calculate_win_probabilities


ET = ZoneInfo("America/New_York")

API = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"


TEAM_CODES = dict(zip(
    [
        "Anaheim Ducks",
        "Boston Bruins",
        "Buffalo Sabres",
        "Calgary Flames",
        "Carolina Hurricanes",
        "Chicago Blackhawks",
        "Colorado Avalanche",
        "Columbus Blue Jackets",
        "Dallas Stars",
        "Detroit Red Wings",
        "Edmonton Oilers",
        "Florida Panthers",
        "Los Angeles Kings",
        "Minnesota Wild",
        "Montréal Canadiens",
        "Nashville Predators",
        "New Jersey Devils",
        "New York Islanders",
        "New York Rangers",
        "Ottawa Senators",
        "Philadelphia Flyers",
        "Pittsburgh Penguins",
        "San Jose Sharks",
        "Seattle Kraken",
        "St. Louis Blues",
        "Tampa Bay Lightning",
        "Toronto Maple Leafs",
        "Utah Mammoth",
        "Vancouver Canucks",
        "Vegas Golden Knights",
        "Washington Capitals",
        "Winnipeg Jets",
    ],
    [
        "ANA", "BOS", "BUF", "CGY", "CAR", "CHI",
        "COL", "CBJ", "DAL", "DET", "EDM", "FLA",
        "LAK", "MIN", "MTL", "NSH", "NJD", "NYI",
        "NYR", "OTT", "PHI", "PIT", "SJS", "SEA",
        "STL", "TBL", "TOR", "UTA", "VAN", "VGK",
        "WSH", "WPG",
    ],
))


# ============================================================
# NHL API HELPERS
# ============================================================

def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=25,
        headers={
            "User-Agent": "Mozilla/5.0 FrozenForecast/1.0"
        },
    )

    response.raise_for_status()
    return response.json()


def norm(name):
    text = unicodedata.normalize(
        "NFKD",
        str(name or ""),
    )

    return re.sub(
        "[^a-z]",
        "",
        "".join(
            character
            for character in text
            if not unicodedata.combining(character)
        ).lower(),
    )


def season_for(date):
    year = int(date[:4])

    if int(date[5:7]) >= 7:
        return f"{year}{year + 1}"

    return f"{year - 1}{year}"


# ============================================================
# NHL SCHEDULE
# ============================================================

def fetch_schedule(date):
    return get_json(
        f"{API}/score/{date}"
    ).get("games", [])


# ============================================================
# TEAM STATISTICS
# ============================================================

def fetch_team_stats(season):

    data = get_json(
        f"{STATS}/team/summary",
        {
            "isAggregate": "false",
            "isGame": "false",
            "cayenneExp": (
                f"gameTypeId=2 and seasonId={season}"
            ),
            "limit": 100,
        },
    )["data"]

    output = {}

    for team in data:

        code = TEAM_CODES.get(
            team.get("teamFullName")
        )

        if not code:
            continue

        games_played = team.get("gamesPlayed") or 0
        shots_for = team.get("shotsForPerGame")
        shots_against = team.get("shotsAgainstPerGame")

        if (
            games_played
            and shots_for
            and shots_against is not None
        ):

            output[code] = {
                "sf": float(shots_for),
                "sa": float(shots_against),
                "shoot": (
                    float(team.get("goalsFor") or 0)
                    / (float(shots_for) * games_played)
                ),
            }

    return output


# ============================================================
# GOALIE STATISTICS
# ============================================================

def fetch_goalie_stats(season):

    data = get_json(
        f"{STATS}/goalie/summary",
        {
            "isAggregate": "false",
            "isGame": "false",
            "cayenneExp": (
                f"gameTypeId=2 and seasonId={season}"
            ),
            "limit": 200,
        },
    )["data"]

    output = {}

    for goalie in data:

        if goalie.get("savePct") is None:
            continue

        shots = float(
            goalie.get("shotsAgainst") or 0
        )

        adjusted_save_percentage = (
            float(goalie["savePct"]) * shots
            + 0.900 * 300
        ) / (shots + 300)

        team_codes = str(
            goalie.get("teamAbbrevs") or ""
        ).replace(",", " ").split()

        for code in team_codes:

            output[
                (
                    code,
                    norm(goalie.get("goalieFullName")),
                )
            ] = adjusted_save_percentage

    return output


# ============================================================
# STARTING GOALIES
# ============================================================

def fetch_starters(date):

    response = requests.get(
        "https://www.dailyfaceoff.com/starting-goalies",
        timeout=25,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    script = soup.find(
        "script",
        id="__NEXT_DATA__",
    )

    if script is None:
        raise ValueError(
            "Daily Faceoff starting-goalie feed format changed."
        )

    data = json.loads(
        script.string
    )["props"]["pageProps"]["data"]

    if not isinstance(data, list):
        raise ValueError(
            "Unexpected Daily Faceoff goalie data."
        )

    output = {}

    for game in data:

        if str(game.get("date", ""))[:10] != date:
            continue

        for side in ("away", "home"):

            code = game.get(
                f"{side}TeamAbbreviation"
            )

            name = game.get(
                f"{side}GoalieName"
            )

            status = str(
                game.get(
                    f"{side}NewsStrengthName"
                ) or ""
            ).lower()

            if "confirm" in status:
                label = "Confirmed"

            elif any(
                word in status
                for word in (
                    "likely",
                    "expected",
                    "probable",
                )
            ):
                label = "Likely"

            else:
                label = "Unconfirmed"

            if code:
                output[code] = {
                    "name": name,
                    "status": label,
                }

    return output


# ============================================================
# VERIFY OFFICIAL NHL ROSTERS
# ============================================================

def verify_rosters(starters):

    checks = {}

    for code, starter in starters.items():

        if not starter.get("name"):
            checks[code] = "MISSING GOALIE"
            continue

        try:
            data = get_json(
                f"{API}/roster/{code}/current"
            )

            names = {
                norm(
                    (
                        goalie.get("firstName") or {}
                    ).get("default", "")
                    + " "
                    + (
                        goalie.get("lastName") or {}
                    ).get("default", "")
                )
                for goalie in data.get("goalies", [])
            }

            checks[code] = (
                "MATCH"
                if norm(starter["name"]) in names
                else "MISMATCH"
            )

        except Exception:
            checks[code] = "UNAVAILABLE"

    return checks


# ============================================================
# V1 GOAL PROJECTIONS + WIN PROBABILITIES
# ============================================================

def build_projections(date, verify=True):

    games = fetch_schedule(date)

    if not games:
        return pd.DataFrame(), {
            "scheduled": 0,
            "projected": 0,
            "rosters": {},
        }

    season = season_for(date)

    teams = fetch_team_stats(season)
    goalies = fetch_goalie_stats(season)
    starters = fetch_starters(date)

    if verify:
        roster = verify_rosters(starters)
    else:
        roster = {
            code: "NOT CHECKED"
            for code in starters
        }

    now = pd.Timestamp.now(tz="UTC")

    rows = []
    skipped = []

    for game in games:

        away = game.get(
            "awayTeam", {}
        ).get("abbrev")

        home = game.get(
            "homeTeam", {}
        ).get("abbrev")

        start = pd.to_datetime(
            game.get("startTimeUTC"),
            utc=True,
            errors="coerce",
        )

        if (
            pd.isna(start)
            or start <= now
            or game.get("gameState")
            in ("LIVE", "CRIT", "FINAL", "OFF")
        ):
            continue

        if (
            away not in teams
            or home not in teams
            or away not in starters
            or home not in starters
        ):
            skipped.append(
                f"{away} @ {home}: team/starter data unavailable"
            )
            continue

        away_starter = starters[away]
        home_starter = starters[home]

        away_save_pct = goalies.get(
            (
                away,
                norm(away_starter["name"]),
            )
        )

        home_save_pct = goalies.get(
            (
                home,
                norm(home_starter["name"]),
            )
        )

        if (
            away_save_pct is None
            or home_save_pct is None
        ):
            skipped.append(
                f"{away} @ {home}: goalie statistics missing"
            )
            continue

        away_team = teams[away]
        home_team = teams[home]

        # ----------------------------------------
        # ORIGINAL V1 GOAL FORMULA — UNCHANGED
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
            + (1 - home_save_pct)
        ) / 2

        home_goals = home_shots * (
            home_team["shoot"]
            + (1 - away_save_pct)
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

        if (
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
    }

    return projections, metadata
