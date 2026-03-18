export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  if (req.method === "OPTIONS") return res.status(200).end();

  const { symbol } = req.query;
  const token = process.env.FINNHUB_TOKEN;

  if (!symbol) return res.status(400).json({ error: "symbol required" });
  if (!token)  return res.status(500).json({ error: "FINNHUB_TOKEN not set" });

  try {
    const to   = Math.floor(Date.now() / 1000);
    const from = to - 365 * 86400;

    const [quoteRes, candleRes] = await Promise.all([
      fetch(`https://finnhub.io/api/v1/quote?symbol=${symbol}&token=${token}`),
      fetch(`https://finnhub.io/api/v1/stock/candle?symbol=${symbol}&resolution=W&from=${from}&to=${to}&token=${token}`)
    ]);

    const quote  = await quoteRes.json();
    const candle = await candleRes.json();

    const week52High = candle.h?.length ? Math.max(...candle.h) : quote.h;
    const week52Low  = candle.l?.length ? Math.min(...candle.l) : quote.l;

    let consolidationWeeks = 0;
    if (candle.c?.length) {
      const base = candle.c[candle.c.length - 1];
      for (let i = candle.c.length - 1; i >= 0; i--) {
        if (Math.abs(candle.c[i] - base) / base < 0.10) consolidationWeeks++;
        else break;
      }
    }

    res.status(200).json({
      symbol, price: quote.c, changePercent: quote.dp,
      week52High, week52Low, consolidationWeeks
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
