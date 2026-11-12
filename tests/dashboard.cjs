const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const path=require('node:path');
const app={innerHTML:'',dataset:{},addEventListener(){}};
const element={addEventListener(){},value:'',focus(){}};
const storage=new Map();
const ctx=vm.createContext({console:{log(){},warn(){},error(){}},Date,Map,Set,Math,Number,String,Array,JSON,Promise,parseFloat,parseInt,isNaN,Infinity,AbortSignal,
  localStorage:{getItem(k){return storage.get(k)||null},setItem(k,v){storage.set(k,v)}},
  document:{hidden:false,activeElement:null,body:{classList:{toggle(){}}},getElementById(id){return id==='app'?app:element},querySelectorAll(){return []},addEventListener(){}},
  window:{scrollTo(){}},setInterval(){},fetch:async()=>{throw Error('unexpected network')}});
let code=readFileSync(path.join(__dirname,'../app.js'),'utf8');
code=code.slice(0,code.lastIndexOf('\nloadAllData();'));
// Replace only the transport binding in the isolated test context.
code=code.replace('const fetchSheet=', 'let fetchSheet=');
vm.runInContext(readFileSync(path.join(__dirname,'../research.js'),'utf8'),ctx);
vm.runInContext(code,ctx);
const run=s=>vm.runInContext(s,ctx);
assert.match(run(`nhlTeamLabel('bos')`),/BOS_light\.svg/);
assert.match(run(`nhlTeamLabel('bos')`),/>BOS<\/span>/);
assert.match(run(`nhlTeamLabel('')`),/>TBD<\/span>/);
assert.doesNotMatch(run(`nhlTeamLabel('<script>')`),/<img|<script>/);
assert.match(run(`renderPlayerHero('Test',{team_abbr:'BOS',opp_abbr_tonight:'NYR'},'PTS',[],false)`),/NYR_light\.svg/);
run(`st.loading=false;st.loadedAt='1:00 PM';st.slateStatus={SLATE_DATE:easternTodayISO(),GAME_COUNT:0};render()`);
assert.match(app.innerHTML,/No games scheduled today/);
for(const view of ['dashboard','gamelog','picks','stats','entry','method','lookup','leaders']){
  run(`switchTab('${view}')`);assert.match(app.innerHTML,/NHL DFS Dashboard/);
}
run(`st.slateStatus={SLATE_DATE:'2025-01-01',GAME_COUNT:1};render()`);
assert.match(app.innerHTML,/Older snapshot/);
// Filter controls must close before the cards, not swallow them into a flex row.
run(`originalStreaks=getStreaks;getStreaks=()=>[{player:'Long Player Name',team:'BOS',opp:'NYR',propType:'skt',streak:4,label:'Point Streak',emoji:'',desc:'games with a point',recentVals:[1,2,1,1],threshold:1,avgDuring:'1.25',seasAvg:'1.00'}];st.streakFilter='all';st.picksView='streaks';switchTab('picks')`);
const streakFilters=app.innerHTML.match(/<div class="streak-filters">([\s\S]*?)<\/div><div class="cards-grid">/);
assert.ok(streakFilters,'Streak cards must be siblings of the filters');
assert.equal((streakFilters[1].match(/<button\b/g)||[]).length,3);
assert.equal((streakFilters[1].match(/<\/button>/g)||[]).length,3);
assert.doesNotMatch(streakFilters[1],/<div\b/);
assert.match(streakFilters[1],/aria-pressed="true"/);
run(`setStreakFilter('gol')`);assert.match(app.innerHTML,/No active streaks/);
run(`getStreaks=originalStreaks;st.streakFilter='all';st.picksView='shortlist'`);
// A small named fixture exercises refresh success/failure without touching Sheets.
run(`fixture={Tonights_Skaters:[{player_name:'Test Skater',team_abbr:'BOS',opp_abbr_tonight:'NYR'}],Skater_Game_Logs:[{player_name:'Test Skater',game_date:'2026-10-06',PTS:1}],Tonights_Goalies:[{player_name:'Test Goalie',team_abbr:'NYR',opp_abbr_tonight:'BOS'}],Goalie_Game_Logs:[{player_name:'Test Goalie',game_date:'2026-10-06',SV:20}],Slate_Status:[{SLATE_DATE:easternTodayISO(),GAME_COUNT:1,PROP_COUNT:0}]};fetchSheet=async name=>fixture[name]||[];st.mode='goalie';st.player='Test Goalie';st.metric='SV';st.line='22.5';st.activeTab='gamelog';st.oppFilter='BOS'`);
async function refresh(){run('loadAllData()');await new Promise(resolve=>setImmediate(resolve));}
(async()=>{
  await refresh();
  assert.equal(run('st.player'),'Test Goalie');assert.equal(run('st.mode'),'goalie');assert.equal(run('st.line'),'22.5');assert.equal(run('st.activeTab'),'gamelog');assert.equal(run('st.oppFilter'),'BOS');
  run(`fetchSheet=async()=>{throw Error('offline')}`);await refresh();
  assert.equal(run('st.gTonight.length'),1);assert.match(run('st.refreshError'),/Refresh failed/);assert.equal(run('st.refreshing'),false);
  run(`fetchSheet=async name=>name==='Slate_Status'?[{SLATE_DATE:easternTodayISO(),GAME_COUNT:0}]:fixture[name]||[]`);await refresh();
  assert.equal(run('st.tonight.length'),0);assert.equal(run('st.gTonight.length'),0);assert.equal(run('st.props.length'),0);
  run(`st.tonight=[{player_name:"Test Player",team_abbr:"BOS",opp_abbr_tonight:"NYR",SLATE_DATE:easternTodayISO(),COMMENCE_TIME:new Date(Date.now()+3600000).toISOString()}];st.gTonight=[];
    st.gameLogs=[1,2,3].map((n)=>({player_name:"Test Player",player_id:1,game_date:easternTodayISO(),SEASON_ID:rrSeason(),GAME_TYPE:2,PTS:n,TOI:'20:30'}));
    st.gameLogs.push({player_name:"Test Player",game_date:'2026-03-01',GAME_TYPE:2,SEASON_ID:'20252026',PTS:100});
    st.props=[{PLAYER_NAME:"Test Player",METRIC:"PTS",DK_LINE:2,OVER_ODDS:150,UNDER_ODDS:-200,REFERENCE_BOOK:'book',LAST_UPDATED:easternTodayISO()+' 12:00'}];
    st.dataVersion++;resetDerived();st.picksView='shortlist';switchTab('picks')`);
  assert.match(app.innerHTML,/TONIGHT'S RESEARCH BOARD/);
  assert.doesNotMatch(app.innerHTML,/Same-Stat Parlays/);
  assert.equal(run("rrScopeRows(st.gameLogs).length"),3);
  assert.equal(run("rrAvg(rrScopeRows(st.gameLogs),'PTS')"),2);
  assert.equal(run("rrToi('20:30')"),20.5);
  assert.equal(run("rrCounts(st.gameLogs.slice(0,3),'PTS',2,'UNDER').pushes"),1);
  assert.equal(run('rrShortlistRows().length'),2);
  run(`rrHandle('trayToggle',rrLegKey(rrShortlistRows()[0]),0,{});rrPersist()`);
  assert.equal(run('rrState().tray.length'),1);
  run('st.research=null;rrState()');
  assert.equal(run('rrState().tray.length'),1);
  const capturedOdds=run('rrState().tray[0].odds');
  run(`st.props[0].OVER_ODDS=250;st.props[0].UNDER_ODDS=-300;st.dataVersion++;resetDerived()`);
  assert.equal(run('rrState().tray[0].odds'),capturedOdds);
  run(`rrHandle('builderGame','BOS|NYR',0,{});rrHandle('builderAdd',rrLegKey(rrBuilderCandidates()[0]),0,{});rrHandle('builderAdd',rrLegKey(rrBuilderCandidates()[1]),0,{})`);
  assert.equal(run('rrState().builderLegs.length'),1);
  assert.match(run('rrState().notice'),/already selected/);
  run(`rrHandle('builderSave','',0,{})`);
  assert.equal(run('rrState().savedEntries.length'),1);
  run(`rrState().builderLegs[0].start=Date.now()-1000;rrHandle('builderSave','',0,{})`);
  assert.equal(run('rrState().savedEntries.length'),1);
  run(`st.tonight[0].COMMENCE_TIME=new Date(Date.now()-1000).toISOString();st.dataVersion++;resetDerived()`);
  assert.equal(run('rrShortlistRows().length'),0);
  assert.equal(run("rrProfit({HIT:'YES',PICK_ODDS:150,PICK_BOOK:'book'})"),1.5);
  assert.equal(run("rrProfit({HIT:'YES'})"),null);
  run(`st.research.lookupPlayer='Test Player';st.research.lookupMode='skater';switchTab('lookup')`);
  assert.match(app.innerHTML,/THE PLAYER LIBRARY/);
  assert.match(app.innerHTML,/Current|current/);
  assert.equal(run('rrCompletedLog(st.gameLogs[0])'),false);
  run(`st.schedule=[{GAME_DATE:easternTodayISO(),GAME_ID:'123',GAME_STATE:'FINAL'}];st.gameLogs[0].gameId='123'`);
  assert.equal(run('rrCompletedLog(st.gameLogs[0])'),true);
  run(`switchTab('leaders')`);assert.match(app.innerHTML,/Daily leaders/);
  run(`switchTab('stats')`);assert.match(app.innerHTML,/Actual ROI/);
  console.log('PASS: eight views, refresh recovery, season isolation, pushes, TOI, shortlist, tray price persistence, builder conflicts/locks, lookup, leaders and actual returns');
})().catch(e=>{console.error(e);process.exitCode=1});
