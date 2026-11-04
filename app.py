
import html
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from engine import build_projections, fetch_schedule

ET = ZoneInfo("America/New_York")
MODEL_VERSION = "v1_goalie_adjusted"

st.set_page_config(
    page_title="Frozen Forecast | NHL Projection Center",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CSS = """
<style>
.stApp {
    background: radial-gradient(
        ellipse at 50% -12%,
        #16436b 0%,
        #081726 39%,
        #040d18 100%
    );
    color: #eaf6ff;
}
.block-container {
    max-width: 1700px;
    padding-top: 1.3rem;
}
h1,h2,h3 {color:#eaf6ff!important}

.ff-hero {
    border:1px solid #42baf2;
    border-radius:16px;
    background:linear-gradient(100deg,#081725,#0d3555 52%,#071521);
    padding:16px 24px;
    box-shadow:0 0 24px #008bff33;
}
.ff-sub {
    font-size:12px;
    letter-spacing:3px;
    color:#9adfff;
}
.ff-head {
    font-weight:1000;
    font-size:clamp(34px,5vw,65px);
    line-height:1.04;
    color:#e9f7ff;
    text-shadow:0 0 20px #27b9ff99;
}
.ff-head span {color:#44c7ff}

.ff-panel {
    background:#071c2ee8;
    border:1px solid #2a95c9;
    border-radius:13px;
    padding:15px;
    margin:0 0 14px;
    box-shadow:0 0 14px #009dff20;
}
.ff-panel h3 {
    margin:0 0 13px;
    font-size:17px;
    border-bottom:1px solid #235577;
    padding-bottom:10px;
}
.ff-num {
    font-size:42px;
    font-weight:900;
    line-height:1.2;
}
.ff-muted {
    color:#9db8cc;
    font-size:12px;
}
.ff-game {
    display:grid;
    grid-template-columns:
        35px 75px minmax(110px,1fr)
        62px 90px minmax(180px,1.5fr) 80px;
    gap:8px;
    align-items:center;
    border-bottom:1px solid #1b415e;
    padding:11px 3px;
    font-size:13px;
}
.ff-game img {
    width:30px;
    height:30px;
    vertical-align:middle;
    margin:0 4px;
}
.ff-total {
    background:#0b456b;
    border:1px solid #39c7ff;
    border-radius:7px;
    padding:7px;
    text-align:center;
    font-size:21px;
    font-weight:900;
    color:white;
}
.ff-pill {
    border:1px solid;
    border-radius:7px;
    text-align:center;
    padding:7px;
    font-weight:800;
    font-size:11px;
}
.ff-high {
    color:#5ff3a0;
    border-color:#18bb69;
    background:#06351e;
}
.ff-medium {
    color:#ffdc62;
    border-color:#dba926;
    background:#392c0c;
}
.ff-low,.ff-blocked {
    color:#ff8c99;
    border-color:#f24d63;
    background:#3a1020;
}
.ff-small {
    font-size:11px;
    color:#c7d9e8;
}
.ff-footer {
    color:#9cb7c9;
    font-size:12px;
    margin-top:14px;
}
.ff-state {
    font-size:10px;
    font-weight:800;
    letter-spacing:.6px;
}
.ff-upcoming {color:#70d9ff}
.ff-live {color:#ffce62}
.ff-final {color:#a5b6c8}
.ff-source {
    color:#90c7e7;
    font-size:10px;
}
@media(max-width:1100px) {
    .ff-game {
        grid-template-columns:
            25px 62px minmax(100px,1fr) 62px 76px;
    }
    .ff-goalies,.ff-rel {grid-column:3/6}
    .ff-game img {width:24px;height:24px}
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------
# HEADER
# --------------------------------------------------

app_dir = Path(__file__).resolve().parent

logo_candidates = [
    app_dir / "assets" / "frozen_forecast_logo.svg",
    app_dir / "frozen_forecast_logo.svg",
]

logo = next(
    (candidate for candidate in logo_candidates if candidate.is_file()),
    None,
)

left, right = st.columns([1, 5], vertical_alignment="center")

with left:
    if logo is not None:
        st.image(logo.read_text(encoding="utf-8"), width=140)
    else:
        st.markdown(
            '<div style="font-size:56px;text-align:center">🏒❄️</div>',
            unsafe_allow_html=True,
        )

with right:
    st.markdown(
        """
        <div class="ff-hero">
            <div class="ff-sub">NHL ANALYTICS • PROJECTION CENTER</div>
            <div class="ff-head">FROZEN <span>FORECAST</span></div>
            <div class="ff-sub">THE NUMBERS BEHIND THE ICE</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------
# CONTROLS
# --------------------------------------------------

now = datetime.now(ET)

with st.sidebar:
    st.header("❄️ Forecast controls")

    game_date = st.date_input(
        "Game date (Eastern Time)",
        value=now.date(),
    )

    verify = st.checkbox(
        "Verify goalies against NHL rosters",
        value=True,
    )

    if st.button("🔄 Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption(
        "Historical projections are loaded from Supabase. "
        "Saved pregame values are preserved after puck drop."
    )


# --------------------------------------------------
# SUPABASE HISTORICAL PREDICTIONS
# --------------------------------------------------

@st.cache_data(ttl=120)
def load_saved_predictions(date):
    from supabase import create_client

    url = st.secrets.get(
        "SUPABASE_URL",
        os.environ.get("SUPABASE_URL"),
    )

    key = st.secrets.get(
        "SUPABASE_KEY",
        os.environ.get("SUPABASE_KEY"),
    )

    if not url or not key:
        raise RuntimeError(
            "Supabase credentials are not configured in Streamlit."
        )

    client = create_client(url, key)

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
            "EARLY": 1,
        })
        .fillna(2)
    )

    saved = (
        saved.sort_values(
            ["priority", "saved_at"],
            ascending=[True, False],
        )
        .drop_duplicates(subset=["game_id"], keep="first")
        .reset_index(drop=True)
    )

    return saved


# --------------------------------------------------
# LIVE PROJECTIONS AND NHL SCHEDULE
# --------------------------------------------------

@st.cache_data(
    ttl=600,
    show_spinner="Collecting NHL statistics and starting goalies…",
)
def cached_projections(date, verify_rosters):
    return build_projections(date, verify_rosters)


@st.cache_data(ttl=120)
def cached_schedule(date):
    return fetch_schedule(date)


def game_status(game):
    state = str(game.get("gameState") or "").upper()

    if state in ("FINAL", "OFF"):
        return "FINAL"

    if state in ("LIVE", "CRIT"):
        return "LIVE"

    start = pd.to_datetime(
        game.get("startTimeUTC"),
        utc=True,
        errors="coerce",
    )

    if pd.notna(start) and start <= pd.Timestamp.now(tz="UTC"):
        return "LIVE"

    return "UPCOMING"


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def format_start(value):
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")

    if pd.isna(timestamp):
        return "TBD"

    return timestamp.tz_convert(ET).strftime("%I:%M %p ET")


def display_text(value, default="—"):
    if value is None or pd.isna(value):
        return default
    return str(value)


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

date_string = str(game_date)

try:
    schedule = cached_schedule(date_string)
except Exception as exc:
    st.error(f"Unable to retrieve NHL schedule: {exc}")
    st.stop()

saved_error = None

try:
    saved_df = load_saved_predictions(date_string)
except Exception as exc:
    saved_df = pd.DataFrame()
    saved_error = str(exc)

live_error = None

try:
    live_df, meta = cached_projections(date_string, verify)
except Exception as exc:
    live_df = pd.DataFrame()
    meta = {}
    live_error = str(exc)

if saved_error:
    st.warning(
        "Historical database could not be loaded: "
        f"{saved_error}"
    )

if live_error:
    st.warning(
        "Current live projections could not be refreshed: "
        f"{live_error}"
    )

st.caption(
    f'📅 {game_date.strftime("%A, %B %d, %Y")}'
    f'  ·  Viewed {now.strftime("%I:%M %p ET")}'
    "  ·  Live cache: up to 10 minutes"
)


# --------------------------------------------------
# MERGE SAVED AND LIVE PROJECTIONS
# --------------------------------------------------

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

rows = []
unavailable = []

for game in schedule:
    game_id = str(game.get("id"))

    away = game.get("awayTeam", {}).get("abbrev", "")
    home = game.get("homeTeam", {}).get("abbrev", "")

    status = game_status(game)

    saved = saved_lookup.get(game_id)
    live = live_lookup.get(game_id)

    # Historical pregame values take precedence once
    # a game is LIVE or FINAL.
    if status != "UPCOMING" and saved is not None:
        source = str(saved["snapshot_type"])

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
            "Goalie Reliability": display_text(
                saved.get("goalie_reliability"),
                "LOW",
            ),
            "Away Status": "Pregame",
            "Home Status": "Pregame",
            "Start ET": format_start(
                game.get("startTimeUTC")
            ),
            "Game Status": status,
            "Projection Source": source,
        }

    elif status == "UPCOMING" and live is not None:
        row = {
            "Game ID": game_id,
            "Away Code": away,
            "Home Code": home,
            "Away xG": safe_float(live["Away xG"]),
            "Home xG": safe_float(live["Home xG"]),
            "Projected Total": safe_float(
                live["Projected Total"]
            ),
            "Away Goalie": display_text(
                live["Away Goalie"]
            ),
            "Home Goalie": display_text(
                live["Home Goalie"]
            ),
            "Goalie Reliability": display_text(
                live["Goalie Reliability"],
                "LOW",
            ),
            "Away Status": display_text(
                live["Away Status"]
            ),
            "Home Status": display_text(
                live["Home Status"]
            ),
            "Start ET": format_start(
                game.get("startTimeUTC")
            ),
            "Game Status": status,
            "Projection Source": "LIVE PREGAME",
        }

    elif saved is not None:
        # Also use saved values when current goalie data
        # is unavailable for an upcoming game.
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
            "Goalie Reliability": display_text(
                saved.get("goalie_reliability"),
                "LOW",
            ),
            "Away Status": "Pregame",
            "Home Status": "Pregame",
            "Start ET": format_start(
                game.get("startTimeUTC")
            ),
            "Game Status": status,
            "Projection Source": str(
                saved["snapshot_type"]
            ),
        }

    else:
        unavailable.append(
            f"{away} @ {home}: no saved pregame projection"
        )
        continue

    rows.append(row)

df = pd.DataFrame(rows)

if df.empty:
    st.warning(
        "No pregame projections are available for this date."
    )

    if unavailable:
        st.write(*unavailable)

    st.stop()

df = (
    df.sort_values(
        "Projected Total",
        ascending=False,
    )
    .reset_index(drop=True)
)


# --------------------------------------------------
# DASHBOARD COUNTS
# --------------------------------------------------

counts = df["Goalie Reliability"].value_counts()

high = int(counts.get("HIGH", 0))
medium = int(counts.get("MEDIUM", 0))
low = int(counts.get("LOW", 0))
blocked = int(counts.get("BLOCKED", 0))

status_counts = df["Game Status"].value_counts()

upcoming = int(status_counts.get("UPCOMING", 0))
in_progress = int(status_counts.get("LIVE", 0))
final = int(status_counts.get("FINAL", 0))

saved_count = int(
    df["Projection Source"].isin(
        ["EARLY", "FINAL PREGAME"]
    ).sum()
)

side, center, insight = st.columns(
    [1.0, 2.8, 1.15],
    gap="small",
)


# --------------------------------------------------
# LEFT COLUMN
# --------------------------------------------------

with side:
    st.markdown(
        f"""
        <div class="ff-panel">
            <h3>🏒 TONIGHT'S SLATE</h3>
            <div class="ff-num">{len(df)} GAMES</div>
            <div class="ff-small">
                🔵 {upcoming} Upcoming<br>
                🟡 {in_progress} Live<br>
                ⚪ {final} Final
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    roster_checks = meta.get("rosters", {})

    roster_matches = sum(
        value == "MATCH"
        for value in roster_checks.values()
    )

    st.markdown(
        f"""
        <div class="ff-panel">
            <h3>📋 DATA CHECKS</h3>
            <div class="ff-small">
                Teams loaded: {meta.get("team_count", 0)}<br>
                Goalies loaded: {meta.get("goalie_count", 0)}<br>
                Official roster matches:
                {roster_matches} / {len(roster_checks)}<br>
                Scheduled matchups: {len(schedule)}<br>
                Matchups displayed: {len(df)}<br>
                Saved projections displayed: {saved_count}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------
# CENTER COLUMN
# --------------------------------------------------

with center:
    st.markdown(
        '<div class="ff-panel"><h3>🏒 NHL GOAL PROJECTIONS</h3></div>',
        unsafe_allow_html=True,
    )

    # Render each row as its own HTML block.
    # This avoids Streamlit interpreting the HTML as Markdown code.
    for i, game in df.iterrows():
        away = html.escape(str(game["Away Code"]))
        home = html.escape(str(game["Home Code"]))

        logo1 = (
            f"https://assets.nhle.com/logos/nhl/svg/"
            f"{away}_light.svg"
        )

        logo2 = (
            f"https://assets.nhle.com/logos/nhl/svg/"
            f"{home}_light.svg"
        )

        reliability = str(
            game["Goalie Reliability"]
        ).upper()

        if reliability not in (
            "HIGH", "MEDIUM", "LOW", "BLOCKED"
        ):
            reliability = "LOW"

        away_goalie = display_text(game["Away Goalie"])
        home_goalie = display_text(game["Home Goalie"])

        away_status = display_text(game["Away Status"])
        home_status = display_text(game["Home Status"])

        goalies = html.escape(
            f"{away_goalie} ({away_status}) / "
            f"{home_goalie} ({home_status})"
        )

        game_state = str(game["Game Status"])
        state_class = game_state.lower()

        source = html.escape(
            str(game["Projection Source"])
        )

        start_text = html.escape(
            str(game["Start ET"])
        )

        row_html = f"""
<div class="ff-game">
    <b>{i + 1:02d}</b>
    <span class="ff-small">
        {start_text}
        <span class="ff-state ff-{state_class}">
            {game_state}
        </span>
    </span>
    <span>
        <img src="{logo1}">
        <b>{away}</b> @
        <img src="{logo2}">
        <b>{home}</b>
    </span>
    <span class="ff-small">
        {game["Away xG"]:.2f} /
        {game["Home xG"]:.2f}
    </span>
    <span class="ff-total">
        {game["Projected Total"]:.2f}
    </span>
    <span class="ff-goalies ff-small">
        {goalies}
        <span class="ff-source">
            {source}
        </span>
    </span>
    <span class="ff-rel ff-pill ff-{reliability.lower()}">
        {reliability}
    </span>
</div>
"""
        st.markdown(
            row_html.strip(),
            unsafe_allow_html=True,
        )


# --------------------------------------------------
# RIGHT COLUMN
# --------------------------------------------------

with insight:
    st.markdown(
        f"""
        <div class="ff-panel">
            <h3>🥅 GOALIE RELIABILITY</h3>
            <div class="ff-num">{len(df)}</div>
            <div class="ff-small">
                🟢 High: {high}<br>
                🟡 Medium: {medium}<br>
                🔴 Low: {low}<br>
                ⛔ Blocked: {blocked}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    highest = df.iloc[0]
    lowest = df.iloc[-1]

    st.markdown(
        f"""
        <div class="ff-panel">
            <h3>🎯 KEY TAKEAWAYS</h3>
            <div class="ff-small">
                Average projected total:
                <b>{df["Projected Total"].mean():.2f}</b>
                <br><br>
                Highest:
                <b>{highest["Projected Total"]:.2f}</b>
                ({html.escape(str(highest["Away Code"]))}
                @ {html.escape(str(highest["Home Code"]))})
                <br><br>
                Lowest:
                <b>{lowest["Projected Total"]:.2f}</b>
                ({html.escape(str(lowest["Away Code"]))}
                @ {html.escape(str(lowest["Home Code"]))})
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.download_button(
        "⬇️ Export projections CSV",
        data=df.to_csv(index=False),
        file_name=f"frozen_forecast_{game_date}.csv",
        mime="text/csv",
        use_container_width=True,
    )


# --------------------------------------------------
# HISTORICAL DATABASE STATUS
# --------------------------------------------------

st.divider()

if saved_error is None:
    st.success(
        f"Frozen Forecast historical database connected. "
        f"{len(saved_lookup)} games have saved pregame predictions."
    )
else:
    st.warning(
        "Historical database unavailable. "
        "Only current pregame projections can be displayed."
    )

with st.expander("📸 Historical pregame snapshots"):
    if saved_df.empty:
        st.info("No saved predictions for this date.")
    else:
        st.dataframe(
            saved_df[
                [
                    "game_id",
                    "away_team",
                    "home_team",
                    "snapshot_type",
                    "projected_total",
                    "saved_at",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )


# --------------------------------------------------
# NOTES
# --------------------------------------------------

st.markdown(
    """
    <div class="ff-footer">
        Frozen Forecast uses heuristic goal projections based on
        team shots, shooting rates, and adjusted goalie save percentages.
        The xG labels are inherited from the development notebook and
        do not represent shot-quality expected goals.
        Saved EARLY and FINAL PREGAME predictions remain unchanged
        after puck drop. Goalie reliability describes lineup
        verification, not predictive certainty.
        No betting advantage is established.
    </div>
    """,
    unsafe_allow_html=True,
)

if unavailable:
    with st.expander("Matchups without available projections"):
        for matchup in unavailable:
            st.write(matchup)



