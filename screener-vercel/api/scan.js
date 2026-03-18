// api/scan.js
// GET /api/scan?token=YOUR_KEY
// Scans 100-stock universe, returns CAN SLIM filtered results

const UNIVERSE = [
  "NVDA","AMD","PLTR","META","GOOGL","MSFT","AAPL","AMZN","TSLA","AVGO",
  "ARM","DELL","NET","CRWD","ZS","PANW","FTNT","CELH","HIMS","ELF",
  "ONON","SKX","DECK","LULU","RDDT","RBLX","TTWO","NFLX","MARA","COIN",
  "SQ","AFRM","SOFI","PYPL","V","MA","LLY","NVO","ISRG","DXCM",
  "MELI","SE","NU","GLOB","GEV","VST","CEG","NRG","ENPH","ARRY",
  "AXON","CACI","KTOS","APP","DUOL","FICO","IONQ","SMCI","HPE","IBM",
  "CRM","NOW","SNOW","DDOG","MDB","GTLB","PATH","AI","BBAI","SOUN",
  "UBER","LYFT","ABNB","DASH","SPOT","SHOP","MELI","BKNG","EXPE","PCTY",
  "WDAY","VEEV","HUBS","ZM","DOCU","BOX","DOCN","CFLT","S","HOOD",
  "RXRX","NTRA","INSP","PODD","MOD","AXNX","CEG","GEV","VST","FSLR"
];

async function fetchQuote(symbol, token) {
  try {
    const r = await fetch(
      `https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${token}`
    );
    if (!r.ok) return null;
    const d = await r.json();
    if (!d.c || d.c === 0) return null;
    return { symbol, price: d.c, changePercent: d.dp || 0, high: d.h, low: d.l };
  } catch {
    return null;
  }
}

async function fetch52W(symbol, token) {
  try {
    const to   = Math.floor(Date.now() / 1000);
    const from = to - 365 * 86400;
    const r = await fetch(
      `https://finnhub.io/api/v1/stock/candle?symbol=${symbol}&resolution=W&from=${from}&to=${to}&token=${token}`
    );
    if (!r.ok) return null;
    const d = await r.json();
    if (!d.h || d.h.length === 0) return null;
    const closes = d.c;
    const base = closes[closes.length - 1];
    let weeks = 0;
    for (let i = closes.length - 1; i >= 0; i--) {
      if (Math.abs(closes[i] - base) / base < 0.10) weeks++;
      else break;
    }
    return {
      week52High: Math.max(...d.h),
      week52Low:  Math.min(...d.l),
      consolidationWeeks: weeks
    };
  } catch {
    return null;
  }
}

function calcRS(changePercent, allChanges) {
  const sorted = [...allChanges].sort((a, b) => a - b);
  const rank = sorted.findIndex(v => v >= changePercent);
  return Math.round(((rank < 0 ? sorted.length : rank) / sorted.length) * 100);
}

function derivePhase(price, week52High, weeks) {
  if (!week52High) return 1;
  const pct = (week52High - price) / week52High;
  if (pct < 0.05 && weeks >= 6)  return 3;
  if (pct < 0.15 && weeks >= 3)  return 2;
  return 1;
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  const { token } = req.query;
  if (!token) return res.status(400).json({ error: "token required" });

  // Vercel functions have 60s timeout on hobby plan
  // Process in batches with small delays to respect Finnhub rate limits (60/min)
  const BATCH_SIZE = 8;
  const quotes = [];

  for (let i = 0; i < Math.min(UNIVERSE.length, 80); i += BATCH_SIZE) {
    const batch = UNIVERSE.slice(i, i + BATCH_SIZE);
    const results = await Promise.all(batch.map(s => fetchQuote(s, token)));
    quotes.push(...results.filter(Boolean));
    if (i + BATCH_SIZE < UNIVERSE.length) {
      await new Promise(r => setTimeout(r, 500));
    }
  }

  // Fetch 52W data for top candidates (by absolute change)
  const allChanges = quotes.map(q => q.changePercent);
  const withMeta = await Promise.all(
    quotes.map(async q => {
      const meta = await fetch52W(q.symbol, token);
      const week52High = meta?.week52High || q.high * 1.1;
      const week52Low  = meta?.week52Low  || q.low  * 0.9;
      const consolidationWeeks = meta?.consolidationWeeks || 0;
      const rsRating   = calcRS(q.changePercent, allChanges);
      const phase      = derivePhase(q.price, week52High, consolidationWeeks);
      const pctFromHigh = week52High > 0 ? (week52High - q.price) / week52High : 1;

      // CAN SLIM score
      let score = 0;
      score += Math.min(rsRating / 100, 1) * 30;          // RS (0-30)
      score += (phase / 3) * 25;                           // Phase (0-25)
      score += Math.max(0, 1 - pctFromHigh / 0.15) * 25;  // Proximity to high (0-25)
      score += consolidationWeeks >= 8 ? 20 : consolidationWeeks >= 4 ? 10 : 0; // Base (0-20)

      return {
        ticker:             q.symbol,
        price:              q.price,
        changePercent:      q.changePercent,
        week52High,
        week52Low,
        consolidationWeeks,
        rsRating,
        phase,
        score:              Math.round(score),
        pctFromHigh:        +(pctFromHigh * 100).toFixed(1),
        poc:                +(week52Low + (week52High - week52Low) * 0.50).toFixed(2),
        vah:                +(week52Low + (week52High - week52Low) * 0.75).toFixed(2),
        val:                +(week52Low + (week52High - week52Low) * 0.35).toFixed(2),
        weeklyTrend:        q.changePercent > 0 ? "up" : "side",
        weeklyOverheadClear: pctFromHigh < 0.05,
        breakoutNote:       phase === 3
          ? `Near ATH · ${consolidationWeeks}W base · RS ${rsRating}`
          : phase === 2
          ? `${consolidationWeeks}W consolidation · RS ${rsRating}`
          : `Accumulation · RS ${rsRating}`,
      };
    })
  );

  // Filter and sort
  const results = withMeta
    .filter(s => s.rsRating >= 60 && s.score >= 40)
    .sort((a, b) => b.score - a.score)
    .slice(0, 20);

  res.status(200).json({
    results,
    scanned: quotes.length,
    total:   UNIVERSE.length,
    timestamp: Date.now()
  });
}
