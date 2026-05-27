# @title 🏒 NHL Daily Picks Grader v3 — Run Morning After Games — 5-4 Baseline
import pandas as pd
import numpy as np
import requests
import time, re, math
import unicodedata
import os, json
import atexit
from datetime import datetime, timedelta
from itertools import combinations
import pytz
import gspread
from google.auth import default
from google.oauth2.service_account import Credentials
from run_logger import RunLogger

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
runlog = RunLogger(gc, SHEET_KEY, sport='NHL', kind='grader')
atexit.register(runlog.finalize_and_write)

eastern = pytz.timezone('US/Eastern')
now_est = datetime.now(eastern)
today_str = now_est.strftime('%Y-%m-%d')
timestamp_est = now_est.strftime('%Y-%m-%d %I:%M:%S %p EST')
RETRY_DNP_LOOKBACK_DAYS = 7
PICK_PERF_MIN_SAMPLE = 25
PICK_PERF_STANDARD_ODDS = -115
PICK_PERF_WILSON_Z = 1.96
PICK_PERF_DRIFT_ALERT_PP = 10
PICK_PERF_TIME_WINDOWS = {
    'last_7d': 7,
    'last_30d': 30,
    'last_90d': 90,
    'all_time': None,
}
PICK_PERF_SNAPSHOT_WINDOWS = ('all_time', 'last_30d')
PICK_PERF_DIMENSIONS = (
    'confidence_norm',
    'prop_type_norm',
    'lean_norm',
    'consensus_bucket',
    'clv_bucket',
    'has_lineup_risk',
    'day_of_week',
    'RUN_NUMBER',
)

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

PICK_PERFORMANCE_COLUMNS = [
    'DIMENSION_TYPE', 'DIMENSION_VALUE', 'TIME_WINDOW',
    'N_PICKS', 'N_PICKS_DECISIVE', 'N_HITS', 'N_MISSES', 'N_PUSHES', 'N_DNP',
    'HIT_RATE', 'HIT_RATE_RAW', 'PUSH_RATE', 'DNP_RATE',
    'ROI_FLAT', 'ROI_PER_PICK',
    'AVG_CLV_EDGE', 'CLV_POSITIVE_RATE', 'CLV_POS_HIT_RATE', 'CLV_NEG_HIT_RATE',
    'WILSON_LOWER_95', 'MIN_SAMPLE_FLAG',
    'LAST_UPDATED',
]
PICK_PERFORMANCE_SNAPSHOT_COLUMNS = ['SNAPSHOT_DATE', 'METRIC_KEY', 'METRIC_VALUE', 'N_PICKS', 'TIME_WINDOW']

def normalize_prop_metric(metric):
    text = str(metric or '').strip().upper()
    text = re.sub(r"\s+", "", text)
    if text == 'BATTER_SO':
        return 'SO'
    return text

def normalize_confidence(val):
    conf = str(val or '').strip().upper()
    return conf if conf in {'SMASH', 'STRONG', 'LEAN'} else 'LEAN'

def pick_perf_clean_cell(val):
    if hasattr(val, 'item'):
        val = val.item()
    if val is None:
        return ''
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return ''
    return val

def pick_perf_safe_upload(spreadsheet, sheet_name, df):
    if df is None or df.empty:
        print(f"   ⏭️  {sheet_name}: No data — skipped")
        return False
    df_clean = df.copy().replace([np.inf, -np.inf], np.nan).fillna('')
    values = [df_clean.columns.tolist()] + [
        [pick_perf_clean_cell(v) for v in row]
        for row in df_clean.values.tolist()
    ]
    try:
        try:
            ws_out = spreadsheet.worksheet(sheet_name)
            ws_out.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws_out = spreadsheet.add_worksheet(title=sheet_name, rows=max(len(values), 100), cols=max(len(df_clean.columns), 26))
        if ws_out.row_count < len(values) or ws_out.col_count < len(df_clean.columns):
            ws_out.resize(rows=max(len(values), ws_out.row_count), cols=max(len(df_clean.columns), ws_out.col_count))
        ws_out.update(values, value_input_option='RAW')
        print(f"   ✅ {sheet_name}: {len(df_clean)} rows × {len(df_clean.columns)} cols")
        return True
    except Exception as e:
        print(f"   ❌ {sheet_name}: {e}")
        return False

def pick_perf_append_upload(spreadsheet, sheet_name, df):
    if df is None or df.empty:
        print(f"   ⏭️  {sheet_name}: No snapshot rows — skipped")
        return False
    df_clean = df.copy().replace([np.inf, -np.inf], np.nan).fillna('')
    rows = [[pick_perf_clean_cell(v) for v in row] for row in df_clean.values.tolist()]
    try:
        try:
            ws_out = spreadsheet.worksheet(sheet_name)
            existing = ws_out.get_all_values()
        except gspread.exceptions.WorksheetNotFound:
            ws_out = spreadsheet.add_worksheet(title=sheet_name, rows=max(len(rows) + 1, 100), cols=max(len(df_clean.columns), 26))
            existing = []
        if not existing:
            ws_out.update([df_clean.columns.tolist()], value_input_option='RAW')
        if ws_out.col_count < len(df_clean.columns):
            ws_out.resize(rows=ws_out.row_count, cols=len(df_clean.columns))
        ws_out.append_rows(rows, value_input_option='RAW')
        print(f"   ✅ {sheet_name}: appended {len(rows)} rows")
        return True
    except Exception as e:
        print(f"   ❌ {sheet_name}: {e}")
        return False

def wilson_lower_bound(p, n, z=PICK_PERF_WILSON_Z):
    if n <= 0:
        return 0.0
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)

def pick_perf_rate(hits, misses):
    denom = hits + misses
    return hits / denom if denom > 0 else np.nan

def pick_perf_prepare_df(df_all):
    if df_all is None or df_all.empty or 'HIT' not in df_all.columns:
        return pd.DataFrame()
    df = df_all[df_all['HIT'].isin(['YES', 'NO', 'PUSH', 'DNP'])].copy()
    if df.empty:
        return df
    idx = df.index
    df['player_norm'] = df.get('player', pd.Series('', index=idx)).map(normalize_person_name)
    df['prop_type_norm'] = df.get('prop_type', pd.Series('', index=idx)).map(normalize_prop_metric)
    df['lean_norm'] = df.get('lean', pd.Series('', index=idx)).fillna('').astype(str).str.upper().replace({'FADE': 'UNDER'})
    df['confidence_norm'] = df.get('confidence', pd.Series('', index=idx)).map(normalize_confidence)
    df['clv_open_f'] = pd.to_numeric(df.get('CLV_OPEN_LINE', pd.Series(np.nan, index=idx)), errors='coerce')
    df['clv_latest_f'] = pd.to_numeric(df.get('CLV_LATEST_LINE', pd.Series(np.nan, index=idx)), errors='coerce')
    df['clv_edge'] = np.where(df['lean_norm'] == 'UNDER', df['clv_open_f'] - df['clv_latest_f'], df['clv_latest_f'] - df['clv_open_f'])
    df['clv_edge'] = pd.to_numeric(df['clv_edge'], errors='coerce')
    df['clv_bucket'] = np.where(df['clv_edge'].isna(), 'unknown', np.where(df['clv_edge'] > 0, 'positive', np.where(df['clv_edge'] < 0, 'negative', 'flat')))
    df['consensus_bucket'] = pd.to_numeric(df.get('CONSENSUS_COUNT', pd.Series(1, index=idx)), errors='coerce').fillna(1).astype(int)
    df['has_lineup_risk'] = df.get('injury_context', pd.Series('', index=idx)).fillna('').astype(str).str.strip().str.startswith('LINEUP RISK')
    df['date_parsed'] = pd.to_datetime(df.get('DATE', pd.Series('', index=idx)), errors='coerce')
    bad_dates = int(df['date_parsed'].isna().sum())
    if bad_dates:
        print(f"   ⚠️ Pick_Performance: {bad_dates} graded rows have unparseable DATE and count only all_time")
    df['day_of_week'] = df['date_parsed'].dt.strftime('%a').fillna('unknown')
    if 'RUN_NUMBER' not in df.columns:
        df['RUN_NUMBER'] = 'unknown'
    else:
        df['RUN_NUMBER'] = df['RUN_NUMBER'].replace('', np.nan).fillna('unknown').astype(str)
    return df

def pick_perf_metrics_row(df_slice, dim_type, dim_value, window_name):
    n_picks = len(df_slice)
    n_hits = int((df_slice['HIT'] == 'YES').sum())
    n_misses = int((df_slice['HIT'] == 'NO').sum())
    n_pushes = int((df_slice['HIT'] == 'PUSH').sum())
    n_dnp = int((df_slice['HIT'] == 'DNP').sum())
    n_decisive = n_picks - n_dnp
    hit_rate = pick_perf_rate(n_hits, n_misses)
    hit_rate_raw = n_hits / n_decisive if n_decisive > 0 else np.nan
    roi_flat = (n_hits * (100 / abs(PICK_PERF_STANDARD_ODDS)) - n_misses) * 100
    roi_per_pick = roi_flat / n_decisive if n_decisive > 0 else np.nan
    clv_numeric = df_slice.dropna(subset=['clv_edge'])
    clv_pos = df_slice[df_slice['clv_edge'] > 0]
    clv_neg = df_slice[df_slice['clv_edge'].notna() & (df_slice['clv_edge'] <= 0)]
    pos_hits = int((clv_pos['HIT'] == 'YES').sum())
    pos_misses = int((clv_pos['HIT'] == 'NO').sum())
    neg_hits = int((clv_neg['HIT'] == 'YES').sum())
    neg_misses = int((clv_neg['HIT'] == 'NO').sum())
    wilson_n = n_hits + n_misses
    wilson_p = n_hits / wilson_n if wilson_n > 0 else 0
    return {
        'DIMENSION_TYPE': dim_type,
        'DIMENSION_VALUE': '' if dim_value is None else str(dim_value),
        'TIME_WINDOW': window_name,
        'N_PICKS': n_picks,
        'N_PICKS_DECISIVE': n_decisive,
        'N_HITS': n_hits,
        'N_MISSES': n_misses,
        'N_PUSHES': n_pushes,
        'N_DNP': n_dnp,
        'HIT_RATE': round(hit_rate, 3) if pd.notna(hit_rate) else np.nan,
        'HIT_RATE_RAW': round(hit_rate_raw, 3) if pd.notna(hit_rate_raw) else np.nan,
        'PUSH_RATE': round(n_pushes / n_picks, 3) if n_picks else 0,
        'DNP_RATE': round(n_dnp / n_picks, 3) if n_picks else 0,
        'ROI_FLAT': round(roi_flat, 3),
        'ROI_PER_PICK': round(roi_per_pick, 3) if pd.notna(roi_per_pick) else np.nan,
        'AVG_CLV_EDGE': round(clv_numeric['clv_edge'].mean(), 3) if not clv_numeric.empty else np.nan,
        'CLV_POSITIVE_RATE': round((clv_numeric['clv_edge'] > 0).mean(), 3) if not clv_numeric.empty else np.nan,
        'CLV_POS_HIT_RATE': round(pick_perf_rate(pos_hits, pos_misses), 3) if pd.notna(pick_perf_rate(pos_hits, pos_misses)) else np.nan,
        'CLV_NEG_HIT_RATE': round(pick_perf_rate(neg_hits, neg_misses), 3) if pd.notna(pick_perf_rate(neg_hits, neg_misses)) else np.nan,
        'WILSON_LOWER_95': round(wilson_lower_bound(wilson_p, wilson_n), 3),
        'MIN_SAMPLE_FLAG': bool(n_decisive >= PICK_PERF_MIN_SAMPLE),
        'LAST_UPDATED': timestamp_est,
    }

def pick_perf_window_df(df, window_name, days, today):
    if days is None:
        return df.copy()
    cutoff = pd.Timestamp(today - timedelta(days=days))
    return df[df['date_parsed'].notna() & (df['date_parsed'] >= cutoff)].copy()

def build_pick_performance_metrics(df_all):
    df = pick_perf_prepare_df(df_all)
    if df.empty:
        return pd.DataFrame(columns=PICK_PERFORMANCE_COLUMNS), df
    today = datetime.now(pytz.timezone('US/Eastern')).date()
    rows = []
    for window_name, days in PICK_PERF_TIME_WINDOWS.items():
        win_df = pick_perf_window_df(df, window_name, days, today)
        if win_df.empty:
            continue
        rows.append(pick_perf_metrics_row(win_df, 'overall', '', window_name))
        for dim in PICK_PERF_DIMENSIONS:
            if dim not in win_df.columns:
                continue
            for dim_value, grp in win_df.groupby(dim, dropna=False):
                rows.append(pick_perf_metrics_row(grp, dim, dim_value, window_name))
    metrics_df = pd.DataFrame(rows, columns=PICK_PERFORMANCE_COLUMNS)
    if metrics_df.empty:
        return metrics_df, df
    window_order = {name: i for i, name in enumerate(PICK_PERF_TIME_WINDOWS.keys())}
    metrics_df['_window_order'] = metrics_df['TIME_WINDOW'].map(window_order).fillna(99)
    metrics_df = metrics_df.sort_values(['_window_order', 'DIMENSION_TYPE', 'WILSON_LOWER_95'], ascending=[True, True, False])
    metrics_df = metrics_df.drop(columns=['_window_order']).reset_index(drop=True)
    return metrics_df, df

def build_snapshot_rows(metrics_df, snapshot_date):
    if metrics_df is None or metrics_df.empty:
        return []
    rows = []
    snap = metrics_df[metrics_df['TIME_WINDOW'].isin(PICK_PERF_SNAPSHOT_WINDOWS)].copy()
    for _, row in snap.iterrows():
        dim_type = row['DIMENSION_TYPE']
        dim_val = str(row['DIMENSION_VALUE'])
        key_suffix = 'overall' if dim_type == 'overall' else f"{dim_type.replace('_norm', '')}.{dim_val}"
        rows.append({'SNAPSHOT_DATE': snapshot_date, 'METRIC_KEY': f"hit_rate.{key_suffix}", 'METRIC_VALUE': row['HIT_RATE'], 'N_PICKS': row['N_PICKS_DECISIVE'], 'TIME_WINDOW': row['TIME_WINDOW']})
        if dim_type in {'overall', 'confidence_norm'}:
            rows.append({'SNAPSHOT_DATE': snapshot_date, 'METRIC_KEY': f"roi_per_pick.{key_suffix}", 'METRIC_VALUE': row['ROI_PER_PICK'], 'N_PICKS': row['N_PICKS_DECISIVE'], 'TIME_WINDOW': row['TIME_WINDOW']})
    return rows

def snapshot_already_exists(spreadsheet, snapshot_date):
    try:
        ws_snap = spreadsheet.worksheet('Pick_Performance_Snapshots')
        rows = ws_snap.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        return False
    except Exception as e:
        print(f"   ⚠️ Snapshot check failed: {e}")
        return False
    if not rows:
        return False
    df_snap = pd.DataFrame(rows)
    return 'SNAPSHOT_DATE' in df_snap.columns and str(snapshot_date) in set(df_snap['SNAPSHOT_DATE'].astype(str))

def print_pick_performance_summary(metrics_df, sport):
    print("\n" + "=" * 60)
    print(f"📊 PICK PERFORMANCE — {sport}")
    print("=" * 60)
    if metrics_df is None or metrics_df.empty:
        print("   No graded picks to analyze.")
        print("=" * 60)
        return
    overall_all = metrics_df[(metrics_df['DIMENSION_TYPE'] == 'overall') & (metrics_df['TIME_WINDOW'] == 'all_time')]
    overall_30 = metrics_df[(metrics_df['DIMENSION_TYPE'] == 'overall') & (metrics_df['TIME_WINDOW'] == 'last_30d')]
    def fmt_row(df_row):
        if df_row.empty:
            return "n/a"
        r = df_row.iloc[0]
        return f"{r['HIT_RATE'] * 100:.1f}% (n={int(r['N_PICKS_DECISIVE'])})" if pd.notna(r['HIT_RATE']) else f"n/a (n={int(r['N_PICKS_DECISIVE'])})"
    print(f"   Overall:       {fmt_row(overall_all)}  |  last 30d: {fmt_row(overall_30)}")
    conf = metrics_df[(metrics_df['DIMENSION_TYPE'] == 'confidence_norm') & (metrics_df['TIME_WINDOW'] == 'all_time')]
    for tier in ['SMASH', 'STRONG', 'LEAN']:
        row = conf[conf['DIMENSION_VALUE'] == tier]
        if not row.empty:
            print(f"   {tier:<14} {fmt_row(row)}")
    prop = metrics_df[(metrics_df['DIMENSION_TYPE'] == 'prop_type_norm') & (metrics_df['TIME_WINDOW'] == 'all_time') & (metrics_df['MIN_SAMPLE_FLAG'] == True)].copy()
    if not prop.empty:
        top = prop.sort_values('WILSON_LOWER_95', ascending=False).head(5)
        worst = prop.sort_values('WILSON_LOWER_95', ascending=True).head(5)
        print("\n   ✅ Top prop types (all-time, Wilson LB):")
        for _, r in top.iterrows():
            print(f"      {r['DIMENSION_VALUE']:<8} {r['HIT_RATE'] * 100:.1f}% (n={int(r['N_PICKS_DECISIVE'])})   LB={r['WILSON_LOWER_95']:.3f}")
        print("\n   🚨 Worst prop types (all-time, Wilson LB):")
        for _, r in worst.iterrows():
            print(f"      {r['DIMENSION_VALUE']:<8} {r['HIT_RATE'] * 100:.1f}% (n={int(r['N_PICKS_DECISIVE'])})   LB={r['WILSON_LOWER_95']:.3f}")
    alerts = []
    all_time = metrics_df[metrics_df['TIME_WINDOW'] == 'all_time']
    last_30 = metrics_df[metrics_df['TIME_WINDOW'] == 'last_30d']
    for _, r30 in last_30[last_30['MIN_SAMPLE_FLAG'] == True].iterrows():
        rall = all_time[
            (all_time['DIMENSION_TYPE'] == r30['DIMENSION_TYPE']) &
            (all_time['DIMENSION_VALUE'] == r30['DIMENSION_VALUE']) &
            (all_time['MIN_SAMPLE_FLAG'] == True)
        ]
        if rall.empty or pd.isna(r30['HIT_RATE']) or pd.isna(rall.iloc[0]['HIT_RATE']):
            continue
        delta = (r30['HIT_RATE'] - rall.iloc[0]['HIT_RATE']) * 100
        if abs(delta) >= PICK_PERF_DRIFT_ALERT_PP:
            label = r30['DIMENSION_TYPE'].replace('_norm', '')
            alerts.append(f"{label}.{r30['DIMENSION_VALUE']}: 30d={r30['HIT_RATE']*100:.1f}% vs all-time={rall.iloc[0]['HIT_RATE']*100:.1f}% (Δ={delta:+.1f}pp)")
    print("\n   ⚠️ Drift alerts:")
    if alerts:
        for alert in alerts[:8]:
            print(f"      {alert}")
    else:
        print("      none")
    print("=" * 60)

def run_pick_performance_section(df_all, sport):
    metrics_df, prepared_df = build_pick_performance_metrics(df_all)
    if prepared_df.empty:
        print("\n📊 Pick_Performance: no graded picks to analyze.")
        return
    wrote_perf = pick_perf_safe_upload(sh, 'Pick_Performance', metrics_df)
    snapshot_date = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d')
    if snapshot_already_exists(sh, snapshot_date):
        print(f"   ⏭️  Pick_Performance_Snapshots: snapshot already exists for {snapshot_date}")
    else:
        snapshot_df = pd.DataFrame(build_snapshot_rows(metrics_df, snapshot_date), columns=PICK_PERFORMANCE_SNAPSHOT_COLUMNS)
        pick_perf_append_upload(sh, 'Pick_Performance_Snapshots', snapshot_df)
    print_pick_performance_summary(metrics_df, sport)
    if wrote_perf:
        print("   📈 Pick_Performance written.")

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
date_series = pd.to_datetime(df_picks['DATE'], errors='coerce')
today_ts = pd.to_datetime(today_str)
retry_cutoff = today_ts - pd.Timedelta(days=RETRY_DNP_LOOKBACK_DAYS)
retry_dnp_mask = (hit_series == 'DNP') & date_series.notna() & (date_series >= retry_cutoff) & (date_series <= today_ts)
blank_ungraded_mask = (hit_series == '') & date_series.notna() & (date_series < today_ts)
ungraded = df_picks[blank_ungraded_mask | retry_dnp_mask].copy()

if ungraded.empty:
    blanks_today = int(((hit_series == '') & date_series.notna() & (date_series >= today_ts)).sum())
    if blanks_today > 0:
        print(f"⏳ {blanks_today} ungraded picks from today ({today_str}) — games haven't finished yet. Run tomorrow.")
    else:
        print("✅ All picks are already graded! Nothing to do.")
    dates_to_grade = []
else:
    dates_to_grade = sorted(ungraded['DATE'].unique())
    retry_ct = int(retry_dnp_mask.sum())
    if retry_ct > 0:
        print(f"🎯 {len(ungraded)} gradeable picks from: {', '.join(dates_to_grade)} ({retry_ct} recent DNP retries)")
    else:
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
runlog.hits = hits
runlog.misses = misses
runlog.dnp_count = dnp
runlog.not_found_count = not_found
runlog.picks_graded = hits + misses

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

    print_clv_summary(df_all)
    print_winning_combo_tracker(df_all, dates_to_grade)
    run_pick_performance_section(df_all, 'NHL')

print("\n🏒 Done! Run this every morning after games.")
