// api/quote.js
// GET /api/quote?symbol=NVDA&token=YOUR_KEY
// Returns Finnhub quote + 52W high/low for a single ticker

export default async function handler(req, res) {
  // Allow requests from Claude artifacts and any browser
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();

  const { symbol, token } = req.query;
  if (!symbol || !token) {
    return res.status(400).json({ error: "symbol and token required" });
  }

  try {
    const BASE = "https://finnhub.io/api/v1";

    // Fetch quote + 52W candles in parallel
    const [quoteRes, candleRes] = await Promise.all([
      fetch(`${BASE}/quote?symbol=${symbol}&token=${token}`),
      fetch(`${BASE}/stock/candle?symbol=${symbol}&resolution=W&from=${Math.floor(Date.now()/1000)-365*86400}&to=${Math.floor(Date.now()/1000)}&token=${token}`)
    ]);

    const quote  = await quoteRes.json();
    const candle = await candleRes.json();

    const week52High = candle.h ? Math.max(...candle.h) : quote.h;
    const week52Low  = candle.l ? Math.min(...candle.l) : quote.l;

    // Estimate consolidation weeks (weeks within 10% of current price)
    let consolidationWeeks = 0;
    if (candle.c && candle.c.length > 0) {
      const base = candle.c[candle.c.length - 1];
      for (let i = candle.c.length - 1; i >= 0; i--) {
        if (Math.abs(candle.c[i] - base) / base < 0.10) consolidationWeeks++;
        else break;
      }
    }

    res.status(200).json({
      symbol,
      price:              quote.c,
      change:             quote.d,
      changePercent:      quote.dp,
      high:               quote.h,
      low:                quote.l,
      open:               quote.o,
      prevClose:          quote.pc,
      week52High,
      week52Low,
      consolidationWeeks,
      timestamp:          Date.now()
    });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
