"""Pure season, usage and captured-price helpers shared by engine and grader."""
from datetime import date
import math
import re
import unicodedata


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def season_for_date(value):
    try:
        day = date.fromisoformat(str(value)[:10])
        year = day.year if day.month >= 7 else day.year - 1
        return f'{year}{year + 1}'
    except ValueError:
        return ''


def game_type(row):
    explicit = number(row.get('GAME_TYPE') or row.get('gameTypeId') or row.get('game_type'))
    if explicit in (1, 2, 3):
        return int(explicit)
    gid = str(row.get('gameId') or row.get('game_id') or '')
    if re.fullmatch(r'\d{10}(?:\.0)?', gid) and gid[4:6] in ('01', '02', '03'):
        return int(gid[4:6])
    return None  # Legacy goalie rows lack game IDs; do not guess playoff status.


def annotate_log(row):
    out = dict(row)
    out['SEASON_ID'] = str(row.get('SEASON_ID') or season_for_date(row.get('game_date')))
    out['GAME_TYPE'] = game_type(row) or ''
    return out


def season_rows(rows, season, kind=2):
    return [r for r in rows if str(r.get('SEASON_ID') or season_for_date(r.get('game_date'))) == str(season) and game_type(r) == kind]


def toi_minutes(value):
    if isinstance(value, str) and ':' in value:
        try:
            minutes, seconds = value.split(':')
            seconds = float(seconds)
            return float(minutes) + seconds / 60 if 0 <= seconds < 60 else None
        except (ValueError, TypeError):
            return None
    return number(value)


def season_summary(rows, season, stats, kind=2):
    current = sorted(season_rows(rows, season, kind), key=lambda r: str(r.get('game_date', '')), reverse=True)
    prior = season_rows(rows, f'{int(str(season)[:4])-1}{int(str(season)[:4])}', kind)
    out = {'SEASON_ID': season, 'GAME_TYPE': kind, 'CURRENT_SEASON_GP': len(current), 'PRIOR_SEASON_GP': len(prior),
           'HISTORY_GP': len(rows), 'SAMPLE_BASIS': 'current season regular season' if kind == 2 else 'current season playoffs',
           'LIMITED_SAMPLE': len(current) < 5}
    for stat in stats:
        for prefix, sample in [('Seas_', current), ('Prior_', prior), ('L5_', current[:5]), ('L3_', current[:3])]:
            vals = [number(r.get(stat)) for r in sample]
            vals = [v for v in vals if v is not None]
            out[prefix + stat] = round(sum(vals)/len(vals), 3) if vals else 0
    for prefix, sample in [('L5_', current[:5]), ('Seas_', current)]:
        vals = [toi_minutes(r.get('TOI')) for r in sample]
        vals = [v for v in vals if v is not None]
        out[prefix+'TOI_MIN'] = round(sum(vals)/len(vals), 3) if vals else ''
    return out


def normalized_name(value):
    text = unicodedata.normalize('NFKD', str(value or '')).lower()
    return re.sub(r'[^a-z0-9]', '', text)


def capture_pick_price(pick, props, captured_at):
    """Match the same player, metric AND line. Never assign another line's odds."""
    lean = str(pick.get('lean', '')).upper()
    lean = 'UNDER' if lean == 'FADE' else lean
    target_line = number(pick.get('line'))
    if lean not in ('OVER', 'UNDER') or target_line is None:
        return {'PRICE_STATUS': 'UNPRICED'}
    metric = str(pick.get('prop_type', '')).upper().strip()
    for prop in props:
        if normalized_name(prop.get('PLAYER_NAME')) != normalized_name(pick.get('player')):
            continue
        if str(prop.get('METRIC', '')).upper().strip() != metric or number(prop.get('DK_LINE')) != target_line:
            continue
        book, odds = prop.get(f'BEST_{lean}_BOOK'), number(prop.get(f'BEST_{lean}_ODDS'))
        if not book or odds is None or abs(odds) < 100:
            book = prop.get('REFERENCE_BOOK') or prop.get('BOOK')
            odds = number(prop.get(f'{lean}_ODDS'))
        if book and odds is not None and abs(odds) >= 100:
            return {'PICK_BOOK': book, 'PICK_ODDS': odds, 'PICK_LINE': target_line,
                    'PRICE_CAPTURED_AT': captured_at, 'PRICE_STATUS': 'CAPTURED'}
    return {'PRICE_STATUS': 'UNPRICED'}


def settled_units(result, odds, book):
    """One unit per settled priced pick; DNP excluded, pushes return the stake."""
    value = number(odds)
    if str(book or '').strip().lower() in {'', 'nan', 'none', 'null'} or value is None or abs(value) < 100:
        return None
    result = str(result or '').upper()
    if result == 'YES':
        return value/100 if value > 0 else 100/abs(value)
    if result == 'NO':
        return -1.0
    if result == 'PUSH':
        return 0.0
    return None
