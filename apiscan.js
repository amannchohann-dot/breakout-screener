const UNIVERSE = [
  "NVDA","AMD","PLTR","META","GOOGL","MSFT","AAPL","AMZN","TSLA","AVGO",
  "ARM","NET","CRWD","ZS","PANW","CELH","HIMS","ONON","SKX","DECK",
  "RDDT","RBLX","NFLX","MARA","COIN","SQ","AFRM","SOFI","LLY","ISRG",
  "MELI","SE","NU","GEV","VST","CEG","AXON","APP","DUOL","FICO",
  "IONQ","SMCI","CRM","NOW","SNOW","DDOG","UBER","ABNB","SHOP","HOOD"
];

async function fetchQuote(symbol, token) {
  try {
    const r = await fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${token}`);
    if (!r.ok) return null;
    const d = await r.json();
    if (!d.c || d.c === 0) return null;
    return { symbol, price: d.c, changePercent: d.dp || 0 };
  } catch { return null; }
}

function calcRS(changePercent, allChanges) {
  const sorted = [...allChanges].sort((a, b) => a - b);
  const rank = sorted.findIndex(v => v >= changePercent);
  return Math.round(((rank < 0 ? sorted.length : rank) / sorted.length) * 100);
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") return res.status(200).end();

  const token = process.env.FINNHUB_TOKEN;
  if (!token) return res.status(500).json({ error: "FINNHUB_TOKEN not set in Environment Variables" });

  const quotes = [];
  const BATCH = 10;

  for (let i = 0; i < UNIVERSE.length; i += BATCH) {
    const batch = UNIVERSE.slice(i, i + BATCH);
    const results = await Promise.all(batch.map(s => fetchQuote(s, token)));
    quotes.push(...results.filter(Boolean));
    if (i + BATCH < UNIVERSE.length) await new Promise(r => setTimeout(r, 600));
  }

  const allChanges = quotes.map(q => q.changePercent);

  const results = quotes.map(q => {
    const rsRating = calcRS(q.changePercent, allChanges);
    const phase    = rsRating >= 80 ? 3 : rsRating >= 60 ? 2 : 1;
    const score    = Math.round((rsRating / 100) * 60 + (phase / 3) * 40);
    return {
      ticker: q.symbol, price: q.price, changePercent: q.changePercent,
      rsRating, phase, score,
      week52High: 0, week52Low: 0, consolidationWeeks: 8,
      poc: +(q.price * 0.92).toFixed(2),
      vah: +(q.price * 0.99).toFixed(2),
      val: +(q.price * 0.85).toFixed(2),
      weeklyTrend: q.changePercent > 0 ? "up" : "side",
      weeklyOverheadClear: rsRating >= 80,
      breakoutNote: `RS ${rsRating} · Phase ${phase}`,
    };
  }).filter(s => s.rsRating >= 50).sort((a, b) => b.score - a.score).slice(0, 15);

  res.status(200).json({ results, scanned: quotes.length, total: UNIVERSE.length, timestamp: Date.now() });
}
