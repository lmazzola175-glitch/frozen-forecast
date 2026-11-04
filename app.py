
import html
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from engine import build_projections, fetch_schedule


# ============================================================
# FROZEN FORECAST — NHL PROJECTION CENTER
# ============================================================

ET = ZoneInfo("America/New_York")
MODEL_VERSION = "v1_goalie_adjusted"

st.set_page_config(
    page_title="Frozen Forecast | NHL Projection Center",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CSS
# ============================================================

st.html("""
<style>
.stApp {
    background:
        radial-gradient(
            ellipse at 50% -15%,
            #16436b 0%,
            #081726 40%,
            #040d18 100%
        );
    color: #eaf6ff;
}

.block-container {
    max-width: 1700px;
    padding-top: 1.3rem;
    padding-bottom: 3rem;
}

h1, h2, h3 {
    color: #eaf6ff !important;
}

.ff-hero {
    border: 1px solid #42baf2;
    border-radius: 16px;
    background: linear-gradient(
        100deg,
        #081725,
        #0d3555 52%,
        #071521
    );
    padding: 17px 24px;
    box-shadow: 0 0 24px #008bff33;
}

.ff-sub {
    font-size: 11px;
    letter-spacing: 3px;
    color: #9adfff;
}

.ff-head {
    font-weight: 1000;
    font-size: clamp(34px, 5vw, 65px);
    line-height: 1.1;
    color: #e9f7ff;
    text-shadow: 0 0 20px #27b9ff99;
}

.ff-head span {
    color: #44c7ff;
}

.ff-panel {
    background: #071c2ee8;
    border: 1px solid #2a95c9;
    border-radius: 13px;
    padding: 15px;
    margin-bottom: 14px;
    box-shadow: 0 0 14px #009dff20;
}

.ff-panel-title {
    font-size: 16px;
    font-weight: 800;
    color: #f0f8ff;
    border-bottom: 1px solid #235577;
    padding-bottom: 11px;
    margin-bottom: 14px;
}

.ff-num {
    font-size: 42px;
    font-weight: 900;
    line-height: 1.2;
}

.ff-small {
    font-size: 12px;
    color: #c7d9e8;
    line-height: 1.85;
}

.ff-muted {
    color: #9db8cc;
    font-size: 12px;
}

.ff-game {
    display: grid;
    grid-template-columns:
        25px
        82px
        minmax(125px, 1.2fr)
        65px
        90px
        minmax(145px, 1.6fr)
        80px;
    gap: 9px;
    align-items: center;
    border-bottom: 1px solid #1b415e;
    padding: 12px 4px;
    font-size: 12px;
    min-width: 0;
}

.ff-game:last-child {
    border-bottom: none;
}

.ff-game > div {
    min-width: 0;
}

.ff-matchup {
    display: flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    font-weight: 800;
}

.ff-matchup img {
    width: 26px;
    height: 26px;
    object-fit: contain;
}

.ff-total {
    background: #0b456b;
    border: 1px solid #39c7ff;
    border-radius: 7px;
    padding: 8px 4px;
    text-align: center;
    font-size: 21px;
    font-weight: 900;
    color: white;
}

.ff-pill {
    border: 1px solid;
    border-radius: 7px;
    text-align: center;
    padding: 9px 4px;
    font-weight: 800;
    font-size: 10px;
}

.ff-high {
    color: #5ff3a0;
    border-color: #18bb69;
    background: #06351e;
}

.ff-medium {
    color: #ffdc62;
    border-color: #dba926;
    background: #392c0c;
}

.ff-low,
.ff-blocked {
    color: #ff8c99;
    border-color: #f24d63;
    background: #3a1020;
}

.ff-state {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.5px;
}

.ff-upcoming {
    color: #70d9ff;
}

.ff-live {
    color: #ffce62;
}

.ff-final {
    color: #a5b6c8;
}

.ff-source {
    color: #90c7e7;
    font-size: 10px;
    margin-top: 4px;
}

.ff-goalies {
    overflow-wrap: anywhere;
    line-height: 1.45;
}

.ff-summary-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    font-size: 11px;
    margin-top: 6px;
}

.ff-section-title {
    font-size: 23px;
    font-weight: 900;
    margin-bottom: 5px;
    color: #eaf6ff;
}

@media(max-width: 1300px) {
    .ff-game {
        grid-template-columns:
            22px
            72px
            minmax(110px, 1fr)
            58px
            76px;
        gap: 6px;
    }

    .ff-goalies {
        grid-column: 3 / 5;
    }

    .ff-rel {
        grid-column: 5;
    }

    .ff-matchup img {
        width: 22px;
        height: 22px;
    }

    .ff-total {
        font-size: 18px;
    }
}

@media(max-width: 700px) {
    .ff-game {
        grid-template-columns:
            22px
            70px
            minmax(105px, 1fr)
            72px;
    }

    .ff-shots {
        display: none;
    }

    .ff-goalies {
        grid-column: 2 / 4;
    }

    .ff-rel {
        grid-column: 4;
    }

    .ff-head {
        font-size: 35px;
    }
}
</style>
""")


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def escape(value):
    return html.escape(str(value), quote=True)


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def display_text(value, default="—"):
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    return str(value)


def format_start(value):
    timestamp = pd.to_datetime(
        value,
        utc=True,
        errors="coerce"
    )

    if pd.isna(timestamp):
        return "TBD"

    return timestamp.tz_convert(
        ET
    ).strftime("%I:%M %p ET")


def game_status(game):
    state = str(
        game.get("gameState") or ""
    ).upper()

    if state in ("FINAL", "OFF"):
        return "FINAL"

    if state in ("LIVE", "CRIT"):
        return "LIVE"

    start = pd.to_datetime(
        game.get("startTimeUTC"),
        utc=True,
        errors="coerce"
    )

    if (
        pd.notna(start)
        and start <= pd.Timestamp.now(tz="UTC")
    ):
        return "LIVE"

    return "UPCOMING"


def panel(title, body):
    return f"""
    <div class="ff-panel">
        <div class="ff-panel-title">{title}</div>
        {body}
    </div>
    """


# ============================================================
# SUPABASE CONNECTION
# ============================================================

def get_supabase_client():
    from supabase import create_client

    url = st.secrets.get(
        "SUPABASE_URL",
        os.environ.get("SUPABASE_URL")
    )

    key = st.secrets.get(
        "SUPABASE_KEY",
        os.environ.get("SUPABASE_KEY")
    )

    if not url or not key:
        raise RuntimeError(
            "Supabase credentials are not configured."
        )

    return create_client(url, key)


# ============================================================
# HISTORICAL PREDICTIONS
# ============================================================

@st.cache_data(ttl=120)
def load_saved_predictions(date):
    client = get_supabase_client()

    response = (
        client.table("predictions")
        .select("*")
        .eq("game_date", str(date))
        .eq("model_version", MODEL_VERSION)
        .execute()
    )

    saved = pd.DataFrame(
        response.data or []
    )

    if saved.empty:
        return saved

    saved["priority"] = (
        saved["snapshot_type"]
        .map({
            "FINAL PREGAME": 0,
            "EARLY": 1
        })
        .fillna(2)
    )

    saved = (
        saved.sort_values(
            ["priority", "saved_at"],
            ascending=[True, False]
        )
        .drop_duplicates(
            subset=["game_id"],
            keep="first"
        )
        .reset_index(drop=True)
    )

    return saved


# ============================================================
# MODEL PERFORMANCE
# ============================================================

@st.cache_data(ttl=600)
def load_model_performance():
    client = get_supabase_client()

    response = (
        client.table("model_accuracy_summary")
        .select("*")
        .execute()
    )

    return pd.DataFrame(
        response.data or []
    )


# ============================================================
# NHL DATA
# ============================================================

@st.cache_data(ttl=600)
def cached_projections(date, verify_rosters):
    return build_projections(
        date,
        verify_rosters
    )


@st.cache_data(ttl=120)
def cached_schedule(date):
    return fetch_schedule(date)


# ============================================================
# HEADER
# ============================================================

app_dir = Path(__file__).resolve().parent

logo_candidates = [
    app_dir / "assets" / "frozen_forecast_logo.svg",
    app_dir / "frozen_forecast_logo.svg",
]

logo = next(
    (
        path
        for path in logo_candidates
        if path.is_file()
    ),
    None
)

header_left, header_right = st.columns(
    [1, 5],
    vertical_alignment="center"
)

with header_left:
    if logo is not None:
        st.image(str(logo), width=135)
    else:
        st.html(
            '<div style="font-size:60px;text-align:center">🏒❄️</div>'
        )

with header_right:
    st.html("""
    <div class="ff-hero">
        <div class="ff-sub">
            NHL ANALYTICS • PROJECTION CENTER
        </div>
        <div class="ff-head">
            FROZEN <span>FORECAST</span>
        </div>
        <div class="ff-sub">
            THE NUMBERS BEHIND THE ICE
        </div>
    </div>
    """)


# ============================================================
# SIDEBAR
# ============================================================

now = datetime.now(ET)

with st.sidebar:
    st.header("❄️ Forecast Controls")

    game_date = st.date_input(
        "Game date (Eastern Time)",
        value=now.date()
    )

    verify = st.checkbox(
        "Verify goalie rosters",
        value=True
    )

    if st.button(
        "🔄 Refresh now",
        use_container_width=True
    ):
        st.cache_data.clear()
        st.rerun()

    st.caption(
        "Historical projections are preserved "
        "after puck drop."
    )


# ============================================================
# LOAD DATA
# ============================================================

date_string = str(game_date)

try:
    schedule = cached_schedule(date_string)
except Exception as exc:
    st.error(
        f"Unable to load NHL schedule: {exc}"
    )
    st.stop()

saved_error = None

try:
    saved_df = load_saved_predictions(
        date_string
    )
except Exception as exc:
    saved_df = pd.DataFrame()
    saved_error = str(exc)

live_error = None

try:
    live_df, meta = cached_projections(
        date_string,
        verify
    )
except Exception as exc:
    live_df = pd.DataFrame()
    meta = {}
    live_error = str(exc)

if saved_error:
    st.warning(
        "Historical database unavailable: "
        + saved_error
    )

if live_error:
    st.warning(
        "Live projections unavailable: "
        + live_error
    )

st.caption(
    f'📅 {game_date.strftime("%A, %B %d, %Y")}'
    f' · Viewed {now.strftime("%I:%M %p ET")}'
    ' · Live cache: up to 10 minutes'
)


# ============================================================
# LOOKUP TABLES
# ============================================================

saved_lookup = {}

if not saved_df.empty:
    saved_lookup = {
        str(row["game_id"]): row
        for _, row in saved_df.iterrows()
    }

live_lookup = {}

if not live_df.empty:
    live_lookup = {
        str(row["Game ID"]): row
        for _, row in live_df.iterrows()
    }


# ============================================================
# BUILD COMPLETE SLATE
# ============================================================

rows = []
unavailable = []

for game in schedule:
    game_id = str(game.get("id"))

    away = game.get(
        "awayTeam", {}
    ).get("abbrev", "")

    home = game.get(
        "homeTeam", {}
    ).get("abbrev", "")

    status = game_status(game)

    saved = saved_lookup.get(game_id)
    live = live_lookup.get(game_id)

    source = None

    if status != "UPCOMING" and saved is not None:
        source = "SAVED"

    elif status == "UPCOMING" and live is not None:
        source = "LIVE"

    elif saved is not None:
        source = "SAVED"

    elif live is not None:
        source = "LIVE"

    if source == "SAVED":
        row = {
            "Game ID": game_id,
            "Away Code": away,
            "Home Code": home,
            "Away xG": safe_float(
                saved.get("away_projected_goals")
            ),
            "Home xG": safe_float(
                saved.get("home_projected_goals")
            ),
            "Projected Total": safe_float(
                saved.get("projected_total")
            ),
            "Away Goalie": display_text(
                saved.get("away_goalie")
            ),
            "Home Goalie": display_text(
                saved.get("home_goalie")
            ),
            "Away Status": "Pregame",
            "Home Status": "Pregame",
            "Goalie Reliability": display_text(
                saved.get("goalie_reliability"),
                "LOW"
            ),
            "Game Status": status,
            "Projection Source": display_text(
                saved.get("snapshot_type")
            ),
            "Start ET": format_start(
                game.get("startTimeUTC")
            )
        }

    elif source == "LIVE":
        row = {
            "Game ID": game_id,
            "Away Code": away,
            "Home Code": home,
            "Away xG": safe_float(
                live.get("Away xG")
            ),
            "Home xG": safe_float(
                live.get("Home xG")
            ),
            "Projected Total": safe_float(
                live.get("Projected Total")
            ),
            "Away Goalie": display_text(
                live.get("Away Goalie")
            ),
            "Home Goalie": display_text(
                live.get("Home Goalie")
            ),
            "Away Status": display_text(
                live.get("Away Status")
            ),
            "Home Status": display_text(
                live.get("Home Status")
            ),
            "Goalie Reliability": display_text(
                live.get("Goalie Reliability"),
                "LOW"
            ),
            "Game Status": status,
            "Projection Source": "LIVE PREGAME",
            "Start ET": format_start(
                game.get("startTimeUTC")
            )
        }

    else:
        unavailable.append(
            f"{away} @ {home}: "
            "no pregame projection available"
        )
        continue

    rows.append(row)


df = pd.DataFrame(rows)

if df.empty:
    st.warning(
        "No projections are available "
        "for this date."
    )
    st.stop()

df = (
    df.sort_values(
        "Projected Total",
        ascending=False
    )
    .reset_index(drop=True)
)


# ============================================================
# COUNTS
# ============================================================

reliability_counts = (
    df["Goalie Reliability"]
    .value_counts()
)

high = int(reliability_counts.get("HIGH", 0))
medium = int(reliability_counts.get("MEDIUM", 0))
low = int(reliability_counts.get("LOW", 0))
blocked = int(reliability_counts.get("BLOCKED", 0))

status_counts = df["Game Status"].value_counts()

upcoming = int(status_counts.get("UPCOMING", 0))
in_progress = int(status_counts.get("LIVE", 0))
final = int(status_counts.get("FINAL", 0))

saved_count = int(
    df["Projection Source"]
    .isin(["EARLY", "FINAL PREGAME"])
    .sum()
)


# ============================================================
# THREE-COLUMN DASHBOARD
# ============================================================

left, middle, right = st.columns(
    [1.0, 2.9, 1.15],
    gap="small"
)


# ============================================================
# LEFT PANELS
# ============================================================

with left:
    st.html(
        panel(
            "🏒 TONIGHT'S SLATE",
            f"""
            <div class="ff-num">
                {len(df)} GAMES
            </div>
            <div class="ff-small">
                🔵 {upcoming} Upcoming<br>
                🟡 {in_progress} Live<br>
                ⚪ {final} Final
            </div>
            """
        )
    )

    roster_checks = meta.get(
        "rosters", {}
    )

    roster_matches = sum(
        value == "MATCH"
        for value in roster_checks.values()
    )

    st.html(
        panel(
            "📋 DATA CHECKS",
            f"""
            <div class="ff-small">
                Teams loaded:
                {meta.get("team_count", 0)}<br>
                Goalies loaded:
                {meta.get("goalie_count", 0)}<br>
                Official roster matches:
                {roster_matches} /
                {len(roster_checks)}<br>
                Scheduled matchups:
                {len(schedule)}<br>
                Matchups displayed:
                {len(df)}<br>
                Saved projections displayed:
                {saved_count}
            </div>
            """
        )
    )


# ============================================================
# CENTER — ALL NHL MATCHUPS
# ============================================================

with middle:
    st.html(
        panel(
            "🏒 NHL GOAL PROJECTIONS",
            ""
        )
    )

    game_html = []

    for i, game in df.iterrows():
        away = escape(game["Away Code"])
        home = escape(game["Home Code"])

        logo1 = (
            "https://assets.nhle.com/"
            f"logos/nhl/svg/{away}_light.svg"
        )

        logo2 = (
            "https://assets.nhle.com/"
            f"logos/nhl/svg/{home}_light.svg"
        )

        reliability = str(
            game["Goalie Reliability"]
        ).upper()

        if reliability not in (
            "HIGH",
            "MEDIUM",
            "LOW",
            "BLOCKED"
        ):
            reliability = "LOW"

        goalie_text = escape(
            f'{game["Away Goalie"]} '
            f'({game["Away Status"]}) / '
            f'{game["Home Goalie"]} '
            f'({game["Home Status"]})'
        )

        status = str(
            game["Game Status"]
        )

        start = escape(
            game["Start ET"]
        )

        source = escape(
            game["Projection Source"]
        )

        game_html.append(
            f"""
            <div class="ff-game">
                <div>
                    <b>{i + 1:02d}</b>
                </div>

                <div class="ff-small">
                    {start}
                    <div class="ff-state ff-{status.lower()}">
                        {escape(status)}
                    </div>
                </div>

                <div class="ff-matchup">
                    <img src="{logo1}" alt="{away}">
                    <span>{away}</span>
                    <span>@</span>
                    <img src="{logo2}" alt="{home}">
                    <span>{home}</span>
                </div>

                <div class="ff-shots ff-small">
                    {game["Away xG"]:.2f} /
                    {game["Home xG"]:.2f}
                </div>

                <div class="ff-total">
                    {game["Projected Total"]:.2f}
                </div>

                <div class="ff-goalies ff-small">
                    {goalie_text}
                    <div class="ff-source">
                        {source}
                    </div>
                </div>

                <div class="ff-rel ff-pill ff-{reliability.lower()}">
                    {reliability}
                </div>
            </div>
            """
        )

    # Render the entire list as ONE HTML block.
    # This prevents Streamlit from interpreting
    # indented HTML as Markdown code.

    st.html(
        '<div class="ff-games">'
        + "".join(game_html)
        + "</div>"
    )


# ============================================================
# RIGHT PANELS
# ============================================================

with right:
    st.html(
        panel(
            "🥅 GOALIE RELIABILITY",
            f"""
            <div class="ff-num">
                {len(df)}
            </div>
            <div class="ff-small">
                🟢 High: {high}<br>
                🟡 Medium: {medium}<br>
                🔴 Low: {low}<br>
                ⛔ Blocked: {blocked}
            </div>
            """
        )
    )

    highest = df.iloc[0]
    lowest = df.iloc[-1]

    average = df[
        "Projected Total"
    ].mean()

    st.html(
        panel(
            "🎯 KEY TAKEAWAYS",
            f"""
            <div class="ff-small">
                Average projected total:
                <b>{average:.2f}</b>
                <br><br>

                Highest:
                <b>
                    {highest["Projected Total"]:.2f}
                </b>
                ({escape(highest["Away Code"])}
                @ {escape(highest["Home Code"])})
                <br><br>

                Lowest:
                <b>
                    {lowest["Projected Total"]:.2f}
                </b>
                ({escape(lowest["Away Code"])}
                @ {escape(lowest["Home Code"])})
            </div>
            """
        )
    )

    st.download_button(
        "⬇️ Export projections CSV",
        data=df.to_csv(index=False),
        file_name=f"frozen_forecast_{game_date}.csv",
        mime="text/csv",
        use_container_width=True
    )


# ============================================================
# HISTORICAL DATABASE
# ============================================================

st.divider()

if saved_error is None:
    st.success(
        "Frozen Forecast historical database connected. "
        f"{len(saved_lookup)} games have saved "
        "pregame predictions."
    )
else:
    st.warning(
        "Historical database is unavailable. "
        "Saved pregame projections could not be loaded."
    )


with st.expander(
    "📸 Historical pregame snapshots"
):
    if saved_df.empty:
        st.info(
            "No saved predictions for this date."
        )
    else:
        columns = [
            "game_id",
            "away_team",
            "home_team",
            "snapshot_type",
            "projected_total",
            "saved_at"
        ]

        available_columns = [
            col
            for col in columns
            if col in saved_df.columns
        ]

        st.dataframe(
            saved_df[available_columns],
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# HISTORICAL MODEL PERFORMANCE
# ============================================================

st.divider()

st.html("""
<div class="ff-section-title">
    📊 HISTORICAL MODEL PERFORMANCE
</div>
""")

st.caption(
    "Frozen Forecast compares saved pregame "
    "goal projections with official NHL final "
    "scores to measure model accuracy."
)

try:
    performance_df = load_model_performance()

    if performance_df.empty:
        st.info(
            "No completed games with matching "
            "saved predictions are available yet. "
            "Metrics will populate automatically "
            "after completed games are collected."
        )

    else:
        st.success(
            "Historical model performance connected."
        )

        st.dataframe(
            performance_df,
            use_container_width=True,
            hide_index=True
        )

        if "mae" in performance_df.columns:
            best = (
                performance_df.sort_values("mae")
                .iloc[0]
            )

            c1, c2, c3 = st.columns(3)

            with c1:
                st.metric(
                    "Best Model MAE",
                    f'{float(best["mae"]):.2f}'
                )

            with c2:
                st.metric(
                    "Best Model RMSE",
                    f'{float(best["rmse"]):.2f}'
                )

            with c3:
                st.metric(
                    "Games Evaluated",
                    int(best["games_evaluated"])
                )

except Exception as exc:
    st.error(
        "Historical model performance "
        f"could not be loaded: {exc}"
    )


# ============================================================
# METHODOLOGY
# ============================================================

st.divider()

st.caption(
    "Frozen Forecast uses heuristic goal projections "
    "based on team shots, shooting percentages, "
    "and adjusted goalie save percentages. "
    "These are not shot-quality expected-goals estimates. "
    "Goalie reliability describes lineup verification, "
    "not predictive certainty. "
    "Saved EARLY and FINAL PREGAME projections remain "
    "unchanged after puck drop. "
    "No betting advantage is established."
)

if unavailable:
    with st.expander(
        "Matchups without available projections"
    ):
        for matchup in unavailable:
            st.write(matchup)




