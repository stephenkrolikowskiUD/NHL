"""
🏒 NHL DFS ENGINE v1.2 — 5-4 Baseline
Architecture: NHL API + Odds API + Gemini → Google Sheets → GitHub Pages HTML
Run in Google Colab. Same pattern as NBA v8.5 and MLB v1.3.0.

v1.2 changes from v1.1:
  - Gemini SDK migrated from google-generativeai → google-genai (v1.1 used deprecated SDK)
  - API keys now pulled from Colab userdata (no more hardcoded placeholders)
  - Cleaned up dead code in props fetch
  - More robust JSON parsing with truncation salvage (matching NBA/MLB pattern)

Sheets written:
  Tonights_Skaters, Skater_Game_Logs, Home_Away_Splits,
  Tonights_Goalies, Goalie_Game_Logs, Goalie_Home_Away,
  DK_Player_Props, Daily_Picks
"""

# Install cell — run this first, then restart runtime
# !pip install google-genai gspread google-auth requests pandas

import requests, json, time, re, math, unicodedata, os, sys
import atexit
from datetime import datetime, date, timedelta
from collections import defaultdict
import pandas as pd
import numpy as np
from google.oauth2.service_account import Credentials
from run_logger import RunLogger

# ═══════════════════════════════════════════════
# 🔑 API KEYS — Loaded from Colab userdata (or prompted)
# ═══════════════════════════════════════════════
def load_secret(name, prompt_text=None, allow_missing=False):
    env_val = os.environ.get(name)
    if env_val:
        print(f"🔐 Loaded {name} from environment!")
        return env_val
    try:
        from google.colab import userdata
        colab_val = userdata.get(name)
        if colab_val:
            print(f"🔐 Loaded {name} from Colab userdata!")
            return colab_val
    except Exception:
        pass
    if allow_missing:
        return None
    import getpass
    return getpass.getpass(prompt_text or f"Paste your {name}: ")

ODDS_API_KEY = load_secret('ODDS_API_KEY', '🔑 Paste your Odds API Key: ')
GEMINI_API_KEY = load_secret('GEMINI_API_KEY', allow_missing=True)
if GEMINI_API_KEY:
    print("🔐 Gemini API key ready!")
else:
    print("⚠️ No Gemini API key found — AI picks will be skipped.")

SHEET_ID = "1OpER7aRmMFWyxMONdg_LqiyQ47cA3dWRSR8UEQH8FIM"
TODAY = date.today().isoformat()  # YYYY-MM-DD
SNAPSHOT_DATE = "2026-05-04"

SHEET_SCHEMAS = {
    'Tonights_Skaters': {
        'required': ['player_name', 'team_abbr', 'opp_abbr_tonight', 'home_away_tonight', 'position',
                     'L5_GAMES_PLAYED', 'GAMES_LAST_7D', 'LIMITED_SAMPLE', 'RETURNING'],
        'recommended': ['opp_goalie_name', 'OPP_GA_PG'],
    },
    'Tonights_Goalies': {
        'required': ['player_name', 'team_abbr', 'opp_abbr_tonight'],
        'recommended': [],
    },
    'Daily_Picks': {
        'required': ['DATE', 'rank', 'player', 'team', 'prop_type', 'line', 'lean', 'confidence', 'HIT'],
        'recommended': ['CONSENSUS_COUNT', 'CONSENSUS_RUNS', 'RUN_NUMBER'],
    },
    'DK_Player_Props': {
        'required': ['PLAYER_NAME', 'METRIC', 'DK_LINE', 'OVER_ODDS', 'UNDER_ODDS'],
        'recommended': ['BOOK', 'REFERENCE_BOOK', 'BEST_OVER_BOOK', 'BEST_OVER_ODDS', 'BEST_OVER_DELTA_PP',
                        'BEST_UNDER_BOOK', 'BEST_UNDER_ODDS', 'BEST_UNDER_DELTA_PP',
                        'ALT_LINE_AVAILABLE', 'ALT_LINE_BOOKS', 'LAST_UPDATED'],
    },
    'All_Books_Props': {
        'required': ['PLAYER_NAME', 'METRIC', 'LINE', 'BOOK', 'OVER_ODDS', 'UNDER_ODDS',
                     'OVER_IMPLIED', 'UNDER_IMPLIED', 'LAST_UPDATED'],
        'recommended': [],
    },
    'Skater_Game_Logs': {
        'required': ['player_id', 'player_name', 'game_date', 'opp_abbr',
                     'G', 'A', 'PTS', 'SOG', 'BLK', 'UD_FP', 'DK_FP'],
        'recommended': ['HITS', 'PPP'],
    },
}

# NHL API base
NHL_API = "https://api-web.nhle.com/v1"
NHL_STATS = "https://api.nhle.com/stats/rest/en"

# Odds API
ODDS_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY = "icehockey_nhl"
SPORT_LABEL = "NHL"
ENABLE_FANDUEL_FALLBACK = os.getenv("ENABLE_FANDUEL_FALLBACK", "false").lower() == "true"
_last_odds_credits_remaining = None

# --- Odds API quota guard ---
QUOTA_FLOOR_GLOBAL = 2000
QUOTA_FLOOR_THIS_SPORT = {
    "MLB": 1000,
    "NBA": 800,
    "NHL": 600,
    "WNBA": 500,
    "WC": 600,
}[SPORT_LABEL]
CACHE_DIR = os.path.expanduser("~/.dfs_engines_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_TTL_SECONDS = {
    "MLB": 900,
    "NBA": 900,
    "NHL": 900,
    "WNBA": 1800,
    "WC": 1800,
}[SPORT_LABEL]


def check_quota_or_abort(resp, context: str) -> None:
    """Read x-requests-remaining from response and abort run if below floor."""
    global _last_odds_credits_remaining
    try:
        remaining = int(resp.headers.get('x-requests-remaining', '99999'))
    except (AttributeError, TypeError, ValueError):
        return
    _last_odds_credits_remaining = remaining
    try:
        runlog.odds_credits_remaining = remaining
    except Exception:
        pass
    floor = QUOTA_FLOOR_THIS_SPORT
    if remaining < floor:
        print(
            f"🛑 QUOTA GUARD: {remaining} remaining < {SPORT_LABEL} floor {floor} "
            f"({context}). Aborting run."
        )
        sys.exit(0)


def cached_odds_fetch(cache_key: str, fetch_fn):
    """Return cached payload if fresh, else fetch and cache."""
    path = os.path.join(CACHE_DIR, f"{SPORT_LABEL}_{cache_key}.json")
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_TTL_SECONDS:
        age = int(time.time() - os.path.getmtime(path))
        with open(path) as f:
            print(f"💾 Cache hit: {cache_key} (age {age}s)")
            return json.load(f)
    data = fetch_fn()
    with open(path, 'w') as f:
        json.dump(data, f)
    return data

def get_nhl_season_id(now=None):
    now = now or datetime.now()
    start_year = now.year if now.month >= 7 else now.year - 1
    return f"{start_year}{start_year + 1}"

def get_nhl_game_type(now=None):
    now = now or datetime.now()
    season_id = get_nhl_season_id(now)
    season_end_year = int(season_id[4:])
    # 2025-26 regular season ends April 16, 2026 and playoffs begin April 18, 2026.
    # We use April 18 of the season-end year as the playoff cutoff instead of flipping all of April.
    playoff_start_cutoff = date(season_end_year, 4, 18)
    return 3 if now.date() >= playoff_start_cutoff else 2

CURRENT_SEASON = get_nhl_season_id()
# Game type: 2=regular season, 3=playoffs
GAME_TYPE = get_nhl_game_type()

print(f"🏒 NHL Engine v1.2 — {TODAY}")
print(f"   Season: {CURRENT_SEASON}, Game Type: {'Playoffs' if GAME_TYPE==3 else 'Regular Season'}")

# ═══════════════════════════════════════════════
# 📊 GOOGLE SHEETS AUTH
# ═══════════════════════════════════════════════
import gspread
from google.auth import default

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
        colab_auth.authenticate_user()
        creds, _ = default(scopes=scopes)
        print("✅ Google auth via Colab")
        return gspread.authorize(creds)
    except Exception as e:
        raise RuntimeError("Google auth unavailable. Set GOOGLE_SERVICE_ACCOUNT_JSON or run in Colab.") from e

gc = get_gspread_client()
wb = gc.open_by_key(SHEET_ID)
print(f"✅ Connected to Google Sheet: {SHEET_ID}")
runlog = RunLogger(gc, SHEET_ID, sport='NHL', kind='engine')
atexit.register(runlog.finalize_and_write)

def clean_cell(val):
    """Clean values for Sheets API — must be at module level for gspread"""
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return ""
        return round(val, 4)
    return val

def safe_upload(name, rows):
    """Upload data to a named sheet tab (overwrite)"""
    if not rows:
        print(f"  ⚠️ No data for {name}, skipping")
        return
    validate_sheet_schema(name, rows)
    try:
        ws = wb.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = wb.add_worksheet(title=name, rows=max(len(rows)+1, 100), cols=40)
    headers = list(rows[0].keys())
    clean_rows = [[clean_cell(r.get(h, "")) for h in headers] for r in rows]
    ws.clear()
    ws.update([headers] + clean_rows)
    print(f"  ✅ {name}: {len(rows)} rows, {len(headers)} cols")
    try:
        runlog.record_write(name, len(rows))
    except Exception:
        pass
    time.sleep(1)

def validate_sheet_schema(sheet_name, rows_or_df):
    schema = SHEET_SCHEMAS.get(sheet_name) if 'SHEET_SCHEMAS' in globals() else None
    if not schema:
        return
    if isinstance(rows_or_df, pd.DataFrame):
        actual_cols = set(rows_or_df.columns)
    else:
        actual_cols = set(rows_or_df[0].keys()) if rows_or_df else set()
    missing_required = [c for c in schema['required'] if c not in actual_cols]
    missing_recommended = [c for c in schema['recommended'] if c not in actual_cols]
    if missing_required:
        msg = f"{sheet_name} missing REQUIRED columns: {missing_required}"
        print(f"   ❌ SCHEMA VIOLATION: {msg}")
        try:
            runlog.warn(msg)
        except Exception:
            pass
        raise RuntimeError(f"Schema validation failed for {sheet_name}: missing required {missing_required}")
    if missing_recommended:
        msg = f"{sheet_name} missing recommended columns: {missing_recommended}"
        print(f"   ⚠️ SCHEMA WARNING: {msg}")
        try:
            runlog.warn(msg)
        except Exception:
            pass

def normalize_date(val):
    """Convert any date format to ISO for consistent comparison.
    Handles: '2026-04-14', '4/14/2026', '04/14/2026'"""
    if not val:
        return ""
    val = str(val).strip()
    if re.match(r'^\d{4}-\d{2}-\d{2}', val):
        return val[:10]  # already ISO, trim any time portion
    for fmt in ('%m/%d/%Y', '%m/%d/%y'):
        try:
            return datetime.strptime(val, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return val

def to_num(val, default=0):
    if val in (None, ""):
        return default
    try:
        num = float(val)
        return default if math.isnan(num) or math.isinf(num) else num
    except Exception:
        return default

def load_existing_logs(sheet_name, numeric_fields):
    try:
        ws = wb.worksheet(sheet_name)
        rows = ws.get_all_records()
    except Exception:
        return []
    cleaned = []
    for row in rows:
        rec = dict(row)
        if "game_date" in rec:
            rec["game_date"] = normalize_date(rec.get("game_date"))
        for field in numeric_fields:
            if field in rec:
                rec[field] = to_num(rec.get(field), 0)
        cleaned.append(rec)
    return cleaned

def load_existing_daily_picks(sheet_name, target_date):
    try:
        ws = wb.worksheet(sheet_name)
        rows = ws.get_all_records()
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "DATE" not in df.columns:
        return pd.DataFrame()
    df["DATE"] = df["DATE"].map(normalize_date)
    return df[df["DATE"] == target_date].copy()

def refresh_clv_daily_picks(sheet_name, target_date, props_rows, timestamp_label):
    if not props_rows:
        return
    try:
        ws = wb.worksheet(sheet_name)
        values = ws.get_all_values()
    except Exception:
        return
    if not values:
        return
    rows = [list(r) for r in values]
    headers = rows[0]
    clv_cols = ['CLV_OPEN_LINE', 'CLV_LATEST_LINE', 'CLV_DELTA', 'CLV_LAST_UPDATE']
    changed = False
    for col in clv_cols:
        if col not in headers:
            headers.append(col)
            for r in rows[1:]:
                r.append('')
            changed = True
    rows[0] = headers
    col_idx = {h: i for i, h in enumerate(headers)}
    line_map = {}
    for prop in props_rows:
        try:
            latest_line = float(prop.get('DK_LINE'))
        except (TypeError, ValueError):
            continue
        key = (
            normalize_player_name(prop.get('PLAYER_NAME', '')),
            normalize_prop_metric(prop.get('METRIC', '')),
        )
        line_map[key] = latest_line
    for r in rows[1:]:
        while len(r) < len(headers):
            r.append('')
        if normalize_date(r[col_idx['DATE']]) != target_date:
            continue
        key = (
            normalize_player_name(r[col_idx.get('player', 0)]),
            normalize_prop_metric(r[col_idx.get('prop_type', 0)]),
        )
        if key not in line_map:
            continue
        latest_line = line_map[key]
        open_raw = r[col_idx['CLV_OPEN_LINE']] or r[col_idx.get('line', 0)]
        try:
            open_line = float(open_raw)
        except (TypeError, ValueError):
            open_line = None
        new_latest = f"{latest_line:g}"
        new_delta = f"{(latest_line - open_line):+.1f}" if open_line is not None else ''
        if open_line is not None and r[col_idx['CLV_OPEN_LINE']] != f"{open_line:g}":
            r[col_idx['CLV_OPEN_LINE']] = f"{open_line:g}"
            changed = True
        if r[col_idx['CLV_LATEST_LINE']] != new_latest:
            r[col_idx['CLV_LATEST_LINE']] = new_latest
            changed = True
        if r[col_idx['CLV_DELTA']] != new_delta:
            r[col_idx['CLV_DELTA']] = new_delta
            changed = True
        if r[col_idx['CLV_LAST_UPDATE']] != timestamp_label:
            r[col_idx['CLV_LAST_UPDATE']] = timestamp_label
            changed = True
    if changed:
        ws.clear()
        ws.update(rows, value_input_option='RAW')
        print("  🔁 CLV latest-line tracker refreshed for today's existing picks.")

def load_boxscore_cache(sheet_name="Boxscore_Cache"):
    try:
        ws = wb.worksheet(sheet_name)
        rows = ws.get_all_records()
    except Exception:
        return {}, set()
    cache = {}
    cached_game_ids = set()
    for row in rows:
        gid = str(row.get("gameId", "")).strip()
        pid = str(row.get("playerId", "")).strip()
        if not gid or not pid:
            continue
        cache[(gid, pid)] = {
            "BLK": int(round(to_num(row.get("BLK"), 0))),
            "HITS": int(round(to_num(row.get("HITS"), 0))),
            "FOW": int(round(to_num(row.get("FOW"), 0))),
        }
        cached_game_ids.add(gid)
    return cache, cached_game_ids

def build_skater_sample_flags(skater_logs_by_player, ref_date=None):
    ref_ts = pd.to_datetime(ref_date or TODAY)
    last7_cutoff = ref_ts - pd.Timedelta(days=6)
    flags = {}
    for pid_key, rows in skater_logs_by_player.items():
        if not rows:
            continue
        sorted_rows = sorted(rows, key=lambda x: normalize_date(x.get("game_date", "")))
        ud_vals = [to_num(r.get("UD_FP", 0), 0) for r in sorted_rows]
        l5_games = min(5, len(sorted_rows))
        season_avg = sum(ud_vals) / len(ud_vals) if ud_vals else 0
        l5_avg = sum(ud_vals[-5:]) / min(5, len(ud_vals)) if ud_vals else 0
        game_dates = pd.to_datetime([normalize_date(r.get("game_date", "")) for r in sorted_rows], errors='coerce')
        games_last_7d = int(((game_dates >= last7_cutoff) & (game_dates <= ref_ts)).sum())
        flags[pid_key] = {
            "L5_GAMES_PLAYED": int(l5_games),
            "GAMES_LAST_7D": int(games_last_7d),
            "LIMITED_SAMPLE": l5_games < 3,
            "RETURNING": bool(season_avg > 0 and l5_avg < (0.7 * season_avg) and games_last_7d < 4),
        }
    return flags

def latest_game_date(rows):
    dates = [normalize_date(r.get("game_date")) for r in rows if normalize_date(r.get("game_date"))]
    return max(dates) if dates else ""

def normalize_player_name(name):
    text = unicodedata.normalize('NFKD', str(name or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[’'`\.]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def normalize_prop_metric(metric):
    return re.sub(r"\s+", "", str(metric or "").strip().upper())

def normalize_confidence(val):
    conf = str(val or "").strip().upper()
    return conf if conf in {"SMASH", "STRONG", "LEAN"} else "LEAN"

def parse_gemini_json_array(raw):
    cleaned = str(raw or "").strip()
    json_match = re.search(r'\[[\s\S]*\]', cleaned)
    if json_match:
        cleaned = json_match.group(0)
    elif cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[1] if '\n' in cleaned else cleaned[3:]
        cleaned = cleaned.rsplit('```', 1)[0]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        lc = cleaned.rfind('}')
        if lc > 0:
            return json.loads(cleaned[:lc + 1] + ']')
        raise

def promote_consensus_confidence(confidence, consensus_count):
    conf = normalize_confidence(confidence)
    if consensus_count < 2:
        return conf
    if conf == 'LEAN':
        return 'STRONG'
    if conf == 'STRONG':
        return 'SMASH'
    return conf

def build_consensus_pick_pool(pick_lists):
    grouped = {}
    for run_idx, picks in enumerate(pick_lists, start=1):
        for pick in picks or []:
            player_key = normalize_player_name(pick.get('player', ''))
            prop_key = normalize_prop_metric(pick.get('prop_type', ''))
            lean_key = str(pick.get('lean', '') or '').strip().upper()
            if not player_key or not prop_key or not lean_key:
                continue
            key = (player_key, prop_key, lean_key)
            entry = grouped.setdefault(key, {'pick': dict(pick), 'count': 0, 'runs': [], 'best_rank': 999})
            if run_idx not in entry['runs']:
                entry['runs'].append(run_idx)
                entry['count'] += 1
            try:
                rank_val = int(float(pick.get('rank', 999)))
            except (TypeError, ValueError):
                rank_val = 999
            if rank_val < entry['best_rank']:
                entry['pick'] = dict(pick)
                entry['best_rank'] = rank_val
    merged = []
    for entry in grouped.values():
        pick = dict(entry['pick'])
        pick['CONSENSUS_COUNT'] = entry['count']
        pick['CONSENSUS_RUNS'] = ','.join(str(r) for r in entry['runs'])
        pick['CONSENSUS_TAG'] = f"CONSENSUS {entry['count']}/3" if entry['count'] >= 2 else ""
        pick['confidence'] = promote_consensus_confidence(pick.get('confidence'), entry['count'])
        merged.append(pick)
    merged.sort(key=lambda pk: (-int(pk.get('CONSENSUS_COUNT', 1)), float(pk.get('rank', 999) or 999)))
    for idx, pick in enumerate(merged, start=1):
        pick['rank'] = idx
    return merged

def append_upload(sheet_name, df):
    if df is None or len(df) == 0:
        print(f"⏭️ Skipping append '{sheet_name}' — no data.")
        return
    validate_sheet_schema(sheet_name, df)
    try:
        try:
            ws = wb.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = wb.add_worksheet(title=sheet_name, rows=5000, cols=30)
            ws.update([df.columns.tolist()])

        existing = ws.get_all_values()
        cleaned = [[clean_cell(v) for v in row] for row in df.values.tolist()]

        if len(existing) <= 1:
            ws.update([df.columns.tolist()] + cleaned)
        else:
            headers = existing[0]
            all_headers = headers + [c for c in df.columns.tolist() if c not in headers]
            df_aligned = df.copy()
            for col in all_headers:
                if col not in df_aligned.columns:
                    df_aligned[col] = ""
            df_aligned = df_aligned[all_headers]
            cleaned = [[clean_cell(v) for v in row] for row in df_aligned.values.tolist()]
            if all_headers != headers:
                final_rows = [all_headers]
                for row in existing[1:]:
                    row_map = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                    final_rows.append([row_map.get(h, "") for h in all_headers])
                final_rows.extend(cleaned)
                ws.clear()
                ws.update(final_rows, value_input_option='RAW')
            else:
                ws.append_rows(cleaned, value_input_option='RAW')

        print(f"✅ Appended {len(df)} rows to '{sheet_name}'")
        try:
            runlog.record_write(sheet_name, len(df))
        except Exception:
            pass
    except Exception as e:
        print(f"❌ FAILED append '{sheet_name}': {e}")

# ═══════════════════════════════════════════════
# 🏒 NHL API HELPERS
# ═══════════════════════════════════════════════
def nhl_get(url):
    """Fetch from NHL API with retries"""
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
            print(f"  ⚠️ NHL API {r.status_code}: {url[:80]}")
        except Exception as e:
            print(f"  ⚠️ NHL API error (attempt {attempt+1}): {e}")
        time.sleep(1)
    return None

# ═══════════════════════════════════════════════
# 📅 STEP 1: TONIGHT'S SCHEDULE
# ═══════════════════════════════════════════════
print(f"\n📅 Fetching schedule for {TODAY}...")
schedule_data = nhl_get(f"{NHL_API}/schedule/{TODAY}")
games = []
if schedule_data:
    for day in schedule_data.get("gameWeek", []):
        if day.get("date") == TODAY:
            games = day.get("games", [])
            break

if not games:
    print("❌ No NHL games today!")
    # Still try — might be a schedule format issue
    # Try alternate endpoint
    sched2 = nhl_get(f"{NHL_API}/score/{TODAY}")
    if sched2:
        games = sched2.get("games", [])

print(f"  Found {len(games)} games tonight")
for g in games:
    away = g.get("awayTeam", {}).get("abbrev", "?")
    home = g.get("homeTeam", {}).get("abbrev", "?")
    print(f"    {away} @ {home}")

# Build team pairs
game_pairs = []
team_opponents = {}  # team_abbr -> opp_abbr
team_home_away = {}  # team_abbr -> "Home"/"Away"
team_game_totals = {}
team_spreads = {}
team_moneylines = {}
starter_goalies = {}

for g in games:
    away_abbr = g.get("awayTeam", {}).get("abbrev", "")
    home_abbr = g.get("homeTeam", {}).get("abbrev", "")
    venue = g.get("venue", {}).get("default", "")
    game_pairs.append({"away": away_abbr, "home": home_abbr, "venue": venue, "game_id": g.get("id")})
    team_opponents[away_abbr] = home_abbr
    team_opponents[home_abbr] = away_abbr
    team_home_away[away_abbr] = "Away"
    team_home_away[home_abbr] = "Home"

def norm_name(name):
    return re.sub(r'[^a-z0-9]+', '', str(name or '').lower())

def extract_goalie_candidate(raw_value, status):
    if not raw_value:
        return None
    candidate = raw_value[0] if isinstance(raw_value, list) and raw_value else raw_value
    if isinstance(candidate, str):
        name = candidate.strip()
        return {"player_name": name, "id": None, "status": status} if name else None
    if not isinstance(candidate, dict):
        return None
    name = (
        candidate.get("fullName") or
        candidate.get("name") if isinstance(candidate.get("name"), str) else None or
        candidate.get("goalieName") or
        candidate.get("name", {}).get("default") or
        candidate.get("default") or
        candidate.get("player", {}).get("fullName") or
        candidate.get("player", {}).get("name", {}).get("default") or
        candidate.get("playerName", {}).get("default") or
        (
            candidate.get("firstName", {}).get("default", "") + " " +
            candidate.get("lastName", {}).get("default", "")
        ) if isinstance(candidate.get("firstName"), dict) or isinstance(candidate.get("lastName"), dict) else "" or
        f"{candidate.get('firstName', '')} {candidate.get('lastName', '')}".strip()
    ).strip()
    if not name:
        return None
    return {
        "player_name": name,
        "id": candidate.get("id") or candidate.get("playerId") or candidate.get("goalieId") or candidate.get("player", {}).get("id"),
        "status": status,
    }

def get_game_goalie_map(game):
    goalie_map = {}
    team_field_map = {
        game.get("awayTeam", {}).get("abbrev", ""): game.get("awayTeam", {}),
        game.get("homeTeam", {}).get("abbrev", ""): game.get("homeTeam", {}),
    }
    for abbr, team_blob in team_field_map.items():
        if not abbr:
            continue
        for field_name, status in [
            ("startingGoalie", "confirmed"),
            ("starterGoalie", "confirmed"),
            ("startingGoalies", "confirmed"),
            ("goalie", "confirmed"),
            ("probableGoalie", "probable"),
            ("projectedGoalie", "projected"),
            ("goalies", "projected"),
        ]:
            candidate = extract_goalie_candidate(team_blob.get(field_name), status)
            if candidate:
                goalie_map[abbr] = candidate
                break
    return goalie_map

tonight_teams = set(team_opponents.keys())
print(f"  Teams playing: {', '.join(sorted(tonight_teams))}")

# ═══════════════════════════════════════════════
# 👥 STEP 2: ROSTERS — Get player IDs for tonight's teams
# ═══════════════════════════════════════════════
print("\n👥 Fetching rosters...")
all_skaters = []   # {id, name, team, pos, ...}
all_goalies = []
goalies_by_team = defaultdict(list)

for team in sorted(tonight_teams):
    roster = nhl_get(f"{NHL_API}/roster/{team}/current")
    if not roster:
        print(f"  ⚠️ No roster for {team}")
        continue
    for group in ["forwards", "defensemen"]:
        for p in roster.get(group, []):
            all_skaters.append({
                "id": p.get("id"),
                "player_name": f"{p.get('firstName',{}).get('default','')} {p.get('lastName',{}).get('default','')}".strip(),
                "team_abbr": team,
                "position": p.get("positionCode", ""),
                "sweater": p.get("sweaterNumber", ""),
            })
    for p in roster.get("goalies", []):
        goalie_row = {
            "id": p.get("id"),
            "player_name": f"{p.get('firstName',{}).get('default','')} {p.get('lastName',{}).get('default','')}".strip(),
            "team_abbr": team,
            "position": "G",
        }
        all_goalies.append(goalie_row)
        goalies_by_team[team].append(goalie_row)
    time.sleep(0.3)

print(f"  {len(all_skaters)} skaters, {len(all_goalies)} goalies across {len(tonight_teams)} teams")

print("\n🥅 Resolving starter/probable goalies...")
for gp in game_pairs:
    game = next((g for g in games if g.get("id") == gp.get("game_id")), None)
    if not game:
        continue
    goalie_map = get_game_goalie_map(game)
    if len(goalie_map) < 2 and gp.get("game_id"):
        boxscore = nhl_get(f"{NHL_API}/gamecenter/{gp['game_id']}/boxscore")
        if boxscore:
            boxscore_goalie_map = get_game_goalie_map(boxscore)
            for team_abbr, goalie_info in boxscore_goalie_map.items():
                goalie_map.setdefault(team_abbr, goalie_info)
    for team_abbr, goalie_info in goalie_map.items():
        starter_goalies[team_abbr] = goalie_info

fallback_goalie_count = 0
for team_abbr in tonight_teams:
    if team_abbr not in starter_goalies:
        roster_goalies = goalies_by_team.get(team_abbr, [])
        if roster_goalies:
            starter_goalies[team_abbr] = {
                "player_name": roster_goalies[0]["player_name"],
                "id": roster_goalies[0]["id"],
                "status": "roster",
            }
            fallback_goalie_count += 1

starter_count = sum(1 for info in starter_goalies.values() if info.get("status") == "confirmed")
probable_count = sum(1 for info in starter_goalies.values() if info.get("status") == "probable")
projected_count = sum(1 for info in starter_goalies.values() if info.get("status") == "projected")
print(f"  ✅ Goalie signals: {starter_count} confirmed, {probable_count} probable, {projected_count} projected, {fallback_goalie_count} roster fallback")

# ═══════════════════════════════════════════════
# 📈 STEP 2.5: TEAM ADVANCED STATS (GA/G, PK%)
# ═══════════════════════════════════════════════
print("\n📈 Fetching team advanced stats...")
team_stats = {}

NHL_NAME_TO_ABBR = {
    "Anaheim Ducks":"ANA","Arizona Coyotes":"ARI","Boston Bruins":"BOS","Buffalo Sabres":"BUF",
    "Calgary Flames":"CGY","Carolina Hurricanes":"CAR","Chicago Blackhawks":"CHI","Colorado Avalanche":"COL",
    "Columbus Blue Jackets":"CBJ","Dallas Stars":"DAL","Detroit Red Wings":"DET","Edmonton Oilers":"EDM",
    "Florida Panthers":"FLA","Los Angeles Kings":"LAK","Minnesota Wild":"MIN","Montréal Canadiens":"MTL",
    "Montreal Canadiens":"MTL","Nashville Predators":"NSH","New Jersey Devils":"NJD","New York Islanders":"NYI",
    "New York Rangers":"NYR","Ottawa Senators":"OTT","Philadelphia Flyers":"PHI","Pittsburgh Penguins":"PIT",
    "San Jose Sharks":"SJS","Seattle Kraken":"SEA","St. Louis Blues":"STL","Tampa Bay Lightning":"TBL",
    "Toronto Maple Leafs":"TOR","Utah Hockey Club":"UTA","Utah HC":"UTA","Utah Mammoth":"UTA","Vancouver Canucks":"VAN","Vegas Golden Knights":"VGK",
    "Washington Capitals":"WSH","Winnipeg Jets":"WPG",
}

try:
    # Always get regular season stats (reliable), supplement with playoff if available
    data = nhl_get(f"{NHL_STATS}/team/summary?cayenneExp=seasonId={CURRENT_SEASON}%20and%20gameTypeId=2")
    if data:
        for t in data.get("data", []):
            full_name = t.get("teamFullName", "")
            abbr = NHL_NAME_TO_ABBR.get(full_name, "")
            if abbr not in tonight_teams:
                continue
            team_stats[abbr] = {
                "GA_PG": round(t.get("goalsAgainstPerGame", 0), 2),
                "PP_PCT": round(t.get("powerPlayPct", 0) * 100, 1),
                "PK_PCT": round(t.get("penaltyKillPct", 0) * 100, 1),
            }
    print(f"  ✅ Team stats for {len(team_stats)} teams")
except Exception as e:
    print(f"  ⚠️ Team stats error: {e}")

# ═══════════════════════════════════════════════
# ═══════════════════════════════════════════════
# 📊 STEP 3: SKATER GAME LOGS + ROLLING AVERAGES
# ═══════════════════════════════════════════════
print("\n📊 Fetching skater game logs...")
print(f"  Pulling logs for {len(all_skaters)} skaters...")

SKATER_STATS = ["G", "A", "PTS", "SOG", "BLK", "HITS", "PPP", "FOW", "PIM", "TOI", "plusMinus"]

existing_skater_logs = load_existing_logs(
    "Skater_Game_Logs",
    ["G", "A", "PTS", "SOG", "BLK", "HITS", "PPP", "FOW", "PIM", "plusMinus", "DK_FP", "UD_FP"]
)
latest_skater_date = latest_game_date(existing_skater_logs)
latest_skater_date_by_pid = {}
for row in existing_skater_logs:
    pid_key = str(row.get("player_id", ""))
    game_date = normalize_date(row.get("game_date", ""))
    if pid_key and game_date and (pid_key not in latest_skater_date_by_pid or game_date > latest_skater_date_by_pid[pid_key]):
        latest_skater_date_by_pid[pid_key] = game_date
if latest_skater_date:
    print(f"  ♻️ Seeding from Skater_Game_Logs through {latest_skater_date} ({len(existing_skater_logs)} existing rows)")
else:
    print("  🆕 No existing Skater_Game_Logs seed found — full skater fetch")

# Phase A: fetch raw game logs per skater (BLK/HITS filled later from boxscore)
skater_raw = {}  # {player_id: [row, row, ...]}
new_skater_rows = 0
for i, sk in enumerate(all_skaters, start=1):
    pid = sk["id"]
    player_latest_skater_date = latest_skater_date_by_pid.get(str(pid), "")
    reg_data = nhl_get(f"{NHL_API}/player/{pid}/game-log/{CURRENT_SEASON}/2")
    reg_logs = reg_data.get("gameLog", []) if reg_data else []
    playoff_logs = []
    if GAME_TYPE == 3:
        po_data = nhl_get(f"{NHL_API}/player/{pid}/game-log/{CURRENT_SEASON}/3")
        playoff_logs = po_data.get("gameLog", []) if po_data else []
    logs = playoff_logs + reg_logs  # playoff games first
    if not logs:
        continue
    parsed = []
    for g in logs:
        game_date = normalize_date(g.get("gameDate", ""))
        if player_latest_skater_date and game_date and game_date <= player_latest_skater_date:
            continue
        parsed.append({
            "player_id": pid,
            "gameId": g.get("gameId") or g.get("id"),
            "player_name": sk["player_name"],
            "team_abbr": sk["team_abbr"],
            "game_date": game_date,
            "opp_abbr": g.get("opponentAbbrev", ""),
            "home_away": "Home" if g.get("homeRoadFlag") == "H" else "Away",
            "G": g.get("goals", 0),
            "A": g.get("assists", 0),
            "PTS": g.get("points", 0),
            "SOG": g.get("shots", 0),
            "BLK": 0,   # filled in Phase B
            "HITS": 0,  # filled in Phase B
            "PPP": g.get("powerPlayPoints", 0) if "powerPlayPoints" in g else (g.get("powerPlayGoals", 0) + g.get("powerPlayAssists", 0) if "powerPlayGoals" in g else 0),
            "FOW": g.get("faceoffWins", g.get("faceOffWins", 0) or 0),
            "TOI": g.get("toi", "0:00"),
            "plusMinus": g.get("plusMinus", 0),
        })
    if parsed:
        skater_raw[pid] = parsed
        new_skater_rows += len(parsed)
    time.sleep(0.15)
    if i % 25 == 0 or i == len(all_skaters):
        print(f"  ... {i}/{len(all_skaters)} skater logs processed")

print(f"  ✅ Fetched {new_skater_rows} new skater game logs across {len(skater_raw)} skaters")

# Phase B: fetch boxscores once per unique game, build BLK/HITS/FOW lookup
print("\n🥊 Fetching boxscores for BLK/HITS/FOW enrichment...")
unique_game_ids = {r["gameId"] for rows in skater_raw.values() for r in rows if r["gameId"]}
print(f"  {len(unique_game_ids)} unique games to fetch")

bs_lookup, cached_game_ids = load_boxscore_cache()
new_boxscore_cache_rows = []
cached_game_count = len(unique_game_ids & cached_game_ids)
games_to_fetch = [gid for gid in unique_game_ids if str(gid) not in cached_game_ids]
if cached_game_count:
    print(f"  ♻️ Reusing cached boxscores for {cached_game_count} games")
print(f"  🌐 Fetching {len(games_to_fetch)} uncached boxscores")

bs_fetched = 0
bs_failed = 0
for gid in games_to_fetch:
    bs = nhl_get(f"{NHL_API}/gamecenter/{gid}/boxscore")
    if not bs:
        bs_failed += 1
        continue
    stats = bs.get("playerByGameStats", {})
    for team_key in ("homeTeam", "awayTeam"):
        team = stats.get(team_key, {}) or {}
        for group in ("forwards", "defense"):
            for p in team.get(group, []) or []:
                ppid = p.get("playerId")
                if not ppid:
                    continue
                cache_row = {
                    "gameId": str(gid),
                    "playerId": str(ppid),
                    "BLK": p.get("blockedShots", 0) or 0,
                    "HITS": p.get("hits", 0) or 0,
                    "FOW": p.get("faceoffWins", p.get("faceOffWins", 0) or 0),
                    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                bs_lookup[(str(gid), str(ppid))] = {
                    "BLK": cache_row["BLK"],
                    "HITS": cache_row["HITS"],
                    "FOW": cache_row["FOW"],
                }
                new_boxscore_cache_rows.append(cache_row)
    bs_fetched += 1
    if bs_fetched % 50 == 0:
        print(f"  ... {bs_fetched}/{len(games_to_fetch)} boxscores fetched")
    time.sleep(0.1)
print(f"  ✅ {bs_fetched} boxscores fetched, {bs_failed} failed, {len(bs_lookup)} player-game entries")

# Phase C: enrich BLK/HITS, compute DK_FP, compute rolling averages, build skater_tonight
print("\n📊 Computing rolling averages with enriched stats...")
combined_skater_logs = list(existing_skater_logs)
existing_skater_keys = {
    (
        str(r.get("player_id", "")),
        str(r.get("gameId", "")),
        normalize_date(r.get("game_date", "")),
        str(r.get("opp_abbr", "")),
        str(r.get("home_away", "")),
    )
    for r in existing_skater_logs
}
skater_tonight = []

def avg(lst, key, n):
    sl = lst[:n]
    return round(sum(r.get(key, 0) for r in sl) / len(sl), 3) if sl else 0

for sk in all_skaters:
    pid = sk["id"]
    parsed_new = skater_raw.get(pid, [])

    # Enrich BLK/HITS/FOW from boxscore, recompute DK_FP with real BLK
    for row in parsed_new:
        key = (str(row["gameId"]), str(pid))
        if key in bs_lookup:
            row["BLK"] = bs_lookup[key]["BLK"]
            row["HITS"] = bs_lookup[key]["HITS"]
            row["FOW"] = bs_lookup[key].get("FOW", row.get("FOW", 0))
        row["DK_FP"] = round(row["G"]*8.5 + row["A"]*5 + row["SOG"]*1.5 + row["BLK"]*1.3, 1)
        row["UD_FP"] = round(row["G"]*6 + row["A"]*4 + row["PPP"]*0.5 + row["SOG"]*1 + row["HITS"]*0.5 + row["BLK"]*1, 1)
        row_key = (
            str(row.get("player_id", "")),
            str(row.get("gameId", "")),
            normalize_date(row.get("game_date", "")),
            str(row.get("opp_abbr", "")),
            str(row.get("home_away", "")),
        )
        if row_key not in existing_skater_keys:
            combined_skater_logs.append(row)
            existing_skater_keys.add(row_key)

skater_logs_by_player = defaultdict(list)
for row in combined_skater_logs:
    pid_key = str(row.get("player_id", ""))
    if pid_key:
        skater_logs_by_player[pid_key].append(row)

skater_logs = []
for pid_key, rows in skater_logs_by_player.items():
    rows.sort(key=lambda x: normalize_date(x["game_date"]), reverse=True)
    skater_logs.extend(rows)

skater_sample_flags = build_skater_sample_flags(skater_logs_by_player, TODAY)
limited_ct = sum(1 for info in skater_sample_flags.values() if info.get("LIMITED_SAMPLE"))
returning_ct = sum(1 for info in skater_sample_flags.values() if info.get("RETURNING"))
print(f"  ✅ Sample flags built — {limited_ct} LIMITED_SAMPLE, {returning_ct} RETURNING")

for sk in all_skaters:
    pid = sk["id"]
    parsed = skater_logs_by_player.get(str(pid))
    if not parsed:
        continue

    most = parsed[0].copy()
    for stat in ["G", "A", "PTS", "SOG", "BLK", "HITS", "PPP", "FOW", "PIM", "DK_FP", "UD_FP"]:
        most[f"Seas_{stat}"] = avg(parsed, stat, len(parsed))
        most[f"L5_{stat}"]   = avg(parsed, stat, 5)
        most[f"L3_{stat}"]   = avg(parsed, stat, 3)

    most["opp_abbr_tonight"] = team_opponents.get(sk["team_abbr"], "")
    most["home_away_tonight"] = team_home_away.get(sk["team_abbr"], "")
    most["position"] = sk["position"]
    most["LAST_UPDATED"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    opp = team_opponents.get(sk["team_abbr"], "")
    h2h_rows = [r for r in parsed if str(r.get("opp_abbr", "")).upper() == opp]
    most["H2H_GP"] = len(h2h_rows)
    for stat in ["G", "A", "PTS", "SOG", "BLK", "HITS", "PPP", "FOW", "UD_FP"]:
        most[f"H2H_{stat}"] = avg(h2h_rows, stat, len(h2h_rows)) if h2h_rows else 0

    starter_info = starter_goalies.get(opp, {})
    if starter_info:
        most["opp_goalie_name"] = starter_info.get("player_name", "TBD")
        most["opp_goalie_status"] = starter_info.get("status", "")
    else:
        opp_goalies = [g for g in all_goalies if g["team_abbr"] == opp]
        most["opp_goalie_name"] = opp_goalies[0]["player_name"] if opp_goalies else "TBD"
        most["opp_goalie_status"] = "roster"

    opp_stats = team_stats.get(opp, {})
    most["OPP_GA_PG"] = opp_stats.get("GA_PG", 0)
    most["OPP_PK_PCT"] = opp_stats.get("PK_PCT", 0)
    most["OPP_PP_PCT"] = opp_stats.get("PP_PCT", 0)
    most["GAME_TOTAL"] = team_game_totals.get(sk["team_abbr"], 0)
    most["SPREAD"] = team_spreads.get(sk["team_abbr"], "")
    most.update(skater_sample_flags.get(str(pid), {
        "L5_GAMES_PLAYED": 0,
        "GAMES_LAST_7D": 0,
        "LIMITED_SAMPLE": False,
        "RETURNING": False,
    }))

    skater_tonight.append(most)

print(f"  ✅ {len(skater_tonight)} skaters with logs, {len(skater_logs)} combined game log rows")

# ═══════════════════════════════════════════════
# 🧱 STEP 4: GOALIE GAME LOGS + ROLLING AVERAGES
# ═══════════════════════════════════════════════
print("\n🧱 Fetching goalie game logs...")
print(f"  Pulling logs for {len(all_goalies)} goalies...")
existing_goalie_logs = load_existing_logs(
    "Goalie_Game_Logs",
    ["W", "L", "SV", "GA", "SA", "SV_PCT", "SO", "DK_FP", "UD_FP"]
)
latest_goalie_date = latest_game_date(existing_goalie_logs)
latest_goalie_date_by_name = {}
for row in existing_goalie_logs:
    name_key = normalize_player_name(row.get("player_name", ""))
    game_date = normalize_date(row.get("game_date", ""))
    if name_key and game_date and (name_key not in latest_goalie_date_by_name or game_date > latest_goalie_date_by_name[name_key]):
        latest_goalie_date_by_name[name_key] = game_date
if latest_goalie_date:
    print(f"  ♻️ Seeding from Goalie_Game_Logs through {latest_goalie_date} ({len(existing_goalie_logs)} existing rows)")
else:
    print("  🆕 No existing Goalie_Game_Logs seed found — full goalie fetch")

combined_goalie_logs = list(existing_goalie_logs)
existing_goalie_keys = {
    (
        normalize_player_name(r.get("player_name", "")),
        normalize_date(r.get("game_date", "")),
        str(r.get("opp_abbr", "")),
        str(r.get("home_away", "")),
    )
    for r in existing_goalie_logs
}
goalie_tonight = []
new_goalie_rows = 0

for i, gk in enumerate(all_goalies, start=1):
    starter_info = starter_goalies.get(gk["team_abbr"])
    if starter_info:
        starter_id = starter_info.get("id")
        starter_name = starter_info.get("player_name", "")
        if starter_id and gk["id"] != starter_id:
            continue
        if not starter_id and starter_name and norm_name(gk["player_name"]) != norm_name(starter_name):
            continue
    pid = gk["id"]
    goalie_latest_date = latest_goalie_date_by_name.get(normalize_player_name(gk["player_name"]), "")
    reg_data = nhl_get(f"{NHL_API}/player/{pid}/game-log/{CURRENT_SEASON}/2")
    reg_logs = reg_data.get("gameLog", []) if reg_data else []
    playoff_logs = []
    if GAME_TYPE == 3:
        po_data = nhl_get(f"{NHL_API}/player/{pid}/game-log/{CURRENT_SEASON}/3")
        playoff_logs = po_data.get("gameLog", []) if po_data else []
    logs = playoff_logs + reg_logs
    if not logs:
        continue
    parsed = []
    for g in logs:
        game_date = normalize_date(g.get("gameDate", ""))
        if goalie_latest_date and game_date and game_date <= goalie_latest_date:
            continue
        sa = g.get("shotsAgainst", 0)
        ga = g.get("goalsAgainst", 0)
        sv = sa - ga if sa else 0
        svp = round(sv / sa, 3) if sa > 0 else 0
        row = {
            "player_id": pid,
            "player_name": gk["player_name"],
            "team_abbr": gk["team_abbr"],
            "game_date": game_date,
            "opp_abbr": g.get("opponentAbbrev", ""),
            "home_away": "Home" if g.get("homeRoadFlag") == "H" else "Away",
            "W": 1 if g.get("decision") == "W" else 0,
            "L": 1 if g.get("decision") == "L" else 0,
            "SV": sv,
            "GA": ga,
            "SA": sa,
            "SV_PCT": svp,
            "SO": 1 if ga == 0 else 0,
            "TOI": g.get("toi", "0:00"),
            "DK_FP": round(sv * 0.7 + (6 if g.get("decision") == "W" else 0) + ga * -3 + (5 if ga == 0 else 0), 1),
            "UD_FP": round(sv * 0.6 + (6 if g.get("decision") == "W" else 0) + ga * -3, 1),
        }
        parsed.append(row)
    for row in parsed:
        row_key = (
            normalize_player_name(row.get("player_name", "")),
            normalize_date(row.get("game_date", "")),
            str(row.get("opp_abbr", "")),
            str(row.get("home_away", "")),
        )
        if row_key not in existing_goalie_keys:
            combined_goalie_logs.append(row)
            existing_goalie_keys.add(row_key)
            new_goalie_rows += 1

goalie_logs_by_name = defaultdict(list)
for row in combined_goalie_logs:
    goalie_logs_by_name[normalize_player_name(row.get("player_name", ""))].append(row)

goalie_logs = []
for name_key, rows in goalie_logs_by_name.items():
    rows.sort(key=lambda x: normalize_date(x["game_date"]), reverse=True)
    goalie_logs.extend(rows)

print(f"  ✅ Fetched {new_goalie_rows} new goalie game logs")

for i, gk in enumerate(all_goalies, start=1):
    starter_info = starter_goalies.get(gk["team_abbr"])
    if starter_info:
        starter_id = starter_info.get("id")
        starter_name = starter_info.get("player_name", "")
        if starter_id and gk["id"] != starter_id:
            continue
        if not starter_id and starter_name and norm_name(gk["player_name"]) != norm_name(starter_name):
            continue
    parsed = goalie_logs_by_name.get(normalize_player_name(gk["player_name"]))
    if not parsed:
        continue

    def avg(lst, key, n):
        sl = lst[:n]
        return round(sum(r.get(key, 0) for r in sl) / len(sl), 3) if sl else 0

    most = parsed[0].copy()
    for stat in ["W", "SV", "GA", "SA", "SV_PCT", "SO", "DK_FP", "UD_FP"]:
        most[f"Seas_{stat}"] = avg(parsed, stat, len(parsed))
        most[f"L5_{stat}"] = avg(parsed, stat, 5)
        most[f"L3_{stat}"] = avg(parsed, stat, 3)

    most["opp_abbr_tonight"] = team_opponents.get(gk["team_abbr"], "")
    most["home_away_tonight"] = team_home_away.get(gk["team_abbr"], "")
    most["starter_status"] = starter_goalies.get(gk["team_abbr"], {}).get("status", "roster")
    most["LAST_UPDATED"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    goalie_tonight.append(most)
    if i % 5 == 0 or i == len(all_goalies):
        print(f"  ... {i}/{len(all_goalies)} goalie logs processed")

print(f"  ✅ {len(goalie_tonight)} goalies with logs, {len(goalie_logs)} combined log rows")

# ═══════════════════════════════════════════════
# 🏠 STEP 5: HOME/AWAY SPLITS
# ═══════════════════════════════════════════════
print("\n🏠 Computing home/away splits...")
skater_splits = []
for name in set(r["player_name"] for r in skater_logs):
    plogs = [r for r in skater_logs if r["player_name"] == name]
    home = [r for r in plogs if r["home_away"] == "Home"]
    away = [r for r in plogs if r["home_away"] == "Away"]
    if not home and not away:
        continue
    sp = {"player_name": name, "Home_GAMES": len(home), "Away_GAMES": len(away)}
    for stat in ["G", "A", "PTS", "SOG", "BLK", "HITS", "PPP", "FOW", "DK_FP", "UD_FP"]:
        sp[f"{stat}_Home"] = round(sum(to_num(r.get(stat, 0), 0) for r in home) / len(home), 3) if home else 0
        sp[f"{stat}_Away"] = round(sum(to_num(r.get(stat, 0), 0) for r in away) / len(away), 3) if away else 0
    skater_splits.append(sp)

goalie_splits = []
for name in set(r["player_name"] for r in goalie_logs):
    plogs = [r for r in goalie_logs if r["player_name"] == name]
    home = [r for r in plogs if r["home_away"] == "Home"]
    away = [r for r in plogs if r["home_away"] == "Away"]
    if not home and not away:
        continue
    sp = {"player_name": name, "Home_GAMES": len(home), "Away_GAMES": len(away)}
    for stat in ["SV", "GA", "SV_PCT", "W", "DK_FP"]:
        sp[f"{stat}_Home"] = round(sum(r[stat] for r in home) / len(home), 3) if home else 0
        sp[f"{stat}_Away"] = round(sum(r[stat] for r in away) / len(away), 3) if away else 0
    goalie_splits.append(sp)

print(f"  ✅ {len(skater_splits)} skater splits, {len(goalie_splits)} goalie splits")



# ═══════════════════════════════════════════════
# 💰 STEP 6: ODDS API — SPREADS & TOTALS
# ═══════════════════════════════════════════════
print("\n💰 Fetching odds (spreads, totals)...")
try:
    def _fetch_game_odds():
        odds_r = requests.get(f"{ODDS_BASE}/sports/{SPORT_KEY}/odds", params={
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american"
        }, timeout=15)
        check_quota_or_abort(odds_r, "NHL game odds")
        print(f"  📊 API quota remaining: {odds_r.headers.get('x-requests-remaining', '?')}")
        if odds_r.status_code != 200:
            print(f"  ❌ Odds API Error: {odds_r.status_code} — {odds_r.text[:200]}")
            return []
        return odds_r.json()

    odds_data = cached_odds_fetch("game_odds", _fetch_game_odds)
    tonight_team_set = set(team_opponents.keys())
    # Parse totals, spreads, and moneylines into team lookup dicts
    for game in odds_data:
        away = game.get("away_team","")
        home = game.get("home_team","")
        away_abbr = NHL_NAME_TO_ABBR.get(away,"")
        home_abbr = NHL_NAME_TO_ABBR.get(home,"")
        if tonight_team_set and ({away_abbr, home_abbr} - tonight_team_set):
            continue
        if not away_abbr and not home_abbr:
            continue
        for bm in game.get("bookmakers",[]):
            if "draftkings" not in bm.get("key","").lower():
                continue
            for mkt in bm.get("markets",[]):
                if mkt["key"] == "totals":
                    for o in mkt.get("outcomes",[]):
                        if o["name"] == "Over":
                            total = o.get("point",0)
                            if away_abbr: team_game_totals[away_abbr] = total
                            if home_abbr: team_game_totals[home_abbr] = total
                elif mkt["key"] == "h2h":
                    for o in mkt.get("outcomes",[]):
                        name = o.get("name","")
                        ml_abbr = NHL_NAME_TO_ABBR.get(name,"")
                        if ml_abbr:
                            team_moneylines[ml_abbr] = o.get("price","")
                elif mkt["key"] == "spreads":
                    for o in mkt.get("outcomes",[]):
                        name = o.get("name","")
                        spread_abbr = NHL_NAME_TO_ABBR.get(name,"")
                        if spread_abbr:
                            team_spreads[spread_abbr] = o.get("point","")
            break
    print(f"  📊 Parsed totals for {len(team_game_totals)} teams")
    # Attach game totals and spreads to skater_tonight (Step 3 ran before odds were fetched)
    for sk in skater_tonight:
        abbr = sk.get("team_abbr","")
        if abbr in team_game_totals:
            sk["GAME_TOTAL"] = team_game_totals[abbr]
        if abbr in team_spreads:
            sk["SPREAD"] = team_spreads[abbr]
        if abbr in team_moneylines:
            sk["MONEYLINE"] = team_moneylines[abbr]
    for gk in goalie_tonight:
        abbr = gk.get("team_abbr","")
        if abbr in team_game_totals:
            gk["GAME_TOTAL"] = team_game_totals[abbr]
        if abbr in team_spreads:
            gk["SPREAD"] = team_spreads[abbr]
        if abbr in team_moneylines:
            gk["MONEYLINE"] = team_moneylines[abbr]

    def implied_prob(price):
        try:
            price = float(price)
        except (TypeError, ValueError):
            return None
        if price < 0:
            return abs(price) / (abs(price) + 100)
        return 100 / (price + 100)

    implied_lookup = {}
    for gp in game_pairs:
        away_abbr = gp.get("away", "")
        home_abbr = gp.get("home", "")
        game_total = team_game_totals.get(away_abbr) or team_game_totals.get(home_abbr)
        away_ml = team_moneylines.get(away_abbr)
        home_ml = team_moneylines.get(home_abbr)
        away_prob = implied_prob(away_ml)
        home_prob = implied_prob(home_ml)
        if not game_total or away_prob is None or home_prob is None or away_prob + home_prob == 0:
            continue
        total_prob = away_prob + home_prob
        away_share = away_prob / total_prob
        home_share = home_prob / total_prob
        implied_lookup[away_abbr] = round(float(game_total) * away_share, 2)
        implied_lookup[home_abbr] = round(float(game_total) * home_share, 2)

    for sk in skater_tonight:
        abbr = sk.get("team_abbr", "")
        if abbr in implied_lookup:
            sk["IMPLIED_TOTAL"] = implied_lookup[abbr]
    for gk in goalie_tonight:
        abbr = gk.get("team_abbr", "")
        if abbr in implied_lookup:
            gk["IMPLIED_TOTAL"] = implied_lookup[abbr]
except Exception as e:
    print(f"  ⚠️ Odds error: {e}")
    odds_data = []

# ═══════════════════════════════════════════════
# MULTI-BOOK PLAYER PROPS
print("\nFetching Multi-Book Player Props...")
SPORT = SPORT_KEY
BOOKMAKER = 'draftkings'
PROP_BOOKMAKER = 'draftkings'
FALLBACK_BOOKMAKER = 'fanduel'
THIN_MARKET_THRESHOLD = 5
# Caesars was dropped on 2026-05-27 — returned 0/0 best-book wins in production verification.
# May be worth re-adding after 6/1 reset to re-test (could have been a one-day API issue).
SUPPORTED_BOOKMAKERS = ['draftkings', 'fanduel', 'betmgm', 'espnbet']
ACTIVE_PROP_BOOKMAKERS = SUPPORTED_BOOKMAKERS if ENABLE_FANDUEL_FALLBACK else [
    b for b in SUPPORTED_BOOKMAKERS if b != FALLBACK_BOOKMAKER
]
REFERENCE_BOOKMAKER = 'draftkings'
BEST_BOOK_TIE_BREAK = 'alpha'

MARKET_BATCHES = [
    ['player_points', 'player_assists', 'player_goals', 'player_shots_on_goal', 'player_blocked_shots'],
    ['player_power_play_points', 'player_total_saves'],
]
PROP_MARKETS = MARKET_BATCHES

market_mapping = {
    'player_points': 'PTS',
    'player_goals': 'G',
    'player_assists': 'A',
    'player_shots_on_goal': 'SOG',
    'player_blocked_shots': 'BLK',
    'player_power_play_points': 'PPP',
    'player_total_saves': 'SV',
}
MARKET_TO_METRIC = market_mapping

BINARY_PROP_MARKETS = {}
name_fixes = {}
DK_PLAYER_PROPS_COLUMNS = [
    'PLAYER_NAME', 'METRIC', 'DK_LINE', 'OVER_ODDS', 'UNDER_ODDS', 'BOOK',
    'REFERENCE_BOOK', 'BEST_OVER_BOOK', 'BEST_OVER_ODDS', 'BEST_OVER_DELTA_PP',
    'BEST_UNDER_BOOK', 'BEST_UNDER_ODDS', 'BEST_UNDER_DELTA_PP',
    'ALT_LINE_AVAILABLE', 'ALT_LINE_BOOKS', 'LAST_UPDATED'
]
ALL_BOOKS_PROPS_COLUMNS = [
    'PLAYER_NAME', 'METRIC', 'LINE', 'BOOK', 'OVER_ODDS', 'UNDER_ODDS',
    'OVER_IMPLIED', 'UNDER_IMPLIED', 'LAST_UPDATED'
]


def american_to_implied(odds):
    try:
        if odds is None or pd.isna(odds):
            return np.nan
        if isinstance(odds, str) and odds.strip().lower() in {'', 'nan', 'none'}:
            return np.nan
        odds = float(odds)
        if odds == 0:
            return np.nan
        return (-odds / (-odds + 100)) if odds < 0 else (100 / (odds + 100))
    except (TypeError, ValueError):
        return np.nan


def implied_to_american(prob):
    try:
        prob = float(prob)
        if prob <= 0 or prob >= 1:
            return None
        return int(round(-100 * prob / (1 - prob))) if prob >= 0.5 else int(round(100 * (1 - prob) / prob))
    except (TypeError, ValueError):
        return None


def apply_multi_book_name_fixes(df, name_fixes):
    if df is None or df.empty or 'PLAYER_NAME' not in df.columns:
        return df
    out = df.copy()
    out['PLAYER_NAME'] = out['PLAYER_NAME'].replace(name_fixes or {})
    return out


def parse_multi_book_market(mkt, metric_name, book_key, binary_prop_markets=None):
    rows_by_key = {}
    market_key = mkt.get('key', '')
    binary_prop_markets = binary_prop_markets or {}
    for oc in mkt.get('outcomes', []):
        player_name = oc.get('description') or oc.get('participant') or oc.get('player') or ''
        bet_type = str(oc.get('name', '')).strip()
        line_val = oc.get('point')
        odds_val = oc.get('price')
        if not player_name or odds_val is None:
            continue
        if line_val is None and market_key in binary_prop_markets:
            line_val = binary_prop_markets[market_key]
        if line_val is None:
            continue
        try:
            line_val = float(line_val)
        except (TypeError, ValueError):
            continue
        key = (player_name, metric_name, line_val, book_key)
        if key not in rows_by_key:
            rows_by_key[key] = {
                'PLAYER_NAME': player_name,
                'METRIC': metric_name,
                'LINE': line_val,
                'BOOK': book_key,
                'OVER_ODDS': np.nan,
                'UNDER_ODDS': np.nan,
            }
        if bet_type in {'Over', 'Yes'}:
            rows_by_key[key]['OVER_ODDS'] = odds_val
        elif bet_type in {'Under', 'No'}:
            rows_by_key[key]['UNDER_ODDS'] = odds_val
    return list(rows_by_key.values())


def finalize_all_books_frame(rows, timestamp_value, name_fixes=None):
    if not rows:
        return pd.DataFrame(columns=ALL_BOOKS_PROPS_COLUMNS)
    df = pd.DataFrame(rows)
    df = df[df['BOOK'].isin(ACTIVE_PROP_BOOKMAKERS)].copy()
    df = apply_multi_book_name_fixes(df, name_fixes or {})
    df['LINE'] = pd.to_numeric(df['LINE'], errors='coerce')
    df['OVER_ODDS'] = pd.to_numeric(df['OVER_ODDS'], errors='coerce')
    df['UNDER_ODDS'] = pd.to_numeric(df['UNDER_ODDS'], errors='coerce')
    df = df.dropna(subset=['PLAYER_NAME', 'METRIC', 'LINE', 'BOOK'])
    df['OVER_IMPLIED'] = df['OVER_ODDS'].map(american_to_implied).round(4)
    df['UNDER_IMPLIED'] = df['UNDER_ODDS'].map(american_to_implied).round(4)
    df['LAST_UPDATED'] = timestamp_value
    df = df.drop_duplicates(subset=['PLAYER_NAME', 'METRIC', 'LINE', 'BOOK'], keep='first')
    return df.reindex(columns=ALL_BOOKS_PROPS_COLUMNS).sort_values(['METRIC', 'PLAYER_NAME', 'LINE', 'BOOK']).reset_index(drop=True)


def _select_best_book(same_line, odds_col):
    available = same_line.dropna(subset=[odds_col]).copy()
    if available.empty:
        return None, np.nan, np.nan, []
    available[odds_col] = pd.to_numeric(available[odds_col], errors='coerce')
    available = available.dropna(subset=[odds_col])
    if available.empty:
        return None, np.nan, np.nan, []
    best_odds = available[odds_col].max()
    tied = sorted(available[available[odds_col] == best_odds]['BOOK'].astype(str).unique())
    best_book = tied[0] if tied else None
    best_implied = american_to_implied(best_odds)
    return best_book, best_odds, best_implied, tied


def compute_best_book_columns(df_long, timestamp_value):
    if df_long is None or df_long.empty:
        return pd.DataFrame(columns=DK_PLAYER_PROPS_COLUMNS), []
    df = df_long.copy()
    df['LINE'] = pd.to_numeric(df['LINE'], errors='coerce')
    df['OVER_ODDS'] = pd.to_numeric(df['OVER_ODDS'], errors='coerce')
    df['UNDER_ODDS'] = pd.to_numeric(df['UNDER_ODDS'], errors='coerce')
    df = df.dropna(subset=['PLAYER_NAME', 'METRIC', 'LINE', 'BOOK'])
    if df.empty:
        return pd.DataFrame(columns=DK_PLAYER_PROPS_COLUMNS), []

    metric_book_coverage = (
        df.groupby(['METRIC', 'BOOK'])['PLAYER_NAME']
        .nunique()
        .reset_index(name='coverage')
        .sort_values(['METRIC', 'coverage', 'BOOK'], ascending=[True, False, True])
    )
    coverage_lookup = {
        metric: grp.iloc[0]['BOOK']
        for metric, grp in metric_book_coverage.groupby('METRIC')
        if not grp.empty
    }

    rows = []
    tie_notes = []
    for (player, metric), grp in df.groupby(['PLAYER_NAME', 'METRIC'], sort=True):
        dk_rows = grp[grp['BOOK'] == REFERENCE_BOOKMAKER].sort_values(['LINE', 'BOOK'])
        if not dk_rows.empty:
            ref = dk_rows.iloc[0]
            reference_book = REFERENCE_BOOKMAKER
        else:
            reference_book = coverage_lookup.get(metric) or sorted(grp['BOOK'].astype(str).unique())[0]
            ref_rows = grp[grp['BOOK'] == reference_book].sort_values(['LINE', 'BOOK'])
            if ref_rows.empty:
                ref_rows = grp.sort_values(['BOOK', 'LINE'])
                reference_book = ref_rows.iloc[0]['BOOK']
            ref = ref_rows.iloc[0]

        ref_line = float(ref['LINE'])
        same_line = grp[grp['LINE'].sub(ref_line).abs() < 1e-9].copy()
        alt_line_books = sorted(grp[grp['LINE'].sub(ref_line).abs() >= 1e-9]['BOOK'].astype(str).unique())
        best_over_book, best_over_odds, best_over_implied, over_ties = _select_best_book(same_line, 'OVER_ODDS')
        best_under_book, best_under_odds, best_under_implied, under_ties = _select_best_book(same_line, 'UNDER_ODDS')
        if len(over_ties) > 1:
            tie_notes.append(f"{player} {metric} OVER tied: {', '.join(over_ties)}")
        if len(under_ties) > 1:
            tie_notes.append(f"{player} {metric} UNDER tied: {', '.join(under_ties)}")

        ref_over_implied = american_to_implied(ref.get('OVER_ODDS'))
        ref_under_implied = american_to_implied(ref.get('UNDER_ODDS'))
        over_delta = (ref_over_implied - best_over_implied) * 100 if pd.notna(ref_over_implied) and pd.notna(best_over_implied) else np.nan
        under_delta = (ref_under_implied - best_under_implied) * 100 if pd.notna(ref_under_implied) and pd.notna(best_under_implied) else np.nan

        rows.append({
            'PLAYER_NAME': player,
            'METRIC': metric,
            'DK_LINE': ref_line,
            'OVER_ODDS': ref.get('OVER_ODDS'),
            'UNDER_ODDS': ref.get('UNDER_ODDS'),
            'BOOK': ref.get('BOOK'),
            'REFERENCE_BOOK': reference_book,
            'BEST_OVER_BOOK': best_over_book,
            'BEST_OVER_ODDS': best_over_odds,
            'BEST_OVER_DELTA_PP': round(over_delta, 3) if pd.notna(over_delta) else np.nan,
            'BEST_UNDER_BOOK': best_under_book,
            'BEST_UNDER_ODDS': best_under_odds,
            'BEST_UNDER_DELTA_PP': round(under_delta, 3) if pd.notna(under_delta) else np.nan,
            'ALT_LINE_AVAILABLE': bool(alt_line_books),
            'ALT_LINE_BOOKS': ','.join(alt_line_books),
            'LAST_UPDATED': timestamp_value,
        })

    df_props_out = pd.DataFrame(rows, columns=DK_PLAYER_PROPS_COLUMNS)
    if not df_props_out.empty:
        df_props_out = df_props_out.sort_values(['METRIC', 'PLAYER_NAME']).reset_index(drop=True)
    return df_props_out, tie_notes


def print_best_book_summary(df_props, df_all_books):
    print("\n" + "=" * 60)
    print("BEST-BOOK ROUTING SUMMARY")
    print("=" * 60)
    print(f"   Books queried:    {', '.join(ACTIVE_PROP_BOOKMAKERS)}")
    if not ENABLE_FANDUEL_FALLBACK:
        print("   ⏭️  FanDuel fallback DISABLED (ENABLE_FANDUEL_FALLBACK=false) — FanDuel skipped")
    if df_all_books is None or df_all_books.empty or df_props is None or df_props.empty:
        print("   Props covered:    0 unique (player, metric) pairs")
        print("=" * 60)
        return
    covered = len(df_props)
    dk_ref = int((df_props['REFERENCE_BOOK'] == REFERENCE_BOOKMAKER).sum()) if 'REFERENCE_BOOK' in df_props.columns else 0
    dk_pct = (dk_ref / covered * 100) if covered else 0
    print(f"   Props covered:    {covered} unique (player, metric) pairs")
    print(f"   DK reference:     {dk_ref} / {covered} ({dk_pct:.1f}%)")
    print("   Best-book wins by:")
    for book in ACTIVE_PROP_BOOKMAKERS:
        over_ct = int((df_props.get('BEST_OVER_BOOK') == book).sum()) if 'BEST_OVER_BOOK' in df_props.columns else 0
        under_ct = int((df_props.get('BEST_UNDER_BOOK') == book).sum()) if 'BEST_UNDER_BOOK' in df_props.columns else 0
        print(f"      {book:<12} {over_ct:>4} OVER  / {under_ct:>4} UNDER")
    over_edge = pd.to_numeric(df_props.get('BEST_OVER_DELTA_PP'), errors='coerce').dropna()
    under_edge = pd.to_numeric(df_props.get('BEST_UNDER_DELTA_PP'), errors='coerce').dropna()
    over_avg = over_edge.mean() if not over_edge.empty else 0
    under_avg = under_edge.mean() if not under_edge.empty else 0
    alt_ct = int(df_props.get('ALT_LINE_AVAILABLE', pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if 'ALT_LINE_AVAILABLE' in df_props.columns else 0
    print(f"   Avg edge captured: +{over_avg:.1f}pp OVER, +{under_avg:.1f}pp UNDER (vs reference)")
    print(f"   Alt lines available: {alt_ct} props")
    print("=" * 60)


df_props = pd.DataFrame(columns=DK_PLAYER_PROPS_COLUMNS)
df_all_books = pd.DataFrame(columns=ALL_BOOKS_PROPS_COLUMNS)
all_props = []
try:
    events_r = requests.get(f"{ODDS_BASE}/sports/{SPORT}/events", params={'apiKey': ODDS_API_KEY}, timeout=15)
    check_quota_or_abort(events_r, "NHL events")
    ev_data = events_r.json() if events_r.status_code == 200 else []
    if events_r.status_code != 200:
        print(f"  ❌ Failed to fetch events: {events_r.status_code} — {events_r.text[:200]}")
    scheduled_event_keys = {(gp.get('away', ''), gp.get('home', '')) for gp in game_pairs if gp.get('away') and gp.get('home')}
    matched_events = []
    for e in ev_data:
        away_abbr = NHL_NAME_TO_ABBR.get(str(e.get('away_team', '')).strip(), '')
        home_abbr = NHL_NAME_TO_ABBR.get(str(e.get('home_team', '')).strip(), '')
        if (away_abbr, home_abbr) in scheduled_event_keys:
            matched_events.append(e)
    if not matched_events:
        matched_events = [e for e in ev_data if e.get('commence_time', '')[:10] == TODAY]
        print(f"  {len(matched_events)} events today (UTC-date fallback)")
    else:
        print(f"  {len(matched_events)} events matched to tonight's schedule")
    if not matched_events:
        print(f"⏭️  No {SPORT_LABEL} games scheduled — skipping props pull.")
        sys.exit(0)

    all_book_rows = []
    api_errors = 0
    last_resp = None
    for event in matched_events:
        eid = event['id']
        for batch in MARKET_BATCHES:
            markets_param = ','.join(batch) if isinstance(batch, list) else batch
            try:
                r = requests.get(f"{ODDS_BASE}/sports/{SPORT}/events/{eid}/odds", params={
                    'apiKey': ODDS_API_KEY,
                    'regions': 'us',
                    'markets': markets_param,
                    'bookmakers': ','.join(ACTIVE_PROP_BOOKMAKERS),
                    'oddsFormat': 'american',
                }, timeout=15)
                check_quota_or_abort(r, f"NHL event props {eid}")
                last_resp = r
                if r.status_code != 200:
                    if api_errors < 3:
                        print(f"  ⚠️ Props API {r.status_code} for event {eid}: {r.text[:100]}")
                    api_errors += 1
                    if api_errors > 5:
                        print("  ⚠️ More than 5 props API errors — continuing with partial data")
                    continue
                data = r.json()
            except Exception as e:
                print(f"  ⚠️ Props error: {e}")
                continue
            for bm in data.get('bookmakers', []):
                book_key = bm.get('key', '')
                if book_key not in ACTIVE_PROP_BOOKMAKERS:
                    continue
                for mkt in bm.get('markets', []):
                    metric = market_mapping.get(mkt.get('key'))
                    if not metric:
                        continue
                    all_book_rows.extend(parse_multi_book_market(mkt, metric, book_key, BINARY_PROP_MARKETS))
        time.sleep(0.5)

    timestamp_props = datetime.now().strftime('%Y-%m-%d %I:%M %p EST')
    df_all_books = finalize_all_books_frame(all_book_rows, timestamp_props, name_fixes)
    if last_resp is not None and hasattr(last_resp, 'headers'):
        print(f"  📊 API quota remaining: {last_resp.headers.get('x-requests-remaining', '?')}")
    if api_errors:
        print(f"  ⚠️ Total props API errors: {api_errors}")
    for book in ACTIVE_PROP_BOOKMAKERS:
        book_ct = 0 if df_all_books.empty else int((df_all_books['BOOK'] == book).sum())
        if book_ct == 0:
            print(f"  {book}: 0 props")
    df_props, tie_notes = compute_best_book_columns(df_all_books, timestamp_props)
    for note in tie_notes[:10]:
        print(f"  ℹ️ Best-book tie: {note}")
    if len(tie_notes) > 10:
        print(f"  ℹ️ Best-book ties suppressed: {len(tie_notes) - 10} more")
    all_props = df_props.to_dict('records') if not df_props.empty else []
    if all_props:
        print(f"  ✅ {len(all_props)} reference props fetched across {df_props['METRIC'].nunique()} markets")
        print(f"  ✅ All_Books_Props rows: {len(df_all_books)} across {df_all_books['BOOK'].nunique()} books")
        goalie_count = int((df_props['METRIC'] == 'SV').sum())
        if goalie_count:
            print(f"  🥅 Goalie props fetched — SV:{goalie_count}")
    else:
        print("  ⚠️ No player props returned.")
    metric_counts = pd.Series([p.get('METRIC') for p in all_props if p.get('METRIC')]).value_counts().to_dict() if all_props else {}
    thin_metrics = sorted([metric for metric in set(market_mapping.values()) if metric_counts.get(metric, 0) < THIN_MARKET_THRESHOLD])
    if thin_metrics:
        print(f"  ⚠️ Thin/missing markets after multi-book fetch: {', '.join(thin_metrics)}")
    print_best_book_summary(df_props, df_all_books)
except Exception as e:
    print(f"  ❌ Failed to fetch player props: {e}")


# ═══════════════════════════════════════════════
# 🤖 STEP 8: GEMINI AI PICKS (v1.2: new google-genai SDK)
# ═══════════════════════════════════════════════
print("\n🤖 Generating Gemini AI picks...")

daily_picks = []
existing_daily_picks = load_existing_daily_picks("Daily_Picks", TODAY)
seen_pick_keys = set()
if len(existing_daily_picks) > 0:
    for _, row in existing_daily_picks.iterrows():
        key = (
            normalize_player_name(str(row.get('player', ''))),
            str(row.get('prop_type', '')).strip().upper(),
            str(row.get('lean', '')).strip().upper(),
        )
        seen_pick_keys.add(key)
existing_run_numbers = pd.to_numeric(existing_daily_picks.get("RUN_NUMBER", pd.Series(dtype=float)), errors="coerce").dropna().astype(int)
today_run_number = int(existing_run_numbers.max()) + 1 if not existing_run_numbers.empty else 1
refresh_clv_daily_picks("Daily_Picks", TODAY, all_props, datetime.now().strftime("%Y-%m-%d %I:%M %p EST"))

if GEMINI_API_KEY and len(games) > 0 and (len(skater_tonight) > 0 or len(goalie_tonight) > 0):
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        gen_config = types.GenerateContentConfig(temperature=0.7, max_output_tokens=8192)

        fallback_used = "props"
        print(f"  Total skaters tonight: {len(skater_tonight)}")
        print(f"  Total goalies tonight: {len(goalie_tonight)}")
        deduped_map = {}
        for sk in skater_tonight:
            sk = sk.copy()
            sk["player_type"] = "skater"
            name_norm = normalize_player_name(sk.get("player_name"))
            if not name_norm:
                continue
            current = deduped_map.get(name_norm)
            if current is None or float(sk.get("Seas_UD_FP", 0) or 0) > float(current.get("Seas_UD_FP", 0) or 0):
                deduped_map[name_norm] = sk
        deduped_skaters = list(deduped_map.values())
        print(f"  Skaters after dedupe: {len(deduped_skaters)}")
        print(f"  Skaters after status filter: {len(deduped_skaters)}")
        deduped_goalie_map = {}
        for gk in goalie_tonight:
            gk = gk.copy()
            gk["player_type"] = "goalie"
            name_norm = normalize_player_name(gk.get("player_name"))
            if not name_norm:
                continue
            current = deduped_goalie_map.get(name_norm)
            if current is None or float(gk.get("Seas_UD_FP", 0) or 0) > float(current.get("Seas_UD_FP", 0) or 0):
                deduped_goalie_map[name_norm] = gk
        deduped_goalies = list(deduped_goalie_map.values())
        print(f"  Goalies after dedupe: {len(deduped_goalies)}")
        logs_by_player = defaultdict(list)
        for g in skater_logs:
            logs_by_player[normalize_player_name(g.get("player_name"))].append(g)
        skaters_with_logs = [p for p in deduped_skaters if logs_by_player.get(normalize_player_name(p.get("player_name")))]
        print(f"  Skaters with logs: {len(skaters_with_logs)}")
        goalie_logs_by_player = defaultdict(list)
        for g in goalie_logs:
            goalie_logs_by_player[normalize_player_name(g.get("player_name"))].append(g)
        goalies_with_logs = [p for p in deduped_goalies if goalie_logs_by_player.get(normalize_player_name(p.get("player_name")))]
        print(f"  Goalies with logs: {len(goalies_with_logs)}")
        props_by_player = defaultdict(list)
        for pr in all_props:
            pname = normalize_player_name(pr.get("PLAYER_NAME"))
            if pname:
                props_by_player[pname].append(pr)
        skaters_with_props = [p for p in skaters_with_logs if props_by_player.get(normalize_player_name(p.get("player_name")))]
        print(f"  Skaters after props filter: {len(skaters_with_props)}")
        goalies_with_props = [p for p in goalies_with_logs if props_by_player.get(normalize_player_name(p.get("player_name")))]
        print(f"  Goalies after props filter: {len(goalies_with_props)}")
        if goalies_with_logs:
            tonight_goalie_names = [g.get("player_name", "") for g in goalies_with_logs if g.get("player_name")]
            print(f"  🥅 Tonight goalie candidates: {', '.join(tonight_goalie_names[:10])}" + (" ..." if len(tonight_goalie_names) > 10 else ""))
        goalie_prop_rows = [p for p in all_props if p.get("METRIC") in {"SV"}]
        if goalie_prop_rows:
            matched_goalie_norms = {normalize_player_name(g.get("player_name")) for g in goalies_with_props}
            unmatched_goalie_props = []
            for prop in goalie_prop_rows:
                pname = prop.get("PLAYER_NAME", "")
                pname_norm = normalize_player_name(pname)
                if pname_norm not in matched_goalie_norms:
                    unmatched_goalie_props.append(f"{pname} [{prop.get('METRIC')}] ({prop.get('BOOK', 'unknown')})")
            if unmatched_goalie_props:
                print(f"  ⚠️ Unmatched goalie props: {', '.join(unmatched_goalie_props[:12])}" + (" ..." if len(unmatched_goalie_props) > 12 else ""))
            else:
                print("  ✅ All fetched goalie props matched tonight's goalie pool")
        if goalies_with_props:
            goalie_prop_metric_counts = defaultdict(int)
            for gk in goalies_with_props:
                for prop in props_by_player.get(normalize_player_name(gk.get("player_name")), []):
                    metric = prop.get("METRIC")
                    if metric in {"SV"}:
                        goalie_prop_metric_counts[metric] += 1
            if goalie_prop_metric_counts:
                goalie_prop_bits = ", ".join(f"{metric}:{count}" for metric, count in sorted(goalie_prop_metric_counts.items()))
                print(f"  Goalie prop matches by metric: {goalie_prop_bits}")
        top_skaters = sorted(skaters_with_props, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:46]
        top_goalies = sorted(goalies_with_props, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:8]
        top_players = top_skaters + top_goalies
        if len(top_players) < 12 and (skaters_with_logs or goalies_with_logs):
            fallback_used = "top players by season fantasy"
            print("WARNING: Gemini pool empty or too small after props filter, falling back to top players by season fantasy points")
            expanded = (
                sorted(skaters_with_logs, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:46] +
                sorted(goalies_with_logs, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:8]
            )
            merged = {normalize_player_name(p.get("player_name")): p for p in top_players}
            for p in expanded:
                merged.setdefault(normalize_player_name(p.get("player_name")), p)
            top_players = list(merged.values())[:60]
        if len(top_players) < 12 and (skaters_with_logs or goalies_with_logs):
            fallback_used = "tonight players with logs"
            print("WARNING: Gemini pool still too small after top-player expansion, falling back to tonight players with logs")
            top_players = (
                sorted(skaters_with_logs, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:46] +
                sorted(goalies_with_logs, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:8]
            )
        if not top_players and (deduped_skaters or deduped_goalies):
            fallback_used = "deduped tonight sheet"
            print("WARNING: Gemini pool empty after log filtering, falling back to deduped tonight player sheet")
            top_players = (
                sorted(deduped_skaters, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:46] +
                sorted(deduped_goalies, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)[:8]
            )
        top_players = sorted(top_players, key=lambda x: x.get("Seas_UD_FP", 0), reverse=True)
        guaranteed_stars = top_players[:15]
        star_top20_names = {normalize_player_name(p.get("player_name")) for p in top_players[:20]}
        remaining_players = [p for p in top_players if normalize_player_name(p.get("player_name")) not in {normalize_player_name(s.get("player_name")) for s in guaranteed_stars}]
        top_players = []
        seen_players = set()
        for p in guaranteed_stars + remaining_players:
            pname_norm = normalize_player_name(p.get("player_name"))
            if not pname_norm or pname_norm in seen_players:
                continue
            player_copy = dict(p)
            player_copy["STAR"] = pname_norm in star_top20_names
            top_players.append(player_copy)
            seen_players.add(pname_norm)
            if len(top_players) >= 60:
                break
        print(f"  Final players sent to Gemini: {len(top_players)}")
        returning_player_map = {
            normalize_player_name(p.get("player_name")): bool(p.get("RETURNING", False))
            for p in top_players
        }
        # Build player summaries for Gemini (mixed skaters + goalies)
        split_lookup = {normalize_player_name(sp["player_name"]): sp for sp in skater_splits}
        goalie_split_lookup = {normalize_player_name(sp["player_name"]): sp for sp in goalie_splits}
        def implied_prob_american(odds):
            try:
                odds = float(odds)
            except (TypeError, ValueError):
                return None
            if odds > 0:
                return 100.0 / (odds + 100.0)
            if odds < 0:
                return abs(odds) / (abs(odds) + 100.0)
            return None

        streak_ctx = ""
        player_streak_map = {}
        try:
            streaks = get_streaks()
            streak_lines = [f"{s['player']} — {s['stat']} streak: {s['streak']} games" for s in streaks if s['streak'] >= 3]
            streak_ctx = "\n".join(streak_lines) if streak_lines else "No active streaks tonight."
            for s in streaks:
                if s.get('streak', 0) >= 3:
                    player_streak_map.setdefault(normalize_player_name(s['player']), []).append(f"{s['stat']} x{s['streak']}")
        except:
            streak_ctx = "Streak data unavailable."

        player_summaries = []
        valid_player_map = {}
        for p in top_players:
            pname = p['player_name']
            pname_norm = normalize_player_name(pname)
            valid_player_map[pname_norm] = pname
            props_for_player = props_by_player.get(pname_norm, [])
            prop_str = ", ".join([f"{pr['METRIC']} {pr['DK_LINE']} (O:{pr['OVER_ODDS']})" for pr in props_for_player]) if props_for_player else "No props"
            prop_signal_str = ""
            is_goalie = p.get("player_type") == "goalie"
            player_logs = goalie_logs_by_player.get(pname_norm, []) if is_goalie else logs_by_player.get(pname_norm, [])
            signal_lines = []
            for pr in props_for_player:
                metric = normalize_prop_metric(pr.get('METRIC'))
                metric = {"G_W": "W", "G_SV": "SV", "G_GA": "GA"}.get(metric, metric)
                line_val = pd.to_numeric(pr.get('DK_LINE'), errors='coerce')
                if metric and pd.notna(line_val) and len(player_logs) >= 3:
                    vals = [float(g.get(metric, 0) or 0) for g in player_logs if g.get(metric) is not None]
                    if len(vals) >= 3:
                        hr = sum(v > line_val for v in vals) / len(vals)
                        ip = implied_prob_american(pr.get('OVER_ODDS'))
                        edge = (hr - ip) * 100 if ip is not None else None
                        if bool(p.get("RETURNING", False)) and edge is not None:
                            edge *= 0.5
                        sig = f"{metric} {line_val:g} HR={hr*100:.0f}%"
                        if edge is not None:
                            sig += f" EV={edge:.0f}%"
                        signal_lines.append(sig)
            if signal_lines:
                prop_signal_str = " | Best prop signals: " + "; ".join(signal_lines[:3])
            gt = p.get('GAME_TOTAL', 0)
            implied_total = p.get('IMPLIED_TOTAL', '')
            spread = p.get('SPREAD', '')
            loc = p.get('home_away_tonight', '')
            split_bits = []
            if is_goalie:
                matchup_str = "Goalie matchup"
                if gt: matchup_str += f" O/U:{gt}"
                if implied_total not in ('', None): matchup_str += f" ITT:{implied_total}"
                if spread: matchup_str += f" Spread:{spread}"
                split_row = goalie_split_lookup.get(pname_norm, {})
                if loc in ('Home', 'Away') and split_row:
                    for stat in ["SV", "GA", "SV_PCT", "W"]:
                        val = split_row.get(f"{stat}_{loc}")
                        if val not in (None, ''):
                            split_bits.append(f"{stat}={val}")
            else:
                opp_ga = p.get('OPP_GA_PG', 0)
                opp_pk = p.get('OPP_PK_PCT', 0)
                matchup_str = f"Opp GA/G:{opp_ga} PK%:{opp_pk}"
                if gt: matchup_str += f" O/U:{gt}"
                if implied_total not in ('', None): matchup_str += f" ITT:{implied_total}"
                if spread: matchup_str += f" Spread:{spread}"
                split_row = split_lookup.get(pname_norm, {})
                if loc in ('Home', 'Away') and split_row:
                    for stat in ["PTS", "SOG", "BLK", "HITS"]:
                        val = split_row.get(f"{stat}_{loc}")
                        if val not in (None, ''):
                            split_bits.append(f"{stat}={val}")
            split_str = f" | Tonight {loc} split: {' '.join(split_bits[:4])}" if split_bits else ""
            streak_bits = player_streak_map.get(pname_norm, [])
            streak_str = f" | Streaks: {', '.join(streak_bits[:3])}" if streak_bits else ""
            sample_str = ""
            if bool(p.get("RETURNING", False)):
                sample_str = f" | SAMPLE FLAG: RETURNING (L5 games={int(p.get('L5_GAMES_PLAYED', 0) or 0)}, last7={int(p.get('GAMES_LAST_7D', 0) or 0)})"
            elif bool(p.get("LIMITED_SAMPLE", False)):
                sample_str = f" | SAMPLE FLAG: LIMITED_SAMPLE (L5 games={int(p.get('L5_GAMES_PLAYED', 0) or 0)})"
            if is_goalie:
                player_summaries.append(
                    f"{pname} [GOALIE] ({p['team_abbr']} vs {p.get('opp_abbr_tonight','?')}) | "
                    f"{'STAR | ' if bool(p.get('STAR', False)) else ''}"
                    f"Seas: {p.get('Seas_SV',0):.2f}SV {p.get('Seas_GA',0):.2f}GA {p.get('Seas_SV_PCT',0):.3f}SV% {p.get('Seas_W',0):.2f}W {p.get('Seas_UD_FP',0):.1f}UD_FP | "
                    f"L3: {p.get('L3_SV',0):.2f}SV {p.get('L3_GA',0):.2f}GA {p.get('L3_SV_PCT',0):.3f}SV% {p.get('L3_W',0):.2f}W {p.get('L3_UD_FP',0):.1f}UD_FP | "
                    f"Starter status: {p.get('starter_status','roster')} | {matchup_str}{split_str}{streak_str}{sample_str} | Props: {prop_str}{prop_signal_str}"
                )
            else:
                goalie_status = p.get('opp_goalie_status', '')
                opp_goalie_logs = goalie_logs_by_player.get(normalize_player_name(p.get('opp_goalie_name', '')), [])
                if opp_goalie_logs:
                    opp_goalie_svp = round(sum(float(g.get('SV_PCT', 0) or 0) for g in opp_goalie_logs) / len(opp_goalie_logs), 3)
                else:
                    opp_goalie_svp = 0
                player_summaries.append(
                    f"{pname} [SKATER] ({p['team_abbr']} vs {p.get('opp_abbr_tonight','?')}) | "
                    f"{'STAR | ' if bool(p.get('STAR', False)) else ''}"
                    f"Seas: {p.get('Seas_PTS',0):.2f}P {p.get('Seas_G',0):.2f}G {p.get('Seas_A',0):.2f}A {p.get('Seas_SOG',0):.2f}SOG {p.get('Seas_BLK',0):.2f}BLK {p.get('Seas_HITS',0):.2f}HIT {p.get('Seas_UD_FP',0):.1f}UD_FP | "
                    f"L3: {p.get('L3_PTS',0):.2f}P {p.get('L3_G',0):.2f}G {p.get('L3_SOG',0):.2f}SOG {p.get('L3_BLK',0):.2f}BLK {p.get('L3_HITS',0):.2f}HIT {p.get('L3_UD_FP',0):.1f}UD_FP | "
                    f"vs {p.get('opp_goalie_name','TBD')}{f' ({goalie_status})' if goalie_status else ''} SV%:{opp_goalie_svp:.3f} | {matchup_str}{split_str}{streak_str}{sample_str} | Props: {prop_str}{prop_signal_str}"
                )
        prompt = f"""You are an NHL props analyst. Today is {TODAY}. NHL {'Playoffs' if GAME_TYPE==3 else 'Regular Season'}.

Here are {len(player_summaries)} players playing tonight with their season averages, L5/L3 averages, home/away splits, active streaks, prop hit-rate/EV signals, Underdog fantasy points, matchup context, and DK prop lines:

{chr(10).join(player_summaries)}

ACTIVE PROP STREAKS:
{streak_ctx}

RULES:
- CRITICAL: ONLY pick players from the data above. Do NOT include any player not in the list.
- Return EXACTLY 10 ranked picks as a JSON array
- Confidence tiers: SMASH (top 3-4 highest conviction only), STRONG (next 4-5), LEAN (rest)
- STRONG should require multiple confirming signals: positive EV, strong hit rate, and supportive matchup/split context. If only one signal is strong, use LEAN instead.
- Players flagged RETURNING have depressed lines due to injury/absence. Their season averages are NOT reliable short-term predictors. Treat with extreme caution — do NOT SMASH these players.
- STAR players are the top 20 by season UD fantasy points in tonight's valid prop pool.
- Prefer at least 4 of your 10 picks to come from STAR players. Non-stars should fill the remaining slots only when they have exceptional edges or matchup context.
- Available prop types: PTS, G, SOG, PPP, HITS, SV
- Do NOT pick A (assists) — observed ~36% NHL hit rate.
- Do NOT pick BLK (blocks) — observed ~25% NHL hit rate.
- Do NOT pick UD_FP or any fantasy-points metric — these are not pickable props
- Skaters can only get skater props. Goalies can only get goalie props (SV).
- DIVERSIFY prop types: max 3 picks of the same prop type per slate.
- Max 3 goalie props per slate.
- Include 1 goalie saves (SV) pick per slate when a high-total game suggests more shots and the listed goalie context supports volume.
- Use DK lines when available; otherwise use L5 average. NEVER return null for line.
- When listed prop signals show strong hit rate and positive EV, give those props more weight.
- SOG (53%) is the best high-volume prop. Prioritize it.
- UNDER props are strong in NHL (observed ~62% hit rate, n=29). Actively evaluate UNDER opportunities on overlined skaters and goalies. Soft target: 2-4 UNDERs per 10-pick slate.
- A and BLK are blacklisted (see above). Do not pick these under any circumstances.

For each pick:
- rank (1-10)
- player (exact name from data)
- team (abbreviation)
- game (e.g. "TOR @ BOS")
- prop_type (must be one of: PTS, G, SOG, PPP, HITS, SV)
- line (the DK line number, or your projected number if no prop)
- lean (OVER or UNDER)
- confidence (SMASH, STRONG, or LEAN)
- rationale (1 sentence why, under 15 words)
- Active prop streaks (3+ games on a prop = strong lean to continue)
- Hit rate: players hitting a prop 80%+ over L10 = high reliability
- EV% matters when available from the listed prop signals — positive edge vs the book deserves more weight
- Factor in opponent defense: high GA/G = leaky defense (good for overs), low PK% = weak penalty kill (boost PPP picks)
- Opposing goalie SV% matters heavily for skater props: lower SV% should materially boost skater overs, especially PTS and SOG.
- High game totals (O/U 6.5+) favor offensive props
- Home/away splits matter — compare tonight's location to the player's split before making a pick

Example format:
[{{"rank":1,"player":"PLAYER_NAME","team":"TEAM","game":"AWAY @ HOME","prop_type":"SOG","line":4.5,"lean":"OVER","confidence":"SMASH","rationale":"Averaging 5.2 SOG/game vs weak goalie"}}]

IMPORTANT: Return ONLY the JSON array. No markdown, no preamble."""

        print(f"  Fallback used: {fallback_used if top_players else 'none'}")
        if not top_players:
            print("  ⚠️ No usable player data — skipping Gemini.")
            raw = ""
            ai_picks = []
        else:
            consensus_pick_lists = []
            consensus_temps = [0.35, 0.55, 0.75]
            for run_idx, temp in enumerate(consensus_temps, start=1):
                run_config = types.GenerateContentConfig(temperature=temp, max_output_tokens=8192)
                print(f"  Calling Gemini API run {run_idx}/3 (temp={temp:.2f})...")
                response = client.models.generate_content(
                    model='gemini-2.5-flash-lite',
                    contents=prompt,
                    config=run_config
                )
                raw = response.text.strip()
                try:
                    run_picks = parse_gemini_json_array(raw)
                    print(f"   ↳ {len(run_picks)} picks returned")
                    consensus_pick_lists.append(run_picks)
                except json.JSONDecodeError:
                    print(f"   ⚠️ Run {run_idx} returned malformed JSON — ignoring that pass")
            ai_picks = build_consensus_pick_pool(consensus_pick_lists)
            consensus_hits = sum(1 for pk in ai_picks if int(pk.get('CONSENSUS_COUNT', 1) or 1) >= 2)
            print(f"  🤝 Consensus merge: {len(ai_picks)} unique picks, {consensus_hits} appearing in 2+ runs")

        # Filter hallucinated players
        print(f"  Gemini picks before post-filter: {len(ai_picks)}")
        bf = len(ai_picks)
        dropped_names = []
        filtered_ai_picks = []
        for pk in ai_picks:
            pname_norm = normalize_player_name(pk.get('player'))
            if pname_norm not in valid_player_map:
                dropped_names.append(pk.get('player', '?'))
                continue
            pk['player'] = valid_player_map[pname_norm]
            filtered_ai_picks.append(pk)
        ai_picks = filtered_ai_picks
        dropped = bf - len(ai_picks)
        print(f"  Gemini picks after post-filter: {len(ai_picks)}")
        if dropped > 0:
            print(f"  🚫 Dropped hallucinated picks: {dropped}")
            if len(dropped_names) <= 20:
                for name in dropped_names:
                    print(f"     - {name}")
            # Re-rank after filtering
            for i, pk in enumerate(ai_picks):
                pk['rank'] = i + 1
        goalie_name_set = {normalize_player_name(g.get("player_name")) for g in deduped_goalies}
        prop_type_counts = {}
        goalie_pick_count = 0
        filtered_by_prop = []
        dropped_prop_caps = []
        for pk in ai_picks:
            prop_type = normalize_prop_metric(pk.get('prop_type'))
            is_goalie_pick = normalize_player_name(pk.get('player')) in goalie_name_set
            BLACKLISTED_NHL_PROPS = {"A", "BLK"}
            if prop_type in BLACKLISTED_NHL_PROPS:
                dropped_prop_caps.append(f"{pk.get('player', '?')} {prop_type} — blacklisted prop")
                continue
            max_for_type = 3
            if prop_type_counts.get(prop_type, 0) >= max_for_type:
                dropped_prop_caps.append(f"{pk.get('player', '?')} {prop_type} — per-type cap")
                continue
            if is_goalie_pick and goalie_pick_count >= 3:
                dropped_prop_caps.append(f"{pk.get('player', '?')} {prop_type} — goalie cap")
                continue
            prop_type_counts[prop_type] = prop_type_counts.get(prop_type, 0) + 1
            if is_goalie_pick:
                goalie_pick_count += 1
            filtered_by_prop.append(pk)
        if dropped_prop_caps:
            print(f"  🚫 Dropped {len(dropped_prop_caps)} extra prop-type picks")
            for reason in dropped_prop_caps[:20]:
                print(f"     - {reason}")
        ai_picks = filtered_by_prop
        if len(ai_picks) > 10:
            dropped_depth = ai_picks[10:]
            ai_picks = ai_picks[:10]
            print(f"  🚫 Trimmed {len(dropped_depth)} lower-conviction picks to keep the slate at 10")
            for pk in dropped_depth[:10]:
                print(f"     - {pk.get('player', '?')} {pk.get('prop_type', '?')} {pk.get('lean', '?')}")
        for i, pk in enumerate(ai_picks):
            pk['rank'] = i + 1
        if ai_picks:
            for pk in ai_picks:
                pk['confidence'] = normalize_confidence(pk.get('confidence'))
                if returning_player_map.get(normalize_player_name(pk.get('player')), False) and pk['confidence'] == 'SMASH':
                    pk['confidence'] = 'STRONG'
            smash_seen = 0
            max_smash = min(3, max(1, len(ai_picks) // 4 + (1 if len(ai_picks) >= 8 else 0)))
            for pk in ai_picks:
                if pk.get('confidence') == 'SMASH':
                    smash_seen += 1
                    if smash_seen > max_smash:
                        pk['confidence'] = 'STRONG'
        if bf > 0 and not ai_picks:
            print("  WARNING: All Gemini picks were filtered out because none matched the normalized valid player pool")
        for pk in ai_picks:
            try:
                line_num = float(pk.get('line'))
                if not math.isnan(line_num) and not math.isinf(line_num):
                    continue
            except (TypeError, ValueError):
                pass
            prop_type = normalize_prop_metric(pk.get('prop_type'))
            player_props = props_by_player.get(normalize_player_name(pk.get('player')), [])
            matched_line = next((pr.get('DK_LINE') for pr in player_props if normalize_prop_metric(pr.get('METRIC')) == prop_type and pr.get('DK_LINE') not in (None, '', 'nan')), None)
            if matched_line not in (None, ''):
                pk['line'] = matched_line
                print(f"  📎 Filled null line for {pk.get('player', '?')}: {matched_line}")
        print("  Gemini pool summary:")
        print(f"     total tonight players: {len(skater_tonight) + len(goalie_tonight)}")
        print(f"     after dedupe: {len(deduped_skaters)}")
        print(f"     after status filter: {len(deduped_skaters)}")
        print(f"     goalies after dedupe: {len(deduped_goalies)}")
        print(f"     after props filter: {len(skaters_with_props) + len(goalies_with_props)}")
        print(f"     fallback used: {fallback_used if top_players else 'none'}")
        print(f"     final sent to Gemini: {len(top_players)}")
        print(f"     picks before post-filter: {bf}")
        print(f"     picks after post-filter: {len(ai_picks)}")
        dropped_summary = dropped_names + dropped_prop_caps + ([f"{pk.get('player', '?')} {pk.get('prop_type', '?')} {pk.get('lean', '?')} — depth trim" for pk in dropped_depth] if 'dropped_depth' in locals() else [])
        print(f"  ✅ {len(ai_picks)} AI picks generated")
        if ai_picks:
            top = ai_picks[0]
            print(f"  🏆 #1: {top.get('player','?')} — {top.get('prop_type','?')} {top.get('lean','?')} {top.get('line','?')} ({top.get('confidence','?')})")
            smash_ct = sum(1 for pk in ai_picks if pk.get('confidence','').upper() == 'SMASH')
            print(f"  💪 {smash_ct} SMASH picks | {len(ai_picks) - smash_ct} standard")

        # Format for Daily_Picks sheet
        for pk in ai_picks:
            data_source = (
                "props_validated" if fallback_used == "props" else
                "expanded_pool" if fallback_used == "top skaters by season fantasy" else
                "stats_fallback" if fallback_used == "tonight skaters with logs" else
                "expanded_pool"
            )
            pick_key = (
                normalize_player_name(pk.get('player', '')),
                str(pk.get('prop_type', '')).strip().upper(),
                str(pk.get('lean', '')).strip().upper(),
            )
            if pick_key in seen_pick_keys:
                print(f"  🔁 Skipping duplicate pick: {pk.get('player')} {pk.get('prop_type')} {pk.get('lean')}")
                continue
            seen_pick_keys.add(pick_key)
            daily_picks.append({
                "DATE": TODAY,
                "RUN_NUMBER": today_run_number,
                "RUN_TIME": datetime.now().strftime("%Y-%m-%d %I:%M %p EST"),
                "rank": pk.get("rank", ""),
                "player": pk.get("player", ""),
                "team": pk.get("team", ""),
                "game": pk.get("game", ""),
                "matchup": pk.get("game", ""),
                "prop_type": pk.get("prop_type", ""),
                "line": pk.get("line", ""),
                "lean": pk.get("lean", ""),
                "confidence": pk.get("confidence", ""),
                "rationale": pk.get("rationale", ""),
                "reasoning": pk.get("rationale", ""),
                "injury_context": pk.get("injury_context", ""),
                "DATA_SOURCE": data_source,
                "source": data_source,
                "CONSENSUS_COUNT": pk.get("CONSENSUS_COUNT", 1),
                "CONSENSUS_RUNS": pk.get("CONSENSUS_RUNS", "1"),
                "CONSENSUS_TAG": pk.get("CONSENSUS_TAG", ""),
                "CLV_OPEN_LINE": pk.get("line", ""),
                "CLV_LATEST_LINE": pk.get("line", ""),
                "CLV_DELTA": 0.0,
                "CLV_LAST_UPDATE": datetime.now().strftime("%Y-%m-%d %I:%M %p EST"),
                "HIT": "",
                "ACTUAL_STAT": "",
                "RESULT": "",
            })
        prop_dist = pd.Series([normalize_prop_metric(pk.get('prop_type')) for pk in ai_picks]).value_counts().to_dict() if ai_picks else {}
        lean_series = pd.Series([str(pk.get('lean', '')).upper() for pk in ai_picks]).replace({'FADE': 'UNDER'}) if ai_picks else pd.Series(dtype=str)
        conf_series = pd.Series([str(pk.get('confidence', '')).upper() for pk in ai_picks]) if ai_picks else pd.Series(dtype=str)
        print(f"  📊 Post-filter prop mix: {prop_dist}")
        print("📊 Final pick distribution:")
        print(f"   Prop types: {prop_dist}")
        print(f"   Lean: {int((lean_series == 'OVER').sum())} OVER / {int((lean_series == 'UNDER').sum())} UNDER")
        print(f"   Confidence: {int((conf_series == 'SMASH').sum())} SMASH / {int((conf_series == 'STRONG').sum())} STRONG / {int((conf_series == 'LEAN').sum())} LEAN")
        print(f"   Stars: {sum(1 for pk in ai_picks if normalize_player_name(pk.get('player')) in star_top20_names)}")
        print(f"   Returning: {sum(1 for pk in ai_picks if returning_player_map.get(normalize_player_name(pk.get('player')), False))}")
        print(f"   Dropped: {len(dropped_summary)} — {', '.join(dropped_summary[:10]) if dropped_summary else 'none'}")

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON parse failed: {e}")
        print(f"  Raw: {raw[:500] if 'raw' in dir() else 'n/a'}")
    except Exception as e:
        print(f"  ❌ AI Picks failed: {e}")
else:
    if not GEMINI_API_KEY:
        print("  ⚠️ No Gemini API key — skipping.")
    elif len(games) == 0:
        print("  ⚠️ No games tonight — skipping.")
    elif len(skater_tonight) == 0:
        print("  ⚠️ No skater data — skipping.")

# ═══════════════════════════════════════════════
# 📤 STEP 9: UPLOAD TO GOOGLE SHEETS
# ═══════════════════════════════════════════════
print("\n📤 Uploading to Google Sheets...")
safe_upload("Tonights_Skaters", skater_tonight)
safe_upload("Skater_Game_Logs", skater_logs)
safe_upload("Home_Away_Splits", skater_splits)
safe_upload("Tonights_Goalies", goalie_tonight)
safe_upload("Goalie_Game_Logs", goalie_logs)
safe_upload("Goalie_Home_Away", goalie_splits)
safe_upload("DK_Player_Props", all_props)
safe_upload("All_Books_Props", df_all_books.to_dict('records') if not df_all_books.empty else [])
if new_boxscore_cache_rows:
    append_upload("Boxscore_Cache", pd.DataFrame(new_boxscore_cache_rows))
if daily_picks:
    try:
        runlog.picks_generated = len(daily_picks)
    except Exception:
        pass
    append_upload("Daily_Picks", pd.DataFrame(daily_picks))

# ═══════════════════════════════════════════════
# 📊 SUMMARY
# ═══════════════════════════════════════════════
print(f"\n{'='*50}")
print(f"🏒 NHL ENGINE v1.2 — RUN COMPLETE")
print(f"{'='*50}")
print(f"  📅 Date: {TODAY}")
print(f"  🗂️  Snapshot: {SNAPSHOT_DATE}")
print(f"  🏟️  Games: {len(games)}")
print(f"  🏒 Skaters: {len(skater_tonight)} with logs")
print(f"  🧱 Goalies: {len(goalie_tonight)} with logs")
print(f"  📊 Game log rows: {len(skater_logs) + len(goalie_logs)}")
print(f"  🎲 Props: {len(all_props)}")
print(f"  🏪 All Books Props: {len(df_all_books)} rows across {df_all_books['BOOK'].nunique() if not df_all_books.empty else 0} books")
print(f"  🤖 AI Picks: {len(daily_picks)}")
print(f"  📝 Google Sheet: {SHEET_ID}")
print(f"{'='*50}")
