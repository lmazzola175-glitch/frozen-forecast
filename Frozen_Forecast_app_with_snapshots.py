import html
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from supabase import create_client
from engine import build_projections, fetch_schedule

ET = ZoneInfo('America/New_York')
st.set_page_config(page_title='Frozen Forecast | NHL Projection Center', page_icon='❄️', layout='wide', initial_sidebar_state='collapsed')

@st.cache_resource
def get_supabase_client():
    return create_client(st.secrets['supabase']['url'], st.secrets['supabase']['key'])

def check_database_connection():
    try:
        client = get_supabase_client()
        client.table('predictions').select('id').limit(1).execute()
        return True, 'Database connected successfully'
    except Exception as error:
        return False, str(error)

def render_database_status():
    st.divider()
    connected, message = check_database_connection()
    if connected:
        st.success('🟢 Frozen Forecast historical database connected')
    else:
        st.error('🔴 Historical database connection failed')
        st.code(message)

def save_early_predictions(projections, selected_date):
    """Save immutable, fresh, pregame baseline snapshots on explicit user action."""
    current = datetime.now(timezone.utc)
    if selected_date != current.astimezone(ET).date():
        return 0, 0, ['Select today’s game date to save new predictions.']
    if projections.empty:
        return 0, 0, ['No eligible games to save.']

    records = []
    problems = []
    for _, game in projections.iterrows():
        try:
            start = pd.to_datetime(game['Start UTC'], utc=True).to_pydatetime()
            calculated = pd.to_datetime(game['Calculated At UTC'], utc=True).to_pydatetime()
            if start <= current:
                problems.append(f"{game['Game ID']}: already started")
                continue
            if calculated > current or (current - calculated).total_seconds() > 900:
                problems.append(f"{game['Game ID']}: stale or invalid calculation timestamp")
                continue
            if calculated >= start:
                problems.append(f"{game['Game ID']}: calculation was not pregame")
                continue
            if str(game['Goalie Reliability']).upper() == 'BLOCKED':
                problems.append(f"{game['Game ID']}: blocked goalie verification")
                continue
            records.append({
                'game_id': str(game['Game ID']),
                'game_date': str(game['Game Date'])[:10],
                'model_version': 'v1_goalie_adjusted',
                'snapshot_type': 'EARLY',
                'saved_at': calculated.isoformat(),
                'scheduled_start': start.isoformat(),
                'away_team': str(game['Away Code']),
                'home_team': str(game['Home Code']),
                'away_projected_goals': float(game['Away xG']),
                'home_projected_goals': float(game['Home xG']),
                'projected_total': float(game['Projected Total']),
                'away_goalie': str(game['Away Goalie']),
                'home_goalie': str(game['Home Goalie']),
                'goalie_reliability': str(game['Goalie Reliability']),
            })
        except (KeyError, ValueError, TypeError) as exc:
            problems.append(f"Game {game.get('Game ID', '?')}: {exc}")

    if not records:
        return 0, 0, problems

    client = get_supabase_client()
    # Read existing keys first. Never upsert: upserts could overwrite history.
    game_ids = [r['game_id'] for r in records]
    existing = client.table('predictions').select('game_id').eq(
        'model_version', 'v1_goalie_adjusted'
    ).eq('snapshot_type', 'EARLY').in_('game_id', game_ids).execute()
    existing_ids = {str(row['game_id']) for row in (existing.data or [])}
    inserted = 0
    for record in records:
        if record['game_id'] in existing_ids:
            continue
        try:
            client.table('predictions').insert(record).execute()
            inserted += 1
        except Exception as exc:
            # A concurrent writer may have inserted the unique key meanwhile.
            if '23505' in str(exc) or 'duplicate key' in str(exc).lower():
                existing_ids.add(record['game_id'])
            else:
                problems.append(f"{record['game_id']}: database write failed ({type(exc).__name__})")
    return inserted, len(existing_ids), problems


def render_snapshot_controls(projections, selected_date):
    st.divider()
    st.subheader('📸 Historical pregame snapshots')
    st.caption('Manual EARLY snapshots for the baseline model. This does not run automatically yet.')
    if st.button('💾 Save EARLY pregame predictions', use_container_width=False):
        try:
            saved, existing, issues = save_early_predictions(projections, selected_date)
            if saved:
                st.success(f'Saved {saved} new immutable EARLY pregame snapshots.')
            else:
                st.info('No new pregame snapshots were saved.')
            if existing:
                st.caption(f'{existing} snapshot(s) already existed and were preserved.')
            if issues:
                with st.expander(f'{len(issues)} skipped or failed game(s)'):
                    for issue in issues:
                        st.write(issue)
        except Exception as exc:
            st.error(f'Database save failed: {type(exc).__name__}. No existing predictions were changed.')

CSS='''<style>
.stApp{background:radial-gradient(ellipse at 50% -12%,#16436b 0%,#081726 39%,#040d18 100%);color:#eaf6ff}
.block-container{max-width:1700px;padding-top:1.3rem}
h1,h2,h3{color:#eaf6ff!important}
.ff-hero{border:1px solid #42baf2;border-radius:16px;background:linear-gradient(100deg,#081725,#0d3555 52%,#071521);padding:16px 24px;box-shadow:0 0 24px #008bff33}
.ff-sub{font-size:12px;letter-spacing:3px;color:#9adfff}.ff-head{font-weight:1000;font-size:clamp(34px,5vw,65px);line-height:1.04;color:#e9f7ff;text-shadow:0 0 20px #27b9ff99}.ff-head span{color:#44c7ff}
.ff-panel{background:#071c2ee8;border:1px solid #2a95c9;border-radius:13px;padding:15px;margin:0 0 14px;box-shadow:0 0 14px #009dff20}
.ff-panel h3{margin:0 0 13px;font-size:17px;border-bottom:1px solid #235577;padding-bottom:10px}
.ff-num{font-size:42px;font-weight:900;line-height:1.2}.ff-muted{color:#9db8cc;font-size:12px}
.ff-game{display:grid;grid-template-columns:35px 75px minmax(110px,1fr) 62px 90px minmax(180px,1.5fr) 80px;gap:8px;align-items:center;border-bottom:1px solid #1b415e;padding:11px 3px;font-size:13px}
.ff-game img{width:30px;height:30px;vertical-align:middle;margin:0 4px}
.ff-total{background:#0b456b;border:1px solid #39c7ff;border-radius:7px;padding:7px;text-align:center;font-size:21px;font-weight:900;color:white}
.ff-pill{border:1px solid;border-radius:7px;text-align:center;padding:7px;font-weight:800;font-size:11px}
.ff-high{color:#5ff3a0;border-color:#18bb69;background:#06351e}.ff-medium{color:#ffdc62;border-color:#dba926;background:#392c0c}.ff-low,.ff-blocked{color:#ff8c99;border-color:#f24d63;background:#3a1020}
.ff-small{font-size:11px;color:#c7d9e8}.ff-footer{color:#9cb7c9;font-size:12px;margin-top:14px}
@media(max-width:1100px){.ff-game{grid-template-columns:25px 62px minmax(100px,1fr) 62px 76px;}.ff-goalies,.ff-rel{grid-column:3/6}.ff-game img{width:24px;height:24px}}
</style>'''
st.markdown(CSS,unsafe_allow_html=True)
# Support either an assets/ folder or a logo at the repository root.
app_dir = Path(__file__).resolve().parent
logo_candidates = [
    app_dir / 'assets' / 'frozen_forecast_logo.svg',
    app_dir / 'frozen_forecast_logo.svg',
]
logo = next((candidate for candidate in logo_candidates if candidate.is_file()), None)
left,right=st.columns([1,5],vertical_alignment='center')
with left:
 if logo is not None:
  # Read the SVG contents rather than relying on Streamlit's media-file path.
  st.image(logo.read_text(encoding='utf-8'),width=140)
 else:
  st.markdown('<div style="font-size:56px;text-align:center">🏒❄️</div>',unsafe_allow_html=True)
with right:st.markdown('<div class="ff-hero"><div class="ff-sub">NHL ANALYTICS • PROJECTION CENTER</div><div class="ff-head">FROZEN <span>FORECAST</span></div><div class="ff-sub">THE NUMBERS BEHIND THE ICE</div></div>',unsafe_allow_html=True)
now=datetime.now(ET)
with st.sidebar:
 st.header('❄️ Forecast controls')
 game_date=st.date_input('Game date (Eastern Time)',value=now.date())
 verify=st.checkbox('Verify goalies against NHL rosters',value=True)
 if st.button('🔄 Refresh now',use_container_width=True):st.cache_data.clear();st.rerun()
 st.caption('Historical predictions can be saved manually below. Automatic collection is not yet configured.')
@st.cache_data(ttl=600,show_spinner='Collecting NHL statistics and starting goalies…')
def cached_projections(date,verify):return build_projections(date,verify)
try:df,meta=cached_projections(str(game_date),verify)
except Exception as e:
 st.error(f'Live refresh failed: {e}');st.info('The NHL or Daily Faceoff feed may be temporarily unavailable. No substitute projections are shown.')
 render_database_status()
 st.stop()

st.caption(f'📅 {game_date.strftime("%A, %B %d, %Y")}  ·  Viewed {now.strftime("%I:%M %p ET")}  ·  Refresh cache: up to 10 minutes')
if df.empty:
 st.warning('No eligible pregame projections for this date. Games may have started, ended, or lack verified goalie/statistics data.')
 if meta.get('skipped'):st.write('Unavailable matchups:',*meta['skipped'])
 render_database_status()
 st.stop()
counts=df['Goalie Reliability'].value_counts();high=int(counts.get('HIGH',0));medium=int(counts.get('MEDIUM',0));low=int(counts.get('LOW',0));blocked=int(counts.get('BLOCKED',0))
side,center,insight=st.columns([1.0,2.8,1.15],gap='small')
with side:
 st.markdown(f'<div class="ff-panel"><h3>🏒 TONIGHT’S SLATE</h3><div class="ff-num">{len(df)} GAMES</div><div class="ff-small">🟢 {high} High &nbsp; 🟡 {medium} Medium<br>🔴 {low} Low &nbsp; ⛔ {blocked} Blocked</div></div>',unsafe_allow_html=True)
 st.markdown(f'<div class="ff-panel"><h3>📋 DATA CHECKS</h3><div class="ff-small">Teams loaded: {meta.get("team_count",0)}<br>Goalies loaded: {meta.get("goalie_count",0)}<br>Official roster matches: {sum(v=="MATCH" for v in meta.get("rosters",{}).values())} / {len(meta.get("rosters",{}))}<br>Projected matchups: {len(df)} / {meta.get("scheduled",0)}</div></div>',unsafe_allow_html=True)
with center:
 st.markdown('<div class="ff-panel"><h3>🏒 NHL GOAL PROJECTIONS</h3>',unsafe_allow_html=True)
 for i,g in df.iterrows():
  away=html.escape(str(g['Away Code']));home=html.escape(str(g['Home Code']))
  logo1=f'https://assets.nhle.com/logos/nhl/svg/{away}_light.svg';logo2=f'https://assets.nhle.com/logos/nhl/svg/{home}_light.svg'
  rel=str(g['Goalie Reliability']);goalies=html.escape(f"{g['Away Goalie']} ({g['Away Status']}) / {g['Home Goalie']} ({g['Home Status']})")
  row=f'''<div class="ff-game"><b>{i+1:02d}</b><span class="ff-small">{html.escape(str(g['Start ET']))}</span><span><img src="{logo1}"><b>{away}</b> @ <img src="{logo2}"><b>{home}</b></span><span class="ff-small">{g['Away xG']:.2f} / {g['Home xG']:.2f}</span><span class="ff-total">{g['Projected Total']:.2f}</span><span class="ff-goalies ff-small">{goalies}</span><span class="ff-rel ff-pill ff-{rel.lower()}">{rel}</span></div>'''
  st.markdown(row,unsafe_allow_html=True)
 st.markdown('</div>',unsafe_allow_html=True)
with insight:
 st.markdown(f'<div class="ff-panel"><h3>🥅 GOALIE RELIABILITY</h3><div class="ff-num">{len(df)}</div><div class="ff-small">🟢 High: {high}<br>🟡 Medium: {medium}<br>🔴 Low: {low}<br>⛔ Blocked: {blocked}</div></div>',unsafe_allow_html=True)
 highest=df.iloc[0];lowest=df.iloc[-1]
 st.markdown(f'<div class="ff-panel"><h3>🎯 KEY TAKEAWAYS</h3><div class="ff-small">Average projected total: <b>{df["Projected Total"].mean():.2f}</b><br><br>Highest: <b>{highest["Projected Total"]:.2f}</b> ({highest["Away Code"]} @ {highest["Home Code"]})<br><br>Lowest: <b>{lowest["Projected Total"]:.2f}</b> ({lowest["Away Code"]} @ {lowest["Home Code"]})</div></div>',unsafe_allow_html=True)
 st.download_button('⬇️ Export projections CSV',data=df.to_csv(index=False),file_name=f'frozen_forecast_{game_date}.csv',mime='text/csv',use_container_width=True)
st.markdown('<div class="ff-footer">Heuristic goal projections based on team shots, shooting rates, and adjusted goalie save percentages. “xG” column labels are inherited from the development notebook; these are not shot-quality expected-goals estimates. Goalie reliability describes lineup verification, not predictive certainty. No betting advantage is established.</div>',unsafe_allow_html=True)
if meta.get('skipped'):
 with st.expander('Matchups omitted due to incomplete data'):st.write(*meta['skipped'])
render_database_status()
render_snapshot_controls(df, game_date)
