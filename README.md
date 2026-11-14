# NHL DFS Dashboard

## Publication evidence (2026-11-13)

### Matching reporting windows

The grader and dashboard now use exactly 7, 30, or 90 calendar dates including today in Eastern time. Previously the grader included an extra day. On November 13, its 30-day summary included October 14 (21 decisive picks: 7 wins and 14 losses), while the dashboard correctly began October 15. That explains the 516 versus 495 decisive-pick discrepancy. Invalid and future dates are excluded consistently, including all-time results.

The dashboard flags publication-cohort totals that differ from the loaded ledger instead of silently presenting them as comparable. Push this update, rerun the NHL grader, and refresh the dashboard to rebuild the summaries. No engine run or Odds API credits are needed. This corrects reporting boundaries, not grades or pick selection.

### Historical reconstruction

The grader now reads Run_Log to classify older picks as RECONSTRUCTED_PREGAME_FEED when one matching engine run succeeded (OK/WARN, no error), logged a positive Daily_Picks write count, and finished before the stored game start. Matching uses run/publication ID first, then a unique explicit-timezone RUN_TIME interval for legacy rows. Ambiguous, missing, failed, or late evidence never becomes a pregame success. A failed or altered direct receipt cannot be rescued by reconstruction.

Publication_Audit records each row's cohort, source run, completion time, and reason. This is inference from retained logs, not a claim that historical selections were read back or viewed. It does not rewrite Daily_Picks or Publication_Ledger, alter grades, or relax performance eligibility. Run the updated grader to reconstruct available history; no engine run or Odds API credits are required for this classification. Coverage depends on retained run logs and game start times, and has not yet been measured against live Sheets.

The engine assigns each emitted pick a publication ID and verifies its saved player, market, side, line, captured price, and game start against Daily_Picks. After feed/status readback it appends a snapshot to Publication_Ledger and verifies that receipt. Failed verification fails the run and marks the slate failed.

The grader reports publication_cohort separately: VERIFIED_PREGAME_FEED, RECONSTRUCTED_PREGAME_FEED, UNVERIFIED_CAPTURE, and LATE_OR_UNVERIFIED. Stats shows these groups without relabeling the existing overall record. Research labels and selection rules are unchanged. Direct receipts verify availability in the research feed; reconstructed rows infer it from successful run logs. Neither proves a browser impression, dynamic shortlist selection, or predictive validation. Repeated publications are not independent bets; existing sport-specific performance eligibility/deduplication remains in effect.

Deployment: push the helper, grader, and frontend updates together. The updated grader can reconstruct historical evidence from retained Run_Log records without rerunning the engine. The updated engine creates direct receipts going forward. Historical rows are never retroactively marked directly verified. Missing evidence leaves captures unverified; unexpected ledger or run-log read errors stop grading rather than silently downgrade evidence.

Validation: offline publication fixtures cover readback mismatch, late publication, numeric round trips, immutable selection snapshots, and retry identity. Live Sheets publication and physical-device verification are still required after deployment.

A personal NHL player-prop research dashboard for turning daily hockey data, live prop markets, AI picks, and grader feedback into one mobile-first view.

This repo is the GitHub Pages frontend for the NHL system. The engine writes data to Google Sheets, the grader closes the loop after games, and `index.html` + `app.js` + `styles.css` read the workbook through public Sheets CSV endpoints.

## What It Does

### Mobile Streaks fix (2026-11-12)

- Fixed mismatched filter tags that could nest the Streaks cards inside the horizontally scrolling filter row.
- Filters now use real buttons with selected-state accessibility; long player and matchup details wrap without pushing the streak count offscreen.
- Frontend-only change: deploy GitHub Pages and refresh the phone. No engine run or API credits required.

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
- **Stats**: captured-price returns, hit rate, and breakdowns by market, side, book and confidence.
- **Game Builder**: editable single-game selections and saved entries.
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
and game-builder calculations. Sample averages describe the selected season and game type;
they are not a new-season projection model.

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

## NHL research expansion

The daily workspace now includes:

- **Dash:** current/prior regular-season and current-playoff samples, recent-game windows, over/under charts, home/away averages, ice time, goalie context and back-to-back status.
- **Picks → Tonight’s Shortlist:** dated quotes for games that have not started, historical evidence, and a saved research tray. At least three measured games are required. Historical returns are observations, not forecasts.
- **Lookup:** search all players in the loaded logs, including players off tonight’s slate.
- **Leaders:** daily skater/goalie results and the pick ledger. Same-day records require a final schedule state. Coverage is limited to collected logs.
- **Game Builder:** editable selections, captured book/price, overlap warnings, start-time locks, and locally saved entries. It does not calculate a combined same-game price.
- **Stats:** units and ROI from each pick’s captured odds, with market, side, book and confidence breakdowns. Unpriced legacy picks are excluded from returns; pushes return the stake and DNPs are excluded.

`research.js` supplies these views alongside `app.js`. `nhl_research.py` contains shared season and pricing helpers for the engine and grader; publish both new files with the existing files.

The engine tags logs with season/game type, separates current and prior samples, retains new players with no current games, and captures the exact matching pick line, side, book and odds. Legacy goalie records are tagged only when matched to authoritative API logs; unknown records remain available under All loaded history. The grader retains legacy flat-price metrics for existing consumers and adds captured-price metrics.

Line assignments and power-play units display “Not provided” unless the data source supplies them. A roster appearance does not establish a confirmed starting goalie. Quotes are daily snapshots, not live sportsbook feeds. Saved trays and entries stay in this browser’s local storage and do not sync across devices.

Publish the frontend, engine, grader and helpers together. New fields and priced pick history begin with subsequent engine/grader runs; old unpriced history is not retroactively assigned prices.

Additional fixture validation:

```sh
node --check research.js
node tests/dashboard.cjs
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m py_compile NHLEngine5-4.py NHLGrader5-4.py nhl_research.py
```
## November 2: Dashboard Team Logos

Daily slate matchups and player-analysis headers now display NHL-hosted team
logos beside the abbreviations. Missing images fall back to the retained text;
unknown teams display TBD. This is frontend-only: push and refresh the page,
with no engine rerun or Odds API usage required.
