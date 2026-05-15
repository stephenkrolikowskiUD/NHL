# @title 🏒 NHL Daily Picks Grader v3 — Run Morning After Games — 5-4 Baseline
import pandas as pd
import numpy as np
import requests
import time, re, math
import unicodedata
import os, json
from datetime import datetime, timedelta
from itertools import combinations
import pytz
import gspread
from google.auth import default
from google.oauth2.service_account import Credentials

def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    svc_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or os.environ.get("GSPREAD_SERVICE_ACCOUNT_JSON")
    if svc_json:
        creds = Credentials.from_service_account_info(json.loads(svc_json), scopes=scopes)
        print("✅ Google auth via service account env")
        return gspread.authorize(creds)
    try:
        from google.colab import auth as colab_auth
        print("Authenticating with Google...")
        colab_auth.authenticate_user()
        creds, _ = default(scopes=scopes)
        print("✅ Google auth via Colab")
        return gspread.authorize(creds)
    except Exception as e:
        raise RuntimeError("Google auth unavailable. Set GOOGLE_SERVICE_ACCOUNT_JSON or run in Colab.") from e

gc = get_gspread_client()

SHEET_KEY = '1OpER7aRmMFWyxMONdg_LqiyQ47cA3dWRSR8UEQH8FIM'
NHL_API = "https://api-web.nhle.com/v1"
SNAPSHOT_DATE = "2026-05-04"
sh = gc.open_by_key(SHEET_KEY)
print(f"✅ Connected to Google Sheet: {SHEET_KEY}")

eastern = pytz.timezone('US/Eastern')
now_est = datetime.now(eastern)
today_str = now_est.strftime('%Y-%m-%d')
RETRY_DNP_LOOKBACK_DAYS = 7

def safe_float(val, default=None):
    if val is None:
        return default
    if isinstance(val, str):
        val = val.strip().replace(',', '')
        if not val or val.upper() in {'N/A', 'NA', 'NONE', 'NULL', 'DNP'}:
            return default
    try:
        num = float(val)
        if math.isnan(num) or math.isinf(num):
            return default
        return num
    except (TypeError, ValueError):
        return default

def current_nhl_season_id(now=None):
    now = now or datetime.now(eastern)
    start_year = now.year if now.month >= 7 else now.year - 1
    return f"{start_year}{start_year + 1}"

def normalize_person_name(name):
    text = unicodedata.normalize('NFKD', str(name or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[’'`\\.]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def find_box_score(box_lookup, player, date):
    box = box_lookup.get((player, date))
    if box is not None:
        return box
    player_norm = normalize_person_name(player)
    for (bn, bd), bv in box_lookup.items():
        if bd == date and normalize_person_name(bn) == player_norm:
            return bv
    available = [bn for (bn, bd) in box_lookup.keys() if bd == date]
    if available:
        print(f"   ⚠️ No match for '{player}' on {date}. Sample available: {available[:5]}")
    return None

def boxscore_player_name(player_blob, player_id_to_name=None):
    player_id_to_name = player_id_to_name or {}
    if not isinstance(player_blob, dict):
        return ""
    pid = player_blob.get("playerId") or player_blob.get("id")
    pid_str = str(pid).strip() if pid is not None else ""
    if pid_str and pid_str in player_id_to_name:
        return player_id_to_name[pid_str]
    name_val = player_blob.get("name")
    if isinstance(name_val, dict):
        default_name = str(name_val.get("default", "")).strip()
        if default_name:
            return default_name
    if isinstance(name_val, str) and name_val.strip():
        return name_val.strip()
    first = player_blob.get("firstName")
    last = player_blob.get("lastName")
    if isinstance(first, dict):
        first = first.get("default", "")
    if isinstance(last, dict):
        last = last.get("default", "")
    full = f"{first or ''} {last or ''}".strip()
    return full

def load_boxscore_into_lookup(box_lookup, game_id, game_date, boxscore, player_id_to_name=None):
    stats = (boxscore or {}).get("playerByGameStats", {}) or {}
    added = 0
    for team_key in ("homeTeam", "awayTeam"):
        team = stats.get(team_key, {}) or {}
        for group in ("forwards", "defense"):
            for p in team.get(group, []) or []:
                player_name = boxscore_player_name(p, player_id_to_name)
                if not player_name:
                    continue
                key = (player_name, game_date)
                if key in box_lookup:
                    continue
                goals = safe_float(p.get("goals"), 0) or 0
                assists = safe_float(p.get("assists"), 0) or 0
                shots = safe_float(p.get("sog", p.get("shots", 0)), 0) or 0
                blocks = safe_float(p.get("blockedShots"), 0) or 0
                hits_val = safe_float(p.get("hits"), 0) or 0
                ppp = safe_float(
                    p.get("powerPlayPoints", p.get("powerPlayGoals", 0) + p.get("powerPlayAssists", 0)),
                    0
                ) or 0
                pim = safe_float(p.get("pim"), 0) or 0
                pts = safe_float(p.get("points"), goals + assists) or 0
                box_lookup[key] = {
                    'G': float(goals),
                    'A': float(assists),
                    'PTS': float(pts),
                    'SOG': float(shots),
                    'BLK': float(blocks),
                    'HITS': float(hits_val),
                    'PPP': float(ppp),
                    'PIM': float(pim),
                    'DK_FP': round(goals*8.5 + assists*5 + shots*1.5 + blocks*1.3, 1),
                    'UD_FP': round(goals*6 + assists*4 + ppp*0.5 + shots + hits_val*0.5 + blocks, 1),
                }
                added += 1
        for p in team.get("goalies", []) or []:
            player_name = boxscore_player_name(p, player_id_to_name)
            if not player_name:
                continue
            key = (player_name, game_date)
            if key in box_lookup:
                continue
            saves = safe_float(p.get("saves"), 0) or 0
            goals_against = safe_float(p.get("goalsAgainst"), 0) or 0
            shots_against = safe_float(p.get("shotsAgainst"), saves + goals_against) or 0
            save_pct = safe_float(p.get("savePctg"), 0) or 0
            decision = str(p.get("decision", "")).upper()
            shutout_raw = p.get("shutout", 0)
            shutout = 1.0 if safe_float(shutout_raw, 0) or str(shutout_raw).upper() in {"TRUE", "YES"} else 0.0
            box_lookup[key] = {
                'SV': float(saves),
                'GA': float(goals_against),
                'SA': float(shots_against),
                'SV_PCT': float(save_pct),
                'W': 1.0 if decision.startswith("W") or decision == "WIN" else 0.0,
                'SO': float(shutout),
                'DK_FP': safe_float(p.get("fantasyPoints"), 0),
                'UD_FP': safe_float(p.get("fantasyPoints"), 0),
            }
            added += 1
    return added

def grade_pick(actual, line_val, lean):
    if actual is None or line_val is None:
        return '', ''
    if actual == line_val:
        return 'PUSH', 'PUSH'
    if lean in ('UNDER', 'FADE'):
        return ('YES', 'HIT') if actual < line_val else ('NO', 'MISS')
    return ('YES', 'HIT') if actual > line_val else ('NO', 'MISS')

def combo_leg_label(row):
    return f"{row.get('player', '?')} {row.get('prop_type', '?')} {row.get('lean', '?')} {row.get('line', '?')}"

def print_winning_combo_tracker(df_all, dates_to_grade):
    if 'DATE' not in df_all.columns or 'HIT' not in df_all.columns:
        return
    hit_df = df_all[df_all['HIT'] == 'YES'].copy()
    if hit_df.empty:
        return
    hit_df['DATE'] = hit_df['DATE'].astype(str)
    target_dates = {str(d) for d in dates_to_grade}
    hit_df = hit_df[hit_df['DATE'].isin(target_dates)]
    if hit_df.empty:
        return
    hit_df['_run'] = pd.to_numeric(hit_df['RUN_NUMBER'], errors='coerce') if 'RUN_NUMBER' in hit_df.columns else np.nan
    print("\n   Winning Combo Tracker:")
    for date in sorted(hit_df['DATE'].unique()):
        date_df = hit_df[hit_df['DATE'] == date]
        run_vals = sorted(date_df['_run'].dropna().astype(int).unique()) if pd.Series(date_df['_run']).notna().any() else [None]
        for run_no in run_vals:
            grp = date_df if run_no is None else date_df[date_df['_run'] == run_no]
            labels = [combo_leg_label(row) for _, row in grp.iterrows()]
            if len(labels) < 2:
                continue
            combos2 = list(combinations(labels, 2))
            combos3 = list(combinations(labels, 3)) if len(labels) >= 3 else []
            header = f"   {date}" + (f" / Run {run_no}" if run_no is not None else "")
            print(f"{header}: {len(combos2)} winning 2-leg, {len(combos3)} winning 3-leg")
            if combos2:
                print(f"      2-leg ex: {' + '.join(combos2[0])}")
            if combos3:
                print(f"      3-leg ex: {' + '.join(combos3[0])}")

def print_clv_summary(df_all):
    needed = {'CLV_OPEN_LINE', 'CLV_LATEST_LINE', 'lean', 'HIT'}
    if not needed.issubset(df_all.columns):
        return
    clv_df = df_all[df_all['HIT'].isin(['YES', 'NO'])].copy()
    if clv_df.empty:
        return
    clv_df['open_line'] = pd.to_numeric(clv_df['CLV_OPEN_LINE'], errors='coerce')
    clv_df['latest_line'] = pd.to_numeric(clv_df['CLV_LATEST_LINE'], errors='coerce')
    clv_df = clv_df.dropna(subset=['open_line', 'latest_line'])
    if clv_df.empty:
        return
    clv_df['lean_norm'] = clv_df['lean'].fillna('').astype(str).str.upper().replace({'FADE': 'UNDER'})
    clv_df['clv_edge'] = np.where(clv_df['lean_norm'] == 'UNDER', clv_df['open_line'] - clv_df['latest_line'], clv_df['latest_line'] - clv_df['open_line'])
    print("\n   CLV Summary:")
    pos_df = clv_df[clv_df['clv_edge'] > 0]
    neg_df = clv_df[clv_df['clv_edge'] <= 0]
    if not pos_df.empty:
        pos_hits = len(pos_df[pos_df['HIT'] == 'YES'])
        print(f"   Positive CLV: {pos_hits}-{len(pos_df)-pos_hits} ({pos_hits/len(pos_df)*100:.0f}%) | Avg {pos_df['clv_edge'].mean():+.2f}")
    if not neg_df.empty:
        neg_hits = len(neg_df[neg_df['HIT'] == 'YES'])
        print(f"   Flat/Negative CLV: {neg_hits}-{len(neg_df)-neg_hits} ({neg_hits/len(neg_df)*100:.0f}%) | Avg {neg_df['clv_edge'].mean():+.2f}")

CURRENT_SEASON = current_nhl_season_id(now_est)

# --- 2. LOAD DAILY_PICKS ---
print("\nLoading Daily_Picks...")
try:
    ws = sh.worksheet('Daily_Picks')
    all_rows = ws.get_all_values()
except Exception as e:
    print(f"❌ Could not find Daily_Picks sheet: {e}")
    raise

if len(all_rows) <= 1:
    print("⚠️ No picks to grade — sheet is empty.")
    headers = ['DATE', 'HIT']
    df_picks = pd.DataFrame(columns=headers)
else:
    headers = all_rows[0]
    data = all_rows[1:]
    df_picks = pd.DataFrame(data, columns=headers)
    print(f"📋 Found {len(df_picks)} total picks across {df_picks['DATE'].nunique()} dates")

# --- 3. FIND UNGRADED PICKS ---
hit_series = df_picks['HIT'].fillna('').astype(str).str.strip()
ungraded = df_picks[hit_series == ''].copy()

if ungraded.empty:
    print("✅ All picks are already graded! Nothing to do.")
    dates_to_grade = []

# Only grade picks from completed dates (not today)
ungraded = ungraded[ungraded['DATE'] < today_str]

if ungraded.empty:
    print(f"⏳ All ungraded picks are from today ({today_str}) — games haven't finished yet. Run tomorrow.")
    dates_to_grade = []
else:
    dates_to_grade = sorted(ungraded['DATE'].unique())
    print(f"🎯 {len(ungraded)} gradeable picks from: {', '.join(dates_to_grade)}")

# --- 4. BUILD BOX SCORE LOOKUP ---
print("\nFetching box score data...")
box_lookup = {}  # (player_name, game_date) → stats dict
sheets_loaded = False

# 4a. Load from Skater_Game_Logs sheet
try:
    print("   📊 Loading from Skater_Game_Logs sheet...")
    ws_logs = sh.worksheet('Skater_Game_Logs')
    log_rows = ws_logs.get_all_records()
    df_skt_logs = pd.DataFrame(log_rows)
    if len(df_skt_logs) > 0:
        for _, row in df_skt_logs.iterrows():
            name = str(row.get('player_name', ''))
            date = str(row.get('game_date', ''))
            if not name or not date:
                continue
            box_lookup[(name, date)] = {
                'G': safe_float(row.get('G'), 0),
                'A': safe_float(row.get('A'), 0),
                'PTS': safe_float(row.get('PTS'), 0),
                'SOG': safe_float(row.get('SOG'), 0),
                'BLK': safe_float(row.get('BLK'), 0),
                'HITS': safe_float(row.get('HITS'), 0),
                'PPP': safe_float(row.get('PPP'), 0),
                'PIM': safe_float(row.get('PIM'), 0),
                'DK_FP': safe_float(row.get('DK_FP'), 0),
                'UD_FP': safe_float(row.get('UD_FP'), 0),
            }
        print(f"   ✅ Loaded {len(box_lookup)} skater game entries")
        sheets_loaded = True
except Exception as e:
    print(f"   ⚠️ Could not load Skater_Game_Logs: {e}")

# 4b. Load goalie logs
try:
    print("   📊 Loading from Goalie_Game_Logs sheet...")
    ws_glogs = sh.worksheet('Goalie_Game_Logs')
    glog_rows = ws_glogs.get_all_records()
    df_gol_logs = pd.DataFrame(glog_rows)
    if len(df_gol_logs) > 0:
        goalie_count = 0
        for _, row in df_gol_logs.iterrows():
            name = str(row.get('player_name', ''))
            date = str(row.get('game_date', ''))
            if not name or not date:
                continue
            key = (name, date)
            if key not in box_lookup:
                box_lookup[key] = {}
            box_lookup[key].update({
                'SV': safe_float(row.get('SV'), 0),
                'GA': safe_float(row.get('GA'), 0),
                'SA': safe_float(row.get('SA'), 0),
                'SV_PCT': safe_float(row.get('SV_PCT'), 0),
                'W': safe_float(row.get('W'), 0),
                'SO': safe_float(row.get('SO'), 0),
                'DK_FP': safe_float(row.get('DK_FP'), 0),
                'UD_FP': safe_float(row.get('UD_FP'), 0),
            })
            goalie_count += 1
        print(f"   ✅ Loaded {goalie_count} goalie game entries")
except Exception as e:
    print(f"   ⚠️ Could not load Goalie_Game_Logs: {e}")

print(f"\n📦 Total box score entries available: {len(box_lookup)}")

# Check which dates we have data for
box_dates = sorted(set(d for _, d in box_lookup.keys()))
box_date_set = set(box_dates)
grade_dates_available = [d for d in dates_to_grade if d in box_dates]
grade_dates_missing = [d for d in dates_to_grade if d not in box_dates]

if grade_dates_available:
    print(f"   ✅ Data available for: {', '.join(grade_dates_available)}")
if grade_dates_missing:
    print(f"   ⚠️ No sheet data for: {', '.join(grade_dates_missing)}")

# --- 4c. FETCH MISSING DATA VIA PLAYER GAME LOGS ---
# For each ungraded player missing data, fetch their game log from NHL API
# This uses the same endpoint the engine uses — guaranteed to work
if grade_dates_missing:
    print("\n   🔄 Fetching missing player data from NHL API...")
    
    # Get unique players we need to grade on missing dates
    missing_picks = ungraded[ungraded['DATE'].isin(grade_dates_missing)]
    player_needed_props = {
        player: {
            str(prop).strip().upper()
            for prop in grp['prop_type'].tolist()
            if str(prop).strip()
        }
        for player, grp in missing_picks.groupby('player')
    }
    players_needed = missing_picks['player'].unique()
    print(f"   Need data for {len(players_needed)} players")
    
    # Step 1: Find which teams played on the missing dates
    teams_on_dates = {}
    for grade_date in grade_dates_missing:
        try:
            sched = requests.get(f"{NHL_API}/schedule/{grade_date}", timeout=15).json()
            teams = set()
            for day in sched.get("gameWeek", []):
                if day.get("date") == grade_date:
                    for g in day.get("games", []):
                        teams.add(g.get("awayTeam", {}).get("abbrev", ""))
                        teams.add(g.get("homeTeam", {}).get("abbrev", ""))
            teams.discard("")
            teams_on_dates[grade_date] = teams
            print(f"   📅 {grade_date}: {len(teams)} teams played ({', '.join(sorted(teams))})")
        except Exception as e:
            print(f"   ⚠️ Could not fetch schedule for {grade_date}: {e}")
            teams_on_dates[grade_date] = set()
    
    # Step 2: Get rosters for those teams to find player IDs/full names
    all_teams = set()
    for teams in teams_on_dates.values():
        all_teams.update(teams)
    
    player_id_map = {}  # player_name → player_id
    player_id_to_name = {}  # player_id → player_name
    print(f"   👥 Fetching rosters for {len(all_teams)} teams...")
    for team in sorted(all_teams):
        try:
            roster = requests.get(f"{NHL_API}/roster/{team}/current", timeout=15).json()
            for group in ["forwards", "defensemen", "goalies"]:
                for p in roster.get(group, []):
                    fname = f"{p.get('firstName',{}).get('default','')} {p.get('lastName',{}).get('default','')}".strip()
                    pid = p.get("id")
                    if fname and pid:
                        player_id_map[fname] = pid
                        player_id_to_name[str(pid)] = fname
            time.sleep(0.2)
        except Exception as e:
            print(f"   ⚠️ Roster fetch failed for {team}: {e}")
    print(f"   ✅ Found {len(player_id_map)} player IDs")

    # Step 3: Load scheduled game boxscores for those dates first (most reliable for grading)
    fallback_game_ids = {}
    for grade_date in grade_dates_missing:
        fallback_game_ids[grade_date] = []
        try:
            sched = requests.get(f"{NHL_API}/schedule/{grade_date}", timeout=15).json()
            for day in sched.get("gameWeek", []):
                if day.get("date") != grade_date:
                    continue
                fallback_game_ids[grade_date] = [str(g.get("id")) for g in day.get("games", []) if g.get("id")]
                break
        except Exception as e:
            print(f"   ⚠️ Could not load game IDs for {grade_date}: {e}")
        if fallback_game_ids[grade_date]:
            print(f"   🎮 {grade_date}: {len(fallback_game_ids[grade_date])} game IDs found")

    fetched = 0
    for grade_date in grade_dates_missing:
        for game_id in fallback_game_ids.get(grade_date, []):
            try:
                boxscore = requests.get(f"{NHL_API}/gamecenter/{game_id}/boxscore", timeout=15).json()
                added = load_boxscore_into_lookup(box_lookup, game_id, grade_date, boxscore, player_id_to_name)
                fetched += added
                print(f"      📦 Boxscore {game_id} ({grade_date}): {added} player rows")
                time.sleep(0.2)
            except Exception as e:
                print(f"      ⚠️ Boxscore fetch failed for {game_id}: {e}")

    # Step 4: For any still-missing player/date rows, fetch per-player game logs as backup
    for player_name in players_needed:
        unresolved_dates = [
            gdate for gdate in grade_dates_missing
            if (player_name, gdate) not in box_lookup
        ]
        if not unresolved_dates:
            continue
        pid = player_id_map.get(player_name)
        if not pid:
            # Try case-insensitive match
            for pn, pi in player_id_map.items():
                if pn.lower() == player_name.lower():
                    pid = pi
                    break
        if not pid:
            print(f"      ⚠️ No player ID for: {player_name}")
            continue
        
        try:
            # Fetch game logs (try playoffs first, then regular season)
            for gt in [3, 2]:
                resp = requests.get(f"{NHL_API}/player/{pid}/game-log/{CURRENT_SEASON}/{gt}", timeout=15)
                if resp.status_code != 200:
                    continue
                logs = resp.json().get("gameLog", [])
                if not logs:
                    continue
                
                for g in logs:
                    gdate = g.get("gameDate", "")
                    if gdate not in unresolved_dates:
                        continue
                    
                    key = (player_name, gdate)
                    if key in box_lookup:
                        continue
                    
                    needs_goalie_stats = bool(player_needed_props.get(player_name, set()) & {'SV', 'GA', 'SA', 'SV_PCT', 'W', 'SO'})
                    is_goalie_log = needs_goalie_stats or any(k in g for k in ['saves', 'shotsAgainst', 'goalsAgainst', 'savePctg'])
                    if is_goalie_log:
                        saves = safe_float(g.get("saves"), 0) or 0
                        goals_against = safe_float(g.get("goalsAgainst"), 0) or 0
                        shots_against = safe_float(g.get("shotsAgainst"), saves + goals_against) or 0
                        save_pct = safe_float(g.get("savePctg"), 0)
                        win_val = 1.0 if str(g.get("decision", "")).upper().startswith("W") or str(g.get("decision", "")).upper() == "WIN" else 0.0
                        shutout = 1.0 if safe_float(g.get("shutout"), 0) or str(g.get("shutout", "")).upper() in {"TRUE", "YES"} else 0.0
                        box_lookup[key] = {
                            'SV': float(saves),
                            'GA': float(goals_against),
                            'SA': float(shots_against),
                            'SV_PCT': float(save_pct or 0),
                            'W': float(win_val),
                            'SO': float(shutout),
                            'DK_FP': safe_float(g.get("fantasyPoints"), 0),
                            'UD_FP': safe_float(g.get("fantasyPoints"), 0),
                        }
                        fetched += 1
                        print(f"      ✅ {player_name} {gdate}: {box_lookup[key]['SV']:.0f} SV, {box_lookup[key]['GA']:.0f} GA")
                    else:
                        goals = int(g.get("goals", 0))
                        assists = int(g.get("assists", 0))
                        shots = int(g.get("shots", 0))
                        blocks = int(g.get("blockedShots", 0))
                        hits_val = int(g.get("hits", 0))
                        ppp = int(g.get("powerPlayPoints", 0) if "powerPlayPoints" in g else 
                                  (g.get("powerPlayGoals", 0) + g.get("powerPlayAssists", 0) if "powerPlayGoals" in g else 0))
                        
                        box_lookup[key] = {
                            'G': float(goals),
                            'A': float(assists),
                            'PTS': float(g.get("points", goals + assists)),
                            'SOG': float(shots),
                            'BLK': float(blocks),
                            'HITS': float(hits_val),
                            'PPP': float(ppp),
                            'PIM': safe_float(g.get("pim"), 0),
                            'DK_FP': round(goals*8.5 + assists*5 + shots*1.5 + blocks*1.3, 1),
                            'UD_FP': round(goals*6 + assists*4 + ppp*0.5 + shots + hits_val*0.5 + blocks, 1),
                        }
                        fetched += 1
                        print(f"      ✅ {player_name} {gdate}: {box_lookup[key]['PTS']:.0f} PTS, {box_lookup[key]['SOG']:.0f} SOG, {box_lookup[key]['DK_FP']:.1f} DK_FP")
            
            time.sleep(0.2)
        except Exception as e:
            print(f"      ⚠️ Failed: {player_name} — {e}")
    
    box_date_set = set(d for _, d in box_lookup.keys())
    print(f"   📦 Fetched {fetched} new entries. Total: {len(box_lookup)}")

# --- 5. GRADE EACH PICK ---
print("\n" + "=" * 60)
print("📝 GRADING PICKS")
print("=" * 60)

graded = 0
hits = 0
misses = 0
pushes = 0
dnp = 0
not_found = 0

col_idx = {h: i for i, h in enumerate(headers)}
actual_col = col_idx.get('ACTUAL_STAT')
hit_col = col_idx.get('HIT')
result_col = col_idx.get('RESULT')

if actual_col is None or hit_col is None:
    print("❌ Missing ACTUAL_STAT or HIT columns in Daily_Picks")
    print(f"   Available columns: {headers}")
    raise SystemExit

def col_letter(idx):
    if idx < 26:
        return chr(65 + idx)
    return chr(64 + idx // 26) + chr(65 + idx % 26)

updates = []

for idx, pick in ungraded.iterrows():
    player = pick.get('player', '')
    date = pick.get('DATE', '')
    prop_type = pick.get('prop_type', 'PTS')
    prop_type_aliases = {'HIT': 'HITS', 'SHOT': 'SOG', 'BLOCK': 'BLK', 'DK_FP': 'UD_FP'}
    prop_type = prop_type_aliases.get(prop_type, prop_type)
    line = pick.get('line', '')
    lean = (pick.get('lean', '') or '').upper()

    if not player or not date:
        continue

    line_val = safe_float(line)
    if line_val is None and prop_type in {'PTS', 'G', 'A', 'PPP'}:
        line_val = 0.5
        print(f"   ℹ️ {player} ({date}) — missing line for {prop_type}, defaulting to 0.5")

    # Try exact name match first, then case-insensitive
    box = find_box_score(box_lookup, player, date)

    sheet_row = int(idx) + 2
    date_has_logs = date in box_date_set

    if box is None:
        if not date_has_logs:
            print(f"   ⏳ {player} ({date}) — logs for this date are not available yet; leaving ungraded for retry")
            continue
        updates.append({'range': f'{col_letter(actual_col)}{sheet_row}', 'value': 'DNP'})
        updates.append({'range': f'{col_letter(hit_col)}{sheet_row}', 'value': 'DNP'})
        if result_col is not None:
            updates.append({'range': f'{col_letter(result_col)}{sheet_row}', 'value': 'DNP'})
        dnp += 1
        print(f"   ⬜ {player} ({date}) — DNP / No box score found")
        continue

    actual = box.get(prop_type)
    if actual is None:
        not_found += 1
        print(f"   ❓ {player} ({date}) — prop_type '{prop_type}' not found in box score")
        print(f"      Available stats: {', '.join(box.keys())}")
        continue

    actual = safe_float(actual)
    hit_str, result_str = grade_pick(actual, line_val, lean)
    if hit_str == 'PUSH':
        pushes += 1
    elif hit_str == 'YES':
        hits += 1
    elif hit_str == 'NO':
        misses += 1

    graded += 1

    updates.append({'range': f'{col_letter(actual_col)}{sheet_row}', 'value': str(actual)})
    updates.append({'range': f'{col_letter(hit_col)}{sheet_row}', 'value': hit_str})
    if result_col is not None:
        updates.append({'range': f'{col_letter(result_col)}{sheet_row}', 'value': result_str})

    icon = "✅" if hit_str == "YES" else "❌" if hit_str == "NO" else "➖" if hit_str == "PUSH" else "⬜"
    print(f"   {icon} {player} | {prop_type} {lean} {line} → Actual: {actual} → {hit_str}")

# --- 6. BATCH UPDATE GOOGLE SHEETS ---
if updates:
    print(f"\n📤 Writing {len(updates)} cell updates to Google Sheets...")
    cells = [{'range': u['range'], 'values': [[u['value']]]} for u in updates]
    ws.batch_update(cells)
    print("✅ Sheet updated!")
else:
    print("\n⚠️ No updates to write.")

# --- 7. SUMMARY ---
total_decided = hits + misses
hit_rate = (hits / total_decided * 100) if total_decided > 0 else 0

print("\n" + "=" * 60)
print("📊 GRADING COMPLETE")
print("=" * 60)
print(f"   ✅ Hits:      {hits}")
print(f"   ❌ Misses:    {misses}")
print(f"   ➖ Pushes:    {pushes}")
print(f"   ⬜ DNP:       {dnp}")
print(f"   ❓ Not found: {not_found}")
print(f"   📈 Hit Rate:  {hits}/{total_decided} ({hit_rate:.1f}%)")
print(f"   📋 Dates:     {', '.join(dates_to_grade)}")
print("=" * 60)

# --- 8. SHOW CUMULATIVE RECORD ---
print("\n📊 Cumulative Record (all graded picks):")
ws_fresh = sh.worksheet('Daily_Picks')
all_fresh = ws_fresh.get_all_records()
df_all = pd.DataFrame(all_fresh)

if 'HIT' in df_all.columns:
    total_yes = len(df_all[df_all['HIT'] == 'YES'])
    total_no = len(df_all[df_all['HIT'] == 'NO'])
    total_push = len(df_all[df_all['HIT'] == 'PUSH'])
    total_dnp = len(df_all[df_all['HIT'] == 'DNP'])
    total_dec = total_yes + total_no
    cum_rate = (total_yes / total_dec * 100) if total_dec > 0 else 0

    print(f"   Record: {total_yes}-{total_no} ({cum_rate:.1f}%)")
    print(f"   Pushes: {total_push} | DNPs: {total_dnp}")

    if 'lean' in df_all.columns:
        print("\n   By Side:")
        side_series = df_all['lean'].fillna('').astype(str).str.upper().replace({'FADE': 'UNDER'})
        for side in ['OVER', 'UNDER']:
            side_df = df_all[side_series == side]
            side_yes = len(side_df[side_df['HIT'] == 'YES'])
            side_no = len(side_df[side_df['HIT'] == 'NO'])
            side_dec = side_yes + side_no
            if side_dec > 0:
                print(f"   {side}: {side_yes}-{side_no} ({side_yes/side_dec*100:.0f}%)")

    print("\n   By Confidence:")
    for tier in ['SMASH', 'STRONG', 'LEAN']:
        tier_df = df_all[df_all['confidence'].str.upper() == tier]
        tier_yes = len(tier_df[tier_df['HIT'] == 'YES'])
        tier_no = len(tier_df[tier_df['HIT'] == 'NO'])
        tier_dec = tier_yes + tier_no
        if tier_dec > 0:
            print(f"   {tier}: {tier_yes}-{tier_no} ({tier_yes/tier_dec*100:.0f}%)")

    if 'prop_type' in df_all.columns:
        print("\n   By Prop Type:")
        for ptype in sorted(df_all['prop_type'].unique()):
            if not ptype:
                continue
            p_df = df_all[df_all['prop_type'] == ptype]
            p_yes = len(p_df[p_df['HIT'] == 'YES'])
            p_no = len(p_df[p_df['HIT'] == 'NO'])
            p_dec = p_yes + p_no
            if p_dec > 0:
                print(f"   {ptype}: {p_yes}-{p_no} ({p_yes/p_dec*100:.0f}%)")

    print("\n   By Date:")
    for date in sorted(df_all['DATE'].unique()):
        d_df = df_all[df_all['DATE'] == date]
        d_yes = len(d_df[d_df['HIT'] == 'YES'])
        d_no = len(d_df[d_df['HIT'] == 'NO'])
        d_dec = d_yes + d_no
        if d_dec > 0:
            print(f"   {date}: {d_yes}-{d_no} ({d_yes/d_dec*100:.0f}%)")
        else:
            d_dnp = len(d_df[d_df['HIT'] == 'DNP'])
            d_empty = len(d_df[d_df['HIT'].isin(['', None])])
            print(f"   {date}: ungraded ({d_empty}) / DNP ({d_dnp})")

    if 'RUN_NUMBER' in df_all.columns:
        print("\n   By Run Number:")
        run_series = pd.to_numeric(df_all['RUN_NUMBER'], errors='coerce')
        for run_no in sorted(run_series.dropna().astype(int).unique()):
            r_df = df_all[run_series == run_no]
            r_yes = len(r_df[r_df['HIT'] == 'YES'])
            r_no = len(r_df[r_df['HIT'] == 'NO'])
            r_dec = r_yes + r_no
            if r_dec > 0:
                print(f"   Run {run_no}: {r_yes}-{r_no} ({r_yes/r_dec*100:.0f}%)")

    print_winning_combo_tracker(df_all, dates_to_grade)

print("\n🏒 Done! Run this every morning after games.")
