"""Frozen Forecast: standalone adaptation of uploaded notebook's Cell 47 formula."""
import json,re,unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import requests
from bs4 import BeautifulSoup

ET=ZoneInfo('America/New_York')
API='https://api-web.nhle.com/v1'
STATS='https://api.nhle.com/stats/rest/en'
TEAM_CODES=dict(zip(
['Anaheim Ducks','Boston Bruins','Buffalo Sabres','Calgary Flames','Carolina Hurricanes','Chicago Blackhawks','Colorado Avalanche','Columbus Blue Jackets','Dallas Stars','Detroit Red Wings','Edmonton Oilers','Florida Panthers','Los Angeles Kings','Minnesota Wild','Montréal Canadiens','Nashville Predators','New Jersey Devils','New York Islanders','New York Rangers','Ottawa Senators','Philadelphia Flyers','Pittsburgh Penguins','San Jose Sharks','Seattle Kraken','St. Louis Blues','Tampa Bay Lightning','Toronto Maple Leafs','Utah Mammoth','Vancouver Canucks','Vegas Golden Knights','Washington Capitals','Winnipeg Jets'],
['ANA','BOS','BUF','CGY','CAR','CHI','COL','CBJ','DAL','DET','EDM','FLA','LAK','MIN','MTL','NSH','NJD','NYI','NYR','OTT','PHI','PIT','SJS','SEA','STL','TBL','TOR','UTA','VAN','VGK','WSH','WPG']))

def get_json(url,params=None):
 r=requests.get(url,params=params,timeout=25,headers={'User-Agent':'Mozilla/5.0 FrozenForecast/1.0'});r.raise_for_status();return r.json()

def norm(name):
 s=unicodedata.normalize('NFKD',str(name or ''))
 return re.sub('[^a-z]','', ''.join(c for c in s if not unicodedata.combining(c)).lower())

def season_for(date):
 y=int(date[:4]);return f'{y if int(date[5:7])>=7 else y-1}{y+1 if int(date[5:7])>=7 else y}'

def fetch_schedule(date):
 return get_json(f'{API}/score/{date}').get('games',[])

def fetch_team_stats(season):
 data=get_json(f'{STATS}/team/summary',{'isAggregate':'false','isGame':'false','cayenneExp':f'gameTypeId=2 and seasonId={season}','limit':100})['data']
 out={}
 for t in data:
  code=TEAM_CODES.get(t.get('teamFullName'))
  if not code: continue
  gp=t.get('gamesPlayed') or 0;sf=t.get('shotsForPerGame');sa=t.get('shotsAgainstPerGame')
  if gp and sf and sa is not None:
   out[code]={'sf':float(sf),'sa':float(sa),'shoot':float(t.get('goalsFor') or 0)/(float(sf)*gp)}
 return out

def fetch_goalie_stats(season):
 data=get_json(f'{STATS}/goalie/summary',{'isAggregate':'false','isGame':'false','cayenneExp':f'gameTypeId=2 and seasonId={season}','limit':200})['data']
 out={}
 for g in data:
  if g.get('savePct') is None:continue
  shots=float(g.get('shotsAgainst') or 0)
  adjusted=(float(g['savePct'])*shots+0.900*300)/(shots+300)
  for code in str(g.get('teamAbbrevs') or '').replace(',',' ').split():
   out[(code,norm(g.get('goalieFullName')))]=adjusted
 return out

def fetch_starters(date):
 r=requests.get('https://www.dailyfaceoff.com/starting-goalies',timeout=25,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status()
 soup=BeautifulSoup(r.text,'html.parser');script=soup.find('script',id='__NEXT_DATA__')
 if script is None:raise ValueError('Daily Faceoff starting-goalie feed format changed.')
 data=json.loads(script.string)['props']['pageProps']['data']
 if not isinstance(data,list):raise ValueError('Unexpected Daily Faceoff goalie data.')
 out={}
 for g in data:
  if str(g.get('date',''))[:10]!=date:continue
  for side in ('away','home'):
   code=g.get(f'{side}TeamAbbreviation');name=g.get(f'{side}GoalieName')
   status=str(g.get(f'{side}NewsStrengthName') or '').lower()
   label='Confirmed' if 'confirm' in status else 'Likely' if any(x in status for x in ('likely','expected','probable')) else 'Unconfirmed'
   if code:out[code]={'name':name,'status':label}
 return out

def verify_rosters(starters):
 checks={}
 for code,starter in starters.items():
  if not starter.get('name'):
   checks[code]='MISSING GOALIE';continue
  try:
   data=get_json(f'{API}/roster/{code}/current')
   names={norm((g.get('firstName') or {}).get('default','')+' '+(g.get('lastName') or {}).get('default','')) for g in data.get('goalies',[])}
   checks[code]='MATCH' if norm(starter['name']) in names else 'MISMATCH'
  except Exception:checks[code]='UNAVAILABLE'
 return checks

def build_projections(date, verify=True):
 games=fetch_schedule(date)
 if not games:return pd.DataFrame(),{'scheduled':0,'projected':0,'rosters':{}}
 season=season_for(date)
 teams=fetch_team_stats(season);goalies=fetch_goalie_stats(season);starters=fetch_starters(date)
 roster=verify_rosters(starters) if verify else {k:'NOT CHECKED' for k in starters}
 now=pd.Timestamp.now(tz='UTC');rows=[];skipped=[]
 for g in games:
  away=g.get('awayTeam',{}).get('abbrev');home=g.get('homeTeam',{}).get('abbrev')
  start=pd.to_datetime(g.get('startTimeUTC'),utc=True,errors='coerce')
  if pd.isna(start) or start<=now or g.get('gameState') in ('LIVE','CRIT','FINAL','OFF'):continue
  if away not in teams or home not in teams or away not in starters or home not in starters:
   skipped.append(f'{away} @ {home}: team/starter data unavailable');continue
  a=starters[away];h=starters[home]
  asv=goalies.get((away,norm(a['name'])));hsv=goalies.get((home,norm(h['name'])))
  if asv is None or hsv is None:
   skipped.append(f'{away} @ {home}: goalie statistics missing');continue
  at=teams[away];ht=teams[home]
  away_shots=(at['sf']+ht['sa'])/2;home_shots=(ht['sf']+at['sa'])/2
  away_goals=away_shots*(at['shoot']+(1-hsv))/2
  home_goals=home_shots*(ht['shoot']+(1-asv))/2
  statuses={a['status'],h['status']}
  reliability='BLOCKED' if roster.get(away)!='MATCH' or roster.get(home)!='MATCH' else 'LOW' if 'Unconfirmed' in statuses else 'MEDIUM' if 'Likely' in statuses else 'HIGH'
  rows.append({'Game ID':str(g['id']),'Game Date':date,'Away Code':away,'Home Code':home,'Away Goalie':a['name'],'Home Goalie':h['name'],'Away Status':a['status'],'Home Status':h['status'],'Away xG':round(away_goals,4),'Home xG':round(home_goals,4),'Projected Total':round(away_goals+home_goals,4),'Goalie Reliability':reliability,'Start ET':start.tz_convert(ET).strftime('%I:%M %p ET'),'Start UTC':start.isoformat(),'Calculated At UTC':now.isoformat()})
 return pd.DataFrame(rows).sort_values('Projected Total',ascending=False).reset_index(drop=True) if rows else pd.DataFrame(),{'scheduled':len(games),'projected':len(rows),'skipped':skipped,'rosters':roster,'team_count':len(teams),'goalie_count':len(goalies)}
