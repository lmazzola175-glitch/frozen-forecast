
import html
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client
from engine import build_projections


# ============================================================
# CONFIGURATION
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
# SUPABASE CONNECTION
# ============================================================

@st.cache_resource
def get_supabase_client():
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["key"],
    )


def check_database_connection():
    try:
        client = get_supabase_client()

        client.table("predictions").select(
            "id"
        ).limit(1).execute()

        return True, "Connected"

    except Exception as exc:
        return False, str(exc)


# ============================================================
# HISTORICAL PREGAME SNAPSHOTS
# ============================================================

def save_early_predictions(projections, selected_date):
    """
    Save fresh EARLY pregame predictions to Supabase.

    Existing snapshots are never overwritten.
    """

    now = datetime.now(timezone.utc)

    if selected_date != now.astimezone(ET).date():
        return 0, 0, [
            "Select today's date to save new predictions."
        ]

    if projections.empty:
        return 0, 0, [
            "No eligible pregame projections."
        ]

    records = []
    issues = []

    for _, game in projections.iterrows():

        game_id = str(game["Game ID"])

        try:
            start = pd.to_datetime(
                game["Start UTC"],
                utc=True,
            ).to_pydatetime()

            calculated = pd.to_datetime(
                game["Calculated At UTC"],
                utc=True,
            ).to_pydatetime()

            if start <= now:
                issues.append(
                    f"{game_id}: game already started"
                )
                continue

            if calculated > now:
                issues.append(
                    f"{game_id}: future calculation timestamp"
                )
                continue

            if (now - calculated).total_seconds() > 900:
                issues.append(
                    f"{game_id}: calculation is stale"
                )
                continue

            if calculated >= start:
                issues.append(
                    f"{game_id}: not a pregame calculation"
                )
                continue

            if (
                str(game["Goalie Reliability"]).upper()
                == "BLOCKED"
            ):
                issues.append(
                    f"{game_id}: roster verification blocked"
                )
                continue

            records.append({
                "game_id": game_id,
                "game_date": str(game["Game Date"])[:10],
                "model_version": MODEL_VERSION,
                "snapshot_type": "EARLY",
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

        except (KeyError, TypeError, ValueError) as exc:
            issues.append(
                f"{game_id}: {exc}"
            )

    if not records:
        return 0, 0, issues

    client = get_supabase_client()

    game_ids = [
        record["game_id"]
        for record in records
    ]

    response = (
        client.table("predictions")
        .select("game_id")
        .eq("model_version", MODEL_VERSION)
        .eq("snapshot_type", "EARLY")
        .in_("game_id", game_ids)
        .execute()
    )

    existing_ids = {
        str(row["game_id"])
        for row in (response.data or [])
    }

    saved = 0
    skipped = 0

    for record in records:

        if record["game_id"] in existing_ids:
            skipped += 1
            continue

        start = pd.to_datetime(
            record["scheduled_start"],
            utc=True,
        ).to_pydatetime()

        if start <= datetime.now(timezone.utc):
            issues.append(
                f"{record['game_id']}: puck drop reached"
            )
            skipped += 1
            continue

        try:
            client.table("predictions").insert(
                record
            ).execute()

            saved += 1

        except Exception as exc:

            if (
                "23505" in str(exc)
                or "duplicate key" in str(exc).lower()
            ):
                skipped += 1
            else:
                issues.append(
                    f"{record['game_id']}: database insert failed"
                )

    return saved, skipped, issues


# ============================================================
# MODEL PERFORMANCE DATA
# ============================================================

@st.cache_data(ttl=300)
def load_model_performance():

    client = get_supabase_client()

    response = (
        client.table("model_accuracy_summary")
        .select(
            "model_version,"
            "snapshot_type,"
            "games_evaluated,"
            "mae,"
            "rmse,"
            "bias,"
            "average_projected_total,"
            "average_actual_total"
        )
        .execute()
    )

    return pd.DataFrame(
        response.data or []
    )


def render_model_performance():

    st.divider()

    st.subheader(
        "📊 Model Performance Center"
    )

    st.caption(
        "Historical accuracy calculated from saved "
        "pregame predictions and official NHL final scores."
    )

    try:
        performance = load_model_performance()

    except Exception as exc:
        st.warning(
            "Model performance data could not be loaded."
        )
        st.caption(str(exc))
        return

    if performance.empty:
        st.info(
            "Waiting for completed games with matching "
            "historical predictions. Performance metrics "
            "will appear automatically when results arrive."
        )
        return

    numeric_columns = [
        "games_evaluated",
        "mae",
        "rmse",
        "bias",
        "average_projected_total",
        "average_actual_total",
    ]

    for column in numeric_columns:
        performance[column] = pd.to_numeric(
            performance[column],
            errors="coerce",
        )

    performance = performance[
        performance["games_evaluated"] > 0
    ].copy()

    if performance.empty:
        st.info(
            "No completed games have been evaluated yet."
        )
        return

    versions = sorted(
        performance["model_version"]
        .dropna()
        .unique()
        .tolist()
    )

    if not versions:
        st.info("No model versions available.")
        return

    default_version = (
        MODEL_VERSION
        if MODEL_VERSION in versions
        else versions[0]
    )

    selected_version = st.selectbox(
        "Model version",
        versions,
        index=versions.index(
            default_version
        ),
    )

    subset = performance[
        performance["model_version"]
        == selected_version
    ].copy()

    snapshot_types = subset[
        "snapshot_type"
    ].tolist()

    preferred = (
        "FINAL PREGAME"
        if "FINAL PREGAME" in snapshot_types
        else snapshot_types[0]
    )

    selected_snapshot = st.radio(
        "Snapshot type",
        snapshot_types,
        index=snapshot_types.index(
            preferred
        ),
        horizontal=True,
    )

    selected = subset[
        subset["snapshot_type"]
        == selected_snapshot
    ].iloc[0]

    def fmt(value):
        if pd.isna(value):
            return "—"
        return f"{value:.3f}"

    st.markdown("### Historical accuracy")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Games evaluated",
        int(selected["games_evaluated"]),
    )

    c2.metric(
        "MAE",
        fmt(selected["mae"]),
    )

    c3.metric(
        "RMSE",
        fmt(selected["rmse"]),
    )

    c4.metric(
        "Bias",
        fmt(selected["bias"]),
    )

    c5, c6 = st.columns(2)

    c5.metric(
        "Average projected goals",
        fmt(
            selected["average_projected_total"]
        ),
    )

    c6.metric(
        "Average actual goals",
        fmt(
            selected["average_actual_total"]
        ),
    )

    st.markdown(
        "### EARLY vs. FINAL PREGAME"
    )

    comparison = subset[
        [
            "snapshot_type",
            "games_evaluated",
            "mae",
            "rmse",
            "bias",
            "average_projected_total",
            "average_actual_total",
        ]
    ].copy()

    comparison.columns = [
        "Snapshot",
        "Games",
        "MAE",
        "RMSE",
        "Bias",
        "Avg projected",
        "Avg actual",
    ]

    st.dataframe(
        comparison,
        hide_index=True,
        use_container_width=True,
    )

    if len(comparison) > 1:
        st.caption(
            "EARLY and FINAL PREGAME may include "
            "different games. A fair head-to-head "
            "comparison requires matching game IDs."
        )

    if int(selected["games_evaluated"]) < 30:
        st.caption(
            "Small sample: accuracy estimates may "
            "change considerably as more games finish."
        )

    st.caption(
        "MAE = mean absolute error. "
        "RMSE = root mean squared error. "
        "Positive bias means projected totals "
        "are higher than actual totals."
    )


# ============================================================
# CUSTOM CSS
# ============================================================

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
    padding: 16px 24px;
    box-shadow: 0 0 24px #008bff33;
}

.ff-sub {
    font-size: 12px;
    letter-spacing: 3px;
    color: #9adfff;
}

.ff-head {
    font-weight: 1000;
    font-size: clamp(34px, 5vw, 65px);
    line-height: 1.04;
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
    margin: 0 0 14px;
    box-shadow: 0 0 14px #009dff20;
}

.ff-panel h3 {
    margin: 0 0 13px;
    font-size: 17px;
    border-bottom: 1px solid #235577;
    padding-bottom: 10px;
}

.ff-num {
    font-size: 42px;
    font-weight: 900;
    line-height: 1.2;
}

.ff-game {
    display: grid;
    grid-template-columns:
        35px 75px minmax(110px, 1fr)
        62px 90px minmax(180px, 1.5fr) 80px;
    gap: 8px;
    align-items: center;
    border-bottom: 1px solid #1b415e;
    padding: 11px 3px;
    font-size: 13px;
}

.ff-game img {
    width: 30px;
    height: 30px;
    vertical-align: middle;
    margin: 0 4px;
}

.ff-total {
    background: #0b456b;
    border: 1px solid #39c7ff;
    border-radius: 7px;
    padding: 7px;
    text-align: center;
    font-size: 21px;
    font-weight: 900;
    color: white;
}

.ff-pill {
    border: 1px solid;
    border-radius: 7px;
    text-align: center;
    padding: 7px;
    font-weight: 800;
    font-size: 11px;
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

.ff-small {
    font-size: 11px;
    color: #c7d9e8;
}

.ff-footer {
    color: #9cb7c9;
    font-size: 12px;
    margin-top: 14px;
}

@media (max-width: 1100px) {

    .ff-game {
        grid-template-columns:
            25px 62px minmax(100px, 1fr)
            62px 76px;
    }

    .ff-goalies, .ff-rel {
        grid-column: 3 / 6;
    }

    .ff-game img {
        width: 24px;
        height: 24px;
    }
}

</style>
"""

st.markdown(
    CSS,
    unsafe_allow_html=True,
)


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
    None,
)

left, right = st.columns(
    [1, 5],
    vertical_alignment="center",
)

with left:

    if logo is not None:
        st.image(
            logo.read_text(
                encoding="utf-8"
            ),
            width=140,
        )

    else:
        st.markdown(
            "🏒❄️",
        )

with right:

    st.markdown(
        '<div class="ff-hero">'
        '<div class="ff-sub">'
        'NHL ANALYTICS • PROJECTION CENTER'
        '</div>'
        '<div class="ff-head">'
        'FROZEN <span>FORECAST</span>'
        '</div>'
        '<div class="ff-sub">'
        'THE NUMBERS BEHIND THE ICE'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# SIDEBAR
# ============================================================

now = datetime.now(ET)

with st.sidebar:

    st.header(
        "❄️ Forecast controls"
    )

    game_date = st.date_input(
        "Game date (Eastern Time)",
        value=now.date(),
    )

    verify = st.checkbox(
        "Verify goalies against NHL rosters",
        value=True,
    )

    if st.button(
        "🔄 Refresh now",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()

    st.caption(
        "GitHub Actions collect EARLY and FINAL "
        "PREGAME predictions and official NHL results."
    )


# ============================================================
# LIVE PROJECTIONS
# ============================================================

@st.cache_data(
    ttl=600,
    show_spinner="Collecting NHL statistics and starting goalies…",
)
def cached_projections(date, verify):
    return build_projections(
        date,
        verify,
    )


try:
    df, meta = cached_projections(
        str(game_date),
        verify,
    )

except Exception as exc:

    st.error(
        f"Live refresh failed: {exc}"
    )

    st.info(
        "The NHL or Daily Faceoff feed may "
        "be temporarily unavailable."
    )

    df = pd.DataFrame()
    meta = {}


st.caption(
    f'📅 {game_date.strftime("%A, %B %d, %Y")}'
    f' · Viewed {now.strftime("%I:%M %p ET")}'
    ' · Refresh cache: up to 10 minutes'
)


# ============================================================
# THREE-COLUMN NHL DASHBOARD
# ============================================================

if df.empty:

    st.warning(
        "No eligible pregame projections for "
        "this date. Games may have started, "
        "ended, or lack verified data."
    )

else:

    counts = df[
        "Goalie Reliability"
    ].value_counts()

    high = int(
        counts.get("HIGH", 0)
    )

    medium = int(
        counts.get("MEDIUM", 0)
    )

    low = int(
        counts.get("LOW", 0)
    )

    blocked = int(
        counts.get("BLOCKED", 0)
    )

    side, center, insight = st.columns(
        [1.0, 2.8, 1.15],
        gap="small",
    )

    # --------------------------------------------------------
    # LEFT COLUMN
    # --------------------------------------------------------

    with side:

        st.markdown(
            f'<div class="ff-panel">'
            f'<h3>🏒 TONIGHT’S SLATE</h3>'
            f'<div class="ff-num">{len(df)} GAMES</div>'
            f'<div class="ff-small">'
            f'🟢 {high} High &nbsp; '
            f'🟡 {medium} Medium<br>'
            f'🔴 {low} Low &nbsp; '
            f'⛔ {blocked} Blocked'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        roster_checks = meta.get(
            "rosters", {}
        )

        roster_matches = sum(
            value == "MATCH"
            for value in roster_checks.values()
        )

        st.markdown(
            f'<div class="ff-panel">'
            f'<h3>📋 DATA CHECKS</h3>'
            f'<div class="ff-small">'
            f'Teams loaded: {meta.get("team_count", 0)}<br>'
            f'Goalies loaded: {meta.get("goalie_count", 0)}<br>'
            f'Official roster matches: '
            f'{roster_matches} / {len(roster_checks)}<br>'
            f'Projected matchups: '
            f'{len(df)} / {meta.get("scheduled", 0)}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # --------------------------------------------------------
    # CENTER COLUMN — CORRECTED HTML RENDERING
    # --------------------------------------------------------

    with center:

        st.markdown(
            '<div class="ff-panel">'
            '<h3>🏒 NHL GOAL PROJECTIONS</h3>',
            unsafe_allow_html=True,
        )

        for i, g in df.iterrows():

            away = html.escape(
                str(g["Away Code"])
            )

            home = html.escape(
                str(g["Home Code"])
            )

            logo1 = (
                "https://assets.nhle.com/logos/nhl/svg/"
                f"{away}_light.svg"
            )

            logo2 = (
                "https://assets.nhle.com/logos/nhl/svg/"
                f"{home}_light.svg"
            )

            rel = str(
                g["Goalie Reliability"]
            )

            goalies = html.escape(
                f"{g['Away Goalie']} "
                f"({g['Away Status']}) / "
                f"{g['Home Goalie']} "
                f"({g['Home Status']})"
            )

            # IMPORTANT:
            # Construct HTML without leading indentation.
            # This prevents Streamlit from displaying raw tags.

            row = (
                f'<div class="ff-game">'
                f'<b>{i + 1:02d}</b>'
                f'<span class="ff-small">'
                f'{html.escape(str(g["Start ET"]))}'
                f'</span>'
                f'<span>'
                f'<img src="{logo1}"><b>{away}</b> @ '
                f'<img src="{logo2}"><b>{home}</b>'
                f'</span>'
                f'<span class="ff-small">'
                f'{g["Away xG"]:.2f} / {g["Home xG"]:.2f}'
                f'</span>'
                f'<span class="ff-total">'
                f'{g["Projected Total"]:.2f}'
                f'</span>'
                f'<span class="ff-goalies ff-small">'
                f'{goalies}'
                f'</span>'
                f'<span class="ff-rel ff-pill ff-{rel.lower()}">'
                f'{rel}'
                f'</span>'
                f'</div>'
            )

            st.markdown(
                row,
                unsafe_allow_html=True,
            )

        st.markdown(
            "</div>",
            unsafe_allow_html=True,
        )

    # --------------------------------------------------------
    # RIGHT COLUMN
    # --------------------------------------------------------

    with insight:

        st.markdown(
            f'<div class="ff-panel">'
            f'<h3>🥅 GOALIE RELIABILITY</h3>'
            f'<div class="ff-num">{len(df)}</div>'
            f'<div class="ff-small">'
            f'🟢 High: {high}<br>'
            f'🟡 Medium: {medium}<br>'
            f'🔴 Low: {low}<br>'
            f'⛔ Blocked: {blocked}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        ranked = df.sort_values(
            "Projected Total",
            ascending=False,
        )

        highest = ranked.iloc[0]
        lowest = ranked.iloc[-1]

        st.markdown(
            f'<div class="ff-panel">'
            f'<h3>🎯 KEY TAKEAWAYS</h3>'
            f'<div class="ff-small">'
            f'Average projected total: '
            f'<b>{df["Projected Total"].mean():.2f}</b>'
            f'<br><br>'
            f'Highest: '
            f'<b>{highest["Projected Total"]:.2f}</b> '
            f'({highest["Away Code"]} @ '
            f'{highest["Home Code"]})'
            f'<br><br>'
            f'Lowest: '
            f'<b>{lowest["Projected Total"]:.2f}</b> '
            f'({lowest["Away Code"]} @ '
            f'{lowest["Home Code"]})'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        st.download_button(
            "⬇️ Export projections CSV",
            data=df.to_csv(
                index=False
            ),
            file_name=(
                f"frozen_forecast_{game_date}.csv"
            ),
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown(
        '<div class="ff-footer">'
        'Heuristic goal projections based on team shots, '
        'shooting rates, and adjusted goalie save percentages. '
        'The “xG” labels are inherited from the development '
        'notebook; these are not shot-quality expected-goals '
        'estimates. Goalie reliability describes lineup '
        'verification, not predictive certainty. '
        'No betting advantage is established.'
        '</div>',
        unsafe_allow_html=True,
    )

    if meta.get("skipped"):

        with st.expander(
            "Matchups omitted due to incomplete data"
        ):
            st.write(
                *meta["skipped"]
            )


# ============================================================
# HISTORICAL DATABASE STATUS
# ============================================================

st.divider()

connected, message = check_database_connection()

if connected:

    st.success(
        "🟢 Frozen Forecast historical database connected"
    )

else:

    st.error(
        "🔴 Historical database connection failed"
    )

    st.caption(message)


# ============================================================
# HISTORICAL SNAPSHOT CONTROLS
# ============================================================

if not df.empty:

    st.divider()

    st.subheader(
        "📸 Historical pregame snapshots"
    )

    st.caption(
        "Manual EARLY snapshots for the baseline model. "
        "Automated collection also runs through GitHub Actions."
    )

    if st.button(
        "💾 Save EARLY pregame predictions"
    ):

        try:

            saved, skipped, issues = save_early_predictions(
                df,
                game_date,
            )

            if saved:

                st.success(
                    f"Saved {saved} new immutable "
                    "EARLY pregame snapshots."
                )

            else:

                st.info(
                    "No new pregame snapshots were saved."
                )

            if skipped:

                st.caption(
                    f"{skipped} existing or ineligible "
                    "snapshots were skipped."
                )

            if issues:

                with st.expander(
                    "Skipped games and warnings"
                ):

                    for issue in issues:
                        st.write(issue)

        except Exception as exc:

            st.error(
                "Unable to save historical snapshots."
            )

            st.caption(str(exc))


# ============================================================
# MODEL PERFORMANCE CENTER
# ============================================================

render_model_performance()


