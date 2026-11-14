
// ══════════════════════════════════════════════════
// 🏒 NHL DFS DASHBOARD — Built on NBA/MLB architecture
// ══════════════════════════════════════════════════
const SHEET_ID="1OpER7aRmMFWyxMONdg_LqiyQ47cA3dWRSR8UEQH8FIM";

const GAME_ENTRY_TIER_WEIGHTS = { SMASH: 1.5, STRONG: 1.0, LEAN: 0.7 };
const GAME_ENTRY_DEFAULT_WLB = 0.42;
const GAME_ENTRY_MIN_LEGS = 1;
const GAME_ENTRY_MAX_LEGS = 8;
const GAME_ENTRY_DEFAULT_LEGS = 5;
const GAME_ENTRY_MAX_LEGS_PER_PLAYER = 3;
const S_METRICS=["G","A","PTS","SOG","BLK","HITS","PPP","FOW","TOI","PIM","UD_FP"];
const G_METRICS=["SV","GA","SV_PCT","W","SO","UD_FP","TOI"];

const COMBO_STATS={"SOG+BLK":["SOG","BLK"],"BLK+HITS":["BLK","HITS"]};
function getMetricVal(g,m){if(COMBO_STATS[m])return COMBO_STATS[m].reduce((s,k)=>s+toNum(g[k]),0);return m==="TOI"?(rrToi(g[m])||0):toNum(g[m])}
function getRollingVal(row,prefix,m){if(COMBO_STATS[m])return COMBO_STATS[m].reduce((s,k)=>s+toNum(row[`${prefix}${k}`]),0);return toNum(row[`${prefix}${m}`])}

let st={
  tonight:[],gameLogs:[],splits:[],
  gTonight:[],gGameLogs:[],gSplits:[],
  picks:[],props:[],
  pickPerformance:[],pickPerformanceSnaps:[],statsTimeWindow:"last_30d",gameEntry:{selectedGame:null,legCount:GAME_ENTRY_DEFAULT_LEGS,entry:null},
  mode:"skater",player:"",metric:"PTS",line:"",
  activeTab:"dashboard",oppFilter:"",
  picksView:"shortlist",propsMetric:"ALL",propsSearch:"",
  streakFilter:"all",dueFilter:"all",drafted:new Set(),slipLegs:"3",parlayStat:"PTS",
  loading:true,error:null,loadedAt:null,latestPickDate:"",pickGuard:null,dataVersion:0,theme:(localStorage.getItem("nhl-dashboard-theme")||"dark")
};
function applyTheme(){document.body.classList.toggle("light-theme",st.theme==="light")}
function toggleTheme(){st.theme=st.theme==="light"?"dark":"light";localStorage.setItem("nhl-dashboard-theme",st.theme);applyTheme();render()}
let derived={
  version:-1,
  skaterLogsByName:new Map(),
  goalieLogsByName:new Map(),
  propsByName:new Map(),
  tonightByName:new Map(),
  gTonightByName:new Map(),
  latestPickDate:"",
  latestPickRun:0,
  picksByNameLatest:new Map(),
  memo:new Map()
};
function resetDerived(){
  derived={version:-1,skaterLogsByName:new Map(),goalieLogsByName:new Map(),propsByName:new Map(),tonightByName:new Map(),gTonightByName:new Map(),latestPickDate:"",latestPickRun:0,picksByNameLatest:new Map(),memo:new Map()};
}
function indexRowsByName(rows,nameKey){
  const map=new Map();
  for(const row of rows||[]){
    const key=normalizePlayerName(row?.[nameKey]);
    if(!key)continue;
    if(!map.has(key))map.set(key,[]);
    map.get(key).push(row);
  }
  return map;
}
function ensureDerived(){
  if(derived.version===st.dataVersion)return;
  resetDerived();
  derived.version=st.dataVersion;
  derived.skaterLogsByName=indexRowsByName(st.gameLogs,"player_name");
  derived.goalieLogsByName=indexRowsByName(st.gGameLogs,"player_name");
  for(const logs of derived.skaterLogsByName.values())logs.sort((a,b)=>(b.game_date||"").localeCompare(a.game_date||""));
  for(const logs of derived.goalieLogsByName.values())logs.sort((a,b)=>(b.game_date||"").localeCompare(a.game_date||""));
  derived.propsByName=indexRowsByName(st.props,"PLAYER_NAME");
  for(const row of st.tonight||[]){
    const key=normalizePlayerName(row?.player_name);
    if(key&&!derived.tonightByName.has(key))derived.tonightByName.set(key,row);
  }
  for(const row of st.gTonight||[]){
    const key=normalizePlayerName(row?.player_name);
    if(key&&!derived.gTonightByName.has(key))derived.gTonightByName.set(key,row);
  }
  const allDates=[...new Set((st.picks||[]).map(p=>normalizeDate(p.DATE||p.date)).filter(Boolean))].sort();
  derived.latestPickDate=allDates.length?allDates[allDates.length-1]:"";
  const sameDatePicks=(st.picks||[]).filter(p=>normalizeDate(p.DATE||p.date)===derived.latestPickDate);
  derived.latestPickRun=sameDatePicks.length?Math.max(...sameDatePicks.map(p=>toNum(p.RUN_NUMBER||p.run_number||0))):0;
  for(const p of st.picks||[]){
    const key=normalizePlayerName(p?.player);
    if(!key)continue;
    if(normalizeDate(p.DATE||p.date)===derived.latestPickDate && toNum(p.RUN_NUMBER||p.run_number||0)===derived.latestPickRun && !derived.picksByNameLatest.has(key))derived.picksByNameLatest.set(key,p);
  }
}
function getMemo(key,build){
  ensureDerived();
  const memoKey=`${st.dataVersion}:${key}`;
  if(derived.memo.has(memoKey))return derived.memo.get(memoKey);
  const value=build();
  derived.memo.set(memoKey,value);
  return value;
}
function getPlayerLogs(name,isG){
  ensureDerived();
  return ((isG?derived.goalieLogsByName:derived.skaterLogsByName).get(normalizePlayerName(name)))||[];
}
function getTonightPlayerRow(name,isG){
  ensureDerived();
  return ((isG?derived.gTonightByName:derived.tonightByName).get(normalizePlayerName(name)))||null;
}

const toNum=v=>parseFloat(v)||0;
const barColor=(v,l)=>!l?"var(--accent)":v>l?"#22c55e":v===l?"var(--ink-muted)":"#ef4444";
const avgColor=(v,l)=>!l?"var(--accent)":v>=l?"var(--accent)":"#f97316";
const esc=s=>{if(s===null||s===undefined)return"";return String(s).replace(/[&<>'"]/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[t]))};
const fmtOdds=v=>{if(!v&&v!==0)return"—";v=parseInt(v);return v>0?`+${v}`:`${v}`};
function impliedProb(odds){if(!odds&&odds!==0)return null;const o=parseInt(odds);if(isNaN(o))return null;return o<0?Math.abs(o)/(Math.abs(o)+100):100/(o+100)}
function cleanName(v){return String(v||"").trim()}
function normalizeDate(val){
  const s=String(val||"").trim();
  if(!s)return"";
  if(/^\d{4}-\d{2}-\d{2}$/.test(s))return s;
  const mdy=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if(mdy){const[,m,d,y]=mdy;return`${y}-${String(m).padStart(2,"0")}-${String(d).padStart(2,"0")}`;}
  const parsed=new Date(s);
  if(!Number.isNaN(parsed.getTime()))return`${parsed.getFullYear()}-${String(parsed.getMonth()+1).padStart(2,"0")}-${String(parsed.getDate()).padStart(2,"0")}`;
  return s;
}
function fmtNowEastern(){
  return new Date().toLocaleString("en-US",{timeZone:"America/New_York",month:"2-digit",day:"2-digit",year:"numeric",hour:"numeric",minute:"2-digit",hour12:true}).replace(",","") + " ET";
}
function parseStartMs(v){
  if(!v)return null;
  const d=new Date(v);
  return Number.isNaN(d.getTime())?null:d.getTime();
}
function getRowStartMs(row){
  if(!row)return null;
  return parseStartMs(row.COMMENCE_TIME||row.commence_time||row.GAME_TIME||row.game_time||row.START_TIME||row.start_time);
}
function getLockInfo(name,isG){
  const row=getTonightPlayerRow(name,!!isG)||{};
  const startMs=getRowStartMs(row);
  return{started:!!(startMs&&Date.now()>=startMs),startMs,row};
}
function lockBadge(name,isG){
  return getLockInfo(name,isG).started?`<span class="locked-badge">🔒 LOCKED</span>`:"";
}
function isTruthyFlag(v){return v===true||v===1||String(v||"").trim().toUpperCase()==="TRUE"}
function getSampleFlags(name,isG){
  const row=getTonightPlayerRow(name,!!isG)||{};
  return{
    returning:isTruthyFlag(row.RETURNING??row.returning),
    limited:isTruthyFlag(row.LIMITED_SAMPLE??row.limited_sample??row.limitedSample),
    l5Games:toNum(row.L5_GAMES_PLAYED??row.l5_games_played),
    gamesLast7d:toNum(row.GAMES_LAST_7D??row.games_last_7d)
  };
}
function riskBadges(name,isG,{showLimited=true}={}){
  const f=getSampleFlags(name,isG);const out=[];
  if(f.returning)out.push(`<span class="risk-badge risk-returning">⚠️ RETURNING</span>`);
  if(showLimited&&f.limited)out.push(`<span class="risk-badge risk-limited">⚠️ LIMITED SAMPLE</span>`);
  return out.join("");
}
function normalizePlayerName(name){
  return cleanName(name).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[’'`\.]/g,'').replace(/[^a-z0-9]+/g,' ').replace(/\s+/g,' ').trim();
}
function normalizePropMetric(metric){return String(metric||"").trim().toUpperCase().replace(/\s+/g,"")}
function normalizeLeanText(lean){const l=String(lean||"").trim().toUpperCase();return l==="FADE"?"UNDER":l}
function normalizeConfidence(conf){const v=cleanName(conf).toUpperCase();return v==="SMASH"||v==="STRONG"||v==="LEAN"?v:"LEAN"}
function aiAgreesWithBet(aiPick,betLikeObject){
  if(!aiPick||!betLikeObject)return false;
  return normalizePlayerName(aiPick.player||aiPick.PLAYER||aiPick.Player||aiPick.PLAYER_NAME)===normalizePlayerName(betLikeObject.name||betLikeObject.player)
    && normalizePropMetric(aiPick.prop_type)===normalizePropMetric(betLikeObject.metric||betLikeObject.prop_type)
    && normalizeLeanText(aiPick.lean)===normalizeLeanText(betLikeObject.lean);
}
function easternTodayISO(){return new Date().toLocaleDateString('en-CA',{timeZone:'America/New_York'})}
function getPickGuard(latestDate,picksCount){
  const tonightCount=st.mode==="goalie"?st.gTonight.length:st.tonight.length;
  if(!tonightCount)return null;
  const today=easternTodayISO();
  if(!picksCount){
    return st.props.length
      ?{level:"warn",text:"Engine issue — AI picks are missing or incomplete for tonight's slate."}
      :{level:"info",text:"No AI picks for tonight yet. Props may still be loading."};
  }
  if(latestDate&&latestDate!==today)return{level:"warn",text:`Showing stale AI picks from ${latestDate}. Engine may be incomplete.`};
  if(picksCount<3&&st.props.length>=10)return{level:"warn",text:`AI picks look incomplete for tonight (${picksCount} loaded).`};
  return null;
}
function renderPickGuard(guard){
  if(!guard)return"";
  const border=guard.level==="warn"?"#f59e0b":"var(--ink-muted)";
  const text=guard.level==="warn"?"#fcd34d":"#cbd5e1";
  return `<div class="card" style="margin:0 16px 12px;border-left:3px solid ${border}"><div style="font-size:11px;color:${text};font-weight:600">${esc(guard.text)}</div></div>`;
}

// ═══ DATA CLEANING ═══
function cleanRows(rows){if(!rows||!rows.length)return rows;return rows.map(row=>{const clean={};for(const[k,v]of Object.entries(row)){const ck=k.replace(/^\uFEFF/,'').replace(/[\u200B-\u200D\uFEFF]/g,'').trim();clean[ck]=v}return clean})}
function normalizeKeys(rows){
  if(!rows||!rows.length)return rows;
  return rows.map(row=>{
    const clean={};
    for(const[k,v]of Object.entries(row)){
      const trimmed=String(k||"")
        .replace(/^\uFEFF/,'')
        .replace(/[\u200B-\u200D\uFEFF]/g,'')
        .trim();
      clean[trimmed]=v;
    }
    return clean;
  });
}

let _restoring=false;
function saveFocus(){const el=document.activeElement;if(el&&el.id)return{id:el.id,pos:el.selectionStart,val:el.value};return null}
function restoreFocus(f){if(!f)return;const el=document.getElementById(f.id);if(el){_restoring=true;el.focus();if(f.val!==undefined)el.value=f.val;if(el.setSelectionRange&&f.pos!==undefined)try{el.setSelectionRange(f.pos,f.pos)}catch(e){}_restoring=false}}

function firstValidPlayer(arr){
  if(!arr||!arr.length)return "";
  for(let i=0;i<Math.min(arr.length,30);i++){const n=arr[i]?.player_name;if(n&&String(n).trim().length>1)return String(n).trim()}
  return "";
}

const fetchSheet=(name)=>new Promise((res,rej)=>{
  fetch(`https://docs.google.com/spreadsheets/d/${SHEET_ID}/gviz/tq?tqx=out:csv&headers=1&sheet=${encodeURIComponent(name)}&cacheBust=${Date.now()}`,{cache:"no-store",signal:AbortSignal.timeout(25000)})
  .then(r=>{if(!r.ok)throw new Error(r.status);return r.text()})
  .then(t=>{Papa.parse(t,{header:true,skipEmptyLines:true,dynamicTyping:true,complete:r=>{console.log(`✅ ${name}: ${r.data.length} rows`);res(r.data)},error:rej})})
  .catch(rej);
});

function hasLogs(name,isG){return getPlayerLogs(name,isG).length>0}
function getProps(name){if(!name||!st.props.length)return[];ensureDerived();return derived.propsByName.get(normalizePlayerName(name))||[]}
function getLatestPickDate(){ensureDerived();return derived.latestPickDate}
function getLatestPickRun(){ensureDerived();return derived.latestPickRun}
function getPick(name){if(!name||!st.picks.length)return null;ensureDerived();return derived.picksByNameLatest.get(normalizePlayerName(name))||null}

function switchTab(t){st.activeTab=t;render()}
function switchMode(m){st.mode=m;st.metric=m==="goalie"?"SV":"PTS";st.line="";st.oppFilter="";const src=m==="goalie"?st.gTonight:st.tonight;st.player=firstValidPlayer(src);render()}
function switchPicksView(v){st.picksView=v;render()}
function setPropsMetric(m){st.propsMetric=m;render()}
function setStreakFilter(f){st.streakFilter=f;render()}
function setDueFilter(f){st.dueFilter=f;render()}
function setSlipLegs(n){st.slipLegs=n;render()}
function setParlayStat(s){st.parlayStat=s;render()}
function toggleDrafted(n){if(st.drafted.has(n))st.drafted.delete(n);else st.drafted.add(n);render()}
function resetDrafted(){st.drafted.clear();render()}
function pickDashPlayer(name){st.player=name;st.oppFilter="";render()}
function streakToDash(name){
  const s=st.tonight.find(t=>normalizePlayerName(t.player_name)===normalizePlayerName(name));
  const g=st.gTonight.find(t=>normalizePlayerName(t.player_name)===normalizePlayerName(name));
  if(s){st.mode="skater";st.metric="PTS";st.player=s.player_name}
  else if(g){st.mode="goalie";st.metric="SV";st.player=g.player_name}
  st.activeTab="dashboard";render();
}
function playerLink(name,label=""){const n=cleanName(label||name||"");return `<span class="player-link" onclick="event.stopPropagation();streakToDash('${esc(name)}')">${esc(n)}</span>`}

// ═══ +EV ENGINE ═══
function getHitRate(name,metric,line,isG){
  const logs=rrScopeRows(getPlayerLogs(name,isG),Number(rrRoster(name,isG).GAME_TYPE)===3?"playoffs":"current");
  if(logs.length<3)return null;const ln=parseFloat(line);if(isNaN(ln))return null;
  const combo=COMBO_STATS[metric];
  let over=0,under=0,push=0;
  for(const g of logs){
    const val=combo?combo.reduce((s,k)=>s+toNum(g[k]),0):toNum(g[metric]);
    if(val>ln)over++;
    else if(val<ln)under++;
    else push++;
  }
  const nonPush=over+under;
  return{
    overRate:nonPush?over/nonPush:0,
    underRate:nonPush?under/nonPush:0,
    pushRate:logs.length?push/logs.length:0,
    over,under,push,nonPush,total:logs.length
  };
}
function isGoalieProp(m){return["SV","GA","SV_PCT","G_SO","G_W"].includes(m)||(m||"").startsWith("G_")}
function propToLogCol(m){const map={G_SV:"SV",G_GA:"GA",G_SO:"SO",G_W:"W"};return map[m]||m}
function getBestBets(){
  return getMemo("bestBets",()=>{if(!st.props.length)return[];const bets=[];
  for(const p of st.props){const name=p.PLAYER_NAME;if(!name)continue;const metric=p.METRIC;const line=parseFloat(p.DK_LINE);if(isNaN(line))continue;
    if(metric==="BLK"||metric==="HITS")continue;
    const overO=parseInt(p.OVER_ODDS),underO=parseInt(p.UNDER_ODDS);if(isNaN(overO)&&isNaN(underO))continue;
    const logCol=propToLogCol(metric);const isG=isGoalieProp(metric);
    if(!rrIsCurrent(rrRoster(name,isG))||String(p.LAST_UPDATED||"").slice(0,10)!==easternTodayISO())continue;
    const hr=getHitRate(name,logCol,line,isG);if(!hr||hr.total<3||!hr.nonPush)continue;
    const oIP=impliedProb(overO),uIP=impliedProb(underO);let oE=null,uE=null;
    if(oIP!==null)oE=hr.overRate-oIP;if(uIP!==null)uE=hr.underRate-uIP;
    let lean,edge,odds,ip,hitRate;
    if(oE!==null&&uE!==null){if(oE>=uE){lean="OVER";edge=oE;odds=overO;ip=oIP;hitRate=hr.overRate}else{lean="UNDER";edge=uE;odds=underO;ip=uIP;hitRate=hr.underRate}}
    else if(oE!==null){lean="OVER";edge=oE;odds=overO;ip=oIP;hitRate=hr.overRate}else{lean="UNDER";edge=uE;odds=underO;ip=uIP;hitRate=hr.underRate}
    if(edge===null)continue;
    const pT=getTonightPlayerRow(name,false)||getTonightPlayerRow(name,true)||{};const flags=getSampleFlags(name,isG);
    bets.push({name,metric,line,lean,edge,odds,impliedProb:ip,hitRate,hits:lean==="OVER"?hr.over:hr.under,total:hr.nonPush,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:pT.opp_goalie_name||"",goalieStatus:pT.opp_goalie_status||"",starterStatus:pT.starter_status||"",moneyline:pT.MONEYLINE||"",gameTotal:pT.GAME_TOTAL||"",impliedTotal:pT.IMPLIED_TOTAL||"",dkLine:p.DK_LINE,overOdds:p.OVER_ODDS,underOdds:p.UNDER_ODDS,prop:p,isG,teamSlot:`${pT.team_abbr||""}${isG?":G":":S"}`,returning:flags.returning,limitedSample:flags.limited});
  }bets.sort((a,b)=>(a.returning===b.returning?b.edge-a.edge:(a.returning?1:-1)));return bets;});
}

// ═══ SMART SLIPS ═══
function getConvictionLegs(){
  const SLIP_WORTHY=new Set(["PTS","G","A","SOG","BLK","PPP","SV","GA","G_W","UD_FP"]);
  const bets=getBestBets().filter(b=>b.edge>0&&!b.returning&&!getLockInfo(b.name,b.isG).started).filter(b=>{
    if(!SLIP_WORTHY.has(b.metric))return false;
    if(b.lean==="UNDER"&&parseFloat(b.dkLine)<=0.5)return false;
    return true;
  });if(!bets.length)return[];
  const latestDate=getLatestPickDate();
  const latestRun=getLatestPickRun();
  const aiMap=new Map();st.picks.filter(pk=>normalizeDate(pk.DATE||pk.date)===latestDate&&toNum(pk.RUN_NUMBER||pk.run_number||0)===latestRun).forEach(pk=>{if(pk.player)aiMap.set(normalizePlayerName(pk.player),pk)});
  const streakMap=new Map();try{getStreaks().forEach(s=>{streakMap.set(`${normalizePlayerName(s.player)}|${normalizePropMetric(s.stat)}`,s)})}catch(e){}
  const legs=[];
  for(const b of bets){const nl=normalizePlayerName(b.name);const evScore=Math.min(b.edge*40,10);let aiScore=0;
    const ai=aiMap.get(nl);let aiAgrees=false;let aiConflictLevel="",aiDisagreementText="";if(ai){const c=normalizeConfidence(ai.confidence);const aiLean=normalizeLeanText(ai.lean);const aiMetric=normalizePropMetric(ai.prop_type);const betMetric=normalizePropMetric(b.metric);const aiComps=COMBO_STATS[aiMetric]||[aiMetric];const betComps=COMBO_STATS[betMetric]||[betMetric];const metricsRelated=betComps.some(x=>aiComps.includes(x))||aiComps.some(x=>betComps.includes(x));if(metricsRelated&&aiLean&&aiLean!==b.lean){aiConflictLevel=aiMetric===betMetric?"strong":"soft";aiDisagreementText=aiMetric===betMetric?`AI says ${aiLean} ${aiMetric}`:`AI leans ${aiLean} ${aiMetric}`;aiScore-=c==="SMASH"?2.5:c==="STRONG"?1.5:0.75}else if(aiAgreesWithBet(ai,b)){aiScore=c==="SMASH"?6:4;aiAgrees=true}}
    let streakScore=0;const sk=streakMap.get(`${nl}|${normalizePropMetric(propToLogCol(b.metric))}`);if(sk){streakScore=sk.streak>=7?3:sk.streak>=5?2:1}
    const reliScore=Math.min(b.total/10,2),hrScore=b.hitRate>=0.8?2:b.hitRate>=0.65?1:0;
    const conviction=evScore+aiScore+streakScore+reliScore+hrScore;
    let signals=[];if(aiAgrees){const c=normalizeConfidence(ai.confidence);signals.push(c==="SMASH"?"🤖 SMASH":"🤖 AI")}
    if(aiConflictLevel==="strong")signals.push("⚠️ AI conflict");else if(aiConflictLevel==="soft")signals.push("⚠️ AI cross-check");
    if(sk)signals.push(`🔥 ${sk.streak}G`);if(b.edge>=0.15)signals.push("💎 Elite");else if(b.edge>=0.08)signals.push("📈 Strong");
    if(b.hitRate>=0.8)signals.push(`✅ ${(b.hitRate*100).toFixed(0)}%`);
    legs.push({...b,conviction,signals,hasAI:aiAgrees,hasAIConflict:!!aiConflictLevel,aiConflictLevel,aiDisagreementText,hasStreak:!!sk,teamSlot:b.teamSlot||`${b.team}${b.isG?":G":":S"}`,gameTotal:toNum(b.gameTotal),lineMateEligible:!b.isG});
  }legs.sort((a,b)=>b.conviction-a.conviction);return legs;
}
function generateSlips(legs,n){
  if(legs.length<n)return[];const slips=[];const maxIter=n<=3?500:300;
  const seen=new Set();const dedupedLegs=legs.filter(l=>{const k=l.name.toLowerCase();if(seen.has(k))return false;seen.add(k);return true;});const pool=dedupedLegs.slice(0,n<=3?15:n<=4?18:20);
  function gen(s,cur,used,tc){if(cur.length===n){let sc=cur.reduce((s,l)=>s+l.conviction,0);const slipTags=[];for(let i=0;i<cur.length;i++){for(let j=i+1;j<cur.length;j++){const a=cur[i],b=cur[j];if(a.lineMateEligible&&b.lineMateEligible&&a.team===b.team&&Math.max(toNum(a.gameTotal),toNum(b.gameTotal))>=6){sc*=1.15;slipTags.push("🔗 LINE MATES")}}}slips.push({legs:cur.slice(),score:sc,avgEdge:cur.reduce((s,l)=>s+l.edge,0)/n,avgHitRate:cur.reduce((s,l)=>s+l.hitRate,0)/n,teams:[...new Set(cur.map(l=>l.teamSlot||l.team))],slipTags:[...new Set(slipTags)]});return}
    for(let i=s;i<pool.length&&slips.length<maxIter;i++){const l=pool[i];if(used.has(l.name))continue;const slot=l.teamSlot||l.team;const t=tc.get(slot)||0;if(t>=2)continue;used.add(l.name);tc.set(slot,t+1);cur.push(l);gen(i+1,cur,used,tc);cur.pop();used.delete(l.name);tc.set(slot,t)}}
  gen(0,[],new Set(),new Map());slips.sort((a,b)=>b.score-a.score);
  const MAX_SLIPS=8;let selected=[];
  for(let cap=2;cap<=MAX_SLIPS;cap++){
    selected=[];const playerUsageCount=new Map();
    for(const slip of slips){
      if(selected.length>=MAX_SLIPS)break;
      const overUsed=slip.legs.some(l=>(playerUsageCount.get(l.name.toLowerCase())||0)>=cap);
      if(overUsed)continue;
      selected.push(slip);
      slip.legs.forEach(l=>{const k=l.name.toLowerCase();playerUsageCount.set(k,(playerUsageCount.get(k)||0)+1);});
    }
    if(selected.length>=MAX_SLIPS)break;
  }
  return selected.slice(0,MAX_SLIPS);
}
function getSmartSlips(){return getMemo("smartSlips",()=>{const legs=getConvictionLegs();return{legs,slips3:generateSlips(legs,3),slips4:generateSlips(legs,4),slips5:generateSlips(legs,5)}})}

// ═══ STREAKS ═══
function getStreakHeat(s){if(s>=10)return{l:"INFERNO",c:"#ef4444",cls:"inferno"};if(s>=5)return{l:"ON FIRE",c:"#ff6b35",cls:"fire"};if(s>=3)return{l:"HOT",c:"#ffaa00",cls:"hot"};return{l:"WARM",c:"#ffd966",cls:"warm"}}
function miniChart(vals,thr){const mx=Math.max(...vals,thr+1);return vals.slice().reverse().map(v=>{const h=Math.max(3,(v/mx)*26);return`<div class="streak-chart-bar" style="height:${h}px;background:${v>=thr?'#22c55e':'#ef4444'};opacity:.85"></div>`}).join("")}
function getStreaks(){
  return getMemo("streaks",()=>{const streaks=[];
  const SKT=[{key:"PTS",threshold:1,label:"Point Streak",emoji:"🔥",desc:"games w/ a point"},{key:"PTS",threshold:2,label:"Multi-Point",emoji:"🔥🔥",desc:"games w/ 2+ PTS"},{key:"G",threshold:1,label:"Goal Streak",emoji:"🚨",desc:"games w/ a goal"},{key:"SOG",threshold:4,label:"Shooting",emoji:"🎯",desc:"games w/ 4+ SOG"},{key:"A",threshold:1,label:"Assist Streak",emoji:"🍎",desc:"games w/ an assist"},{key:"HITS",threshold:3,label:"Physical",emoji:"💪",desc:"games w/ 3+ HITS"},{key:"BLK",threshold:2,label:"Shot Blocker",emoji:"🛡️",desc:"games w/ 2+ BLK"},{key:"PPP",threshold:1,label:"PP Streak",emoji:"⚡",desc:"games w/ a PP point"},{key:"UD_FP",threshold:10,label:"Fantasy",emoji:"🏒",desc:"games w/ 10+ UD FP"}];
  const tNames=new Set(st.tonight.map(p=>p.player_name).filter(Boolean));
  for(const sT of SKT){for(const name of tNames){
    const logs=getPlayerLogs(name,false);
    if(logs.length<3)continue;let streak=0;
    for(const g of logs){if(toNum(g[sT.key])>=sT.threshold)streak++;else break}if(streak<3)continue;
    const pT=getTonightPlayerRow(name,false)||{};
    const rv=logs.slice(0,7).map(g=>toNum(g[sT.key]));
    const ad=(logs.slice(0,streak).reduce((s,g)=>s+toNum(g[sT.key]),0)/streak)||0;
    const sa=toNum(logs[0][`Seas_${sT.key}`]);
    const prop=st.props.find(pr=>normalizePlayerName(pr.PLAYER_NAME)===normalizePlayerName(name)&&normalizePropMetric(pr.METRIC)===normalizePropMetric(sT.key));
    streaks.push({player:name,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:pT.opp_goalie_name||"TBD",goalieStatus:pT.opp_goalie_status||"",stat:sT.key,threshold:sT.threshold,streak,label:sT.label,emoji:sT.emoji,propType:"skt",desc:sT.desc,avgDuring:ad.toFixed(2),seasAvg:sa.toFixed(2),recentVals:rv,dkLine:prop?prop.DK_LINE:null,overOdds:prop?parseInt(prop.OVER_ODDS)||null:null});
  }}
  // Goalie streaks
  const GOL=[{key:"SV",threshold:28,label:"Save Streak",emoji:"🧱",desc:"starts w/ 28+ SV"},{key:"W",threshold:1,label:"Win Streak",emoji:"👑",desc:"consecutive wins"},{key:"GA",threshold:2,label:"Lockdown",emoji:"🔒",compare:"lte",desc:"starts w/ ≤2 GA"}];
  const gNames=new Set(st.gTonight.map(p=>p.player_name).filter(Boolean));
  for(const sT of GOL){for(const name of gNames){
    const logs=getPlayerLogs(name,true);
    if(logs.length<2)continue;let streak=0;const isLte=sT.compare==="lte";
    for(const g of logs){const v=toNum(g[sT.key]);if(isLte?v<=sT.threshold:v>=sT.threshold)streak++;else break}if(streak<2)continue;
    const pT=getTonightPlayerRow(name,true)||{};
    const rv=logs.slice(0,7).map(g=>toNum(g[sT.key]));
    const ad=(logs.slice(0,streak).reduce((s,g)=>s+toNum(g[sT.key]),0)/streak)||0;
    const sa=toNum(logs[0][`Seas_${sT.key}`])||0;
    const prop=st.props.find(pr=>normalizePlayerName(pr.PLAYER_NAME)===normalizePlayerName(name)&&normalizePropMetric(pr.METRIC)===normalizePropMetric(sT.key));
    streaks.push({player:name,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:"",starterStatus:pT.starter_status||"",stat:sT.key,threshold:sT.threshold,streak,label:sT.label,emoji:sT.emoji,propType:"gol",desc:sT.desc,isLte,avgDuring:ad.toFixed(2),seasAvg:sa.toFixed(2),recentVals:rv,dkLine:prop?prop.DK_LINE:null,overOdds:prop?parseInt(prop.OVER_ODDS)||null:null});
  }}
  const best={};for(const s of streaks){const k=`${s.player}|${s.stat}`;if(!best[k]||s.streak>best[k].streak||(s.streak===best[k].streak&&s.threshold>best[k].threshold))best[k]=s}
  return Object.values(best).sort((a,b)=>b.streak-a.streak);});
}

// ═══ THEY'RE DUE ═══
function getDueBoard(){
  return getMemo("dueBoard",()=>{const due=[];const tNames=new Set(st.tonight.map(p=>p.player_name).filter(Boolean));
  const stats=["PTS","G","A","SOG","BLK","HITS","PPP","UD_FP"];
  for(const name of tNames){
    const logs=getPlayerLogs(name,false);
    if(logs.length<7)continue;const pT=getTonightPlayerRow(name,false)||{};const most=pT;
    const MIN_AVG={PTS:0.5,G:0.25,A:0.35,SOG:2.0,BLK:1.0,HITS:1.5,PPP:0.2,UD_FP:4};
    for(const stat of stats){const seasAvg=toNum(most[`Seas_${stat}`]),l5Avg=toNum(most[`L5_${stat}`]);if(seasAvg<=(MIN_AVG[stat]||0))continue;
      const coldGap=(seasAvg-l5Avg)/seasAvg;if(coldGap<0.10)continue;
      let drought=0;for(const g of logs){if(toNum(g[stat])<seasAvg)drought++;else break}if(drought<2)continue;
      let matchupScore=0,matchupTags=[];
      const oppGA=toNum(pT.OPP_GA_PG);if(oppGA>=3.2){matchupScore+=3;matchupTags.push(`Leaky D (${oppGA.toFixed(1)} GA/G)`)}else if(oppGA>=2.9){matchupScore+=1.5;matchupTags.push(`Avg D (${oppGA.toFixed(1)} GA/G)`)}
      const oppPK=toNum(pT.OPP_PK_PCT);if(oppPK<78){matchupScore+=2;matchupTags.push(`Weak PK (${oppPK.toFixed(0)}%)`)}
      const gt=toNum(pT.GAME_TOTAL);if(gt>=6.5){matchupScore+=2;matchupTags.push(`High O/U: ${gt}`)}
      if(stat==="SOG"){
        if(drought>=3){matchupScore+=2.5;matchupTags.push(`Shot drought (${drought}g)`)}
        if(oppGA>=3.0){matchupScore+=1.5;matchupTags.push(`Soft goalie environment`)}
      }else if(stat==="PPP"){
        if(drought>=3){matchupScore+=2.5;matchupTags.push(`PPP drought (${drought}g)`)}
        if(oppPK<80){matchupScore+=2;matchupTags.push(`Special-teams target`)}
      }
      const prop=st.props.find(pr=>normalizePlayerName(pr.PLAYER_NAME)===normalizePlayerName(name)&&normalizePropMetric(pr.METRIC)===normalizePropMetric(stat));
      let propTag=null;if(prop)propTag={line:prop.DK_LINE,overOdds:parseInt(prop.OVER_ODDS)||null};
      const totalScore=coldGap*15+Math.min(drought*1.5,10)+matchupScore;if(totalScore<2)continue;
      const recentVals=logs.slice(0,7).map(g=>toNum(g[stat]));
      due.push({name,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:pT.opp_goalie_name||"TBD",goalieStatus:pT.opp_goalie_status||"",stat,type:"skt",seasAvg:seasAvg.toFixed(2),l5Avg:l5Avg.toFixed(2),coldGap:(coldGap*100).toFixed(0),drought,matchupScore,matchupTags,propTag,recentVals,totalScore});
  }}
  for(const name of new Set(st.gTonight.map(p=>p.player_name).filter(Boolean))){
    const logs=getPlayerLogs(name,true);
    if(logs.length<5)continue;
    const pT=getTonightPlayerRow(name,true)||{};
    const seasGA=toNum(pT.Seas_GA),l3GA=toNum(pT.L3_GA);
    if(seasGA<=0||l3GA<=0)continue;
    const bounceGap=(l3GA-seasGA)/seasGA;
    if(bounceGap<0.20)continue;
    let drought=0;for(const g of logs){if(toNum(g.GA)>seasGA)drought++;else break}
    if(drought<2)continue;
    let matchupScore=0,matchupTags=[];
    const oppITT=toNum(pT.OPP_IMPLIED_TOTAL||pT.opp_implied_total);
    if(oppITT&&oppITT<=2.8){matchupScore+=3;matchupTags.push(`Low opp total (${oppITT.toFixed(1)})`)}
    const moneyline=String(pT.MONEYLINE||"");
    if(moneyline.startsWith("-")){matchupScore+=2;matchupTags.push(`Favored bounceback spot`)}
    const totalScore=bounceGap*15+Math.min(drought*1.5,10)+matchupScore;
    if(totalScore<4)continue;
    const prop=st.props.find(pr=>normalizePlayerName(pr.PLAYER_NAME)===normalizePlayerName(name)&&normalizePropMetric(pr.METRIC)==="GA");
    let propTag=null;if(prop)propTag={line:prop.DK_LINE,overOdds:parseInt(prop.OVER_ODDS)||null};
    const recentVals=logs.slice(0,7).map(g=>toNum(g.GA));
    due.push({name,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:"",goalieStatus:pT.starter_status||"",stat:"GA",type:"gol",seasAvg:seasGA.toFixed(2),l5Avg:l3GA.toFixed(2),coldGap:(bounceGap*100).toFixed(0),drought,matchupScore,matchupTags,propTag,recentVals,totalScore});
  }
  const best={};for(const d of due){if(!best[d.name]||d.totalScore>best[d.name].totalScore)best[d.name]=d}
  return Object.values(best).sort((a,b)=>b.totalScore-a.totalScore);});
}
function dueMiniChart(vals,sa){const mx=Math.max(...vals,sa+1);return vals.slice().reverse().map(v=>{const h=Math.max(3,(v/mx)*26);return`<div class="due-chart-bar" style="height:${h}px;background:${v>=sa?'#22c55e':'var(--accent)'};opacity:.85"></div>`}).join("")}

// ═══ STAT PARLAYS ═══
function getStatParlayBoard(stat){
  return getMemo(`statParlay:${stat}`,()=>{const rows=[];const tSet=new Set([...st.tonight,...st.gTonight].map(p=>p.player_name).filter(Boolean));
  for(const p of st.props){const name=p.PLAYER_NAME;if(!name||!tSet.has(name)||p.METRIC!==stat)continue;
    const dkLine=parseFloat(p.DK_LINE);if(isNaN(dkLine))continue;
    const isG=isGoalieProp(stat);const logs=getPlayerLogs(name,isG);if(logs.length<3)continue;
    const hitsOver=logs.filter(g=>toNum(g[propToLogCol(stat)])>dkLine).length;const hitRate=hitsOver/logs.length;
    const overIP=impliedProb(parseInt(p.OVER_ODDS));const edge=overIP!==null?hitRate-overIP:0;
    const most=logs[0]||{};const seasAvg=toNum(most[`Seas_${stat}`]),l5Avg=toNum(most[`L5_${stat}`]);
    const pT=getTonightPlayerRow(name,false)||getTonightPlayerRow(name,true)||{};
    let matchupScore=0;const oppGA=toNum(pT.OPP_GA_PG);if(oppGA>=3.2)matchupScore+=2;const gt=toNum(pT.GAME_TOTAL);if(gt>=6.5)matchupScore+=2;
    const score=hitRate*40+Math.max(edge,0)*30+matchupScore*3+(l5Avg>seasAvg?5:0);
    rows.push({name,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:pT.opp_goalie_name||"TBD",goalieStatus:pT.opp_goalie_status||"",starterStatus:pT.starter_status||"",moneyline:pT.MONEYLINE||"",impliedTotal:pT.IMPLIED_TOTAL||"",stat,dkLine,overOdds:parseInt(p.OVER_ODDS),underOdds:parseInt(p.UNDER_ODDS),hitRate,hitsOver,total:logs.length,edge,seasAvg,l5Avg,matchupScore,score,isG});
  }rows.sort((a,b)=>b.score-a.score);return rows;});
}
function getStatParlayCombos(board,legs){
  if(board.length<legs)return[];const combos=[];const pool=board.slice(0,legs<=2?12:15);
  function gen(s,cur){if(cur.length===legs){const tc={};for(const d of cur){tc[d.team]=(tc[d.team]||0)+1;if(tc[d.team]>2)return}
    combos.push({players:cur.slice(),score:cur.reduce((s,d)=>s+d.score,0),avgHitRate:cur.reduce((s,d)=>s+d.hitRate,0)/legs,avgEdge:cur.reduce((s,d)=>s+d.edge,0)/legs,teams:[...new Set(cur.map(d=>d.team))]});return}
    for(let i=s;i<pool.length&&combos.length<300;i++){if(cur.some(c=>c.name===pool[i].name))continue;cur.push(pool[i]);gen(i+1,cur);cur.pop()}}
  gen(0,[]);combos.sort((a,b)=>b.score-a.score);return combos.slice(0,8);
}

// ═══ SNIPERS (volume shooters, prop-independent) ═══
function getSnipers(){
  return getMemo("snipers",()=>{const snipers=[];const tNames=new Set(st.tonight.map(p=>p.player_name).filter(Boolean));
  for(const name of tNames){
    const logs=getPlayerLogs(name,false);
    if(logs.length<5)continue;
    const pT=getTonightPlayerRow(name,false)||{};
    const hits3=logs.filter(g=>toNum(g.SOG)>=3).length;
    const hits5=logs.filter(g=>toNum(g.SOG)>=5).length;
    const hits7=logs.filter(g=>toNum(g.SOG)>=7).length;
    const hitRate3=hits3/logs.length,hitRate5=hits5/logs.length,hitRate7=hits7/logs.length;
    if(hitRate3<0.5)continue;
    const most=logs[0]||{};const seasAvg=toNum(most.Seas_SOG),l5Avg=toNum(most.L5_SOG);const trend=l5Avg-seasAvg;
    const prop=st.props.find(pr=>normalizePlayerName(pr.PLAYER_NAME)===normalizePlayerName(name)&&normalizePropMetric(pr.METRIC)==="SOG");
    const dkProp=prop?{line:prop.DK_LINE,over:parseInt(prop.OVER_ODDS)||null}:null;
    const score=hitRate3*40+hitRate5*30+hitRate7*20+Math.min(seasAvg,6)*3+(trend>0?5:0);
    snipers.push({name,team:pT.team_abbr||"",opp:pT.opp_abbr_tonight||"",goalie:pT.opp_goalie_name||"TBD",goalieStatus:pT.opp_goalie_status||"",hits3,hits5,hits7,total:logs.length,hitRate3,hitRate5,hitRate7,seasAvg,l5Avg,trend,dkProp,score});
  }
  snipers.sort((a,b)=>b.score-a.score);return snipers;});
}
function sniperToDash(name){
  const s=st.tonight.find(t=>normalizePlayerName(t.player_name)===normalizePlayerName(name));
  if(s){st.mode="skater";st.metric="SOG";st.player=s.player_name;st.activeTab="dashboard";render()}
}

function getConvergenceBoard(){
  return getMemo("convergenceBoard",()=>{const board=new Map();
  const latestDate=getLatestPickDate();
  const latestRun=getLatestPickRun();
  const allowed=new Set(st.picks.filter(p=>normalizeDate(p.DATE||p.date)===latestDate&&toNum(p.RUN_NUMBER||p.run_number||0)===latestRun).map(p=>normalizePlayerName(p.player)).filter(Boolean));
  const add=(name,source,boost=0,meta={})=>{
    if(!name)return;
    const key=normalizePlayerName(name);
    if(allowed.size && !allowed.has(key))return;
    if(!board.has(key))board.set(key,{name,sources:new Set(),score:0,team:meta.team||"",opp:meta.opp||"",detail:""});
    const row=board.get(key);
    row.sources.add(source);
    row.score+=boost;
    if(!row.team&&meta.team)row.team=meta.team;
    if(!row.opp&&meta.opp)row.opp=meta.opp;
    if(!row.detail&&meta.detail)row.detail=meta.detail;
  };
  const bestBetMap=new Map();
  getBestBets().filter(b=>b.edge>0).slice(0,20).forEach(b=>{bestBetMap.set(normalizePlayerName(b.name),b);add(b.name,"Best Bets",2+Math.min(b.edge*20,3),{team:b.team,opp:b.opp,detail:`${b.lean} ${b.metric} ${b.dkLine}`});});
  st.picks.filter(p=>normalizeDate(p.DATE||p.date)===latestDate&&toNum(p.RUN_NUMBER||p.run_number||0)===latestRun).forEach(pk=>{
    const bestBet=bestBetMap.get(normalizePlayerName(pk.player));
    if(!aiAgreesWithBet(pk,bestBet))return;
    const conf=normalizeConfidence(pk.confidence);
    add(pk.player,"AI",conf==="SMASH"?4:conf==="STRONG"?3:2,{detail:`${pk.lean||""} ${pk.prop_type||""} ${pk.line||""}`.trim()});
  });
  getStreaks().slice(0,20).forEach(s=>add(s.player,"Streaks",s.streak>=7?3:s.streak>=5?2.5:2,{team:s.team,opp:s.opp,detail:`${s.streak}G ${s.stat}`}));
  getDueBoard().slice(0,20).forEach(d=>add(d.name,"Due",1.5+Math.min((d.totalScore||0)/12,2),{team:d.team,opp:d.opp,detail:`Due ${d.stat}`}));
  getSnipers().slice(0,15).forEach(s=>add(s.name,"Snipers",1.5+(s.hitRate3||0)*2,{team:s.team,opp:s.opp,detail:`${(s.hitRate3*100).toFixed(0)}% on 3+ SOG`}));
  return [...board.values()].map(r=>({...r,sourceCount:r.sources.size,sourceList:[...r.sources]})).filter(r=>r.sourceCount>=2).sort((a,b)=>b.sourceCount-a.sourceCount||b.score-a.score).slice(0,5);});
}

function renderConvergenceHTML(){
  const board=getConvergenceBoard();
  if(!board.length)return"";
  const top=board[0];
  return `<div class="convergence-shell"><details class="convergence-details"><summary class="convergence-toggle"><div class="convergence-title"><div style="color:var(--accent);font-size:13px;font-weight:700">🏆 Players of the Day</div><div style="color:var(--ink-muted);font-size:10px">Cross-tab convergence from Best Bets, AI, Streaks, Due, and Snipers.</div></div><div class="convergence-kpis"><span class="convergence-chip"><strong style="color:var(--accent)">${top.sourceCount}</strong> top</span><span class="convergence-chip"><strong>${board.length}</strong> 2+</span><span class="convergence-chip"><strong style="color:#22c55e">${board.filter(p=>p.sourceCount>=3).length}</strong> 3+</span></div></summary><div class="convergence-body"><div class="bet-summary">
    <div class="bs-card"><div class="bs-val" style="color:var(--accent)">${top.sourceCount}</div><div class="bs-lbl">TOP SIGNALS</div></div>
    <div class="bs-card"><div class="bs-val">${board.length}</div><div class="bs-lbl">2+ SURFACES</div></div>
    <div class="bs-card"><div class="bs-val" style="color:#22c55e">${board.filter(p=>p.sourceCount>=3).length}</div><div class="bs-lbl">3+ MATCHES</div></div>
  </div>
  <div class="cards-grid">
    ${board.map((p,i)=>`<div class="bet-card ${i===0?"elite":"mid"}" style="cursor:pointer;border-color:${i===0?"var(--accent)":"var(--border-1)"}" onclick="streakToDash('${esc(p.name)}')"><div class="bet-left"><div class="bet-name">${i===0?"🏆 ":""}${playerLink(p.name)}</div><div class="bet-meta">${esc(p.team||"")} ${p.opp?`vs ${esc(p.opp)}`:""}</div>${p.detail?`<div class="bet-prop"><span class="prop-metric" style="font-size:10px">Lead</span><span style="color:#cbd5e1;font-size:11px">${esc(p.detail)}</span></div>`:""}<div class="draft-tags" style="margin-top:6px">${p.sourceList.map(s=>`<span class="draft-tag" style="background:#0f203822;color:${s==="AI"?"#22c55e":s==="Best Bets"?"var(--accent)":s==="Streaks"?"#ffaa00":s==="Due"?"var(--accent-soft)":"#f59726"}">${esc(s)}</span>`).join("")}</div></div><div class="bet-right"><div class="bet-edge pos">${p.sourceCount}x</div><div class="bet-sub">signals</div></div></div>`).join("")}
  </div></div></details></div>`;
}

// ═══ DRAFT BOARD ═══
function getDraftBoard(){
  return getMemo("draftBoard",()=>{const board=[];const aiMap=new Map();st.picks.forEach(p=>{if(p.player)aiMap.set(normalizePlayerName(p.player),p)});
  for(const p of st.tonight){const name=p.player_name;if(!name)continue;
    const logs=getPlayerLogs(name,false);
    if(!logs.length)continue;const most=logs[0]||{};
    const sG=toNum(most.Seas_G),sA=toNum(most.Seas_A),sSOG=toNum(most.Seas_SOG),sBLK=toNum(most.Seas_BLK),sHITS=toNum(most.Seas_HITS),sPPP=toNum(most.Seas_PPP);
    const projUD=toNum(most.Seas_UD_FP)||(sG*8.5+sA*5+sSOG*1.5+sBLK*1.3);
    const l5G=toNum(most.L5_G),l5A=toNum(most.L5_A),l5SOG=toNum(most.L5_SOG),l5BLK=toNum(most.L5_BLK);
    const l5UD=toNum(most.L5_UD_FP)||(l5G*8.5+l5A*5+l5SOG*1.5+l5BLK*1.3);
    const ai=aiMap.get(normalizePlayerName(name)),isSmash=ai&&normalizeConfidence(ai.confidence)==="SMASH";
    let pos="W";const posRaw=(p.position||"").toUpperCase();
    if(posRaw.includes("C"))pos="C";else if(posRaw.includes("D"))pos="D";else if(posRaw.includes("G"))pos="G";
    const flags=getSampleFlags(name,false);
    board.push({name,team:p.team_abbr||"",opp:p.opp_abbr_tonight||"",goalie:p.opp_goalie_name||"TBD",goalieStatus:p.opp_goalie_status||"",projUD:projUD.toFixed(1),l5UD:l5UD.toFixed(1),sG,sA,sSOG,sBLK,sPPP,isSmash,isGoalie:false,pos,returning:flags.returning,limitedSample:flags.limited});
  }
  for(const p of st.gTonight){const name=p.player_name;if(!name)continue;
    const logs=getPlayerLogs(name,true);
    if(!logs.length)continue;const most=logs[0]||{};
    const sSV=toNum(most.Seas_SV),sGA=toNum(most.Seas_GA),sW=toNum(most.Seas_W);
    const projUD=toNum(most.Seas_UD_FP)||(sW*6+sSV*0.7+sGA*-3);
    const l5UD=toNum(most.L5_UD_FP)||(toNum(most.L5_W)*6+toNum(most.L5_SV)*0.7+toNum(most.L5_GA)*-3);
    const ai=aiMap.get(normalizePlayerName(name)),isSmash=ai&&normalizeConfidence(ai.confidence)==="SMASH";
    const flags=getSampleFlags(name,true);
    board.push({name,team:p.team_abbr||"",opp:p.opp_abbr_tonight||"",goalie:"",projUD:projUD.toFixed(1),l5UD:l5UD.toFixed(1),sSV,sGA,sW,isSmash,isGoalie:true,pos:"G",returning:flags.returning,limitedSample:flags.limited});
  }
  board.sort((a,b)=>parseFloat(b.projUD)-parseFloat(a.projUD));return board;});
}

function getDraftStacks(){
  return getMemo("draftStacks",()=>{
    const board=getDraftBoard().filter(p=>!p.isGoalie);
    const byName=new Map(board.map(p=>[normalizePlayerName(p.name),p]));
    const byTeamGame=new Map();
    for(const row of st.tonight||[]){
      const key=normalizePlayerName(row.player_name);
      if(!key||!byName.has(key))continue;
      const team=row.team_abbr||"";
      const opp=row.opp_abbr_tonight||"";
      const gameKey=[team,opp].sort().join("|");
      if(!byTeamGame.has(team))byTeamGame.set(team,[]);
      byTeamGame.get(team).push({...row,__gameKey:gameKey});
    }
    const seen=new Set();const pairs=[];
    for(const [team,rows] of byTeamGame.entries()){
      for(let i=0;i<rows.length;i++){
        for(let j=i+1;j<rows.length;j++){
          const ra=rows[i],rb=rows[j];
          const a=byName.get(normalizePlayerName(ra.player_name));
          const b=byName.get(normalizePlayerName(rb.player_name));
          if(!a||!b)continue;
          const key=[normalizePlayerName(a.name),normalizePlayerName(b.name)].sort().join("|");
          if(seen.has(key))continue;
          seen.add(key);
          const gameTotal=Math.max(toNum(ra.GAME_TOTAL),toNum(rb.GAME_TOTAL));
          const oppGA=Math.max(toNum(ra.OPP_GA_PG),toNum(rb.OPP_GA_PG));
          const proj=toNum(a.projUD)+toNum(b.projUD);
          const score=proj+(gameTotal>=6?4:0)+(oppGA>=3.2?4:oppGA>=2.9?2:0)+(toNum(a.sPPP)>=0.5&&toNum(b.sPPP)>=0.5?2:0);
          const tags=[];
          if(gameTotal>=6)tags.push("⚡ HIGH TOTAL");
          if(oppGA>=3.0)tags.push("🎯 STACK TARGET");
          tags.push("🔗 CORRELATED");
          pairs.push({players:[a,b],score,combinedProj:proj.toFixed(1),team,opp:a.opp,goalie:ra.opp_goalie_name||"TBD",gameTotal,oppGA,tags});
        }
      }
    }
    return pairs.sort((a,b)=>b.score-a.score).slice(0,10);
  });
}

function getDraftStackTagMap(){
  return getMemo("draftStackTags",()=>{
    const map=new Map();
    getDraftStacks().forEach(stack=>{
      stack.players.forEach(p=>{
        const key=normalizePlayerName(p.name);
        if(!map.has(key))map.set(key,new Set());
        stack.tags.forEach(tag=>map.get(key).add(tag));
      });
    });
    return map;
  });
}

// ═══ MAIN RENDER ═══

const STATS_WINDOWS=[['last_7d','Last 7 days'],['last_30d','Last 30 days'],['last_90d','Last 90 days'],['all_time','All time']];
const STATS_BREAK_EVEN=0.524;

function entryField(row,keys){for(const k of keys){if(row&&row[k]!==undefined&&row[k]!==null&&String(row[k]).trim()!=='')return row[k]}return ''}
function entryMetric(m){return typeof normalizePropMetric==='function'?normalizePropMetric(m):(typeof normalizePropName==='function'?normalizePropName(m):String(m||'').trim().toUpperCase())}
function entryTeam(row){return String(entryField(row,['team_abbr','TEAM_ABBREVIATION','TEAM','team','teamAbbr','TEAM_ABBR'])||'').trim().toUpperCase()}
function entryOpp(row){return String(entryField(row,['opp_abbr_tonight','TONIGHT_OPP','OPP','opponent','OPPONENT','opp'])||'').trim().toUpperCase()}
function entryPlayer(row){return cleanName(entryField(row,['player_name','PLAYER_NAME','PLAYER','player','Player']))}
function entryPairId(a,b){a=String(a||'').trim().toUpperCase();b=String(b||'').trim().toUpperCase();if(!a||!b)return '';return [a,b].sort().join('|')}
function entryGameFromText(game){const s=String(game||'').trim();const m=s.match(/\b([A-Z]{2,4})\s*(?:@|vs\.?|VS)\s*([A-Z]{2,4})\b/);if(!m)return null;return {id:entryPairId(m[1],m[2]),label:s,teams:[m[1],m[2]]}}
function entryTodayISO(){const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).reduce((a,p)=>(a[p.type]=p.value,a),{});return `${parts.year}-${parts.month}-${parts.day}`}
function entryDateISO(v){if(v===undefined||v===null||String(v).trim()==='')return '';const raw=String(v).trim();if(/^\d{4}-\d{2}-\d{2}$/.test(raw))return raw;const md=raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);if(md)return `${md[3]}-${md[1].padStart(2,"0")}-${md[2].padStart(2,"0")}`;const n=Number(raw);if(Number.isFinite(n)&&n>20000&&n<90000){const d=new Date(Math.round((n-25569)*86400*1000));return d.toISOString().slice(0,10)}const d=new Date(raw);if(Number.isNaN(d.getTime()))return typeof normalizeDate==='function'?normalizeDate(raw):'';const parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d).reduce((a,p)=>(a[p.type]=p.value,a),{});return `${parts.year}-${parts.month}-${parts.day}`}
function entryRowDate(row){return entryField(row,['DATE','date','GAME_DATE','game_date','Date','GAME_DAY','game_day','start_date','START_DATE','commence_time','COMMENCE_TIME','game_time','GAME_TIME','start_time','START_TIME'])}
function entryRowIsToday(row){const raw=entryRowDate(row);const iso=entryDateISO(raw);return !iso||iso===entryTodayISO()}
function entryStartValue(row){return entryField(row,['commence_time','COMMENCE_TIME','game_time','GAME_TIME','start_time','START_TIME','GAME_DATE','game_date','DATE','date'])}
function entryStartMs(v){if(v===undefined||v===null||String(v).trim()==='')return Number.POSITIVE_INFINITY;const d=new Date(String(v));return Number.isNaN(d.getTime())?Number.POSITIVE_INFINITY:d.getTime()}
function entryDisplayTime(v){const ms=entryStartMs(v);if(!Number.isFinite(ms))return '';return new Date(ms).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York',timeZoneName:'short'})}
function entryAllPicks(){return Array.isArray(st.picks)&&st.picks.length?st.picks:(Array.isArray(st.aiPicks)?st.aiPicks:[])}
function entryRosterRows(){const rows=[];const add=(arr,type)=>{(arr||[]).forEach(r=>{const player=entryPlayer(r),team=entryTeam(r),opp=entryOpp(r);if(player&&team&&opp)rows.push({player,team,opp,type,row:r,id:entryPairId(team,opp)})})};add(st.tonight,'player');add(st.pTonight,'player');add(st.gTonight,'player');return rows}
function getEntryGames(){return getMemo('gameEntry:games',()=>{const byId=new Map();const add=(id,label,teams=[],time='')=>{if(!id)return;const sortTime=entryStartMs(time);const timeText=entryDisplayTime(time);const baseLabel=label||teams.join(' vs ');const displayLabel=timeText?`${baseLabel} — ${timeText}`:baseLabel;if(!byId.has(id))byId.set(id,{id,label:displayLabel,baseLabel,teams,time,sortTime});else{const g=byId.get(id);if((baseLabel||'').includes('@')){g.baseLabel=baseLabel;g.label=timeText?`${baseLabel} — ${timeText}`:baseLabel}if(Number.isFinite(sortTime)&&!Number.isFinite(g.sortTime)){g.time=time;g.sortTime=sortTime;g.label=timeText?`${g.baseLabel} — ${timeText}`:g.baseLabel}}};entryLatestPicks().forEach(p=>{const g=entryGameFromText(p.game||p.GAME||p.matchup||p.MATCHUP);if(g)add(g.id,g.label,g.teams,entryStartValue(p))});entryRosterRows().forEach(r=>{if(entryRowIsToday(r.row))add(r.id,`${r.team} vs ${r.opp}`,[r.team,r.opp],entryStartValue(r.row))});(st.schedule||[]).forEach(r=>{if(!entryRowIsToday(r))return;const away=String(entryField(r,['away_team','AWAY_TEAM','away','AWAY','away_abbr','away_team_abbr'])||'').toUpperCase();const home=String(entryField(r,['home_team','HOME_TEAM','home','HOME','home_abbr','home_team_abbr'])||'').toUpperCase();const t=entryStartValue(r);if(away&&home)add(entryPairId(away,home),`${away} @ ${home}`,[away,home],t)});return [...byId.values()].sort((a,b)=>(a.sortTime-b.sortTime)||a.baseLabel.localeCompare(b.baseLabel))})}
function setGameEntryGame(gameId){st.gameEntry=st.gameEntry||{selectedGame:null,legCount:GAME_ENTRY_DEFAULT_LEGS,entry:null};st.gameEntry.selectedGame=gameId;st.gameEntry.entry=null;st.dataVersion++;render()}
function setGameEntryLegs(n){st.gameEntry=st.gameEntry||{selectedGame:null,legCount:GAME_ENTRY_DEFAULT_LEGS,entry:null};st.gameEntry.legCount=Math.max(GAME_ENTRY_MIN_LEGS,Math.min(GAME_ENTRY_MAX_LEGS,parseInt(n)||GAME_ENTRY_DEFAULT_LEGS));st.gameEntry.entry=null;st.dataVersion++;render()}
function entryLatestPicks(){const rows=entryAllPicks().filter(p=>entryDateISO(p.DATE||p.date)===entryTodayISO());const maxRun=Math.max(0,...rows.map(p=>toNum(p.RUN_NUMBER||p.run_number||0)));return maxRun?rows.filter(p=>toNum(p.RUN_NUMBER||p.run_number||0)===maxRun):rows}
function entryFindProp(player,metric,line){const pn=normalizePlayerName(player),mn=entryMetric(metric),lt=String(line??'').trim();return (st.props||[]).find(p=>normalizePlayerName(p.PLAYER_NAME)===pn&&entryMetric(p.METRIC)===mn&&(lt===''||String(p.DK_LINE??'').trim()===lt))||(st.props||[]).find(p=>normalizePlayerName(p.PLAYER_NAME)===pn&&entryMetric(p.METRIC)===mn)||null}
function entryBookName(book){const k=String(book||'').toLowerCase();return {draftkings:'DK',fanduel:'FD',betmgm:'BetMGM',espnbet:'ESPN BET',caesars:'Caesars'}[k]||String(book||'')}
function entryBestBook(prop,lean){if(!prop)return null;const side=String(lean||'OVER').toUpperCase()==='UNDER'?'UNDER':'OVER';const book=prop[`BEST_${side}_BOOK`];const odds=prop[`BEST_${side}_ODDS`];if(!book||odds==='')return null;const delta=Number(prop[`BEST_${side}_DELTA_PP`]);return {book:String(book),odds,delta:Number.isFinite(delta)?delta:null,isDK:String(book).toLowerCase()==='draftkings'}}
function renderEntryBestBookLine(prop,lean){const b=entryBestBook(prop,lean);if(!b)return '';const color=b.isDK?'var(--ink-muted)':'var(--accent)';const delta=b.delta!==null&&!b.isDK&&Math.abs(b.delta)>0.05?` (${b.delta>0?'+':''}${b.delta.toFixed(1)}pp${b.delta>=3?' ⭐':''})`:'';return `<div style="font-size:10px;color:${color};font-weight:800;margin-top:3px">🏪 Best @ ${entryBookName(b.book)} ${entryFmtOdds(b.odds)}${delta}</div>`}
function entryBestBookKey(leg){const b=entryBestBook(leg.prop,leg.lean);return b?entryBookName(b.book):''}
function entryPerfWLB(metric){const mn=entryMetric(metric);const row=(st.pickPerformance||[]).find(r=>String(r.DIMENSION_TYPE||r.dimension_type||'').toLowerCase()==='prop_type_norm'&&entryMetric(r.DIMENSION_VALUE||r.dimension_value)===mn&&String(r.TIME_WINDOW||r.time_window||'')==='all_time'&&String(r.MIN_SAMPLE_FLAG||r.min_sample_flag||'').toUpperCase()==='TRUE');const v=row?Number(row.WILSON_LOWER_95||row.wilson_lower_95):NaN;return Number.isFinite(v)?v:GAME_ENTRY_DEFAULT_WLB}
function buildCandidatePool(gameId){const games=getEntryGames();const game=games.find(g=>g.id===gameId);if(!game)return {game:null,candidates:[]};const roster=entryRosterRows().filter(r=>r.id===gameId);const playerNames=new Set(roster.map(r=>normalizePlayerName(r.player)));const candidates=[];const seenAI=new Set();entryLatestPicks().forEach(p=>{const g=entryGameFromText(p.game||p.GAME||p.matchup||p.MATCHUP);let inGame=g&&g.id===gameId;if(!inGame&&playerNames.has(normalizePlayerName(p.player)))inGame=true;if(!inGame)return;const prop=entryFindProp(p.player,p.prop_type,p.line);if(!prop)return;const lean=String(p.lean||'OVER').toUpperCase()==='UNDER'?'UNDER':'OVER';const odds=lean==='OVER'?prop.OVER_ODDS:prop.UNDER_ODDS;if(!odds)return;const key=`${normalizePlayerName(p.player)}|${entryMetric(p.prop_type)}|${lean}`;seenAI.add(key);candidates.push({player:p.player,prop_type:entryMetric(p.prop_type),line:p.line||prop.DK_LINE,lean,odds,ai_tier:normalizeConfidence(p.confidence),source:'AI',prop})});(st.props||[]).forEach(prop=>{if(!playerNames.has(normalizePlayerName(prop.PLAYER_NAME)))return;['OVER','UNDER'].forEach(lean=>{const odds=lean==='OVER'?prop.OVER_ODDS:prop.UNDER_ODDS;if(!odds)return;const key=`${normalizePlayerName(prop.PLAYER_NAME)}|${entryMetric(prop.METRIC)}|${lean}`;if(seenAI.has(key))return;candidates.push({player:prop.PLAYER_NAME,prop_type:entryMetric(prop.METRIC),line:prop.DK_LINE,lean,odds,ai_tier:'LEAN',source:'DK',prop})})});return {game,candidates}}
function scoreCandidate(c){const tier=normalizeConfidence(c.ai_tier||'LEAN');const tierWeight=GAME_ENTRY_TIER_WEIGHTS[tier]||GAME_ENTRY_TIER_WEIGHTS.LEAN;const wlb=entryPerfWLB(c.prop_type);return {...c,ai_tier:tier,tier_weight:tierWeight,wlb,leg_score:tierWeight*wlb}}
function selectTopN(candidates,n){const sorted=candidates.map(scoreCandidate).sort((a,b)=>b.leg_score-a.leg_score);const used=new Set(),perPlayer=new Map(),out=[];for(const c of sorted){const playerKey=normalizePlayerName(c.player),key=`${playerKey}|${entryMetric(c.prop_type)}`;if(used.has(key))continue;if((perPlayer.get(playerKey)||0)>=GAME_ENTRY_MAX_LEGS_PER_PLAYER)continue;used.add(key);perPlayer.set(playerKey,(perPlayer.get(playerKey)||0)+1);out.push(c);if(out.length>=n)break}return out}
function entryAmericanToDecimal(odds){const o=Number(String(odds).replace(/[^0-9+\-.]/g,''));if(!Number.isFinite(o)||o===0)return 1;return o>0?1+o/100:1+100/Math.abs(o)}
function entryDecimalToAmerican(dec){if(!Number.isFinite(dec)||dec<=1)return 0;return dec>=2?Math.round((dec-1)*100):-Math.round(100/(dec-1))}
function entryFmtOdds(odds){if(typeof fmtOdds==='function')return fmtOdds(odds);const o=Number(odds);return Number.isFinite(o)?(o>0?`+${o}`:`${o}`):String(odds||'—')}
function calculateParlayMath(legs){const decimal=legs.reduce((p,l)=>p*entryAmericanToDecimal(l.odds),1);return {decimal,american:entryDecimalToAmerican(decimal),return10:decimal*10,profit10:(decimal*10)-10}}
function buildGameEntry(){const ge=st.gameEntry||{};if(!ge.selectedGame)return null;const {game,candidates}=buildCandidatePool(ge.selectedGame);if(!game)return null;const requested=ge.legCount||GAME_ENTRY_DEFAULT_LEGS;const legs=selectTopN(candidates,requested);const math=calculateParlayMath(legs);return {game,requested,legs,candidates,math,score:legs.reduce((s,l)=>s+l.leg_score,0)}}
function renderGameSelector(games){if(!games.length)return `<div class="section"><div class="card"><div class="card-title">TONIGHT'S GAMES</div><div class="empty" style="padding:24px;text-align:center">No games scheduled tonight.</div></div></div>`;const sel=st.gameEntry?.selectedGame;return `<div class="section"><div class="card"><div class="card-title">TONIGHT'S GAMES</div><div style="display:grid;gap:8px;margin-top:10px">${games.map(g=>`<button onclick='setGameEntryGame(${JSON.stringify(g.id)})' style="text-align:left;border:1px solid ${sel===g.id?'var(--accent)':'#334155'};background:${sel===g.id?'#38bdf822':'transparent'};color:${sel===g.id?'var(--accent)':'inherit'};border-radius:8px;padding:10px 12px;font-weight:800;cursor:pointer">${esc(g.label)}${g.time?` <span style="opacity:.75;font-size:11px">— ${esc(g.time)}</span>`:''}</button>`).join('')}</div></div></div>`}
function renderLegCountSelector(){const cur=st.gameEntry?.legCount||GAME_ENTRY_DEFAULT_LEGS;return `<div class="section"><div class="card"><div class="card-title">LEGS</div><div style="display:flex;flex-wrap:wrap;gap:6px;margin:10px 0">${Array.from({length:8},(_,i)=>i+1).map(n=>`<button onclick="setGameEntryLegs(${n})" style="border:1px solid ${cur===n?'var(--accent)':'#334155'};background:${cur===n?'var(--accent)':'transparent'};color:${cur===n?'#07130b':'inherit'};border-radius:999px;padding:7px 12px;font-weight:900;cursor:pointer">${n}</button>`).join('')}</div><div style="font-size:11px;color:var(--ink-muted)">Underdog Pick'em supports 2-8 legs. 1 leg is a straight bet (informational only).</div></div></div>`}
function renderEntry(entry){if(!entry)return '';if(!entry.candidates.length)return `<div class="section"><div class="card"><div class="card-title">🎟️ ENTRY</div><div class="empty" style="padding:24px;text-align:center">No props available for this game yet.</div></div></div>`;if(!entry.legs.length)return `<div class="section"><div class="card"><div class="card-title">🎟️ ENTRY</div><div class="empty" style="padding:24px;text-align:center">No usable odds for this game yet.</div></div></div>`;const odds=entry.math.american;const oddsText=odds>0?`+${odds}`:`${odds}`;const books=[...new Set(entry.legs.map(entryBestBookKey).filter(Boolean))];const warning=books.length>=2?`<div style="margin-top:12px;background:#f59e0b14;border:1px solid #f59e0b55;color:#fbbf24;border-radius:8px;padding:8px;font-size:11px">⚠️ Cross-book: legs split across ${books.join(', ')}. Single-book parlay may price differently.</div>`:'';const shortage=entry.legs.length<entry.requested?`<div style="margin-top:8px;color:#fbbf24;font-size:11px">Only ${entry.legs.length} legs available (you requested ${entry.requested}).</div>`:'';return `<div class="section"><div class="card"><div class="card-title">🎟️ ENTRY — ${esc(entry.game.label)} · ${entry.legs.length} legs</div><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0"><div class="stat-box"><div class="val">${oddsText}</div><div class="lbl">Combined</div></div><div class="stat-box"><div class="val">$${entry.math.return10.toFixed(0)}</div><div class="lbl">$10 return</div></div><div class="stat-box"><div class="val">${entry.score.toFixed(2)}</div><div class="lbl">Score</div></div></div>${shortage}<div style="height:1px;background:#334155;margin:12px 0"></div>${entry.legs.map((l,i)=>`<div style="padding:10px 0;border-bottom:1px solid #263238"><div style="display:flex;justify-content:space-between;gap:8px"><div style="font-weight:900">${i+1}. ${typeof playerLink==='function'?playerLink(l.player,l.prop_type,l.line):esc(l.player)} — ${l.prop_type} ${l.lean} ${l.line}</div><div style="font-weight:900;color:${l.lean==='OVER'?'#22c55e':'#ef4444'}">${entryFmtOdds(l.odds)}</div></div><div style="font-size:11px;color:var(--ink-muted);margin-top:4px">Why: ${l.ai_tier} × ${l.prop_type} WLB ${l.wlb.toFixed(2)} = ${l.leg_score.toFixed(2)} · ${l.source}</div>${renderEntryBestBookLine(l.prop,l.lean)}</div>`).join('')}${warning}<button onclick="copyEntryToClipboard()" style="margin-top:14px;border:1px solid var(--accent);background:#38bdf822;color:var(--accent);border-radius:8px;padding:10px 12px;font-weight:900;cursor:pointer;width:100%">${window.__entryCopied?'✓ Copied':'📋 Copy entry'}</button></div></div>`}
function renderGameEntryView(){st.gameEntry=st.gameEntry||{selectedGame:null,legCount:GAME_ENTRY_DEFAULT_LEGS,entry:null};const games=getEntryGames();let html=renderGameSelector(games);if(st.gameEntry.selectedGame){html+=renderLegCountSelector();html+=renderEntry(buildGameEntry())}return html}
function entryCopyText(entry){const odds=entry.math.american;const oddsText=odds>0?`+${odds}`:`${odds}`;return `${entry.game.label} — ${entry.legs.length}-leg entry\n${entry.legs.map((l,i)=>`${i+1}. ${l.player} - ${l.prop_type} ${l.lean} ${l.line}`).join('\n')}\nCombined ${oddsText} | $10 → $${entry.math.return10.toFixed(0)}\nBuilt: ${new Date().toLocaleString()}`}
function copyEntryToClipboard(){const entry=buildGameEntry();if(!entry)return;const text=entryCopyText(entry);if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(()=>{window.__entryCopied=true;render();setTimeout(()=>{window.__entryCopied=false;render()},1200)}).catch(()=>entryShowCopyFallback(text))}else entryShowCopyFallback(text)}
function entryShowCopyFallback(text){window.__entryCopied=false;const box=document.createElement('textarea');box.value=text;box.style.position='fixed';box.style.left='10px';box.style.bottom='10px';box.style.width='320px';box.style.height='160px';box.style.zIndex='9999';document.body.appendChild(box);box.focus();box.select()}

function setStatsTimeWindow(w){st.statsTimeWindow=w;render()}
function statField(row,name){return row?.[name]??row?.[name.toLowerCase()]??row?.[name.toUpperCase()]??''}
function statNum(row,name){return toNum(statField(row,name))}
function statBool(row,name){const v=String(statField(row,name)).trim().toUpperCase();return v==='TRUE'||v==='YES'||v==='1'}
function statPct(v){const n=Number(v);return Number.isFinite(n)?(n*100).toFixed(1)+'%':'—'}
function statPct0(v){const n=Number(v);return Number.isFinite(n)?Math.round(n*100)+'%':'—'}
function statSigned(v){const n=Number(v);if(!Number.isFinite(n))return '—';return (n>0?'+':'')+n.toFixed(3)}
function statsRowsForWindow(rows,w){return (rows||[]).filter(r=>String(statField(r,'TIME_WINDOW'))===w)}
function getMetricsForSlice(rows,dimType,dimValue,timeWindow){return (rows||[]).find(r=>String(statField(r,'DIMENSION_TYPE'))===dimType&&String(statField(r,'DIMENSION_VALUE'))===String(dimValue)&&String(statField(r,'TIME_WINDOW'))===timeWindow)||null}
function statsWindowLabel(w){return (STATS_WINDOWS.find(x=>x[0]===w)||[])[1]||w}
function renderTimeWindowSelector(currentWindow){return `<div class="stats-strip" style="position:sticky;top:0;z-index:5;display:flex;gap:6px">${STATS_WINDOWS.map(([w,l])=>`<button class="tab-btn ${currentWindow===w?'active':''}" onclick="setStatsTimeWindow('${w}')" style="white-space:nowrap;${currentWindow===w?'background:var(--accent);color:#07110b;border-color:var(--accent);':''}">${l}</button>`).join('')}</div>`}
function detectDrifts(rows,threshold=0.10){const all=(rows||[]).filter(r=>String(statField(r,'TIME_WINDOW'))==='all_time'&&statBool(r,'MIN_SAMPLE_FLAG'));const recent=(rows||[]).filter(r=>String(statField(r,'TIME_WINDOW'))==='last_30d'&&statBool(r,'MIN_SAMPLE_FLAG'));const map=new Map(all.map(r=>[`${statField(r,'DIMENSION_TYPE')}|${statField(r,'DIMENSION_VALUE')}`,r]));return recent.map(r=>{const key=`${statField(r,'DIMENSION_TYPE')}|${statField(r,'DIMENSION_VALUE')}`;const base=map.get(key);if(!base)return null;const hr30=statNum(r,'HIT_RATE'),hrAll=statNum(base,'HIT_RATE');const delta=hr30-hrAll;if(!Number.isFinite(delta)||Math.abs(delta)<threshold)return null;return{dimension_type:statField(r,'DIMENSION_TYPE'),dimension_value:statField(r,'DIMENSION_VALUE'),hit_rate_last_30d:hr30,hit_rate_all_time:hrAll,delta,n:statNum(r,'N_PICKS_DECISIVE')}}).filter(Boolean).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta))}
function renderDriftAlerts(rows){const drifts=detectDrifts(rows);if(!drifts.length)return '';const shown=drifts.slice(0,5);return `<div style="padding:0 16px 8px"><div style="color:#fbbf24;font-size:12px;font-weight:800;margin-bottom:6px">Drift Alerts</div>${shown.map(d=>`<div class="card" style="border-color:#fbbf2444;margin-bottom:6px"><div style="font-size:12px;color:#fbbf24;font-weight:800">⚠️ DRIFT — ${esc(String(d.dimension_value||d.dimension_type))}</div><div style="font-size:11px;color:var(--ink-1);margin-top:4px">last 30d ${statPct(d.hit_rate_last_30d)} vs all-time ${statPct(d.hit_rate_all_time)} (${d.delta>0?'+':''}${Math.round(d.delta*100)}pp on n=${Math.round(d.n)})</div></div>`).join('')}${drifts.length>5?`<div style="color:var(--ink-muted);font-size:10px;padding:2px 4px">... and ${drifts.length-5} more</div>`:''}</div>`}
function renderOverallTotals(rows,w){const r=getMetricsForSlice(rows,'overall','',w);if(!r)return `<div class="empty">No overall stats for ${statsWindowLabel(w)}.</div>`;const low=!statBool(r,'MIN_SAMPLE_FLAG');return `<div class="card" style="margin:0 16px 10px;border-color:#38bdf844"><div class="card-title">OVERALL — ${statsWindowLabel(w)} ${low?'<span style="font-size:10px;color:#fbbf24">(low sample)</span>':''}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;align-items:end"><div><div style="font-size:34px;font-weight:900;color:var(--accent)">${statPct(statNum(r,'HIT_RATE'))}</div><div style="font-size:11px;color:var(--ink-muted)">Push-adjusted hit rate</div><div style="font-size:12px;color:var(--ink-1);margin-top:6px">${Math.round(statNum(r,'N_PICKS_DECISIVE'))} decisive / ${Math.round(statNum(r,'N_PICKS'))} picks</div></div><div style="text-align:right"><div style="font-size:18px;font-weight:800;color:${statNum(r,'ROI_PER_PICK')>=0?'#22c55e':'#ef4444'}">ROI/pick ${statSigned(statNum(r,'ROI_PER_PICK'))}</div><div style="font-size:11px;color:var(--ink-muted)">Flat -115 model</div></div></div></div>`}
function renderOverallCard(rows,w){
  return renderOverallTotals(rows,w)+renderPublicationEvidence(rows,w);
}
function renderPublicationEvidence(rows,w){
  const labels={VERIFIED_PREGAME_FEED:'Verified pregame feed',RECONSTRUCTED_PREGAME_FEED:'Reconstructed pregame feed',UNVERIFIED_CAPTURE:'Unverified captures',LATE_OR_UNVERIFIED:'Late or timing unverified'};
  const cohorts=statsRowsForWindow(rows,w).filter(r=>statField(r,'DIMENSION_TYPE')==='publication_cohort');
  const body=cohorts.map(r=>{
    const value=statField(r,'ACTUAL_ROI_PCT');
    const roi=value!==''&&Number.isFinite(Number(value))?Number(value).toFixed(1)+'%':'Unavailable';
    return '<p><strong>'+esc(labels[statField(r,'DIMENSION_VALUE')]||statField(r,'DIMENSION_VALUE'))+'</strong>: '+Math.round(statNum(r,'N_PICKS_DECISIVE'))+' decisive · '+statPct(statNum(r,'HIT_RATE'))+' hit rate · '+roi+' recorded-price return</p>';
  }).join('');
return '<section class="card" style="margin:0 16px 10px"><h3>Publication evidence</h3><p>Grader-computed research feed availability, not proof of viewing or predictive quality. Overall includes all eligible cohorts; repeated publications are not independent bets.</p>'+ (body||'<p>Awaiting publication cohorts from the updated grader. Historical runs may support reconstruction; direct receipts are never backfilled.</p>')+'</section>';
}
function hitBar(rate){const r=Math.max(0,Math.min(1,Number(rate)||0));const w=Math.round(r*100);const good=r>=STATS_BREAK_EVEN;return `<div style="height:7px;background:#26313a;border-radius:999px;overflow:hidden;margin-top:5px"><div style="height:100%;width:${w}%;background:${good?'#22c55e':'#ef4444'}"></div></div><div style="font-size:9px;color:var(--ink-muted);margin-top:2px">break-even 52.4%</div>`}
function renderTierBreakdown(rows,w){const tiers=['SMASH','STRONG','LEAN'];const found=tiers.map(t=>getMetricsForSlice(rows,'confidence_norm',t,w)).filter(Boolean);if(!found.length)return '';const rates=found.map(r=>statNum(r,'HIT_RATE'));const collapse=found.length>=2&&rates.some((a,i)=>rates.some((b,j)=>j>i&&Math.abs(a-b)<=0.01));return `<div style="padding:0 16px 10px"><div style="color:var(--accent);font-size:12px;font-weight:800;margin-bottom:6px">Confidence Tiers ${collapse?'<span style="color:#fbbf24;font-size:10px">⚠️ tier collapse</span>':''}</div>${tiers.map(t=>{const r=getMetricsForSlice(rows,'confidence_norm',t,w);if(!r)return '';const rate=statNum(r,'HIT_RATE');const color=t==='SMASH'?'#22c55e':t==='STRONG'?'#fbbf24':'var(--ink-muted)';return `<div class="card" style="margin-bottom:6px"><div style="display:flex;justify-content:space-between;gap:10px"><div><span style="background:${color}22;color:${color};border:1px solid ${color}55;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:800">${t}</span><div style="font-size:11px;color:var(--ink-muted);margin-top:5px">n=${Math.round(statNum(r,'N_PICKS_DECISIVE'))} · ROI/p ${statSigned(statNum(r,'ROI_PER_PICK'))}</div></div><div style="font-size:20px;font-weight:900;color:${color}">${statPct(rate)}</div></div>${hitBar(rate)}</div>`}).join('')}</div>`}
function renderLeanBreakdown(rows,w){const over=getMetricsForSlice(rows,'lean_norm','OVER',w),under=getMetricsForSlice(rows,'lean_norm','UNDER',w);if(!over&&!under)return '';let call='';if(over&&under&&statBool(over,'MIN_SAMPLE_FLAG')&&statBool(under,'MIN_SAMPLE_FLAG')){const diff=statNum(under,'HIT_RATE')-statNum(over,'HIT_RATE');if(Math.abs(diff)>=0.05)call=`<div class="card" style="border-color:#60a5fa55;margin-bottom:6px;color:#bfdbfe;font-size:11px">💡 ${diff>0?'UNDERs':'OVERs'} outperforming by ${Math.abs(diff*100).toFixed(1)}pp — consider review.</div>`}return `<div style="padding:0 16px 10px"><div style="color:var(--accent);font-size:12px;font-weight:800;margin-bottom:6px">Lean Breakdown</div>${call}${['OVER','UNDER'].map(v=>{const r=v==='OVER'?over:under;if(!r)return '';return `<div class="card" style="margin-bottom:6px"><div style="display:flex;justify-content:space-between"><div style="font-weight:800;color:var(--ink-1)">${v}<div style="font-size:11px;color:var(--ink-muted)">n=${Math.round(statNum(r,'N_PICKS_DECISIVE'))} · ROI/p ${statSigned(statNum(r,'ROI_PER_PICK'))}</div></div><div style="font-size:20px;font-weight:900;color:${statNum(r,'HIT_RATE')>=STATS_BREAK_EVEN?'#22c55e':'#ef4444'}">${statPct(statNum(r,'HIT_RATE'))}</div></div></div>`}).join('')}</div>`}
function renderCLVSummary(rows,w){const pos=getMetricsForSlice(rows,'clv_bucket','positive',w),neg=getMetricsForSlice(rows,'clv_bucket','negative',w);if(!pos&&!neg)return '';const cell=(label,r)=>`<div class="card"><div style="font-size:11px;color:var(--ink-muted);text-transform:uppercase">${label}</div><div style="font-size:20px;font-weight:900;color:${label.includes('Positive')?'#22c55e':'#ef4444'}">${r?statPct(statNum(r,'HIT_RATE')):'—'}</div><div style="font-size:11px;color:var(--ink-1)">n=${r?Math.round(statNum(r,'N_PICKS_DECISIVE')):0}</div></div>`;return `<div style="padding:0 16px 10px"><div style="color:var(--accent);font-size:12px;font-weight:800;margin-bottom:6px">CLV Summary</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px">${cell('Positive CLV',pos)}${cell('Negative CLV',neg)}</div></div>`}
function renderPropTypeList(rows,w,ranking='best',limit=5){const arr=statsRowsForWindow(rows,w).filter(r=>statField(r,'DIMENSION_TYPE')==='prop_type_norm'&&statBool(r,'MIN_SAMPLE_FLAG')).sort((a,b)=>ranking==='best'?statNum(b,'WILSON_LOWER_95')-statNum(a,'WILSON_LOWER_95'):statNum(a,'WILSON_LOWER_95')-statNum(b,'WILSON_LOWER_95')).slice(0,limit);if(!arr.length)return '';const good=ranking==='best';return `<div style="padding:0 16px 10px"><div style="color:${good?'#22c55e':'#ef4444'};font-size:12px;font-weight:800;margin-bottom:6px">${good?'Top':'Worst'} Prop Types</div><div class="card" style="padding:0;overflow:hidden"><table style="width:100%;border-collapse:collapse;font-size:11px"><thead><tr style="color:var(--ink-muted)"><th style="text-align:left;padding:8px">PROP</th><th>HIT</th><th>n</th><th>ROI/p</th><th>WLB</th></tr></thead><tbody>${arr.map(r=>`<tr style="border-top:1px solid #26313a"><td style="padding:8px;font-weight:800;color:var(--ink-1)">${esc(statField(r,'DIMENSION_VALUE'))}</td><td style="text-align:center;color:${statNum(r,'HIT_RATE')>=STATS_BREAK_EVEN?'#22c55e':'#ef4444'};font-weight:800">${statPct0(statNum(r,'HIT_RATE'))}</td><td style="text-align:center">${Math.round(statNum(r,'N_PICKS_DECISIVE'))}</td><td style="text-align:center">${statSigned(statNum(r,'ROI_PER_PICK'))}</td><td style="text-align:center">${statNum(r,'WILSON_LOWER_95').toFixed(3)}</td></tr>`).join('')}</tbody></table></div></div>`}

const MULTI_BOOK_ACCENT = "var(--accent)";
function mbField(row,name){if(!row)return "";return row[name]??row[name.toLowerCase()]??row[name.toUpperCase()]??""}
function mbBool(v){const s=String(v??"").trim().toUpperCase();return s==="TRUE"||s==="YES"||s==="1"}
function mbMetric(m){return typeof normalizePropMetric==="function"?normalizePropMetric(m):(typeof normalizePropName==="function"?normalizePropName(m):String(m||"").trim().toUpperCase())}
function formatBookName(bookKey){const k=String(bookKey||"").trim().toLowerCase();return {draftkings:"DK",fanduel:"FD",betmgm:"BetMGM",espnbet:"ESPN BET",caesars:"Caesars"}[k]||String(bookKey||"").trim()}
function findPropForPick(player,metric,line){const pn=normalizePlayerName(player),mn=mbMetric(metric),lineText=String(line??"").trim();const props=st.props||[];return props.find(p=>normalizePlayerName(p.PLAYER_NAME)===pn&&mbMetric(p.METRIC)===mn&&(lineText===""||String(p.DK_LINE??"").trim()===lineText))||props.find(p=>normalizePlayerName(p.PLAYER_NAME)===pn&&mbMetric(p.METRIC)===mn)||null}
function getBestBookForLean(prop,lean){if(!prop)return null;const side=String(lean||"OVER").toUpperCase()==="UNDER"?"UNDER":"OVER";const book=mbField(prop,`BEST_${side}_BOOK`);const odds=mbField(prop,`BEST_${side}_ODDS`);if(!book||odds==="")return null;const deltaRaw=mbField(prop,`BEST_${side}_DELTA_PP`);const delta=Number(deltaRaw);return {side,book:String(book),odds,delta:Number.isFinite(delta)?delta:null,isDK:String(book).toLowerCase()==="draftkings"}}
function renderBestBookPill(prop,lean){const b=getBestBookForLean(prop,lean);if(!b)return "";const book=formatBookName(b.book);const oddsText=typeof fmtOdds==="function"?fmtOdds(b.odds):String(b.odds);const showDelta=b.delta!==null&&Math.abs(b.delta)>0.05&&!b.isDK;const deltaText=showDelta?` <b>${b.delta>0?"+":""}${b.delta.toFixed(1)}pp</b>`:"";const star=showDelta&&b.delta>=3?" ⭐":"";const bg=b.isDK?"rgba(148,163,184,.12)":`${MULTI_BOOK_ACCENT}24`;const border=b.isDK?"rgba(148,163,184,.25)":`${MULTI_BOOK_ACCENT}88`;const color=b.isDK?"var(--ink-muted)":MULTI_BOOK_ACCENT;return `<span class="best-book-pill" title="Best ${b.side}: ${book} ${oddsText}${showDelta?` (${b.delta.toFixed(1)}pp cheaper than reference)`:""}" style="display:inline-flex;align-items:center;gap:4px;border:1px solid ${border};background:${bg};color:${color};border-radius:999px;padding:2px 7px;font-size:10px;font-weight:800;white-space:nowrap">${b.side[0]} ${book} ${oddsText}${deltaText}${star}</span>`}
function renderAltLineFlag(prop){if(!mbBool(mbField(prop,'ALT_LINE_AVAILABLE')))return "";const books=mbField(prop,'ALT_LINE_BOOKS')||"available";return `<span class="alt-line-flag" title="Alt lines: ${esc(String(books))}" style="display:inline-flex;align-items:center;border:1px solid #f59e0b66;background:#f59e0b18;color:#fbbf24;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:800;white-space:nowrap">🔀 alt</span>`}
function renderReferenceFootnote(prop){const ref=mbField(prop,'REFERENCE_BOOK');if(!ref||String(ref).toLowerCase()==='draftkings')return "";return `<span style="font-size:10px;color:#fbbf24">DK n/a — using ${formatBookName(ref)} as reference</span>`}
function renderPropBestBookBlock(prop){if(!prop)return "";const over=renderBestBookPill(prop,'OVER'),under=renderBestBookPill(prop,'UNDER'),alt=renderAltLineFlag(prop),ref=renderReferenceFootnote(prop);const top=[over,under,alt].filter(Boolean).join(" ");if(!top&&!ref)return "";return `<div class="best-book-block" style="display:flex;flex-wrap:wrap;gap:5px;margin-top:6px;align-items:center">${top}${ref?`<div style="flex-basis:100%">${ref}</div>`:""}</div>`}
function renderPropBestBookTableRow(prop,colspan=7){const block=renderPropBestBookBlock(prop);return block?`<tr class="best-book-row"><td colspan="${colspan}" style="text-align:left;padding:0 8px 8px;border-top:0">${block}</td></tr>`:""}
function renderBestBookLine(prop,lean){const b=getBestBookForLean(prop,lean);if(!b)return "";const book=formatBookName(b.book);const oddsText=typeof fmtOdds==="function"?fmtOdds(b.odds):String(b.odds);const delta=b.delta!==null&&!b.isDK&&Math.abs(b.delta)>0.05?` <span style="font-weight:800">(${b.delta>0?"+":""}${b.delta.toFixed(1)}pp vs DK${b.delta>=3?" ⭐":""})</span>`:"";const color=b.isDK?"var(--ink-muted)":MULTI_BOOK_ACCENT;return `<div class="best-book-line" style="margin-top:5px;font-size:10px;color:${color};font-weight:700">🏪 Best: ${book} @ ${oddsText}${delta}</div>`}
function bestBookKeyForLean(prop,lean){const b=getBestBookForLean(prop,lean);return b?formatBookName(b.book):""}
function renderCrossBookWarning(legs){const books=[...new Set((legs||[]).map(l=>bestBookKeyForLean(l.prop,l.lean)).filter(Boolean))];return books.length>=2?`<div class="cross-book-warning" style="margin-top:6px;font-size:10px;color:#fbbf24;background:#f59e0b14;border:1px solid #f59e0b44;border-radius:6px;padding:6px">⚠️ Best book differs across legs (${books.join(", ")}). Single-book parlay may not match leg-by-leg EV.</div>`:""}

function renderStatsView(){const w=st.statsTimeWindow||'last_30d';const rows=typeof getMemo==='function'?getMemo('statsRows:'+w,()=>st.pickPerformance||[]):(st.pickPerformance||[]);let html=renderTimeWindowSelector(w);if(!rows.length)return html+`<div class="empty" style="padding:40px 20px;text-align:center">📊 Stats unavailable — Pick Performance data will appear after the next grader run.</div>`;if(!statsRowsForWindow(rows,w).length)return html+`<div class="empty" style="padding:40px 20px;text-align:center">No Pick Performance rows for ${statsWindowLabel(w)}.</div>`;const updated=rows.map(r=>statField(r,'LAST_UPDATED')).filter(Boolean).sort().pop()||'';html+=renderDriftAlerts(rows);html+=renderOverallCard(rows,w);html+=renderTierBreakdown(rows,w);html+=renderLeanBreakdown(rows,w);html+=renderCLVSummary(rows,w);html+=renderPropTypeList(rows,w,'best');html+=renderPropTypeList(rows,w,'worst');html+=`<div class="timestamp">Data through ${esc(updated||'latest grader run')} · Updated daily after grader run</div>`;return html}

function renderDailySlate(){
  const rows=[...st.tonight,...st.gTonight];
  const status=st.slateStatus||{};
  const dates=rows.map(r=>String(r.LAST_UPDATED||"").slice(0,10)).filter(Boolean).sort();
  const snapshot=String(status.SLATE_DATE||dates.at(-1)||"");
  const stale=!!snapshot&&snapshot!==easternTodayISO();
  const games=new Map();
  for(const row of rows){
    const teams=[row.team_abbr,row.opp_abbr_tonight].filter(Boolean).sort();
    if(teams.length!==2)continue;
    const key=teams.join('-');
    if(!games.has(key))games.set(key,row);
  }
  const dateLabel=new Date().toLocaleDateString('en-US',{timeZone:'America/New_York',weekday:'long',month:'short',day:'numeric'});
  return `<section class="daily-slate" aria-label="Daily slate">
    <div class="slate-heading"><div><div class="analysis-eyebrow">THE DAILY ICE</div><h1>${dateLabel}</h1><p>${stale?`Snapshot from ${esc(snapshot)} · awaiting the next engine run`:snapshot?`${games.size} matchups · ${st.tonight.length} skaters · ${st.gTonight.length} goalies`:'Waiting for a dated slate snapshot'}</p></div><div class="slate-status ${stale?'stale':''}">${stale?'Older snapshot':'Daily updates'}<small>Sheet checked ${esc(st.loadedAt||'—')} ET</small></div></div>
    ${st.refreshError?`<div class="refresh-notice" role="status">${esc(st.refreshError)}</div>`:''}
    <div class="slate-games">${[...games.values()].map((r,i)=>{
      const ms=getRowStartMs(r);
      const label=ms?new Date(ms).toLocaleTimeString('en-US',{timeZone:'America/New_York',hour:'numeric',minute:'2-digit'})+' ET':'Time TBA';
      const away=r.home_away_tonight==='Home'?r.opp_abbr_tonight:r.team_abbr;
      const home=r.home_away_tonight==='Home'?r.team_abbr:r.opp_abbr_tonight;
      return `<button class="slate-game" data-slate-player="${esc(r.player_name)}"><span class="nhl-matchup">${nhlTeamLabel(away)} <i>@</i> ${nhlTeamLabel(home)}</span><small>${stale?'Previous slate · ':''}${label}</small></button>`;
    }).join('')||`<div class="slate-empty">${snapshot===easternTodayISO()&&Number(status.GAME_COUNT)===0?'No games scheduled today. Picks and performance history remain available.':'No player slate is available yet. Refresh after the next engine run.'}</div>`}</div>
  </section>`;
}
function renderPlayerHero(player,pT,metric,allLogs,isG){
  if(!player)return `<section class="analysis-hero"><div class="analysis-eyebrow">PLAYER ANALYSIS</div><h2>Waiting for the next slate</h2><p>Skater and goalie research will appear when the daily data is ready.</p></section>`;
  return `<section class="analysis-hero"><div class="analysis-hero-top"><div><div class="analysis-eyebrow">${isG?'GOALIE':'SKATER'} ANALYSIS</div><h2>${esc(player)}</h2><p class="nhl-matchup">${nhlTeamLabel(pT.team_abbr)} · ${esc(pT.position|| (isG?'G':'Skater'))} · ${pT.home_away_tonight==='Away'?'at':'vs'} ${nhlTeamLabel(pT.opp_abbr_tonight)}${isG?' · '+esc(pT.starter_status||'Starter unconfirmed'):''}</p></div><div class="analysis-focus"><strong>${esc(metric)}</strong><span>${allLogs.length} games in loaded history</span></div></div></section>`;
}

function render(){
  const focus=saveFocus();const app=document.getElementById("app");rrState();
  if(st.loading){app.innerHTML=`<div class="loading"><div style="font-size:32px;animation:bounce .8s ease-in-out infinite">🏒</div><div style="color:var(--ink-muted);font-size:14px">Loading dashboard...</div></div>`;return}
  if(st.error){app.innerHTML=`<div class="error">⚠️ ${esc(st.error)}<br><br><span style="color:var(--ink-muted);font-size:12px">Make sure your Google Sheet is set to "Anyone with the link can view"</span><br><button class="refresh-btn" onclick="loadAllData()">Try again</button></div>`;return}

  const isG=st.mode==="goalie";const curMetrics=isG?G_METRICS:S_METRICS;
  const {player,metric,line,activeTab,oppFilter}=st;
  const curTonight=isG?st.gTonight:st.tonight;const curLogs=isG?st.gGameLogs:st.gameLogs;const curSplits=isG?st.gSplits:st.splits;
  const lineNum=parseFloat(line)||0;
  const pT=getTonightPlayerRow(player,isG)||{};const pHasLogs=hasLogs(player,isG);
  const allLogs=getPlayerLogs(player,isG);
  const last10=[...allLogs].reverse().slice(-10);const most=pT;
  const seasAvg=getRollingVal(most,"Seas_",metric);const l5Avg=getRollingVal(most,"L5_",metric);
  const shortAvg=isG?getRollingVal(most,"L3_",metric):getRollingVal(most,"L5_",metric);
  const lastGame=getMetricVal(most,metric);const shortLbl=isG?"L3":"L5";
  const hL5=lineNum?allLogs.slice(0,5).filter(g=>getMetricVal(g,metric)>lineNum).length:null;
  const hSeas=lineNum?allLogs.filter(g=>getMetricVal(g,metric)>lineNum).length:null;
  const sRate=hSeas!==null&&allLogs.length>0?hSeas/allLogs.length:null;
  const maxLog=Math.max(...last10.map(g=>getMetricVal(g,metric)),lineNum||0,1);
  const metricOpts=curMetrics.map(m=>`<option value="${m}" ${m===metric?"selected":""}>${m}</option>`).join("");
  const bars=last10.map(g=>{const v=getMetricVal(g,metric);const h=Math.max(4,(v/maxLog)*80);return`<div class="bar-wrap"><div class="bar-val">${v}</div><div class="bar" style="height:${h}px;background:${barColor(v,lineNum)}"></div><div class="bar-date">${(g.game_date||"").slice(5)}</div><div class="bar-date" style="color:var(--accent-soft);margin-top:0">${g.opp_abbr?(g.home_away==="Home"?"vs":"@")+g.opp_abbr:""}</div></div>`}).join("");
  const avgs=[{l:"History",v:seasAvg},{l:"L5",v:l5Avg},{l:"L10",v:allLogs.slice(0,10).reduce((s,g)=>s+getMetricVal(g,metric),0)/(Math.min(allLogs.length,10)||1)},{l:"Last",v:lastGame}].map(a=>`<div class="avg-card" style="border:1px solid ${lineNum&&a.v>=lineNum?"#22c55e44":lineNum?"#ef444433":"var(--border-1)"}"><div class="avg-label">${a.l}</div><div class="avg-val" style="color:${avgColor(a.v,lineNum)}">${a.v.toFixed(2)}</div></div>`).join("");

  // Stat strip
  let statStrip="";
  if(isG){["W","SV","GA","SV_PCT","SO","UD_FP"].forEach(s=>{});
    const ws=allLogs.filter(g=>toNum(g.W)>=1).length,ls=allLogs.length-ws;
    const svT=allLogs.reduce((a,g)=>a+toNum(g.SV),0),gaT=allLogs.reduce((a,g)=>a+toNum(g.GA),0);
    const svPct=svT+gaT>0?(svT/(svT+gaT)).toFixed(3):".000";
    statStrip=`<div class="stat-item"><div class="stat-label">W-L</div><div class="stat-val">${ws}-${ls}</div></div><div class="stat-item"><div class="stat-label">SV</div><div class="stat-val">${svT}</div></div><div class="stat-item"><div class="stat-label">GA</div><div class="stat-val">${gaT}</div></div><div class="stat-item"><div class="stat-label">SV%</div><div class="stat-val">${svPct}</div></div><div class="stat-item"><div class="stat-label">SO</div><div class="stat-val">${allLogs.filter(g=>toNum(g.SO)>=1).length}</div></div><div class="stat-item"><div class="stat-label">UD FP</div><div class="stat-val">${allLogs.reduce((a,g)=>a+toNum(g.UD_FP),0).toFixed(1)}</div></div>`;
  }else{statStrip=["G","A","PTS","SOG","BLK","HITS","PPP","FOW","UD_FP"].map(s=>`<div class="stat-item"><div class="stat-label">${s}</div><div class="stat-val">${toNum(most[`Seas_${s}`]).toFixed(s==="UD_FP"?1:1)}</div></div>`).join("")}

  const sp=curSplits.find(s=>s.player_name===player)||{};
  const hV=toNum(sp[`${metric}_Home`]),aV=toNum(sp[`${metric}_Away`]);
  let haBars=`<div class="no-data">No data</div>`;
  if(hV>0||aV>0){const mx=Math.max(hV,aV,.1);const hGP=toNum(sp.Home_GAMES),aGP=toNum(sp.Away_GAMES);const hTotal=Math.round(hV*hGP),aTotal=Math.round(aV*aGP);haBars=[{l:"Home",v:hV,c:"#8b5cf6",t:hTotal,gp:hGP},{l:"Away",v:aV,c:"#06b6d4",t:aTotal,gp:aGP}].map(b=>`<div class="mini-bar-wrap"><div class="mini-bar" style="height:${Math.max(4,(b.v/mx)*60)}px;background:${b.c}"></div><div class="mini-bar-label">${b.l}</div><div class="mini-bar-val">${b.v.toFixed(2)}/g</div><div class="mini-bar-val" style="color:#22c55e;font-size:7px">${b.t} in ${b.gp}G</div></div>`).join("")}

  const lastUp=most.LAST_UPDATED||pT.LAST_UPDATED||"—";
  const earlyBanner=!pHasLogs&&player?`<div class="early-banner"><div class="icon">🌱</div><div class="msg">Early Season — No Game Logs Yet</div><div class="sub">${esc(player)} is rostered. Matchup info and props are available.</div></div>`:"";

  const pProps=getProps(player);const pPick=getPick(player);
  let propsHTML="";
  if(pProps.length>0){propsHTML=`<div class="section"><div class="label">🎲 DraftKings Props</div>${pProps.map(p=>`<div class="prop-card" style="display:block"><div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start"><div class="prop-left"><div class="prop-metric">${p.METRIC}</div><div class="prop-line">${p.DK_LINE}</div></div><div class="prop-right"><div class="prop-odds prop-over">O ${fmtOdds(p.OVER_ODDS)}</div><div class="prop-odds prop-under">U ${fmtOdds(p.UNDER_ODDS)}</div></div></div>${renderPropBestBookBlock(p)}</div>`).join("")}</div>`}
  let pickBanner="";
  if(pPick){const c=pPick.confidence||"",cls=c==="SMASH"?"smash":c==="STRONG"?"strong":"lean";pickBanner=`<div class="section"><div class="card" style="border-left:3px solid ${c==="SMASH"?"#22c55e":"#3b82f6"}"><div class="card-title">🤖 AI Pick</div><div style="display:flex;align-items:center;gap:8px;margin-top:4px"><div class="pick-type">${pPick.prop_type||""}</div><div class="pick-lean ${(pPick.lean||"").toLowerCase()}">${pPick.lean||""} ${pPick.line||""}</div><div class="pick-conf ${cls}">${c}</div></div><div class="pick-rationale">${esc(pPick.rationale||"")}</div></div></div>`}

  // Game log
  let logHTML="";
  if(activeTab==="gamelog"){
    if(!pHasLogs){logHTML=`<div class="early-banner"><div class="icon">🌱</div><div class="msg">No Game Logs Yet</div></div>`}
    else{const opps=[...new Set(allLogs.map(g=>g.opp_abbr).filter(Boolean))].sort();
      const oppOpts=`<option value="">All Opponents</option>`+opps.map(o=>`<option value="${o}" ${oppFilter===o?"selected":""}>${o}</option>`).join("");
      const fLogs=oppFilter?allLogs.filter(g=>g.opp_abbr===oppFilter):allLogs;
      const logCols=isG?["SV","GA","SV_PCT","SO","W","UD_FP"]:["G","A","PTS","SOG","BLK","HITS","PPP","FOW","PIM","TOI","UD_FP"];
      const ths=logCols.map(c=>`<th class="${c===metric?"hl":""}">${c}</th>`).join("");
      const trs=fLogs.map(g=>{const cells=logCols.map(c=>{const v=toNum(g[c]);let cls=c===metric?"hl":"";if(c===metric&&lineNum)cls=v>lineNum?"hit":v===lineNum?"push":"miss";return`<td class="${cls}">${c==="UD_FP"||c==="SV_PCT"?v.toFixed(c==="SV_PCT"?3:1):v}</td>`}).join("");return`<tr><td>${(g.game_date||"").slice(5)}</td><td>${g.opp_abbr||"—"}</td><td>${g.home_away||"—"}</td>${cells}</tr>`}).join("");
      logHTML=`<div class="log-controls"><select id="oppFilter">${oppOpts}</select></div><div class="log-table-wrap"><table><thead><tr><th>DATE</th><th>OPP</th><th>H/A</th>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`}
  }

  // ═══ PICKS TAB ═══
  let picksHTML="";
  if(activeTab==="picks"){
    const subTabs=`<div class="sub-tabs" style="padding-top:12px">
      <button class="sub-tab ${st.picksView==='shortlist'?'active':''}" onclick="switchPicksView('shortlist')">Tonight’s Shortlist</button>
      <div class="sub-tab ${st.picksView==="bets"?"active":""}" onclick="switchPicksView('bets')">Historical Signals</div>
      <div class="sub-tab ${st.picksView==="slips"?"active":""}" onclick="switchPicksView('slips')">🎫 Slips</div>
      <div class="sub-tab ${st.picksView==="picks"?"active":""}" onclick="switchPicksView('picks')">🤖 AI Picks</div>
      <div class="sub-tab ${st.picksView==="draft"?"active":""}" onclick="switchPicksView('draft')">🏒 Draft</div>
      <div class="sub-tab ${st.picksView==="streaks"?"active":""}" onclick="switchPicksView('streaks')">🔥 Streaks</div>
      <div class="sub-tab ${st.picksView==="due"?"active":""}" onclick="switchPicksView('due')">🧊 Due</div>
      <div class="sub-tab ${st.picksView==="snipers"?"active":""}" onclick="switchPicksView('snipers')">💥 Snipers</div>
    <div class="sub-tab ${st.picksView==="parlays"?"active":""}" onclick="switchPicksView('parlays')">🎯 Parlays</div>
      <div class="sub-tab ${st.picksView==="props"?"active":""}" onclick="switchPicksView('props')">🎲 Props</div>
    </div>`;
    const picksIntro=subTabs+renderConvergenceHTML();

    if(st.picksView==="shortlist")picksHTML=subTabs+rrShortlist();
    else if(st.picksView==="bets"){
      const allBets=getBestBets();const posEV=allBets.filter(b=>b.edge>0);const elite=posEV.filter(b=>b.edge>=0.15);const strong=posEV.filter(b=>b.edge>=0.08&&b.edge<0.15);
      picksHTML=picksIntro;if(!allBets.length)picksHTML+=`<div class="no-data" style="padding:40px;text-align:center">No props for +EV analysis. Run engine first.</div>`;
      else{picksHTML+=`<div class="bet-summary"><div class="bs-card"><div class="bs-val">${posEV.length}</div><div class="bs-lbl">+EV PROPS</div></div><div class="bs-card"><div class="bs-val" style="color:#ef4444">${elite.length}</div><div class="bs-lbl">ELITE (15%+)</div></div><div class="bs-card"><div class="bs-val" style="color:var(--accent)">${strong.length}</div><div class="bs-lbl">STRONG (8%+)</div></div><div class="bs-card"><div class="bs-val" style="color:var(--ink-muted)">${allBets.length}</div><div class="bs-lbl">ANALYZED</div></div></div>`;
        picksHTML+=`<div style="padding:0 16px 4px;color:var(--ink-muted);font-size:10px">Edge = hit rate − DK implied probability. Min 3 games.</div><div class="cards-grid">`;
        picksHTML+=posEV.slice(0,40).map(b=>{const ep=(b.edge*100).toFixed(1),hr=(b.hitRate*100).toFixed(0),ip=(b.impliedProb*100).toFixed(0);const cls=b.edge>=0.15?"elite":b.edge>=0.08?"strong":"mid";const badges=riskBadges(b.name,b.isG,{showLimited:false});
          const matchupMeta=b.isG?`${esc(b.team)} vs ${esc(b.opp)}${b.starterStatus?` · ${esc(b.starterStatus)}`:""}`:`${esc(b.team)} vs ${esc(b.opp)} · vs ${esc(b.goalie||"TBD")}${b.goalieStatus?` (${esc(b.goalieStatus)})`:""}`;
          const vegasMeta=[b.moneyline?`ML ${b.moneyline}`:"",b.impliedTotal?`ITT ${b.impliedTotal}`:"",`${b.hits}/${b.total} games`].filter(Boolean).join(" · ");
          const locked=getLockInfo(b.name,b.isG).started;
          return`<div class="bet-card ${cls}${locked?" locked-card":""}" style="cursor:pointer;border-color:${b.lean==="OVER"?"#22c55e":"#ef4444"}" onclick="streakToDash('${esc(b.name)}')"><div class="bet-left"><div class="bet-name">${b.isG?`🥅 `:""}${playerLink(b.name)}${badges}${lockBadge(b.name,b.isG)}</div><div class="bet-meta">${matchupMeta}</div><div class="bet-meta">${vegasMeta}</div><div class="bet-prop"><span class="prop-metric" style="font-size:10px">${b.metric}</span><span class="${b.lean==="OVER"?"prop-over":"prop-under"}" style="font-weight:700;font-size:13px">${b.lean} ${b.dkLine}</span><span style="color:var(--accent-soft);font-size:11px">${fmtOdds(b.odds)}</span><span class="ev-badge ev-pos ev-big ${b.returning||locked?"muted-risk":""}">+${ep}% EV</span></div>${renderBestBookLine(b.prop,b.lean)}<div class="bet-bar ${b.returning||locked?"muted-risk":""}"><div class="bet-bar-fill" style="width:${hr}%;background:${b.edge>=0.15?"#ef4444":b.edge>=0.08?"#22c55e":"#f59726"}"></div></div><div style="display:flex;justify-content:space-between;margin-top:3px;font-size:9px;color:var(--ink-muted)"><span>You: ${hr}%</span><span>DK: ${ip}%</span></div></div><div class="bet-right"><div class="bet-edge pos ${b.returning||locked?"muted-risk":""}">+${ep}%</div><div class="bet-sub">${locked?"started":b.returning?"reduced":"edge"}</div></div></div>`}).join("")+`</div>`}

    }else if(st.picksView==="slips"){
      const r=getSmartSlips();picksHTML=picksIntro;
      if(!r.legs.length)picksHTML+=`<div class="no-data" style="padding:40px;text-align:center">No +EV props for slips.</div>`;
      else{const slips=st.slipLegs==="3"?r.slips3:st.slipLegs==="4"?r.slips4:r.slips5;const pay={"3":"6x","4":"10x","5":"20x"};
        picksHTML+=`<div class="bet-summary"><div class="bs-card"><div class="bs-val">${r.legs.length}</div><div class="bs-lbl">ELIGIBLE</div></div><div class="bs-card"><div class="bs-val" style="color:var(--accent)">${r.legs.filter(l=>l.hasAI).length}</div><div class="bs-lbl">AI-BACKED</div></div><div class="bs-card"><div class="bs-val" style="color:#ffaa00">${r.legs.filter(l=>l.hasStreak).length}</div><div class="bs-lbl">ON STREAKS</div></div><div class="bs-card"><div class="bs-val" style="color:#fda4af">${r.legs.filter(l=>l.hasAIConflict).length}</div><div class="bs-lbl">AI CONFLICTS</div></div><div class="bs-card"><div class="bs-val" style="color:var(--accent-soft)">${pay[st.slipLegs]}</div><div class="bs-lbl">PAYOUT</div></div></div>`;
        picksHTML+=`<div class="slip-controls"><span style="color:var(--ink-muted);font-size:11px">Legs:</span><div class="pf-btn ${st.slipLegs==="3"?"active":""}" onclick="setSlipLegs('3')">3-Leg</div><div class="pf-btn ${st.slipLegs==="4"?"active":""}" onclick="setSlipLegs('4')">4-Leg</div><div class="pf-btn ${st.slipLegs==="5"?"active":""}" onclick="setSlipLegs('5')">5-Leg</div></div>`;
        if(!slips.length)picksHTML+=`<div class="no-data" style="padding:20px;text-align:center">Not enough legs.</div>`;
        else picksHTML+=slips.map((s,i)=>{const best=i===0;return`<div class="slip-card ${best?"best":""}"><div class="slip-header"><span class="slip-rank">${best?"⭐ BEST":"#"+(i+1)} · ${st.slipLegs}-LEG</span><span class="slip-score">${s.score.toFixed(1)} pts</span></div><div class="slip-legs">${s.legs.map(l=>{const locked=getLockInfo(l.name,l.isG).started;return`<div class="slip-leg${locked?" locked-card":""}"><span class="slip-leg-team">${esc(l.team)}</span><div style="flex:1;min-width:0"><span class="slip-leg-name">${l.isG?`🥅 `:""}${playerLink(l.name)}</span>${lockBadge(l.name,l.isG)}${l.aiDisagreementText?`<div style="font-size:9px;color:${l.aiConflictLevel==="strong"?"#fda4af":"#fde68a"};margin-top:2px">${esc(l.aiDisagreementText)}</div>`:""}${renderBestBookLine(l.prop,l.lean)}</div><div class="slip-leg-prop"><span class="slip-leg-metric">${l.metric}</span><span class="slip-leg-lean ${l.lean.toLowerCase()}">${l.lean} ${l.dkLine}</span><span class="slip-leg-edge">+${(l.edge*100).toFixed(0)}%</span></div></div>`}).join("")}</div>${(s.legs.some(l=>l.signals.length)||s.slipTags?.length)?`<div class="slip-tags">${[...new Set([...(s.slipTags||[]),...s.legs.flatMap(l=>l.signals)])].slice(0,5).map(sg=>`<span class="slip-tag">${sg}</span>`).join("")}</div>`:""}${renderCrossBookWarning(s.legs)}<div class="slip-meta"><span>Avg edge: +${(s.avgEdge*100).toFixed(1)}%</span><span>Avg hit: ${(s.avgHitRate*100).toFixed(0)}%</span><span>${s.teams.length} teams</span></div></div>`}).join("")}

    }else if(st.picksView==="picks"){
      const latestDate=getLatestPickDate();
      const latestRun=getLatestPickRun();
    const todayPicks=st.picks.filter(p=>normalizeDate(p.DATE||p.date)===latestDate&&toNum(p.RUN_NUMBER||p.run_number||0)===latestRun);
      const pickGuard=st.pickGuard;
      if(!todayPicks.length)picksHTML=picksIntro+renderPickGuard(pickGuard)+`<div class="no-data" style="padding:40px;text-align:center">No AI picks today.</div>`;
      else{const smash=todayPicks.filter(p=>normalizeConfidence(p.confidence)==="SMASH").length;const hits=todayPicks.filter(p=>{const h=(p.HIT||"").toString().toUpperCase();return h==="YES"||h==="TRUE"}).length;const miss=todayPicks.filter(p=>{const h=(p.HIT||"").toString().toUpperCase();return h==="NO"||h==="FALSE"}).length;const tracked=hits+miss;
        picksHTML=picksIntro+renderPickGuard(pickGuard)+`<div class="picks-summary"><div class="ps-card"><div class="ps-val">${todayPicks.length}</div><div class="ps-lbl">PICKS</div></div><div class="ps-card"><div class="ps-val">${smash}</div><div class="ps-lbl">SMASH</div></div>${tracked?`<div class="ps-card"><div class="ps-val" style="color:${hits>=miss?"#22c55e":"#ef4444"}">${hits}-${miss}</div><div class="ps-lbl">RECORD</div></div>`:`<div class="ps-card"><div class="ps-val" style="color:var(--ink-muted)">—</div><div class="ps-lbl">RECORD</div></div>`}</div><div class="cards-grid">`;
        picksHTML+=todayPicks.map(pk=>{const c=normalizeConfidence(pk.confidence),cls=c==="SMASH"?"smash":c==="STRONG"?"strong":"";const h=(pk.HIT||"").toString().toUpperCase();const hasR=pk.ACTUAL_STAT!=null&&pk.ACTUAL_STAT!==""&&!isNaN(pk.ACTUAL_STAT);const isG=(pk.prop_type||"").startsWith("G_")||pk.prop_type==="SV"||pk.prop_type==="GA"||pk.prop_type==="G_W";const flags=getSampleFlags(pk.player,isG);const badges=riskBadges(pk.player,isG);let rHTML="";if(hasR||h){const rC=h==="YES"||h==="TRUE"?"result-hit":"result-miss";const rL=h==="YES"||h==="TRUE"?"✅ HIT":h==="NO"||h==="FALSE"?"❌ MISS":"⏳";rHTML=`<div class="pick-result"><span class="result-badge ${rC}">${rL}</span>${hasR?`<span class="result-actual">Actual: ${pk.ACTUAL_STAT}</span>`:""}</div>`}
          const locked=getLockInfo(pk.player,isG).started;
          const pickProp=findPropForPick(pk.player,pk.prop_type,pk.line);
          return`<div class="pick-card ${cls}${locked?" locked-card":""}"><div><span class="pick-rank">#${pk.rank||"—"}</span><span class="pick-player">${playerLink(pk.player)}${badges}${lockBadge(pk.player,isG)}</span></div><div class="pick-matchup">${esc(pk.game||"")}</div><div class="pick-prop"><div class="pick-type">${pk.prop_type||""}</div><div class="pick-lean ${(pk.lean||"").toLowerCase()}">${pk.lean||""} ${pk.line||""}</div><div class="pick-conf ${cls}">${c||"LEAN"}</div></div>${renderBestBookLine(pickProp,pk.lean)}${pk.rationale?`<div class="pick-rationale">"${esc(pk.rationale)}"</div>`:""}${flags.returning?`<div class="risk-subnote">Returning from absence — season averages may not reflect current form.</div>`:""}${rHTML}</div>`}).join("")+`</div>`}

    }else if(st.picksView==="streaks"){
      const all=getStreaks();const fil=st.streakFilter==="all"?all:st.streakFilter==="skt"?all.filter(s=>s.propType==="skt"):all.filter(s=>s.propType==="gol");
      picksHTML=picksIntro;if(!fil.length)picksHTML+=`<div class="no-data" style="padding:40px;text-align:center">No active streaks.</div>`;
      else{picksHTML+=`<div style="padding:12px 16px 4px;display:flex;justify-content:space-between;align-items:center"><div style="color:#ffaa00;font-size:13px;font-weight:700">🔥 Active Streaks</div><div style="color:var(--ink-muted);font-size:10px">${fil.length} streaks</div></div><div class="streak-filters">${[['all','All'],['skt','🏒 Skaters'],['gol','🧱 Goalies']].map(([value,label])=>`<button type="button" class="pf-btn ${st.streakFilter===value?'active':''}" aria-pressed="${st.streakFilter===value}" onclick="setStreakFilter('${value}')">${label}</button>`).join('')}</div><div class="cards-grid">`;
        picksHTML+=fil.map(s=>{const heat=getStreakHeat(s.streak);const odds=s.overOdds?fmtOdds(s.overOdds):"";const matchupMeta=s.propType==="gol"?`${esc(s.team)} vs ${esc(s.opp)}${s.starterStatus?` · ${esc(s.starterStatus)}`:""}`:`${esc(s.team)} vs ${esc(s.opp)} · vs ${esc(s.goalie||"TBD")}${s.goalieStatus?` (${esc(s.goalieStatus)})`:""}`;
          return`<div class="streak-card ${heat.cls}${getLockInfo(s.player,s.propType==="gol").started?" locked-card":""}" onclick="streakToDash('${esc(s.player)}')"><div class="streak-left"><div><span class="streak-emoji">${s.emoji}</span><span class="streak-name">${playerLink(s.player)}${lockBadge(s.player,s.propType==="gol")}</span><span class="streak-label">${s.label}</span></div><div class="streak-meta">${matchupMeta}</div><div class="streak-meta">${s.desc}</div><div class="streak-chart">${miniChart(s.recentVals,s.threshold)}</div>${s.dkLine?`<div class="streak-prop">DK ${s.stat} ${s.dkLine} ${odds?" O:"+odds:""} · Avg: ${s.avgDuring}</div>`:`<div class="streak-prop">Avg during: ${s.avgDuring} · Season: ${s.seasAvg}</div>`}</div><div class="streak-right"><div class="streak-count">${s.streak}</div><div class="streak-sub">${getLockInfo(s.player,s.propType==="gol").started?"started":"games"}</div></div></div>`}).join("")+`</div>`}

    }else if(st.picksView==="due"){
      const all=getDueBoard();picksHTML=picksIntro;
      if(!all.length)picksHTML+=`<div class="no-data" style="padding:40px;text-align:center">No "due" candidates.</div>`;
      else{picksHTML+=`<div class="bet-summary"><div class="bs-card"><div class="bs-val" style="color:var(--accent)">${all.length}</div><div class="bs-lbl">DUE UP</div></div><div class="bs-card"><div class="bs-val" style="color:#818cf8">${all.filter(d=>d.matchupScore>=2).length}</div><div class="bs-lbl">+ MATCHUP</div></div><div class="bs-card"><div class="bs-val" style="color:#fde68a">${all.filter(d=>d.propTag).length}</div><div class="bs-lbl">HAS PROP</div></div></div>`;
        picksHTML+=`<div style="padding:0 16px 4px;color:var(--ink-muted);font-size:10px">Cold streak + strong season avg + soft opponent = regression coming.</div><div class="cards-grid">`;
        picksHTML+=all.map((d,i)=>{const top=i<3;const tags=[`<span class="due-tag cold">❄️ ${d.coldGap}% below avg</span>`,`<span class="due-tag cold">📉 ${d.drought}G drought</span>`];d.matchupTags.forEach(mt=>tags.push(`<span class="due-tag matchup">✅ ${esc(mt)}</span>`));if(d.propTag)tags.push(`<span class="due-tag prop">🎲 DK ${d.stat} ${d.propTag.line}${d.propTag.overOdds?" O:"+fmtOdds(d.propTag.overOdds):""}</span>`);
          return`<div class="due-card ${top?"top":""}${getLockInfo(d.name,d.type==="gol").started?" locked-card":""}" onclick="streakToDash('${esc(d.name)}')"><div class="due-left"><div><span style="font-size:14px;margin-right:4px">🧊</span><span class="due-name">${playerLink(d.name)}${lockBadge(d.name,d.type==="gol")}</span><span class="due-label">${d.stat}</span></div><div class="due-meta">${esc(d.team)} vs ${esc(d.opp)} · vs ${esc(d.goalie)}${d.goalieStatus?` (${esc(d.goalieStatus)})`:""}</div><div class="due-meta">Season: ${d.seasAvg}/g → L5: ${d.l5Avg}/g</div><div class="due-chart">${dueMiniChart(d.recentVals,parseFloat(d.seasAvg))}</div><div class="due-tags">${tags.join("")}</div></div><div class="due-right"><div class="due-score">${d.totalScore.toFixed(0)}</div><div class="due-sub">${getLockInfo(d.name,d.type==="gol").started?"started":"due score"}</div></div></div>`}).join("")+`</div>`}

    }else if(st.picksView==="snipers"){
      const snipers=getSnipers();picksHTML=picksIntro;
      if(!snipers.length)picksHTML+=`<div class="no-data" style="padding:40px;text-align:center">Not enough game log history yet. Needs 5+ games per skater.</div>`;
      else{const t3=snipers.filter(s=>s.hitRate3>=0.7).length;const t5=snipers.filter(s=>s.hitRate5>=0.5).length;const t7=snipers.filter(s=>s.hitRate7>=0.3).length;
        picksHTML+=`<div class="bet-summary"><div class="bs-card"><div class="bs-val" style="color:#22c55e">${t3}</div><div class="bs-lbl">3+ SOG 70%+</div></div><div class="bs-card"><div class="bs-val" style="color:#f59726">${t5}</div><div class="bs-lbl">5+ SOG 50%+</div></div><div class="bs-card"><div class="bs-val" style="color:#ef4444">${t7}</div><div class="bs-lbl">7+ SOG 30%+</div></div><div class="bs-card"><div class="bs-val" style="color:var(--ink-muted)">${snipers.length}</div><div class="bs-lbl">QUALIFIED</div></div></div>`;
        picksHTML+=`<div style="padding:0 16px 4px;color:var(--ink-muted);font-size:10px">Volume shooters — ranked by SOG consistency + recent form. Prop-independent.</div><div class="cards-grid">`;
        picksHTML+=snipers.slice(0,30).map((s,i)=>{const cls=s.hitRate3>=0.85?"elite":s.hitRate3>=0.7?"strong":"mid";const trendIcon=s.trend>0.2?"📈":s.trend<-0.2?"📉":"➡️";const trendColor=s.trend>0.2?"#22c55e":s.trend<-0.2?"#ef4444":"var(--ink-muted)";
          let tags=[];if(s.hitRate5>=0.5)tags.push(`<span class="draft-tag" style="background:#f5972622;color:#f59726">🎯 5+ SOG ${(s.hitRate5*100).toFixed(0)}%</span>`);
          if(s.hitRate7>=0.3)tags.push(`<span class="draft-tag" style="background:#ef444422;color:#ef4444">💥 7+ SOG ${(s.hitRate7*100).toFixed(0)}%</span>`);
          if(s.seasAvg>=3.5)tags.push(`<span class="draft-tag" style="background:#38bdf822;color:var(--accent)">Volume ${s.seasAvg.toFixed(1)}/g</span>`);
          if(s.dkProp)tags.push(`<span class="draft-tag" style="background:#fde68a22;color:#fde68a">🎲 DK ${s.dkProp.line} O:${fmtOdds(s.dkProp.over)}</span>`);
          const locked=getLockInfo(s.name,false).started;return `<div class="bet-card ${cls}${locked?" locked-card":""}" onclick="sniperToDash('${esc(s.name)}')"><div class="bet-left"><div class="bet-name">${playerLink(s.name)}${lockBadge(s.name,false)}</div><div class="bet-meta">${esc(s.team)} vs ${esc(s.opp)} · vs ${esc(s.goalie)}${s.goalieStatus?` (${esc(s.goalieStatus)})`:""}</div><div class="bet-prop"><span class="prop-metric" style="font-size:10px">SOG</span><span style="color:#22c55e;font-weight:700;font-size:13px">${s.hits3}/${s.total} games 3+</span><span style="color:${trendColor};font-size:11px">${trendIcon} L5: ${s.l5Avg.toFixed(1)}/g</span></div><div class="bet-bar"><div class="bet-bar-fill" style="width:${s.hitRate3*100}%;background:#22c55e"></div></div>${tags.length?`<div class="draft-tags" style="margin-top:6px">${tags.join("")}</div>`:""}</div><div class="bet-right"><div class="bet-edge pos">${(s.hitRate3*100).toFixed(0)}%</div><div class="bet-sub">${locked?"started":"3+ SOG"}</div></div></div>`;
        }).join("")+`</div>`}

    }else if(st.picksView==="parlays"){
      const pStat=st.parlayStat;const board=getStatParlayBoard(pStat);const combos2=getStatParlayCombos(board,2);const combos3=getStatParlayCombos(board,3);
      const availStats=["PTS","G","A","SOG","BLK","HITS","PPP","SV"];
      picksHTML=picksIntro+`<div style="padding:12px 16px 4px;color:#818cf8;font-size:13px;font-weight:700">🎯 Stat Parlays</div><div style="padding:0 16px 4px;color:var(--ink-muted);font-size:10px">Same-stat parlays ranked by hit rate + EV + matchup.</div>`;
      picksHTML+=`<div class="due-filters">${availStats.map(s=>`<div class="pf-btn ${pStat===s?"active":""}" onclick="setParlayStat('${s}')">${s}</div>`).join("")}</div>`;
      if(!board.length)picksHTML+=`<div class="no-data" style="padding:40px;text-align:center">No DK ${pStat} props available.</div>`;
      else{picksHTML+=`<div class="cards-grid">${board.slice(0,12).map((d,i)=>{const hrPct=(d.hitRate*100).toFixed(0);const isTop=i<3;const matchupMeta=d.isG?`${esc(d.team)} vs ${esc(d.opp)}${d.starterStatus?` · ${esc(d.starterStatus)}`:""}`:`${esc(d.team)} vs ${esc(d.opp)} · vs ${esc(d.goalie)}${d.goalieStatus?` (${esc(d.goalieStatus)})`:""}`;const vegasMeta=[d.moneyline?`ML ${d.moneyline}`:"",d.impliedTotal?`ITT ${d.impliedTotal}`:""].filter(Boolean).join(" · ");const locked=getLockInfo(d.name,d.isG).started;return`<div class="due-card ${isTop?"top":""}${locked?" locked-card":""}" onclick="streakToDash('${esc(d.name)}')"><div class="due-left"><div><span style="font-size:12px;font-weight:800;color:${isTop?"#818cf8":"var(--accent)"};margin-right:6px">#${i+1}</span><span class="due-name">${playerLink(d.name)}${lockBadge(d.name,d.isG)}</span></div><div class="due-meta">${matchupMeta}</div>${vegasMeta?`<div class="due-meta">${vegasMeta}</div>`:""}<div class="due-tags"><span class="due-tag">${hrPct}% hit</span>${d.edge>0?`<span class="due-tag matchup">+${(d.edge*100).toFixed(0)}% EV</span>`:""}<span class="due-tag prop">DK ${d.dkLine} O:${fmtOdds(d.overOdds)}</span></div></div><div class="due-right"><div class="due-score" style="color:${isTop?"#818cf8":"var(--accent)"}">${d.score.toFixed(0)}</div><div class="due-sub">${locked?"started":"score"}</div></div></div>`}).join("")}</div>`;
        if(combos2.length)picksHTML+=`<div style="padding:12px 16px 0"><div style="color:var(--accent);font-size:12px;font-weight:700;margin-bottom:8px">🎰 Best 2-Leg ${pStat} Parlays</div><div class="cards-grid">${combos2.map((c,i)=>{const matchupMeta=c.players.map(p=>p.isG?`${esc(p.team)}-${esc(p.opp)}${p.starterStatus?` ${esc(p.starterStatus)}`:""}`:`${esc(p.team)}-${esc(p.opp)} vs ${esc(p.goalie||"TBD")}${p.goalieStatus?` (${esc(p.goalieStatus)})`:""}`).join(" · ");const vegasMeta=c.players.map(p=>[p.moneyline?`${esc(p.team)} ML ${p.moneyline}`:"",p.impliedTotal?`${esc(p.team)} ITT ${p.impliedTotal}`:""].filter(Boolean).join(" · ")).filter(Boolean).join(" · ");return`<div class="bet-card ${i===0?"elite":"mid"}" style="cursor:default"><div class="bet-left"><div class="bet-name">${c.players.map(p=>playerLink(p.name)).join(" + ")}</div><div class="bet-meta">${matchupMeta}</div><div class="bet-meta">${vegasMeta||`${c.teams.join(" · ")} · Avg edge: ${c.avgEdge>0?"+":""}${(c.avgEdge*100).toFixed(0)}%`}</div></div><div class="bet-right"><div class="bet-edge pos">${(c.avgHitRate*100).toFixed(0)}%</div><div class="bet-sub">avg hit</div></div></div>`}).join("")}</div></div>`;
        if(combos3.length)picksHTML+=`<div style="padding:12px 16px 0"><div style="color:var(--accent);font-size:12px;font-weight:700;margin-bottom:8px">🎰 Best 3-Leg ${pStat} Parlays</div><div class="cards-grid">${combos3.map((c,i)=>{const matchupMeta=c.players.map(p=>p.isG?`${esc(p.team)}-${esc(p.opp)}${p.starterStatus?` ${esc(p.starterStatus)}`:""}`:`${esc(p.team)}-${esc(p.opp)} vs ${esc(p.goalie||"TBD")}${p.goalieStatus?` (${esc(p.goalieStatus)})`:""}`).join(" · ");const vegasMeta=c.players.map(p=>[p.moneyline?`${esc(p.team)} ML ${p.moneyline}`:"",p.impliedTotal?`${esc(p.team)} ITT ${p.impliedTotal}`:""].filter(Boolean).join(" · ")).filter(Boolean).join(" · ");return`<div class="bet-card ${i===0?"elite":"mid"}" style="cursor:default"><div class="bet-left"><div class="bet-name">${c.players.map(p=>playerLink(p.name)).join(" + ")}</div><div class="bet-meta">${matchupMeta}</div><div class="bet-meta">${vegasMeta||`${c.teams.join(" · ")} · Avg edge: ${c.avgEdge>0?"+":""}${(c.avgEdge*100).toFixed(0)}%`}</div></div><div class="bet-right"><div class="bet-edge pos">${(c.avgHitRate*100).toFixed(0)}%</div><div class="bet-sub">avg hit</div></div></div>`}).join("")}</div></div>`}

    }else if(st.picksView==="draft"){
      const board=getDraftBoard();const avail=board.filter(p=>!st.drafted.has(p.name));const stacks=getDraftStacks().slice(0,5);const stackTags=getDraftStackTagMap();
      function getTier(proj,isGoalie){const v=parseFloat(proj);if(isGoalie){if(v>=20)return{label:"TIER 1 — Elite",cls:"tier1",color:"var(--accent)"};if(v>=10)return{label:"TIER 2 — Solid",cls:"tier2",color:"#3b82f6"};return{label:"TIER 3 — Backup",cls:"tier3",color:"#8b5cf6"}}if(v>=8)return{label:"TIER 1 — Elite",cls:"tier1",color:"var(--accent)"};if(v>=5)return{label:"TIER 2 — Strong",cls:"tier2",color:"#3b82f6"};if(v>=3)return{label:"TIER 3 — Solid",cls:"tier3",color:"#8b5cf6"};return{label:"TIER 4 — Depth",cls:"",color:"var(--ink-muted)"}}
      function getPosClass(pos){if(pos==="G")return"draft-pos-g";if(pos==="C")return"draft-pos-c";if(pos==="D")return"draft-pos-d";return"draft-pos-w"}
      picksHTML=picksIntro+`<div style="padding:12px 16px 4px;color:var(--accent);font-size:13px;font-weight:700">🏒 Draft Cheat Sheet</div><div style="padding:0 16px 4px;color:var(--ink-muted);font-size:10px">Tap to mark as drafted.</div><div class="draft-controls"><button class="draft-reset" onclick="resetDrafted()">Reset</button><div class="draft-count">${st.drafted.size} drafted · ${avail.length} left</div></div><div class="cards-grid">`;
      let lt="";board.forEach((p,i)=>{const tier=getTier(p.projUD,p.pos==="G");const d=st.drafted.has(p.name);const tc=tier.label!==lt;lt=tier.label;
        let tags=[];if(p.isSmash)tags.push(`<span class="draft-tag" style="background:#22c55e22;color:#22c55e">SMASH</span>`);
        if(!p.isGoalie){if(p.sPPP>=0.5)tags.push(`<span class="draft-tag" style="background:#f5972622;color:#f59726">⚡ PP</span>`);if(p.sSOG>=3)tags.push(`<span class="draft-tag" style="background:#ef444422;color:#ef4444">🎯 SHOTS</span>`)}
        if(p.returning)tags.push(`<span class="draft-tag" style="background:#f59e0b22;color:#fbbf24">⚠️ RETURNING</span>`);
        if(p.limitedSample)tags.push(`<span class="draft-tag" style="background:#64748b22;color:#cbd5e1">⚠️ LIMITED SAMPLE</span>`);
        const l5v=parseFloat(p.l5UD),projv=parseFloat(p.projUD);if(l5v>projv*1.15)tags.push(`<span class="draft-tag" style="background:#22c55e22;color:#22c55e">📈 HOT</span>`);
        (stackTags.get(normalizePlayerName(p.name))||new Set()).forEach(tag=>{const clr=tag.includes("CORRELATED")?"#60a5fa":tag.includes("HIGH TOTAL")?"#fbbf24":"#34d399";tags.push(`<span class="draft-tag" style="background:${clr}22;color:${clr}">${tag}</span>`);});
        const meta=p.isGoalie?`${esc(p.team)} vs ${esc(p.opp)}`:`${esc(p.team)} vs ${esc(p.opp)} · vs ${esc(p.goalie)}${p.goalieStatus?` (${esc(p.goalieStatus)})`:""}`;
        const locked=getLockInfo(p.name,p.pos==="G").started;
        picksHTML+=`${tc?`<div class="draft-tier-label" style="color:${tier.color}">${tier.label}</div>`:""}<div class="draft-card${d?" drafted":""}${p.isSmash&&!d?" smash":!d?" "+tier.cls:""}${p.pos==="G"&&!d?" goalie":""}${locked?" locked-card":""}" onclick="toggleDrafted('${esc(p.name)}')"><div class="draft-rank" style="color:${d?"var(--border-1)":tier.color}">${i+1}</div><div class="draft-main"><div class="draft-name">${playerLink(p.name)}${lockBadge(p.name,p.pos==="G")}<span class="draft-pos ${getPosClass(p.pos)}">${p.pos}</span></div><div class="draft-meta">${meta}</div>${p.returning?`<div class="risk-subnote">Returning from absence — season averages may not reflect current form.</div>`:""}${tags.length?`<div class="draft-tags">${tags.join("")}</div>`:""}</div><div class="draft-fp"><div class="draft-fp-val" style="color:${d?"var(--border-1)":tier.color}">${p.projUD}</div><div class="draft-fp-lbl">${locked?"STARTED":"UD FP"}</div>${l5v!==projv?`<div style="font-size:9px;color:${l5v>projv?"#22c55e":"#ef4444"};margin-top:1px">L5: ${p.l5UD}</div>`:""}</div></div>`});
      picksHTML+=`</div>`;
      if(stacks.length){
        picksHTML+=`<div style="padding:14px 16px 4px;color:var(--accent);font-size:12px;font-weight:700">⚡ Stacks</div><div style="padding:0 16px 6px;color:var(--ink-muted);font-size:10px">Top 2-player skater stacks ranked by combined UD projection, game total, and opposing-goalie weakness.</div><div class="cards-grid">`;
        picksHTML+=stacks.map((s,i)=>`<div class="bet-card ${i===0?"elite":"mid"}" style="cursor:default"><div class="bet-left"><div class="bet-name">${playerLink(s.players[0].name)} + ${playerLink(s.players[1].name)}</div><div class="bet-meta">${esc(s.team)} vs ${esc(s.opp)} · vs ${esc(s.goalie)}${s.gameTotal?` · O/U ${s.gameTotal}`:""}${s.oppGA?` · ${s.oppGA.toFixed(1)} GA/G`:""}</div><div class="draft-tags" style="margin-top:6px">${s.tags.map(tag=>`<span class="draft-tag" style="background:${tag.includes("CORRELATED")?"#60a5fa22":tag.includes("HIGH TOTAL")?"#fbbf2422":"#34d39922"};color:${tag.includes("CORRELATED")?"#60a5fa":tag.includes("HIGH TOTAL")?"#fbbf24":"#34d399"}">${tag}</span>`).join("")}</div></div><div class="bet-right"><div class="bet-edge pos">${s.combinedProj}</div><div class="bet-sub">UD FP</div></div></div>`).join("");
        picksHTML+=`</div>`;
      }

    }else{
      // Props table
      const allM=[...new Set(st.props.map(p=>p.METRIC).filter(Boolean))].sort();const fil=st.propsMetric==="ALL"?st.props:st.props.filter(p=>p.METRIC===st.propsMetric);
      const srch=st.propsSearch?fil.filter(p=>(p.PLAYER_NAME||"").toLowerCase().includes(st.propsSearch.toLowerCase())):fil;
      const sorted=[...srch].sort((a,b)=>(a.PLAYER_NAME||"").localeCompare(b.PLAYER_NAME||"")).slice(0,200);
      const parlayStats=["PTS","G","A","SOG","BLK","HITS","PPP","SV"].filter(m=>allM.includes(m));
      const propsParlayStat=parlayStats.includes(st.parlayStat)?st.parlayStat:(parlayStats[0]||"PTS");
      const propsBoard=getStatParlayBoard(propsParlayStat);
      const propsCombos3=getStatParlayCombos(propsBoard,3).slice(0,5);
      picksHTML=picksIntro+`<div style="padding:8px 16px"><input type="text" id="propsSearchInput" placeholder="Search player..." value="${esc(st.propsSearch)}"/></div>
      <div class="props-filter"><div class="pf-btn ${st.propsMetric==="ALL"?"active":""}" onclick="setPropsMetric('ALL')">All</div>${allM.map(m=>`<div class="pf-btn ${st.propsMetric===m?"active":""}" onclick="setPropsMetric('${m}')">${m}</div>`).join("")}</div>
      <div style="padding:0 16px;color:var(--ink-muted);font-size:10px;margin-bottom:4px">${srch.length} props</div>`;
      if(parlayStats.length){
        picksHTML+=`<div style="padding:12px 16px 4px;color:#818cf8;font-size:13px;font-weight:700">🎯 Same-Stat Parlays</div><div style="padding:0 16px 4px;color:var(--ink-muted);font-size:10px">Top 3-leg same-stat combos ranked by conviction score, hit rate, EV, and matchup.</div><div class="due-filters">${parlayStats.map(s=>`<div class="pf-btn ${propsParlayStat===s?"active":""}" onclick="setParlayStat('${s}')">${s}</div>`).join("")}</div>`;
        if(propsCombos3.length){
          picksHTML+=`<div class="cards-grid">${propsCombos3.map((c,i)=>{const score=Math.round(c.score);const tags=["🧱 SAME STAT"];if(c.avgHitRate>=0.65)tags.push("🔥 HIGH HIT RATE");if(c.avgEdge>0.08)tags.push("💎 ELITE EDGE");if(c.teams.length===3)tags.push("🌍 3 TEAMS");return`<div class="bet-card ${i===0?"elite":"mid"}" style="cursor:default"><div class="bet-left"><div class="bet-name">${c.players.map(p=>playerLink(p.name)).join(" + ")}</div><div class="bet-meta">${propsParlayStat} OVER · ${c.players.map(p=>`${esc(p.team)} vs ${esc(p.opp)}`).join(" · ")}</div><div class="draft-tags" style="margin-top:6px">${tags.map(tag=>`<span class="draft-tag" style="background:${tag.includes("ELITE")?"#22c55e22":tag.includes("HIGH HIT")?"#fbbf2422":"#818cf822"};color:${tag.includes("ELITE")?"#22c55e":tag.includes("HIGH HIT")?"#fbbf24":"#818cf8"}">${tag}</span>`).join("")}</div></div><div class="bet-right"><div class="bet-edge pos">${score}</div><div class="bet-sub">conviction</div><div style="font-size:10px;color:#a5b4fc;margin-top:4px">${(c.avgHitRate*100).toFixed(0)}% hit · ${c.avgEdge>0?"+":""}${(c.avgEdge*100).toFixed(0)}% EV</div></div></div>`}).join("")}</div>`;
        }else{
          picksHTML+=`<div class="no-data" style="padding:20px 16px;text-align:center">No same-stat ${propsParlayStat} parlay combos available.</div>`;
        }
      }
      picksHTML+=`
      <div class="props-tbl-wrap"><table><thead><tr><th>Player</th><th>Prop</th><th>Line</th><th>Over</th><th>Under</th><th>Hit%</th><th>Edge</th></tr></thead><tbody>${sorted.map(p=>{
        const isGP=isGoalieProp(p.METRIC);const hr=getHitRate(p.PLAYER_NAME,propToLogCol(p.METRIC),parseFloat(p.DK_LINE),isGP);const oIP=impliedProb(parseInt(p.OVER_ODDS));const flags=getSampleFlags(p.PLAYER_NAME,isGP);
        const hrP=hr?`${(hr.overRate*100).toFixed(0)}%`:"—";const ev=hr&&oIP!==null?hr.overRate-oIP:null;
        const evS=ev!==null?`<span class="ev-badge ${ev>0.08?"ev-pos":ev>0?"ev-neutral":"ev-neg"}">${ev>0?"+":""}${(ev*100).toFixed(0)}%</span>`:"—";
        const locked=getLockInfo(p.PLAYER_NAME,isGP).started;
        return`<tr class="${flags.returning?"props-returning":""}${locked?" props-locked":""}"><td style="text-align:left;font-weight:600">${playerLink(p.PLAYER_NAME)}${flags.returning?` <span class="risk-badge risk-returning">⚠️</span>`:flags.limited?` <span class="risk-badge risk-limited">⚠️</span>`:""}${locked?` <span class="locked-badge">🔒</span>`:""}</td><td><span style="color:var(--accent);font-weight:600">${p.METRIC}</span></td><td style="font-weight:700">${p.DK_LINE}</td><td class="${parseInt(p.OVER_ODDS)<=-130?"odds-over":parseInt(p.OVER_ODDS)>=130?"odds-under":"odds-even"}">${fmtOdds(p.OVER_ODDS)}</td><td class="${parseInt(p.UNDER_ODDS)<=-130?"odds-over":parseInt(p.UNDER_ODDS)>=130?"odds-under":"odds-even"}">${fmtOdds(p.UNDER_ODDS)}</td><td style="font-weight:600">${hrP}</td><td>${evS}</td></tr>${renderPropBestBookTableRow(p,7)}`}).join("")}</tbody></table></div>`;
    }
  }

  // ═══ ASSEMBLE ═══
  const showCtrl=activeTab==="dashboard"||activeTab==="gamelog";
  app.innerHTML=`
  <div class="header">
    <div class="header-top"><div class="header-title">NHL DFS Dashboard</div><div style="display:flex;gap:8px"><button class="theme-btn" id="themeBtn">${st.theme==="light"?"🌙 Dark":"☀️ Light"}</button><button class="refresh-btn" id="refreshBtn" ${st.refreshing?"disabled":""}>${st.refreshing?"Refreshing…":"↻ Refresh"}</button></div></div>
    <div class="top-nav"><button class="tab-btn ${activeTab==="dashboard"?"active":""}" onclick="switchTab('dashboard')">Dashboard</button>
<button class="tab-btn ${activeTab==="gamelog"?"active":""}" onclick="switchTab('gamelog')">Game Logs</button>
<button class="tab-btn ${activeTab==="picks"?"active":""}" onclick="switchTab('picks')">Picks</button>
<button class="tab-btn ${activeTab==="entry"?"active":""}" onclick="switchTab('entry')">Builder</button>
<button class="tab-btn ${activeTab==="lookup"?"active":""}" onclick="switchTab('lookup')">Lookup</button>
<button class="tab-btn ${activeTab==="leaders"?"active":""}" onclick="switchTab('leaders')">Leaders</button>
<button class="tab-btn ${activeTab==="stats"?"active":""}" onclick="switchTab('stats')">Performance</button>
<button class="tab-btn ${activeTab==="method"?"active":""}" onclick="switchTab('method')">Info</button></div>
    ${showCtrl?`<div class="header-controls">
      <div class="mode-toggle">
        <button type="button" class="mode-btn" onclick="switchMode('skater')" style="${st.mode==='skater'?'background:var(--accent);color:var(--surface-0);border-color:var(--accent)':'background:var(--surface-1);color:var(--ink-muted)'}">🏒 Skaters</button>
        <button type="button" class="mode-btn" onclick="switchMode('goalie')" style="${st.mode==='goalie'?'background:var(--accent);color:var(--surface-0);border-color:var(--accent)':'background:var(--surface-1);color:var(--ink-muted)'}">🧱 Goalies</button>
      </div>
      <div class="search-wrap">
        <input type="text" id="dashPlayerSearch" aria-label="Search players" list="playerList" placeholder="Search ${st.mode}..." value="${esc(player)}" autocomplete="off" onfocus="this.select()" onchange="if(this.value)pickDashPlayer(this.value)"/>
        <datalist id="playerList">${curTonight.filter(p=>p.player_name).map(p=>`<option value="${esc(p.player_name)}">${esc(p.team_abbr||"")}</option>`).join("")}</datalist>
      </div>
      <div class="ctrl-row">
        <select id="metricSel" aria-label="Metric">${metricOpts}</select>
        <input type="number" id="lineInput" value="${line}" placeholder="Line" aria-label="Comparison line" step="0.5"/>
      </div>
    </div>`:""}
  </div>

  ${renderDailySlate()}
  <div class="page ${activeTab==="dashboard"?"active":""}">${activeTab==="dashboard"?rrDashboard():""}</div>
  <div class="page ${activeTab==="gamelog"?"active":""}">${logHTML}</div>
  <div class="page ${activeTab==="picks"?"active":""}">${picksHTML}</div>
  <div class="page ${activeTab==="stats"?"active":""}">${activeTab==="stats"?rrPerformanceView():""}</div>
  <div class="page ${activeTab==="entry"?"active":""}">${activeTab==="entry"?rrBuilder():""}</div>
  <div class="page ${activeTab==="lookup"?"active":""}">${activeTab==="lookup"?rrLookup():""}</div>
  <div class="page ${activeTab==="leaders"?"active":""}">${activeTab==="leaders"?rrLeaders():""}</div>
  <div class="page ${activeTab==="method"?"active":""}">${activeTab==="method"?rrInfo():""}</div>
  ${rrState().copyFallback?`<section class="rr-panel"><label>Copy selections<textarea readonly>${esc(rrState().copyFallback)}</textarea></label></section>`:""}
  <div class="tab-bar"><button class="tab-btn ${activeTab==="dashboard"?"active":""}" onclick="switchTab('dashboard')">Dashboard</button>
<button class="tab-btn ${activeTab==="gamelog"?"active":""}" onclick="switchTab('gamelog')">Game Logs</button>
<button class="tab-btn ${activeTab==="picks"?"active":""}" onclick="switchTab('picks')">Picks</button>
<button class="tab-btn ${activeTab==="entry"?"active":""}" onclick="switchTab('entry')">Builder</button>
<button class="tab-btn ${activeTab==="lookup"?"active":""}" onclick="switchTab('lookup')">Lookup</button>
<button class="tab-btn ${activeTab==="leaders"?"active":""}" onclick="switchTab('leaders')">Leaders</button>
<button class="tab-btn ${activeTab==="stats"?"active":""}" onclick="switchTab('stats')">Performance</button>
<button class="tab-btn ${activeTab==="method"?"active":""}" onclick="switchTab('method')">Info</button></div>`;

  document.getElementById("metricSel")?.addEventListener("change",e=>{st.metric=e.target.value;render()});
  document.getElementById("lineInput")?.addEventListener("change",e=>{st.line=e.target.value;render()});
  document.getElementById("themeBtn")?.addEventListener("click",toggleTheme);
  document.getElementById("refreshBtn")?.addEventListener("click",loadAllData);
  document.getElementById("oppFilter")?.addEventListener("change",e=>{st.oppFilter=e.target.value;render()});
  document.getElementById("propsSearchInput")?.addEventListener("input",e=>{st.propsSearch=e.target.value;render()});
  document.querySelectorAll("[data-slate-player]").forEach(el=>el.addEventListener("click",()=>streakToDash(el.dataset.slatePlayer)));
  rrBind();
  applyTheme();
  restoreFocus(focus);
}

// ═══ LOAD DATA ═══
function loadAllData(){
  if(st.refreshing)return;
  st.refreshing=true;st.refreshError="";st.error=null;
  st.loading=!st.loadedAt;render();
  Promise.all([
    fetchSheet("Tonights_Skaters").catch(()=>null),
    fetchSheet("Skater_Game_Logs").catch(()=>null),
    fetchSheet("Tonights_Goalies").catch(()=>[]),
    fetchSheet("Goalie_Game_Logs").catch(()=>[]),
    fetchSheet("Home_Away_Splits").catch(()=>[]),
    fetchSheet("Goalie_Home_Away").catch(()=>[]),
    fetchSheet("DK_Player_Props").catch(()=>[]),
    fetchSheet("Daily_Picks").catch(()=>[]),
    fetchSheet("Pick_Performance").catch(()=>[]),
    fetchSheet("Pick_Performance_Snapshots").catch(()=>[]),
    fetchSheet("Slate_Status").catch(()=>[]),
    fetchSheet("Schedule").catch(()=>[])
  ]).then(([tonight,logs,gTonight,gLogs,splits,gSplits,props,picks,pickPerformance,pickPerformanceSnaps,slateStatus,schedule])=>{
    if(!tonight||!logs)throw new Error("Required player sheets unavailable");
    resetDerived();
    st.schedule=normalizeKeys(cleanRows(schedule||[]));
    st.slateStatus=normalizeKeys(cleanRows(slateStatus||[]))[0]||{};
    st.tonight=normalizeKeys(cleanRows(tonight));
    st.gameLogs=normalizeKeys(cleanRows(logs));
    st.gTonight=normalizeKeys(cleanRows(gTonight||[]));
    st.gGameLogs=normalizeKeys(cleanRows(gLogs||[]));
    st.splits=normalizeKeys(cleanRows(splits||[]));
    st.gSplits=normalizeKeys(cleanRows(gSplits||[]));
    st.props=normalizeKeys(cleanRows(props||[]));
    if(st.slateStatus.SLATE_DATE===easternTodayISO() && st.slateStatus.PROP_COUNT!==undefined && Number(st.slateStatus.PROP_COUNT)===0)st.props=[];
    st.pickPerformance=normalizeKeys(cleanRows(pickPerformance||[]));
    st.pickPerformanceSnaps=normalizeKeys(cleanRows(pickPerformanceSnaps||[]));
    st.picks=normalizeKeys(cleanRows(picks||[])).map(p=>({
      ...p,
      player: cleanName(p.player||p.PLAYER||p.Player||p.PLAYER_NAME),
      prop_type: normalizePropMetric(p.prop_type||p.PROP_TYPE||p.Prop_Type),
      lean: normalizeLeanText(p.lean||p.LEAN||p.Lean),
      confidence: normalizeConfidence(p.confidence||p.CONFIDENCE||p.Confidence),
	      DATE: normalizeDate(p.DATE||p.date||p.Date),
	      RUN_NUMBER: toNum(p.RUN_NUMBER||p.run_number||0)
	    }));
	    const DASHBOARD_EXPECTS = {
	      Tonights_Skaters: ['player_name', 'team_abbr', 'opp_abbr_tonight',
	                         'RETURNING', 'LIMITED_SAMPLE', 'L5_GAMES_PLAYED', 'GAMES_LAST_7D'],
	      Daily_Picks: ['DATE', 'player', 'prop_type', 'line', 'lean', 'confidence', 'HIT'],
	      DK_Player_Props: ['PLAYER_NAME', 'METRIC', 'DK_LINE', 'OVER_ODDS', 'UNDER_ODDS'],
	    };
	    const _schemaSources = {
	      Tonights_Skaters: st.tonight,
	      Daily_Picks: st.picks,
	      DK_Player_Props: st.props,
	    };
	    const _schemaIssues = [];
	    for (const [sheet, expectedCols] of Object.entries(DASHBOARD_EXPECTS)) {
	      const rows = _schemaSources[sheet];
	      if (!rows || !rows.length) continue;
	      const actualCols = new Set(Object.keys(rows[0]));
	      const missing = expectedCols.filter(c => !actualCols.has(c));
	      if (missing.length) _schemaIssues.push(`${sheet}: missing [${missing.join(', ')}]`);
	    }
	    if (_schemaIssues.length) {
	      console.warn('⚠️ SCHEMA DRIFT DETECTED:');
	      _schemaIssues.forEach(i => console.warn('  ' + i));
	    } else {
	      console.log('✅ Dashboard schema audit: all expected columns present');
	    }
	    if(String(st.slateStatus.SLATE_DATE||"")===easternTodayISO() && Number(st.slateStatus.GAME_COUNT)===0){
      st.tonight=[];st.gTonight=[];st.props=[];
    }
    st.dataVersion+=1;
    st.latestPickDate=getLatestPickDate();
    const latestPickRun=getLatestPickRun();
    const latestPicks=st.latestPickDate?st.picks.filter(p=>normalizeDate(p.DATE||p.date)===st.latestPickDate&&toNum(p.RUN_NUMBER||p.run_number||0)===latestPickRun):[];
    st.pickGuard=getPickGuard(st.latestPickDate,latestPicks.length);
    st.loading=false;st.refreshing=false;st.loadedAt=new Date().toLocaleTimeString("en-US",{timeZone:"America/New_York",hour:"numeric",minute:"2-digit"});st.lastFetchMs=Date.now();
    const source=st.mode==="goalie"?st.gTonight:st.tonight;
    if(!source.some(p=>p.player_name===st.player)){
      st.player=firstValidPlayer(source);st.line="";
      if(!st.player){st.mode=st.mode==="goalie"?"skater":"goalie";st.metric=st.mode==="goalie"?"SV":"PTS";st.player=firstValidPlayer(st.mode==="goalie"?st.gTonight:st.tonight)}
    }
    console.log(`🏒 NHL Dashboard loaded — mode:${st.mode}, player:"${st.player}"`);
    console.log(`   Skaters: ${st.tonight.length}, Logs: ${st.gameLogs.length}, Goalies: ${st.gTonight.length}`);
    console.log(`   Props: ${st.props.length}, Picks: ${st.picks.length}`);
    if(st.pickGuard)console.warn(`⚠️ ${st.pickGuard.text}`);
    render();
  }).catch(err=>{console.error("❌",err);st.loading=false;st.refreshing=false;if(st.loadedAt)st.refreshError="Refresh failed. Showing the last loaded data.";else st.error="Could not load data. Check the connection and Sheet sharing settings.";render()});
}
loadAllData();
// Refresh published data while the dashboard is open; the engine owns daily updates.
setInterval(()=>{if(!document.hidden)loadAllData()},5*60*1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&Date.now()-(st.lastFetchMs||0)>5*60*1000)loadAllData()});
