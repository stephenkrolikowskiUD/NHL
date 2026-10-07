# NHL DFS Dashboard

A personal NHL player-prop research dashboard for turning daily hockey data, live prop markets, AI picks, and grader feedback into one mobile-first view.

This repo is the GitHub Pages frontend for the NHL system. The engine writes data to Google Sheets, the grader closes the loop after games, and `index.html` + `app.js` + `styles.css` read the workbook through public Sheets CSV endpoints.

## What It Does

- Shows skater and goalie context for tonight's slate: game logs, home/away splits, starter status, opponent context, props, and AI picks.
- Supports both skater and goalie workflows, including save props, shots, hits, points, and related boards.
- Surfaces best bets, smart slips, streaks, due spots, props, Stats, and Game Entry views.
- Displays Pick Performance analytics so confidence tiers, prop types, leans, CLV buckets, and ROI can be judged from graded history.
- Surfaces multi-book best-price routing when the engine has current prop data.

## How It Works

1. `NHLEngine5-4.py` pulls NHL schedule data, player logs, goalie context, live props, and Gemini picks.
2. The engine writes dashboard tabs to the NHL Google Sheet.
3. `index.html` loads those tabs through Google Sheets CSV endpoints.
4. `NHLGrader5-4.py` grades completed picks and writes `HIT`, `ACTUAL_STAT`, and `RESULT` back to `Daily_Picks`.
5. Pick Performance turns that graded history into the Stats tab.

## Key Tabs

- **Dash**: selected-player or goalie context, matchup, props, splits, and logs.
- **Log**: game-log focused view.
- **Picks**: AI picks, best bets, slips, streaks, due spots, props, and parlay helpers.
- **Stats**: Pick Performance hit rate, ROI, CLV, confidence tiers, prop types, and drift checks.
- **Game Entry**: single-game auto-entry builder.
- **Info**: method notes and glossary.

## Run Mode

NHL is automated through GitHub Actions. The engine runs during the day, and the grader runs after games to update the feedback loop.

## Data Sources

- Google Sheets workbook: `1OpER7aRmMFWyxMONdg_LqiyQ47cA3dWRSR8UEQH8FIM`
- NHL API
- The Odds API
- Gemini output from the engine

## Current Experiments

- Pick Performance driven prompt tuning.
- Multi-book best-price routing.
- NHL UNDER monitoring after early Pick Performance showed a stronger UNDER signal.
- Game Entry, a fast single-game entry builder.

## Important Notes

- Keep the dashboard file named `index.html`; GitHub Pages depends on it.
- No private API keys live in this repo or in the HTML.
- Public Sheet IDs are identifiers, not secrets.
- This is a personal research tool, not betting advice.


## October 2026 refresh

The frontend now follows NFLDesktop's workspace layout: compact navigation,
a daily matchup strip, a player-analysis hero, responsive research cards, and
shared theme colors. It retains NHL's skater/goalie, picks, logs, performance,
and game-builder calculations. The history average describes the loaded logs;
it is not a new-season projection model.

While visible, the page checks Sheets every five minutes and when returning
after five minutes away. Refresh preserves the player, metric, line, and tab;
a failed refresh retains the previous data and shows a notice.

The engine writes a `Slate_Status` tab with `SLATE_DATE`, `GAME_COUNT`,
`LAST_UPDATED`, `STATUS`, and (for ready slates) `PROP_COUNT`. A verified off day
publishes `NO_GAMES` and exits before odds/AI requests. An unverified schedule
fails without claiming there are no games. Empty current props are hidden even
if Sheets still contains a prior market snapshot. Current player rows include
`COMMENCE_TIME` and `SLATE_DATE`; schedule and odds dates use America/New_York.

Daily GitHub Actions schedules are restored in the workflow files:

- Engine: 05:45, 15:00, 19:00, and 22:30 UTC.
- Grader: 06:00 and 10:00 UTC.

UTC schedules shift by one local hour when daylight saving time changes.
These schedules take effect after the workflow changes reach the default branch.
The frontend and engine should be published together; until an updated engine
run, the frontend uses existing row timestamps to identify older data.

### Local validation

```sh
node --check app.js
node tests/dashboard.cjs
python3 tests/test_daily_dates.py
```

These checks use fixtures and isolated engine helpers: they do not spend API
credits or write to Sheets. A complete authenticated engine/grader run still
requires the existing GitHub repository secrets.
