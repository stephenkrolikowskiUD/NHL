const {readFileSync,writeFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const app={innerHTML:'',dataset:{},addEventListener(){}};
const element={addEventListener(){},value:''};
const ctx=vm.createContext({console,Date,Map,Set,Math,Number,String,Array,JSON,Promise,parseFloat,parseInt,isNaN,Infinity,AbortSignal,
  localStorage:{getItem(){return null},setItem(){}},
  document:{hidden:false,activeElement:null,body:{classList:{toggle(){}}},getElementById(id){return id==='app'?app:element},querySelectorAll(){return []},addEventListener(){}},
  window:{scrollTo(){}},setInterval(){},fetch:async()=>{throw Error('No network in fixture')}});
const run=s=>vm.runInContext(s,ctx);
run(readFileSync(path.join(root,'research.js'),'utf8'));
let code=readFileSync(path.join(root,'app.js'),'utf8');
run(code.slice(0,code.lastIndexOf('\nloadAllData();')));
run(`
  st.loading=false;st.activeTab='dashboard';st.mode='skater';st.player='Fixture Skater';st.metric='PTS';st.line='1.5';
  st.slateStatus={SLATE_DATE:easternTodayISO(),GAME_COUNT:1,STATUS:'READY'};
  st.tonight=[{player_name:st.player,team_abbr:'BOS',position:'C',opp_abbr_tonight:'NYR',SLATE_DATE:easternTodayISO(),COMMENCE_TIME:new Date(Date.now()+3600000).toISOString()}];
  st.gameLogs=Array.from({length:12},(_,i)=>({player_name:st.player,team_abbr:'BOS',opp_abbr:i%2?'MTL':'NYR',home_away:i%3?'Away':'Home',game_date:new Date(Date.now()-(i+1)*864e5).toISOString().slice(0,10),SEASON_ID:rrSeason(),GAME_TYPE:2,PTS:i===4?'':i%4,G:i%2,A:1,SOG:2+i%4,HITS:1,BLK:0,TOI:'20:30'}));
  st.props=[{PLAYER_NAME:st.player,METRIC:'PTS',DK_LINE:1.5,OVER_ODDS:120,UNDER_ODDS:-140,REFERENCE_BOOK:'DraftKings',LAST_UPDATED:easternTodayISO()}];
  st.dataVersion++;resetDerived();rrState().window='all';render();
`);
const populated=app.innerHTML;
assert.match(populated,/<\/header>\s*<div class="rr-stat-strip"/);
assert.match(populated,/<span class="rr-focus-metric">PTS · OVER<\/span><strong>1.5<\/strong>/);
assert.match(populated,/rr-chart-panel[\s\S]*?rr-chart-toolbar[\s\S]*?data-rr="scope"[\s\S]*?data-rr="lean"[\s\S]*?<\/section>/);
assert.match(populated,/<section class="rr-panel rr-context-column">[\s\S]*?<\/section>\s*<section class="rr-panel rr-markets-panel">/);
assert.doesNotMatch(populated,/<aside class="rr-context-column">/);
assert.ok(populated.indexOf('daily-slate')<populated.indexOf('rr-analysis'));
assert.match(populated,/12 selected \/ 12 matching \/ 12 scoped games/);
assert.match(populated,/11 measured \/ 12 selected games/);
assert.match(populated,/H2H vs NYR/);
assert.doesNotMatch(populated,/rr-panel rr-(chart|averages|splits)-panel/);
assert.doesNotMatch(run(`rrPlayerIdentity('Fixture Skater')`),/analysis-eyebrow/);
assert.match(populated,/class="rr-average-grid">[\s\S]*?<span>Season<\/span>[\s\S]*?<span>L10<\/span>[\s\S]*?<span>L5<\/span>[\s\S]*?<span>Last<\/span>/);
assert.equal((populated.match(/class="rr-split-card"/g)||[]).length,2);
assert.equal((populated.match(/class="rr-mini-bar"/g)||[]).length,4);
assert.match(run(`rrSplitBars([['Missing',[{PTS:''}]],['Zero',[{PTS:0}]]],'PTS')`),/0 measured \/ 1 games/);
assert.equal((run(`rrSplitBars([['Missing',[{PTS:''}]],['Zero',[{PTS:0}]]],'PTS')`).match(/class="rr-mini-bar"/g)||[]).length,1);
const styles=readFileSync(path.join(root,'styles.css'),'utf8');
assert.match(styles,/\.rr-markets-panel\{grid-column:1;grid-row:3\}/);
assert.match(styles,/\.rr-average-grid\{display:grid;grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
assert.match(styles,/@media\(max-width:767px\)\{[^}]*\}[\s\S]*?\.rr-average-grid\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
assert.match(populated,/rr-chart-panel[\s\S]*rr-averages-panel[\s\S]*rr-splits-panel[\s\S]*rr-context-column/);
assert.equal((populated.match(/class="rr-bar-column"/g)||[]).length,12);
run(`rrHandle('chartOpponent','NYR');rrHandle('chartVenue','Home');rrHandle('window','5')`);
assert.equal(run(`rrChartSample(rrScopeRows(st.gameLogs),rrState()).rows.length`),2);
assert.match(app.innerHTML,/2 selected \/ 2 matching \/ 12 scoped games/);
assert.match(app.innerHTML,/Season<\/span><strong>1.64/);
run(`rrHandle('chartVenue','Away')`);
assert.equal(run(`rrChartSample(rrScopeRows(st.gameLogs),rrState()).rows.length`),4);
run(`rrHandle('chartOpponent','NOT_A_TEAM')`);
assert.equal(run(`rrChartSample(rrScopeRows(st.gameLogs),rrState()).opponent`),'ALL');
run(`rrHandle('chartVenue','ALL');rrHandle('window','5')`);
assert.equal(run(`rrChartSample(rrScopeRows(st.gameLogs),rrState()).rows.length`),5);
// Untagged history must not become a classified current-season sample.
run(`st.gameLogs=st.gameLogs.map(({GAME_TYPE,SEASON_ID,...g})=>g);st.dataVersion++;resetDerived();render()`);
assert.match(app.innerHTML,/0 current \/ 0 prior/);
assert.match(app.innerHTML,/No classified history in this scope/);
assert.match(app.innerHTML,/rr-chart-empty/);
assert.doesNotMatch(app.innerHTML,/class="rr-mini-bar"/);
assert.doesNotMatch(app.innerHTML,/class="rr-chart"/);
assert.match(app.innerHTML,/rr-averages-panel[\s\S]*rr-splits-panel[\s\S]*rr-context-column/);
const empty=app.innerHTML;
assert.match(empty,/<\/header>\s*<div class="rr-stat-strip"/);
assert.match(empty,/<section class="rr-panel rr-markets-panel">/);
run(`rrHandle('scope','all')`);
assert.equal(run(`rrScopeRows(st.gameLogs,'all').length`),12);
assert.match(app.innerHTML,/5 selected \/ 12 matching \/ 12 scoped games/);
run(`st.gGameLogs=[{player_name:'Fixture Goalie',game_date:easternTodayISO(),GAME_TYPE:2,SEASON_ID:rrSeason(),SV:27,GA:3,SV_PCT:0.9}];st.dataVersion++;resetDerived()`);
assert.match(run(`rrAnalysis('Fixture Goalie',true,'SV_PCT','0.9')`),/0.900/);
assert.equal(run(`rrCounts([{SV:0},{SV:''},{SV:2}],'SV',0).pushes`),1);
assert.equal(run(`rrCounts([{SV:0},{SV:''},{SV:2}],'SV',0).n`),2);
assert.equal(run(`rrScopeRows([{GAME_TYPE:3,SEASON_ID:rrSeason()},{GAME_TYPE:2,SEASON_ID:rrSeason()}],'playoffs').length`),1);
if(process.env.NHL_RESEARCH_PREVIEW){
  const css=readFileSync(path.join(root,'styles.css'),'utf8');
  for(const [file,html] of [['/tmp/nhl-research-preview.html',populated],['/tmp/nhl-research-empty-preview.html',empty]]){
    writeFileSync(file,`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NHL research fixture</title><style>${css}</style></head><body><p style="padding:12px;color:var(--accent)">SYNTHETIC QA FIXTURE ONLY - static rendered preview, not real player statistics or quotes.</p><div id="app">${html}</div></body></html>`);
    console.log(`Preview: ${file}`);
  }
}
console.log('PASS: research layout, scope isolation, filters, counts, missing history and goalie precision');
