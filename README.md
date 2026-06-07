# NHL DFS Dashboard

A personal NHL player-prop research dashboard for turning daily hockey data, live prop markets, AI picks, and grader feedback into one mobile-first view.

This repo is the GitHub Pages frontend for the NHL system. The engine writes data to Google Sheets, the grader closes the loop after games, and `index.html` reads the workbook through public Sheets CSV endpoints.

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
