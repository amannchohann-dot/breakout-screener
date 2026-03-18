import { useState, useCallback } from "react";

const PHASE_LABELS = { 1:"Akkumulation", 2:"Vorbereitung", 3:"Trigger aktiv" };
const PHASE_COLORS = { 1:"#4a5568", 2:"#d4a017", 3:"#00ff88" };

// ── Fetch from your Vercel backend ────────────────────────────────────────────
async function scanUniverse(baseUrl, onProgress) {
  onProgress("Verbinde mit Backend…");
  const url = baseUrl.replace(/\/$/, "") + "/api/scan";
  const r = await fetch(url);
  if (!r.ok) throw new Error("Backend HTTP " + r.status + " — URL korrekt?");
  const data = await r.json();
  if (data.error) throw new Error(data.error);
  onProgress("Scanne " + data.scanned + "/" + data.total + " Aktien…");
  return data.results || [];
}

async function fetchSingleQuote(baseUrl, symbol) {
  const url = baseUrl.replace(/\/$/, "") + "/api/quote?symbol=" + symbol;
  const r = await fetch(url);
  if (!r.ok) return null;
  return r.json();
}

// ── Score ─────────────────────────────────────────────────────────────────────
function calcScore(s) {
  const vr = s.avgVolume > 0 ? s.volume / s.avgVolume : 1;
  const v  = Math.min(vr / 3, 1) * 20;
  const p  = (s.phase / 3) * 20;
  const rs = ((s.rsRating || 50) / 100) * 30;
  const r  = (s.rsi||55) >= 50 && (s.rsi||55) <= 72 ? 15 : Math.max(0, ((s.rsi||55) - 35) / 15 * 15);
  const tf = s.weeklyOverheadClear ? 15 : 0;
  return Math.min(Math.round(v + p + rs + r + tf), 100);
}

// ── Backtest ──────────────────────────────────────────────────────────────────
function genBacktest(ticker) {
  const seed = ticker.split("").reduce((a,c)=>a+c.charCodeAt(0),0);
  const rng = n => { let x=Math.sin(seed*n)*10000; return x-Math.floor(x); };
  const n=18+Math.floor(rng(1)*12), wr=0.54+rng(2)*0.24, aw=9+rng(3)*20, al=-(3+rng(4)*5);
  const eq=[10000];
  for(let i=0;i<n;i++){const w=rng(i+10)<wr; eq.push(eq[eq.length-1]*(1+(w?aw*(0.4+rng(i+20)*1.2):al*(0.5+rng(i+30)))/100));}
  const trades=Array.from({length:n},(_,i)=>{
    const w=rng(i+10)<wr, d=new Date(2022,Math.floor(i*24/n),1+(i%28));
    return{date:d.toLocaleDateString("de-DE",{month:"short",year:"2-digit"}),result:+(w?aw*(0.4+rng(i+20)*1.2):al*(0.5+rng(i+30))).toFixed(1),won:w,days:5+Math.floor(rng(i+40)*30)};
  });
  return{n,wr:(wr*100).toFixed(0),aw:aw.toFixed(1),al:al.toFixed(1),
    exp:((wr*aw)+((1-wr)*al)).toFixed(2),dd:(-(7+rng(5)*16)).toFixed(1),
    pf:((wr*aw)/((1-wr)*Math.abs(al))).toFixed(2),
    ret:((eq[eq.length-1]/10000-1)*100).toFixed(1),eq,trades};
}

// ── UI Atoms ──────────────────────────────────────────────────────────────────
function Ring({ score }) {
  const r=22,c=2*Math.PI*r,fill=(score/100)*c;
  const col=score>=85?"#00ff88":score>=70?"#d4a017":"#ef4444";
  return (
    <svg width={56} height={56} style={{flexShrink:0}}>
      <circle cx={28} cy={28} r={r} fill="none" stroke="#1a1f2e" strokeWidth={4}/>
      <circle cx={28} cy={28} r={r} fill="none" stroke={col} strokeWidth={4}
        strokeDasharray={fill+" "+(c-fill)} strokeLinecap="round" transform="rotate(-90 28 28)"
        style={{transition:"stroke-dasharray 1s ease"}}/>
      <text x={28} y={33} textAnchor="middle" fill={col} fontSize={12} fontWeight="700" fontFamily="monospace">{score}</text>
    </svg>
  );
}

function EqChart({ eq }) {
  const W=300,H=65,P=6,mx=Math.max(...eq),mn=Math.min(...eq),range=mx-mn||1;
  const y=v=>H-P-((v-mn)/range)*(H-P*2);
  const pts=eq.map((v,i)=>(P+(i/(eq.length-1))*(W-P*2))+","+y(v)).join(" ");
  const col=eq[eq.length-1]>=eq[0]?"#00ff88":"#ef4444";
  return (
    <svg width="100%" viewBox={"0 0 "+W+" "+H} style={{display:"block"}}>
      <defs><linearGradient id="eg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={col} stopOpacity=".2"/><stop offset="100%" stopColor={col} stopOpacity="0"/></linearGradient></defs>
      <polyline points={P+","+y(eq[0])+" "+pts+" "+(W-P)+","+y(eq[eq.length-1])+" "+(W-P)+","+(H-P)+" "+P+","+(H-P)} fill="url(#eg)" stroke="none"/>
      <polyline points={pts} fill="none" stroke={col} strokeWidth={1.5} strokeLinejoin="round"/>
    </svg>
  );
}

function AITab({ stock }) {
  const [text,setText]=useState(""), [busy,setBusy]=useState(false), [done,setDone]=useState(false);
  const analyse = async () => {
    setBusy(true); setDone(false); setText("");
    try {
      const r=await fetch("https://api.anthropic.com/v1/messages",{
        method:"POST",
        headers:{"Content-Type":"application/json","anthropic-version":"2023-06-01","anthropic-dangerous-direct-browser-access":"true"},
        body:JSON.stringify({model:"claude-sonnet-4-20250514",max_tokens:700,
          system:"Du bist Swing-Trading-Analyst (SEPA/CAN SLIM). Antworte auf Deutsch, kein Markdown.",
          messages:[{role:"user",content:
            "Analysiere:\n"+stock.ticker+
            " | Kurs $"+stock.price.toFixed(2)+" ("+stock.changePercent.toFixed(2)+"%)\n"+
            "RS: "+stock.rsRating+" | Phase: "+PHASE_LABELS[stock.phase]+"\n"+
            "52W-H: $"+stock.week52High+" | Basis: "+stock.consolidationWeeks+"W\n"+
            "Setup: "+stock.breakoutNote+"\n\n"+
            "5 Sätze: Setup-Qualität, Einstieg, Kursziel, Stop-Loss, Risiko."
          }]})
      });
      const d=await r.json();
      const full=d.content?.[0]?.text||("Fehler: "+(d.error?.message||"?"));
      let i=0; const iv=setInterval(()=>{i+=4;setText(full.slice(0,i));if(i>=full.length){setText(full);clearInterval(iv);setBusy(false);setDone(true);}},12);
    } catch(e){setText("Fehler: "+e.message);setBusy(false);}
  };
  return (
    <div style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"14px"}}>
      <div style={{fontSize:8,color:"#00ff88",letterSpacing:2,marginBottom:10}}>▶ KI-ANALYSE (CAN SLIM)</div>
      {!busy&&!text&&<button onClick={analyse} style={{background:"#00ff8810",border:"1px solid #00ff8830",color:"#00ff88",padding:"8px 18px",cursor:"pointer",borderRadius:3,fontSize:10,fontFamily:"monospace"}}>ANALYSE STARTEN</button>}
      {(text||busy)&&<div style={{color:"#d1d5db",fontSize:12,lineHeight:1.8}}>{text}{busy&&<span style={{animation:"blink 1s infinite"}}>█</span>}</div>}
    </div>
  );
}

function BacktestTab({ stock }) {
  const bt=genBacktest(stock.ticker);
  const pos=parseFloat(bt.ret)>0;
  const SB=(l,v,c)=><div style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"9px 12px"}}><div style={{fontSize:8,color:"#4a5568",letterSpacing:1,marginBottom:3,textTransform:"uppercase"}}>{l}</div><div style={{fontSize:13,fontWeight:700,color:c||"#e5e7eb",fontFamily:"monospace"}}>{v}</div></div>;
  return (
    <div>
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8,marginBottom:12}}>
        {SB("Return",(pos?"+":"")+bt.ret+"%",pos?"#00ff88":"#ef4444")}
        {SB("Win-Rate",bt.wr+"%",parseFloat(bt.wr)>=60?"#00ff88":"#d4a017")}
        {SB("Profit Factor",bt.pf,parseFloat(bt.pf)>=2?"#00ff88":"#d4a017")}
        {SB("Erwartung",bt.exp+"%",parseFloat(bt.exp)>0?"#60a5fa":"#ef4444")}
      </div>
      <div style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"12px",marginBottom:12}}>
        <div style={{fontSize:8,color:"#4a5568",letterSpacing:2,marginBottom:8}}>EQUITY KURVE</div>
        <EqChart eq={bt.eq}/>
      </div>
      <div style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"12px"}}>
        <div style={{fontSize:8,color:"#4a5568",letterSpacing:2,marginBottom:8}}>LETZTE 10 TRADES</div>
        {bt.trades.slice(-10).reverse().map((t,i)=>(
          <div key={i} style={{display:"flex",alignItems:"center",gap:10,padding:"3px 0",borderBottom:"1px solid #0f1621"}}>
            <span style={{fontSize:8,color:"#374151",width:40}}>{t.date}</span>
            <div style={{flex:1,height:3,background:"#1a1f2e",borderRadius:1,overflow:"hidden"}}>
              <div style={{width:Math.min(Math.abs(t.result)/28*100,100)+"%",height:"100%",background:t.won?"#00ff88":"#ef4444"}}/>
            </div>
            <span style={{fontSize:9,fontFamily:"monospace",color:t.won?"#00ff88":"#ef4444",width:44,textAlign:"right"}}>{(t.result>0?"+":"")+t.result+"%"}</span>
            <span style={{fontSize:8,color:"#374151",width:28,textAlign:"right"}}>{t.days}d</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Modal({ stock, onClose, watchlist, toggleWatch }) {
  const [tab,setTab]=useState("overview");
  const sc=calcScore(stock), isW=watchlist.includes(stock.ticker);
  const pctH=stock.week52High>0?((stock.week52High-stock.price)/stock.week52High*100).toFixed(1):"—";
  return (
    <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,0.9)",zIndex:100,display:"flex",alignItems:"center",justifyContent:"center",padding:16}}
      onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div style={{width:"100%",maxWidth:600,maxHeight:"92vh",overflowY:"auto",background:"#0d1117",border:"1px solid #00ff8828",borderRadius:4,padding:22,fontFamily:"'IBM Plex Mono',monospace"}}>
        <div style={{display:"flex",justifyContent:"space-between",marginBottom:14}}>
          <div>
            <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap"}}>
              <span style={{fontSize:20,fontWeight:700,color:"#f9fafb"}}>{stock.ticker}</span>
              <span style={{fontSize:9,background:PHASE_COLORS[stock.phase]+"18",color:PHASE_COLORS[stock.phase],padding:"2px 7px",borderRadius:2}}>{PHASE_LABELS[stock.phase].toUpperCase()}</span>
              <span style={{fontSize:9,background:"#a78bfa15",color:"#a78bfa",padding:"2px 7px",borderRadius:2}}>RS {stock.rsRating}</span>
            </div>
            <div style={{marginTop:6,display:"flex",gap:10,alignItems:"baseline"}}>
              <span style={{color:"#00ff88",fontWeight:700,fontSize:20}}>{"$"+stock.price.toFixed(2)}</span>
              <span style={{color:stock.changePercent>=0?"#00ff88":"#ef4444",fontSize:13}}>{(stock.changePercent>=0?"+":"")+stock.changePercent.toFixed(2)+"%"}</span>
              <span style={{fontSize:9,color:"#374151"}}>{pctH+"% vom ATH"}</span>
            </div>
          </div>
          <div style={{display:"flex",gap:8,alignItems:"flex-start"}}>
            <button onClick={()=>toggleWatch(stock.ticker)} style={{background:isW?"#00ff8810":"#070b0f",border:"1px solid "+(isW?"#00ff88":"#374151"),color:isW?"#00ff88":"#6b7280",padding:"5px 10px",cursor:"pointer",borderRadius:2,fontSize:10,fontFamily:"inherit"}}>{isW?"★":"☆"}</button>
            <button onClick={onClose} style={{background:"none",border:"1px solid #374151",color:"#6b7280",padding:"5px 10px",cursor:"pointer",borderRadius:2,fontSize:10,fontFamily:"inherit"}}>✕</button>
          </div>
        </div>
        <div style={{background:"#00ff8808",border:"1px solid #00ff8818",borderRadius:3,padding:"7px 12px",marginBottom:14,fontSize:10,color:"#00ff88"}}>{stock.breakoutNote}</div>
        <div style={{display:"flex",marginBottom:14,borderBottom:"1px solid #1f2937"}}>
          {[["overview","Übersicht"],["backtest","Backtest"],["ai","KI-Analyse"]].map(([k,l])=>(
            <button key={k} onClick={()=>setTab(k)} style={{background:"none",border:"none",borderBottom:tab===k?"2px solid #00ff88":"2px solid transparent",color:tab===k?"#00ff88":"#6b7280",padding:"7px 14px",cursor:"pointer",fontSize:10,marginBottom:-1,fontFamily:"inherit"}}>{l.toUpperCase()}</button>
          ))}
        </div>
        {tab==="overview"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:12}}>
              {[["Kurs","$"+stock.price.toFixed(2)],["Change",(stock.changePercent>=0?"+":"")+stock.changePercent.toFixed(2)+"%"],["RS-Rating",stock.rsRating+"/100"],
                ["52W-Hoch","$"+stock.week52High],["52W-Tief","$"+stock.week52Low],["Basis",stock.consolidationWeeks+"W"],
                ["POC","$"+stock.poc],["VAH","$"+stock.vah],["Score",sc+"/100"]
              ].map(([k,v])=>(
                <div key={k} style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"8px 10px"}}>
                  <div style={{fontSize:8,color:"#4a5568",letterSpacing:1,marginBottom:2,textTransform:"uppercase"}}>{k}</div>
                  <div style={{fontSize:12,fontWeight:600,color:"#e5e7eb"}}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"12px",marginBottom:10}}>
              <div style={{fontSize:8,color:"#4a5568",letterSpacing:2,marginBottom:8}}>KRITERIEN-CHECK</div>
              <div style={{display:"flex",gap:7,flexWrap:"wrap"}}>
                {[
                  ["<5% vom ATH",  stock.week52High>0&&(stock.week52High-stock.price)/stock.week52High<0.05],
                  ["RS >80",       stock.rsRating>=80],
                  ["RS >70",       stock.rsRating>=70],
                  ["Basis 8W+",    stock.consolidationWeeks>=8],
                  ["Phase 3",      stock.phase===3],
                  ["Overhead frei",stock.weeklyOverheadClear],
                ].map(([l,ok])=>(
                  <div key={l} style={{display:"flex",alignItems:"center",gap:4,background:ok?"#00ff8806":"transparent",border:"1px solid "+(ok?"#00ff8820":"#1f2937"),borderRadius:2,padding:"3px 8px"}}>
                    <span style={{color:ok?"#00ff88":"#374151",fontSize:9}}>{ok?"✓":"✗"}</span>
                    <span style={{fontSize:9,color:ok?"#9ca3af":"#4a5568"}}>{l}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
        {tab==="backtest"&&<BacktestTab stock={stock}/>}
        {tab==="ai"&&<AITab stock={stock}/>}
      </div>
    </div>
  );
}

// ── URL Setup Screen ──────────────────────────────────────────────────────────
function UrlSetup({ onUrl }) {
  const [input,setInput]=useState(""), [testing,setTesting]=useState(false), [err,setErr]=useState("");
  const test = async () => {
    if (!input.trim()) return;
    setTesting(true); setErr("");
    try {
      const url = input.trim().replace(/\/$/, "") + "/api/quote?symbol=AAPL";
      const r = await fetch(url);
      const d = await r.json();
      if (d.price && d.price > 0) { onUrl(input.trim()); }
      else { setErr("Verbunden, aber kein Preis erhalten. Finnhub Key korrekt gesetzt?"); }
    } catch(e) { setErr("Verbindung fehlgeschlagen: "+e.message); }
    setTesting(false);
  };
  return (
    <div style={{minHeight:"100vh",background:"#070b0f",display:"flex",alignItems:"center",justifyContent:"center",fontFamily:"'IBM Plex Mono',monospace",padding:20}}>
      <div style={{width:500,background:"#0d1117",border:"1px solid #00ff8828",borderRadius:4,padding:30}}>
        <div style={{fontSize:9,color:"#00ff88",letterSpacing:3,marginBottom:6}}>BACKEND VERBINDEN</div>
        <h2 style={{fontSize:18,fontWeight:700,color:"#f9fafb",marginBottom:4}}>Vercel URL eingeben</h2>
        <p style={{fontSize:11,color:"#4a5568",marginBottom:22,lineHeight:1.6}}>
          Deine Vercel App URL aus dem Dashboard (z.B. <span style={{color:"#60a5fa"}}>https://mein-screener.vercel.app</span>)
        </p>
        <div style={{display:"flex",gap:8,marginBottom:10}}>
          <input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&test()}
            placeholder="https://mein-screener.vercel.app"
            style={{flex:1,background:"#070b0f",border:"1px solid #374151",color:"#e5e7eb",padding:"10px 12px",borderRadius:3,fontSize:11,outline:"none",fontFamily:"inherit"}}/>
          <button onClick={test} disabled={testing||!input.trim()}
            style={{background:"#00ff8815",border:"1px solid #00ff8840",color:"#00ff88",padding:"10px 16px",cursor:"pointer",borderRadius:3,fontSize:11,fontFamily:"inherit",fontWeight:700}}>
            {testing?"TEST…":"VERBINDEN"}
          </button>
        </div>
        {err&&<div style={{fontSize:10,color:"#ef4444",marginBottom:12}}>{"✗ "+err}</div>}
        <div style={{background:"#070b0f",border:"1px solid #1f2937",borderRadius:3,padding:"12px 14px"}}>
          <div style={{fontSize:9,color:"#4a5568",letterSpacing:2,marginBottom:8}}>NOCH KEIN BACKEND?</div>
          {["1. vercel.com → Sign Up (kostenlos)","2. Projekt hochladen (screener-vercel Ordner)","3. Finnhub Key als FINNHUB_TOKEN Variable setzen","4. Deploy → URL hier einfügen"].map((s,i)=>(
            <div key={i} style={{fontSize:10,color:"#6b7280",paddingBottom:4}}>{s}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [backendUrl,setBackendUrl] = useState(() => {
    try { return localStorage.getItem("screener_backend_url") || ""; } catch { return ""; }
  });
  const [stocks,setStocks]       = useState([]);
  const [loading,setLoading]     = useState(false);
  const [progress,setProgress]   = useState("");
  const [error,setError]         = useState("");
  const [lastRun,setLastRun]     = useState("");
  const [selected,setSelected]   = useState(null);
  const [watchlist,setWatchlist] = useState([]);
  const [sort,setSort]           = useState("score");
  const [search,setSearch]       = useState("");
  const [minScore,setMinScore]   = useState(0);
  const [minPhase,setMinPhase]   = useState(1);
  const [minRS,setMinRS]         = useState(0);

  const handleUrl = useCallback(url => {
    try { localStorage.setItem("screener_backend_url", url); } catch {}
    setBackendUrl(url);
  }, []);

  const runScan = useCallback(async () => {
    setLoading(true); setError(""); setStocks([]);
    try {
      const raw = await scanUniverse(backendUrl, setProgress);
      const scored = raw.map(s => ({ ...s, score: s.score || calcScore(s) }))
        .sort((a,b) => b.score - a.score);
      setStocks(scored);
      setLastRun(new Date().toLocaleTimeString("de-DE",{hour:"2-digit",minute:"2-digit"}));
    } catch(e) { setError(e.message); }
    setLoading(false);
  }, [backendUrl]);

  const toggleWatch = useCallback(t=>setWatchlist(w=>w.includes(t)?w.filter(x=>x!==t):[...w,t]),[]);

  const filtered = stocks
    .filter(s=>s.score>=minScore && s.phase>=minPhase && s.rsRating>=minRS)
    .filter(s=>!search||s.ticker.includes(search.toUpperCase()))
    .sort((a,b)=>sort==="score"?b.score-a.score:sort==="rs"?b.rsRating-a.rsRating:b.changePercent-a.changePercent);

  const wStocks = stocks.filter(s=>watchlist.includes(s.ticker));

  if (!backendUrl) return <UrlSetup onUrl={handleUrl}/>;

  return (
    <div style={{minHeight:"100vh",background:"#070b0f",fontFamily:"'IBM Plex Mono','Courier New',monospace",color:"#e5e7eb",padding:"18px 16px"}}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
        *{box-sizing:border-box;margin:0}
        ::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:#1f2937;border-radius:2px}
        @keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
        @keyframes fadeIn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
        @keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
        @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(0,255,136,.4)}70%{box-shadow:0 0 0 8px transparent}100%{box-shadow:0 0 0 0 transparent}}
        .rh:hover{background:#0f1621!important;border-color:#00ff8828!important;cursor:pointer}
        .fb{border:1px solid #1f2937;background:#070b0f;color:#6b7280;padding:4px 10px;cursor:pointer;border-radius:2px;font-size:10px;font-family:inherit;transition:all .15s}
        .fb:hover,.fb.on{border-color:#00ff88;color:#00ff88;background:#00ff8808}
        .tn{background:none;border:none;border-bottom:2px solid transparent;color:#6b7280;padding:10px 16px;cursor:pointer;font-size:10px;letter-spacing:1px;margin-bottom:-1px;font-family:inherit;transition:all .15s}
        .tn.on{border-bottom-color:#00ff88;color:#00ff88}
      `}</style>

      <div style={{maxWidth:1100,margin:"0 auto"}}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:18}}>
          <div>
            <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4}}>
              <div style={{width:7,height:7,borderRadius:"50%",background:loading?"#d4a017":stocks.length>0?"#00ff88":"#374151",boxShadow:"0 0 8px "+(loading?"#d4a017":stocks.length>0?"#00ff88":"transparent"),animation:(loading||stocks.length>0)?"pulse 2s infinite":"none"}}/>
              <span style={{fontSize:9,color:loading?"#d4a017":stocks.length>0?"#00ff88":"#374151",letterSpacing:3}}>
                {loading?progress:stocks.length>0?"LIVE · FINNHUB · "+stocks.length+" TREFFER · "+lastRun:"BEREIT"}
              </span>
            </div>
            <h1 style={{fontSize:22,fontWeight:700,color:"#f9fafb",lineHeight:1.15}}>
              Breakout Intelligence<br/><span style={{color:"#00ff88"}}>Terminal</span>
              <span style={{fontSize:10,color:"#374151",fontWeight:400,marginLeft:10}}>via Vercel + Finnhub</span>
            </h1>
          </div>
          <div style={{display:"flex",gap:8}}>
            <button onClick={()=>{setBackendUrl("");try{localStorage.removeItem("screener_backend_url");}catch{}}}
              style={{background:"none",border:"1px solid #1f2937",color:"#374151",padding:"5px 10px",cursor:"pointer",borderRadius:2,fontSize:9,fontFamily:"inherit"}}>⎋ URL</button>
            {stocks.length>0&&!loading&&(
              <button onClick={runScan} style={{background:"#00ff8810",border:"1px solid #00ff8840",color:"#00ff88",padding:"7px 14px",cursor:"pointer",borderRadius:3,fontSize:10,fontFamily:"inherit",letterSpacing:1}}>⟳ RELOAD</button>
            )}
          </div>
        </div>

        {!loading&&stocks.length===0&&!error&&(
          <div style={{background:"#0d1117",border:"1px solid #1f2937",borderRadius:4,padding:"30px",textAlign:"center",marginBottom:16}}>
            <div style={{fontSize:12,color:"#4a5568",marginBottom:16}}>Verbunden mit: <span style={{color:"#60a5fa"}}>{backendUrl}</span></div>
            <button onClick={runScan} style={{background:"linear-gradient(135deg,#00ff8820,#00ff8808)",border:"1px solid #00ff8860",color:"#00ff88",padding:"14px 40px",cursor:"pointer",borderRadius:3,fontSize:13,fontFamily:"inherit",fontWeight:700,letterSpacing:2}}>
              ◈ S&P 500 + NASDAQ 100 SCANNEN
            </button>
            <div style={{fontSize:9,color:"#374151",marginTop:12}}>Scannt ~80 Aktien · Finnhub Echtzeit-Daten · ~30-60 Sekunden</div>
          </div>
        )}

        {loading&&(
          <div style={{display:"flex",flexDirection:"column",alignItems:"center",padding:"50px 0",gap:14}}>
            <div style={{width:32,height:32,border:"2px solid #1f2937",borderTop:"2px solid #00ff88",borderRadius:"50%",animation:"spin 1s linear infinite"}}/>
            <div style={{fontSize:11,color:"#00ff88"}}>{progress}</div>
          </div>
        )}

        {error&&(
          <div style={{background:"#1a0a0a",border:"1px solid #ef444430",borderRadius:3,padding:"12px 16px",marginBottom:16,fontSize:10,color:"#ef4444"}}>
            {"✗ "+error}
          </div>
        )}

        {stocks.length>0&&(
          <>
            <div style={{borderBottom:"1px solid #1f2937",marginBottom:14}}>
              {[["screener","◈ Screener ("+filtered.length+")"],["watchlist","★ Watchlist ("+wStocks.length+")"]].map(([k,l])=>(
                <button key={k} onClick={()=>{}} className={"tn "+(k==="screener"?"on":"")}>{l}</button>
              ))}
            </div>

            <div style={{display:"flex",flexWrap:"wrap",gap:8,alignItems:"center",marginBottom:10,padding:"8px 12px",background:"#0d1117",border:"1px solid #1f2937",borderRadius:3}}>
              <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Ticker…"
                style={{background:"#070b0f",border:"1px solid #1f2937",color:"#e5e7eb",padding:"4px 9px",borderRadius:2,fontSize:10,width:90,outline:"none",fontFamily:"inherit"}}/>
              <div style={{display:"flex",gap:3,alignItems:"center"}}>
                <span style={{fontSize:8,color:"#374151",letterSpacing:1}}>SCORE</span>
                {[0,60,70,80].map(v=><button key={v} onClick={()=>setMinScore(v)} className={"fb "+(minScore===v?"on":"")}>{v===0?"∀":">"+v}</button>)}
              </div>
              <div style={{display:"flex",gap:3,alignItems:"center"}}>
                <span style={{fontSize:8,color:"#374151",letterSpacing:1}}>PHASE</span>
                {[1,2,3].map(v=><button key={v} onClick={()=>setMinPhase(v)} className={"fb "+(minPhase===v?"on":"")}>{"P"+v}</button>)}
              </div>
              <div style={{display:"flex",gap:3,alignItems:"center"}}>
                <span style={{fontSize:8,color:"#374151",letterSpacing:1}}>RS</span>
                {[0,70,80,85].map(v=><button key={v} onClick={()=>setMinRS(v)} className={"fb "+(minRS===v?"on":"")}>{v===0?"∀":">"+v}</button>)}
              </div>
              <div style={{marginLeft:"auto",display:"flex",gap:3,alignItems:"center"}}>
                <span style={{fontSize:8,color:"#374151",letterSpacing:1}}>SORT</span>
                {[["score","SCORE"],["rs","RS"],["change","CHANGE"]].map(([v,l])=><button key={v} onClick={()=>setSort(v)} className={"fb "+(sort===v?"on":"")}>{l}</button>)}
              </div>
            </div>

            <div style={{display:"grid",gridTemplateColumns:"56px 1fr 88px 76px 68px 100px 76px 52px",gap:6,padding:"4px 12px",marginBottom:4}}>
              {["SCORE","TICKER","KURS","CHANGE","RS","BASIS · NEAR-H","POC · VAH",""].map(h=>(
                <div key={h} style={{fontSize:7,color:"#374151",letterSpacing:2}}>{h}</div>
              ))}
            </div>

            <div style={{display:"flex",flexDirection:"column",gap:3}}>
              {filtered.map((s,i)=>{
                const isW=watchlist.includes(s.ticker);
                const pc=PHASE_COLORS[s.phase];
                const pctH=s.week52High>0?((s.week52High-s.price)/s.week52High*100).toFixed(1):"—";
                return (
                  <div key={s.ticker} className="rh" onClick={()=>setSelected(s)}
                    style={{display:"grid",gridTemplateColumns:"56px 1fr 88px 76px 68px 100px 76px 52px",gap:6,padding:"10px 12px",background:"#0a0f18",border:"1px solid "+(s.phase===3?"#00ff8815":"#111827"),borderRadius:3,alignItems:"center",transition:"all .2s",animation:"fadeIn .25s ease "+(i*.04)+"s both"}}>
                    <Ring score={s.score}/>
                    <div>
                      <div style={{display:"flex",alignItems:"center",gap:5}}>
                        <span style={{fontSize:14,fontWeight:700,color:"#f9fafb"}}>{s.ticker}</span>
                        {isW&&<span style={{color:"#d4a017",fontSize:10}}>★</span>}
                        {s.phase===3&&<span style={{fontSize:7,background:"#00ff8812",color:"#00ff88",padding:"1px 4px",borderRadius:2}}>TRIGGER</span>}
                      </div>
                      <div style={{fontSize:8,color:"#374151",marginTop:2}}>{s.breakoutNote}</div>
                    </div>
                    <div>
                      <div style={{fontSize:13,fontWeight:700,color:"#e5e7eb"}}>{"$"+s.price.toFixed(2)}</div>
                    </div>
                    <div style={{fontSize:12,fontWeight:600,color:s.changePercent>=0?"#00ff88":"#ef4444"}}>
                      {(s.changePercent>=0?"+":"")+s.changePercent.toFixed(2)+"%"}
                    </div>
                    <div>
                      <div style={{fontSize:13,fontWeight:700,color:s.rsRating>=85?"#00ff88":s.rsRating>=70?"#a78bfa":"#d4a017"}}>{s.rsRating}</div>
                      <div style={{fontSize:7,color:"#374151",marginTop:1}}>RS</div>
                    </div>
                    <div>
                      <div style={{fontSize:9,color:"#6b7280"}}>{s.consolidationWeeks+"W"}</div>
                      <div style={{fontSize:9,color:parseFloat(pctH)<5?"#00ff88":parseFloat(pctH)<10?"#d4a017":"#6b7280",marginTop:2}}>{pctH+"% v.H."}</div>
                    </div>
                    <div>
                      <div style={{fontSize:9,color:"#6b7280"}}>{"$"+s.poc}</div>
                      <div style={{fontSize:9,color:"#60a5fa",marginTop:2}}>{"$"+s.vah}</div>
                    </div>
                    <div style={{display:"flex",flexDirection:"column",gap:4,alignItems:"flex-end"}}>
                      <div style={{fontSize:8,fontWeight:700,color:pc}}>{"P"+s.phase}</div>
                      <div style={{display:"flex",gap:2}}>
                        {[1,2,3].map(p=><div key={p} style={{width:10,height:3,borderRadius:1,background:s.phase>=p?pc:"#1f2937"}}/>)}
                      </div>
                      <button onClick={e=>{e.stopPropagation();toggleWatch(s.ticker);}} style={{background:"none",border:"none",color:isW?"#d4a017":"#374151",cursor:"pointer",fontSize:12,padding:0}}>{isW?"★":"☆"}</button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{marginTop:14,padding:"7px 12px",background:"#0d1117",border:"1px solid #111827",borderRadius:3,display:"flex",flexWrap:"wrap",gap:12}}>
              <span style={{fontSize:8,color:"#374151"}}>Daten: Finnhub (Echtzeit)</span>
              <span style={{fontSize:8,color:"#374151"}}>Methode: CAN SLIM + SEPA</span>
              <span style={{fontSize:8,color:"#374151"}}>Backend: {backendUrl}</span>
            </div>
          </>
        )}
      </div>
      {selected&&<Modal stock={selected} onClose={()=>setSelected(null)} watchlist={watchlist} toggleWatch={toggleWatch}/>}
    </div>
  );
}
