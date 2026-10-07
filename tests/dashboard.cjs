const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const path=require('node:path');
const app={innerHTML:''};
const element={addEventListener(){},value:'',focus(){}};
const ctx=vm.createContext({console:{log(){},warn(){},error(){}},Date,Map,Set,Math,Number,String,Array,JSON,Promise,parseFloat,parseInt,isNaN,Infinity,AbortSignal,
  localStorage:{getItem(){return null},setItem(){}},
  document:{hidden:false,activeElement:null,body:{classList:{toggle(){}}},getElementById(id){return id==='app'?app:element},querySelectorAll(){return []},addEventListener(){}},
  window:{scrollTo(){}},setInterval(){},fetch:async()=>{throw Error('unexpected network')}});
let code=readFileSync(path.join(__dirname,'../app.js'),'utf8');
code=code.slice(0,code.lastIndexOf('\nloadAllData();'));
// Replace only the transport binding in the isolated test context.
code=code.replace('const fetchSheet=', 'let fetchSheet=');
vm.runInContext(code,ctx);
const run=s=>vm.runInContext(s,ctx);
run(`st.loading=false;st.loadedAt='1:00 PM';st.slateStatus={SLATE_DATE:easternTodayISO(),GAME_COUNT:0};render()`);
assert.match(app.innerHTML,/No games scheduled today/);
for(const view of ['dashboard','gamelog','picks','stats','entry','method']){
  run(`switchTab('${view}')`);assert.match(app.innerHTML,/NHL DFS Dashboard/);
}
run(`st.slateStatus={SLATE_DATE:'2025-01-01',GAME_COUNT:1};render()`);
assert.match(app.innerHTML,/Older snapshot/);
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
  console.log('PASS: six views, stale/empty slate, refresh selection, failure recovery and no-game rollover');
})().catch(e=>{console.error(e);process.exitCode=1});
