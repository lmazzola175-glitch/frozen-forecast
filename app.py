

import html
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
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
    background: radial-gradient(
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
        100deg, #081725, #0d3555 52%, #071521
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

.ff-game {
    display: grid;
    grid-template-columns:
        25px 82px minmax(125px, 1.2fr)
        65px 90px minmax(145px, 1.6fr) 80px;
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

.ff-low, .ff-blocked {
    color: #ff8c99;
    border-color: #f24d63;
    background: #3a1020;
}

.ff-state {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.5px;
}

.ff-upcoming { color: #70d9ff; }
.ff-live { color: #ffce62; }
.ff-final { color: #a5b6c8; }

.ff-source {
    color: #90c7e7;
    font-size: 10px;
    margin-top: 4px;
}

.ff-goalies {
    overflow-wrap: anywhere;
    line-height: 1.45;
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
            22px 72px minmax(110px, 1fr) 58px 76px;
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
            22px 70px minmax(105px, 1fr) 72px;
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
# UTILITIES
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

    return timestamp.tz_convert(ET).strftime("%I:%M %p ET")


def game_status(game):
    state = str(game.get("gameState") or "").upper()

    if state in ("FINAL", "OFF"):
        return "FINAL"

    if state in ("LIVE", "CRIT"):
        return "LIVE"

    start = pd.to_datetime(
        game.get("startTimeUTC"),
        utc=True,
        errors="coerce"
    )

    if pd.notna(start) and start <= pd.Timestamp.now(tz="UTC"):
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
# SUPABASE
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

    saved = pd.DataFrame(response.data or [])

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

    return (
        saved.sort_values(
            ["priority", "saved_at"],
            ascending=[True, False]
        )
        .drop_duplicates("game_id")
        .reset_index(drop=True)
    )


@st.cache_data(ttl=600)
def load_model_performance():
    client = get_supabase_client()

    response = (
        client.table("model_accuracy_summary")
        .select("*")
        .execute()
    )

    return pd.DataFrame(response.data or [])


@st.cache_data(ttl=600)
def load_game_accuracy_details():
    """
    Load completed-game prediction accuracy records.

    Pagination prevents truncation at the usual
    Supabase 1,000-row response limit.
    """
    client = get_supabase_client()

    records = []
    page_size = 1000

    for offset in range(0, 50000, page_size):
        response = (
            client.table("game_accuracy_details")
            .select("*")
            .order("game_date", desc=True)
            .range(
                offset,
                offset + page_size - 1
            )
            .execute()
        )

        batch = response.data or []
        records.extend(batch)

        if len(batch) < page_size:
            break

    return pd.DataFrame(records)


# ============================================================
# NHL DATA
# ============================================================

@st.cache_data(ttl=600)
def cached_projections(date, verify_rosters):
    return build_projections(date, verify_rosters)


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
        path for path in logo_candidates
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
            '<div style="font-size:60px;'
            'text-align:center">🏒❄️</div>'
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
    saved_df = load_saved_predictions(date_string)
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
            ),
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
            ),
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
        "No projections are available for this date."
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
    df["Goalie Reliability"].value_counts()
)

high = int(
    reliability_counts.get("HIGH", 0)
)

medium = int(
    reliability_counts.get("MEDIUM", 0)
)

low = int(
    reliability_counts.get("LOW", 0)
)

blocked = int(
    reliability_counts.get("BLOCKED", 0)
)

status_counts = (
    df["Game Status"].value_counts()
)

upcoming = int(
    status_counts.get("UPCOMING", 0)
)

in_progress = int(
    status_counts.get("LIVE", 0)
)

final = int(
    status_counts.get("FINAL", 0)
)

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
# CENTER — NHL MATCHUPS
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
        away = escape(
            game["Away Code"]
        )

        home = escape(
            game["Home Code"]
        )

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

    average = (
        df["Projected Total"].mean()
    )

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
        file_name=(
            f"frozen_forecast_{game_date}.csv"
        ),
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
            col for col in columns
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
    "Frozen Forecast evaluates frozen pregame "
    "goal projections against official NHL final scores."
)

try:
    performance_df = load_model_performance()

    if performance_df.empty:
        st.info(
            "Waiting for completed games with matching "
            "pregame predictions. Accuracy metrics and "
            "charts will populate after final scores "
            "are collected."
        )

    else:
        performance_df = (
            performance_df.copy()
        )

        numeric_cols = [
            "games_evaluated",
            "mae",
            "rmse",
            "bias",
            "average_projected_total",
            "average_actual_total",
        ]

        for col in numeric_cols:
            if col in performance_df.columns:
                performance_df[col] = pd.to_numeric(
                    performance_df[col],
                    errors="coerce"
                )

        valid = performance_df.dropna(
            subset=[
                "mae",
                "rmse",
                "games_evaluated"
            ]
        ).copy()

        if valid.empty:
            st.info(
                "Performance records are present, "
                "but valid metrics are not available yet."
            )

        else:
            best = (
                valid.sort_values(
                    [
                        "mae",
                        "games_evaluated"
                    ],
                    ascending=[
                        True,
                        False
                    ]
                )
                .iloc[0]
            )

            st.caption(
                "Summary cards show the lowest observed "
                "MAE among available model/snapshot groups. "
                "Small samples may be misleading."
            )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Games Evaluated",
                f'{int(best["games_evaluated"]):,}'
            )

            c2.metric(
                "Mean Absolute Error",
                f'{best["mae"]:.2f} goals'
            )

            c3.metric(
                "Root Mean Squared Error",
                f'{best["rmse"]:.2f} goals'
            )

            c4.metric(
                "Prediction Bias",
                (
                    f'{best["bias"]:+.2f} goals'
                    if pd.notna(best.get("bias"))
                    else "—"
                )
            )

            st.caption(
                f'Model: '
                f'{best.get("model_version", "Unknown")}'
                f' | Snapshot: '
                f'{best.get("snapshot_type", "Unknown")}'
            )

            st.markdown(
                "#### EARLY vs. FINAL PREGAME"
            )

            comparison = valid[
                valid["snapshot_type"].isin(
                    [
                        "EARLY",
                        "FINAL PREGAME"
                    ]
                )
            ].copy()

            if comparison.empty:
                st.info(
                    "No snapshot performance "
                    "comparisons are available."
                )

            else:
                display_columns = [
                    "model_version",
                    "snapshot_type",
                    "games_evaluated",
                    "mae",
                    "rmse",
                    "bias",
                    "average_projected_total",
                    "average_actual_total",
                ]

                display_columns = [
                    col for col in display_columns
                    if col in comparison.columns
                ]

                st.dataframe(
                    comparison[display_columns],
                    use_container_width=True,
                    hide_index=True
                )

                chart_data = comparison[
                    [
                        "model_version",
                        "snapshot_type",
                        "mae"
                    ]
                ].copy()

                chart_data["Group"] = (
                    chart_data["snapshot_type"].astype(str)
                    + " | "
                    + chart_data["model_version"].astype(str)
                )

                st.markdown(
                    "#### Mean Absolute Error by Snapshot"
                )

                st.bar_chart(
                    chart_data.set_index("Group")[["mae"]],
                    y_label="Mean absolute error (goals)"
                )

            st.markdown(
                "#### How to Read These Metrics"
            )

            st.caption(
                "MAE is the average absolute difference "
                "between projected and actual total goals. "
                "RMSE penalizes larger errors more heavily. "
                "Positive bias means the model tends to "
                "project too many goals; negative bias "
                "means it tends to project too few."
            )

except Exception as exc:
    st.error(
        "Historical model performance "
        f"could not be loaded: {exc}"
    )


# ============================================================
# V1 VS. V2 — FAIR HEAD-TO-HEAD MODEL COMPARISON
# ============================================================

st.divider()
st.html("""
<div class="ff-section-title">
    🧪 V1 VS. V2 MODEL COMPARISON
</div>
""")
st.caption(
    "A fair head-to-head comparison uses only completed games with "
    "predictions from both models at the same snapshot stage. "
    "Lower MAE and RMSE are better."
)

try:
    head_to_head_source = load_game_accuracy_details()
except Exception as exc:
    head_to_head_source = pd.DataFrame()
    st.warning(f"Model comparison could not load: {exc}")

if head_to_head_source.empty:
    st.info("No completed games with saved model predictions are available yet.")
else:
    h2h = head_to_head_source.copy()
    required = {
        "game_id", "game_date", "model_version", "snapshot_type",
        "projected_total", "actual_total"
    }
    missing = required - set(h2h.columns)

    if missing:
        st.warning("Model comparison is missing required fields: " + ", ".join(sorted(missing)))
    else:
        h2h["game_id"] = h2h["game_id"].astype(str)
        h2h["game_date"] = pd.to_datetime(h2h["game_date"], errors="coerce")
        for field in ("projected_total", "actual_total"):
            h2h[field] = pd.to_numeric(h2h[field], errors="coerce")
        h2h = h2h.dropna(
            subset=["game_date", "projected_total", "actual_total"]
        ).copy()

        model_names = sorted(h2h["model_version"].dropna().astype(str).unique())
        snapshot_names = [
            snap for snap in ("FINAL PREGAME", "EARLY")
            if snap in set(h2h["snapshot_type"].dropna())
        ]

        if len(model_names) < 2 or not snapshot_names:
            st.info("At least two models with matching completed-game predictions are required.")
        else:
            mc1, mc2, mc3 = st.columns([1.2, 1.2, 1])
            with mc1:
                first_model = st.selectbox(
                    "First model", model_names,
                    index=model_names.index("v1_goalie_adjusted")
                    if "v1_goalie_adjusted" in model_names else 0,
                    key="h2h_first_model",
                )
            with mc2:
                second_model = st.selectbox(
                    "Second model", model_names,
                    index=model_names.index("v2_recent5_w20")
                    if "v2_recent5_w20" in model_names else min(1, len(model_names) - 1),
                    key="h2h_second_model",
                )
            with mc3:
                selected_stage = st.selectbox(
                    "Snapshot stage", snapshot_names, key="h2h_snapshot"
                )

            if first_model == second_model:
                st.info("Choose two different models to compare.")
            else:
                comparison_data = h2h.loc[
                    h2h["model_version"].isin([first_model, second_model])
                    & h2h["snapshot_type"].eq(selected_stage)
                ].copy()
                if "saved_at" in comparison_data.columns:
                    comparison_data = comparison_data.sort_values("saved_at")
                comparison_data = comparison_data.drop_duplicates(
                    ["game_id", "model_version"], keep="last"
                )

                # Pivot on game ID to guarantee exactly the same game sample.
                projections = comparison_data.pivot(
                    index="game_id", columns="model_version", values="projected_total"
                )
                common_ids = projections.dropna(subset=[first_model, second_model]).index
                common = comparison_data.loc[
                    comparison_data["game_id"].isin(common_ids)
                ].copy()

                if common.empty:
                    st.info(
                        "No completed games have predictions from both models "
                        "for the selected snapshot stage."
                    )
                else:
                    game_info = (
                        common.sort_values("game_date")
                        .drop_duplicates("game_id")
                        .set_index("game_id")
                    )
                    paired = pd.DataFrame(index=common_ids)
                    paired["game_date"] = game_info.loc[common_ids, "game_date"]
                    paired["actual_total"] = game_info.loc[common_ids, "actual_total"]
                    if "matchup" in game_info.columns:
                        paired["matchup"] = game_info.loc[common_ids, "matchup"]
                    else:
                        paired["matchup"] = common_ids.astype(str)
                    paired["first_prediction"] = projections.loc[common_ids, first_model]
                    paired["second_prediction"] = projections.loc[common_ids, second_model]
                    paired = paired.sort_values(["game_date", "matchup"]).reset_index()
                    paired["first_error"] = paired["first_prediction"] - paired["actual_total"]
                    paired["second_error"] = paired["second_prediction"] - paired["actual_total"]
                    paired["first_absolute"] = paired["first_error"].abs()
                    paired["second_absolute"] = paired["second_error"].abs()
                    n = len(paired)
                    first_mae = paired["first_absolute"].mean()
                    second_mae = paired["second_absolute"].mean()
                    first_rmse = np.sqrt((paired["first_error"] ** 2).mean())
                    second_rmse = np.sqrt((paired["second_error"] ** 2).mean())
                    first_bias = paired["first_error"].mean()
                    second_bias = paired["second_error"].mean()

                    st.markdown("#### Head-to-Head Results")
                    h1, h2, h3 = st.columns(3)
                    h1.metric("Matched completed games", f"{n:,}")
                    h2.metric(f"{first_model} MAE", f"{first_mae:.3f} goals")
                    h3.metric(f"{second_model} MAE", f"{second_mae:.3f} goals")

                    if np.isclose(first_mae, second_mae):
                        st.info("Both models are tied on mean absolute error for this sample.")
                    else:
                        winner = first_model if first_mae < second_mae else second_model
                        difference = abs(first_mae - second_mae)
                        st.caption(
                            f"Current MAE leader: {winner} by {difference:.3f} goals per game. "
                            "A small sample is not proof of future predictive superiority."
                        )

                    summary = pd.DataFrame([
                        {"Model": first_model, "Games": n, "MAE": first_mae,
                         "RMSE": first_rmse, "Bias": first_bias},
                        {"Model": second_model, "Games": n, "MAE": second_mae,
                         "RMSE": second_rmse, "Bias": second_bias},
                    ])
                    st.dataframe(
                        summary.style.format({"MAE": "{:.3f}", "RMSE": "{:.3f}", "Bias": "{:+.3f}"}),
                        use_container_width=True, hide_index=True,
                    )

                    st.markdown("#### Cumulative Mean Absolute Error")
                    cumulative = pd.DataFrame({
                        "Completed games": np.arange(1, n + 1),
                        first_model: paired["first_absolute"].cumsum().to_numpy() / np.arange(1, n + 1),
                        second_model: paired["second_absolute"].cumsum().to_numpy() / np.arange(1, n + 1),
                    })
                    st.line_chart(
                        cumulative.set_index("Completed games"),
                        y_label="Cumulative MAE (goals)",
                    )
                    st.caption(
                        "Each point includes one more completed game, in date/matchup order. "
                        "Both lines always use the same games."
                    )

                    st.markdown("#### Evaluation Sample Progress")
                    next_target = next((target for target in (30, 50, 100) if n < target), None)
                    if next_target is None:
                        st.success(f"{n} paired games evaluated — 100-game milestone reached.")
                    else:
                        st.progress(min(n / next_target, 1.0))
                        st.caption(f"{n} of {next_target} paired games toward the next milestone.")

                    st.markdown("#### Game-by-Game Model Comparison")
                    paired_display = paired[[
                        "game_date", "matchup", "actual_total",
                        "first_prediction", "second_prediction",
                        "first_absolute", "second_absolute",
                    ]].copy()
                    paired_display["game_date"] = paired_display["game_date"].dt.strftime("%Y-%m-%d")
                    paired_display.columns = [
                        "Date", "Matchup", "Actual Total",
                        f"{first_model} Projection", f"{second_model} Projection",
                        f"{first_model} Absolute Error", f"{second_model} Absolute Error",
                    ]
                    st.dataframe(
                        paired_display, use_container_width=True, hide_index=True,
                        column_config={
                            name: st.column_config.NumberColumn(name, format="%.2f")
                            for name in paired_display.columns[3:]
                        },
                    )
                    st.download_button(
                        "⬇️ Export Head-to-Head Comparison CSV",
                        data=paired_display.to_csv(index=False),
                        file_name="frozen_forecast_model_comparison.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )


# ============================================================
# GAME-BY-GAME ACCURACY TRACKER
# ============================================================

st.divider()

st.html("""
<div class="ff-section-title">
    🎯 GAME-BY-GAME ACCURACY TRACKER
</div>
""")

st.caption(
    "Compare frozen pregame predictions with official "
    "NHL final scores. Filters and rankings use "
    "completed games only."
)

try:
    details = load_game_accuracy_details()

except Exception as exc:
    details = pd.DataFrame()

    st.warning(
        "Game-by-game accuracy data "
        f"could not be loaded: {exc}"
    )


if details.empty:
    st.info(
        "No completed games with matching saved "
        "predictions are available yet."
    )

else:
    details = details.copy()

    numeric_columns = [
        "projected_total",
        "actual_total",
        "absolute_error",
        "prediction_error",
    ]

    for column in numeric_columns:
        details[column] = pd.to_numeric(
            details[column],
            errors="coerce"
        )

    details["game_date"] = pd.to_datetime(
        details["game_date"],
        errors="coerce"
    )

    details = details.dropna(
        subset=[
            "game_date",
            "projected_total",
            "actual_total",
            "absolute_error",
        ]
    )

    if details.empty:
        st.info(
            "No valid completed-game accuracy "
            "records are available yet."
        )

    else:

        # ====================================================
        # FILTER OPTIONS
        # ====================================================

        model_options = sorted(
            details["model_version"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        available_snapshots = (
            details["snapshot_type"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        snapshot_options = [
            item
            for item in (
                "FINAL PREGAME",
                "EARLY"
            )
            if item in available_snapshots
        ]

        snapshot_options += sorted(
            set(available_snapshots)
            - set(snapshot_options)
        )

        f1, f2, f3 = st.columns(
            [1.2, 1.2, 1]
        )

        with f1:
            selected_model = st.selectbox(
                "Model version",
                model_options,
                key="accuracy_model"
            )

        with f2:
            selected_snapshot = st.selectbox(
                "Snapshot",
                snapshot_options,
                key="accuracy_snapshot"
            )

        with f3:
            dates = sorted(
                details["game_date"]
                .dt.date
                .unique()
                .tolist(),
                reverse=True
            )

            date_choice = st.selectbox(
                "Game date",
                ["All dates"] + dates,
                key="accuracy_date"
            )

        # ====================================================
        # APPLY FILTERS
        # ====================================================

        filtered = details.loc[
            (
                details["model_version"].astype(str)
                == selected_model
            )
            &
            (
                details["snapshot_type"].astype(str)
                == selected_snapshot
            )
        ].copy()

        if date_choice != "All dates":
            filtered = filtered.loc[
                filtered["game_date"].dt.date
                == date_choice
            ].copy()

        if "saved_at" in filtered.columns:
            filtered = filtered.sort_values(
                "saved_at",
                ascending=False
            )

        filtered = filtered.drop_duplicates(
            subset=["game_id"],
            keep="first"
        )

        filtered["prediction_error"] = (
            filtered["projected_total"]
            - filtered["actual_total"]
        )

        filtered["absolute_error"] = (
            filtered["prediction_error"].abs()
        )

        if filtered.empty:
            st.info(
                "No completed games match these filters."
            )

        else:

            # ================================================
            # ACCURACY METRICS
            # ================================================

            count = len(filtered)

            mae = (
                filtered["absolute_error"].mean()
            )

            rmse = np.sqrt(
                (
                    filtered["prediction_error"] ** 2
                ).mean()
            )

            bias = (
                filtered["prediction_error"].mean()
            )

            k1, k2, k3, k4 = st.columns(4)

            k1.metric(
                "Completed Games",
                f"{count:,}"
            )

            k2.metric(
                "Mean Absolute Error",
                f"{mae:.2f} goals"
            )

            k3.metric(
                "RMSE",
                f"{rmse:.2f} goals"
            )

            k4.metric(
                "Prediction Bias",
                f"{bias:+.2f} goals"
            )

            # ================================================
            # BEST AND WORST PREDICTIONS
            # ================================================

            best_game = filtered.loc[
                filtered["absolute_error"].idxmin()
            ]

            worst_game = filtered.loc[
                filtered["absolute_error"].idxmax()
            ]

            b1, b2 = st.columns(2)

            with b1:
                st.success(
                    f'Closest prediction: '
                    f'{best_game["matchup"]} — '
                    f'{best_game["absolute_error"]:.2f} '
                    f'goals off'
                )

            with b2:
                st.warning(
                    f'Largest miss: '
                    f'{worst_game["matchup"]} — '
                    f'{worst_game["absolute_error"]:.2f} '
                    f'goals off'
                )

            # ================================================
            # INDIVIDUAL GAME RESULTS
            # ================================================

            st.markdown(
                "#### Individual Game Results"
            )

            show = filtered.sort_values(
                [
                    "game_date",
                    "absolute_error"
                ],
                ascending=[
                    False,
                    False
                ]
            ).copy()

            show["game_date"] = (
                show["game_date"]
                .dt.strftime("%Y-%m-%d")
            )

            column_names = {
                "game_date": "Date",
                "matchup": "Matchup",
                "projected_total": "Projected",
                "actual_total": "Actual",
                "prediction_error": "Signed Error",
                "absolute_error": "Absolute Error",
                "prediction_direction": "Direction",
                "goalie_reliability": "Goalie Reliability",
            }

            available_columns = [
                col for col in column_names
                if col in show.columns
            ]

            visible = (
                show[available_columns]
                .rename(columns=column_names)
            )

            st.dataframe(
                visible.style.format({
                    "Projected": "{:.2f}",
                    "Actual": "{:.0f}",
                    "Signed Error": "{:+.2f}",
                    "Absolute Error": "{:.2f}",
                }),
                use_container_width=True,
                hide_index=True
            )

            # ================================================
            # NEW: PROJECTED VS ACTUAL GOALS
            # ================================================

            st.markdown(
                "#### Projected vs. Actual Goals"
            )

            comparison_chart = filtered[
                [
                    "game_date",
                    "matchup",
                    "projected_total",
                    "actual_total"
                ]
            ].copy()

            comparison_chart["Game"] = (
                comparison_chart["game_date"]
                .dt.strftime("%m/%d")
                + " | "
                + comparison_chart["matchup"].astype(str)
            )

            comparison_chart = (
                comparison_chart.sort_values(
                    [
                        "game_date",
                        "matchup"
                    ]
                )
            )

            comparison_chart = (
                comparison_chart.rename(
                    columns={
                        "projected_total":
                            "Projected Goals",
                        "actual_total":
                            "Actual Goals"
                    }
                )
            )

            st.line_chart(
                comparison_chart.set_index("Game")[
                    [
                        "Projected Goals",
                        "Actual Goals"
                    ]
                ],
                y_label="Total Goals"
            )

            st.caption(
                "The projected line represents Frozen "
                "Forecast's pregame estimate. "
                "The actual line represents the official "
                "final total. Larger gaps indicate "
                "larger prediction errors."
            )

            # ================================================
            # PREDICTION ERROR BY MATCHUP
            # ================================================

            st.markdown(
                "#### Prediction Error by Matchup"
            )

            chart = show.sort_values(
                "absolute_error",
                ascending=False
            ).copy()

            chart["Game"] = (
                chart["game_date"].astype(str)
                + " · "
                + chart["matchup"].astype(str)
            )

            chart = (
                chart.set_index("Game")[
                    ["absolute_error"]
                ]
                .rename(
                    columns={
                        "absolute_error":
                            "Absolute Error (goals)"
                    }
                )
            )

            st.bar_chart(
                chart,
                horizontal=True
            )

            # ================================================
            # EXPORT ACCURACY DATA
            # ================================================

            st.download_button(
                "⬇️ Export Game-by-Game Accuracy CSV",
                data=show.to_csv(index=False),
                file_name=(
                    "frozen_forecast_game_accuracy.csv"
                ),
                mime="text/csv",
                use_container_width=True
            )

            st.caption(
                "Signed error = projected minus actual. "
                "Positive means overprediction; negative "
                "means underprediction. Snapshot comparisons "
                "should use the same completed games for "
                "a fair head-to-head evaluation."
            )


# ============================================================
# WINNER PREDICTION ACCURACY TRACKER
# ============================================================

@st.cache_data(ttl=600)
def load_winner_prediction_records():
    """Read frozen predictions and final scores; never update either."""
    client = get_supabase_client()

    def fetch_all(table_name, columns="*"):
        records = []
        page_size = 1000
        for offset in range(0, 100000, page_size):
            response = (
                client.table(table_name)
                .select(columns)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = response.data or []
            records.extend(batch)
            if len(batch) < page_size:
                break
        return pd.DataFrame(records)

    predictions = fetch_all("predictions")
    if predictions.empty:
        return pd.DataFrame(), "No saved predictions yet."

    required_predictions = {
        "game_id", "game_date", "model_version", "snapshot_type",
        "away_team", "home_team", "away_win_probability",
        "home_win_probability", "projected_winner",
    }
    missing = required_predictions - set(predictions.columns)
    if missing:
        return pd.DataFrame(), (
            "Prediction fields missing: " + ", ".join(sorted(missing))
        )

    # The score table name can be overridden in Streamlit secrets.
    # Try common names for compatibility with existing Supabase setups.
    configured = st.secrets.get(
        "RESULTS_TABLE", os.environ.get("RESULTS_TABLE", "")
    )
    candidates = list(dict.fromkeys(
        [name for name in (configured, "results", "game_results", "nhl_results") if name]
    ))
    scores = None
    errors = []
    for table_name in candidates:
        try:
            candidate = fetch_all(table_name)
            if candidate.empty:
                scores = candidate
                break
            if {"game_id", "away_goals", "home_goals"}.issubset(candidate.columns):
                scores = candidate
                break
            errors.append(f"{table_name}: missing game_id/away_goals/home_goals")
        except Exception as exc:
            errors.append(f"{table_name}: {exc}")

    if scores is None:
        return pd.DataFrame(), (
            "Could not find the completed-game score table. "
            "Set RESULTS_TABLE in Streamlit secrets to its exact name. "
            + " | ".join(errors)
        )
    if scores.empty:
        return pd.DataFrame(), "Waiting for completed-game scores."

    scores = scores.copy()
    scores["game_id"] = scores["game_id"].astype(str)
    scores["away_goals"] = pd.to_numeric(scores["away_goals"], errors="coerce")
    scores["home_goals"] = pd.to_numeric(scores["home_goals"], errors="coerce")
    scores = scores.dropna(subset=["away_goals", "home_goals"])
    if "updated_at" in scores.columns:
        scores = scores.sort_values("updated_at")
    scores = scores.drop_duplicates("game_id", keep="last")

    predictions = predictions.copy()
    predictions["game_id"] = predictions["game_id"].astype(str)
    for col in ("away_win_probability", "home_win_probability"):
        predictions[col] = pd.to_numeric(predictions[col], errors="coerce")
    if "saved_at" in predictions.columns:
        predictions = predictions.sort_values("saved_at")
    predictions = predictions.drop_duplicates(
        ["game_id", "model_version", "snapshot_type"], keep="last"
    )

    joined = predictions.merge(
        scores[["game_id", "away_goals", "home_goals"]],
        on="game_id", how="inner", validate="many_to_one"
    )
    if joined.empty:
        return pd.DataFrame(), "No completed games match saved predictions yet."

    # NHL official final scores include OT/SO winners. Do not infer a
    # winner from tied scores, if such a record is accidentally present.
    joined = joined.loc[joined["away_goals"] != joined["home_goals"]].copy()
    joined = joined.dropna(subset=["away_win_probability", "home_win_probability"])
    joined = joined.loc[
        joined["away_win_probability"].between(0, 1)
        & joined["home_win_probability"].between(0, 1)
        & ((joined["away_win_probability"] + joined["home_win_probability"] - 1).abs() < 0.01)
    ].copy()
    if joined.empty:
        return pd.DataFrame(), "Completed scores exist, but no valid winner probabilities match."

    joined["actual_winner"] = np.where(
        joined["away_goals"] > joined["home_goals"],
        joined["away_team"], joined["home_team"]
    )
    joined["actual_away_win"] = (
        joined["actual_winner"] == joined["away_team"]
    ).astype(int)
    joined["winner_correct"] = np.where(
        joined["projected_winner"].isin(["TOSS-UP", "TIE", ""])
        | joined["projected_winner"].isna(),
        np.nan,
        (joined["projected_winner"] == joined["actual_winner"]).astype(float)
    )
    joined["brier_score"] = (
        joined["away_win_probability"] - joined["actual_away_win"]
    ) ** 2
    joined["matchup"] = joined["away_team"] + " @ " + joined["home_team"]
    return joined, None


st.divider()
st.html('''
<div class="ff-section-title">🏆 WINNER PREDICTION ACCURACY</div>
''')
st.caption(
    "Compare frozen NHL winner picks against official final scores. "
    "Brier score measures probability accuracy (lower is better). "
    "Only completed games with saved probabilities are included."
)

try:
    winner_records, winner_message = load_winner_prediction_records()
except Exception as exc:
    winner_records = pd.DataFrame()
    winner_message = f"Unable to load winner accuracy: {exc}"

if winner_records.empty:
    st.info(winner_message or "No completed winner predictions available yet.")
else:
    winner_models = sorted(winner_records["model_version"].dropna().unique().tolist())
    winner_stages = [
        x for x in ("FINAL PREGAME", "EARLY")
        if x in set(winner_records["snapshot_type"].dropna())
    ]
    if not winner_stages:
        st.info("No EARLY or FINAL PREGAME winner predictions are available.")
    else:
        stage = st.selectbox(
            "Winner prediction snapshot", winner_stages,
            key="winner_accuracy_stage"
        )
        staged = winner_records.loc[
            winner_records["snapshot_type"].eq(stage)
        ].copy()

        # Fair comparison: every displayed model uses the same games.
        if len(winner_models) > 1:
            game_sets = [
                set(staged.loc[staged["model_version"].eq(m), "game_id"])
                for m in winner_models
            ]
            common_games = set.intersection(*game_sets) if game_sets else set()
            comparison_rows = staged.loc[staged["game_id"].isin(common_games)].copy()
        else:
            comparison_rows = staged.copy()
            common_games = set(comparison_rows["game_id"])

        st.markdown("#### Model Winner Accuracy — Matched Games")
        if comparison_rows.empty:
            st.info("No completed games have valid winner probabilities for every model at this stage.")
        else:
            summaries = []
            for model, group in comparison_rows.groupby("model_version"):
                graded = group.dropna(subset=["winner_correct"])
                summaries.append({
                    "Model": model,
                    "Matched games": group["game_id"].nunique(),
                    "Graded picks": len(graded),
                    "Correct picks": int(graded["winner_correct"].sum()),
                    "Win accuracy": graded["winner_correct"].mean() if len(graded) else np.nan,
                    "Brier score": group["brier_score"].mean(),
                })
            summary_df = pd.DataFrame(summaries).sort_values("Brier score")
            st.dataframe(
                summary_df.style.format({
                    "Win accuracy": "{:.1%}", "Brier score": "{:.4f}"
                }, na_rep="—"),
                use_container_width=True, hide_index=True
            )
            st.caption(
                f"Matched sample: {len(common_games)} completed games. "
                "TOSS-UP predictions are ungraded for winner accuracy, "
                "but still contribute to Brier score."
            )

        st.markdown("#### Individual Winner Predictions")
        selected_winner_model = st.selectbox(
            "Model to inspect", winner_models, key="winner_accuracy_model"
        )
        individual = staged.loc[
            staged["model_version"].eq(selected_winner_model)
        ].copy()
        if individual.empty:
            st.info("No completed winner predictions for this model and snapshot.")
        else:
            graded = individual.dropna(subset=["winner_correct"])
            w1, w2, w3, w4 = st.columns(4)
            w1.metric("Completed games", f"{len(individual):,}")
            w2.metric("Correct picks", f"{int(graded['winner_correct'].sum()):,} / {len(graded):,}")
            w3.metric(
                "Winner accuracy",
                f"{graded['winner_correct'].mean():.1%}" if len(graded) else "—"
            )
            w4.metric("Brier score", f"{individual['brier_score'].mean():.4f}")

            individual["Result"] = individual["winner_correct"].map(
                {1.0: "CORRECT", 0.0: "INCORRECT"}
            ).fillna("TOSS-UP")
            individual["Away win %"] = 100 * individual["away_win_probability"]
            individual["Home win %"] = 100 * individual["home_win_probability"]
            individual["Final score"] = (
                individual["away_goals"].astype(int).astype(str) + "–"
                + individual["home_goals"].astype(int).astype(str)
            )
            show_columns = [
                "game_date", "matchup", "Final score", "projected_winner",
                "actual_winner", "Away win %", "Home win %", "Result", "brier_score"
            ]
            visible = individual[show_columns].rename(columns={
                "game_date": "Date", "matchup": "Matchup",
                "projected_winner": "Projected winner",
                "actual_winner": "Actual winner", "brier_score": "Brier score"
            }).sort_values(["Date", "Matchup"], ascending=[False, True])
            st.dataframe(
                visible.style.format({
                    "Away win %": "{:.1f}%", "Home win %": "{:.1f}%",
                    "Brier score": "{:.4f}"
                }),
                use_container_width=True, hide_index=True
            )
            st.download_button(
                "⬇️ Export Winner Accuracy CSV",
                data=visible.to_csv(index=False),
                file_name=f"frozen_forecast_winners_{selected_winner_model}_{stage.replace(' ', '_')}.csv",
                mime="text/csv", use_container_width=True
            )

st.caption(
    "Win probabilities use a Poisson scoring model with a 50/50 split "
    "of regulation ties. These probabilities are not yet historically calibrated. "
    "Winner accuracy and goal-total MAE measure different prediction tasks."
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







