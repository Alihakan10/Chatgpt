const TradingView = require("@mathieuc/tradingview");

const TV_INDICATOR = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const TIMEFRAME = "120";
const RANGE = 500;
const MULTIPLIER = 2.0;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isCompletedBar(period) {
  if (!period || period.$time == null) return false;

  const dt = new Date(Number(period.$time) * 1000);

  // TradingView BIST 2H session: the 17:00 bar closes at 18:00.
  let end = new Date(dt.getTime() + 2 * 60 * 60 * 1000);

  if (dt.getHours() === 17 && dt.getMinutes() === 0) {
    end = new Date(dt);
    end.setHours(18, 0, 0, 0);
  }

  return end.getTime() <= Date.now();
}

async function getExactBuy(symbol) {
  const client = new TradingView.Client();

  try {
    const indicator = await TradingView.getIndicator(TV_INDICATOR);
    indicator.setOption("ATR_Multiplier", MULTIPLIER);

    const chart = new client.Session.Chart();
    chart.setMarket(symbol, {
      timeframe: TIMEFRAME,
      range: RANGE,
      session: "regular",
      adjustment: "splits"
    });

    const study = new chart.Study(indicator);

    const result = await new Promise((resolve, reject) => {
      let settled = false;

      const finish = value => {
        if (settled) return;
        settled = true;
        resolve(value);
      };

      study.onError((...err) => {
        if (!settled) reject(new Error(JSON.stringify(err)));
      });

      study.onReady(() => {
        // Wait for the first full study update.
      });

      study.onUpdate((changes) => {
        if (!changes || !changes.includes("plots")) return;

        const periods = Array.isArray(study.periods)
          ? study.periods
          : [];

        if (!periods.length) return;

        const completed = periods.filter(isCompletedBar);

        if (!completed.length) return;

        const current = completed[0];
        const previous = completed[1];

        const buy =
          Number(current.SuperTrend_Buy) === 1 &&
          Number(current.SuperTrend_Direction_Change) === 1;

        finish({
          symbol,
          buy,
          candle_time: Number(current.$time),
          price: Number(current.close),
          current_buy: current.SuperTrend_Buy,
          current_change: current.SuperTrend_Direction_Change,
          previous_buy: previous ? previous.SuperTrend_Buy : null,
          previous_change: previous ? previous.SuperTrend_Direction_Change : null
        });
      });

      setTimeout(() => {
        if (!settled) reject(new Error("TradingView study timeout"));
      }, 15000);
    });

    return result;
  } finally {
    try { client.end(); } catch (_) {}
  }
}

async function getSymbols() {
  const response = await fetch("https://scanner.tradingview.com/turkey/scan", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      filter: [],
      options: {lang: "tr"},
      symbols: {query: {types: []}, tickers: []},
      columns: ["name"],
      sort: {sortBy: "name", sortOrder: "asc"},
      range: [0, 1000]
    })
  });

  if (!response.ok) {
    throw new Error("TradingView scanner HTTP " + response.status);
  }

  const data = await response.json();
  return [...new Set(
    (data.data || [])
      .map(x => x.s)
      .filter(x => typeof x === "string" && x.startsWith("BIST:"))
  )].slice(0, LIMIT);
}

async function main() {
  const symbols = await getSymbols();

  console.log("=".repeat(70));
  console.log("TRADINGVIEW GERCEK BUY ETIKET TESTI");
  console.log("Hisse: " + symbols.length);
  console.log("ATR Period: 10 | Multiplier: 2.0 | Source: HL2 | Timeframe: 2H");
  console.log("Kaynak: TradingView SuperTrend study output");
  console.log("=".repeat(70));

  const buys = [];
  let errors = 0;

  for (let i = 0; i < symbols.length; i++) {
    const symbol = symbols[i];
    console.log(`[${i + 1}/${symbols.length}] ${symbol}`);

    try {
      const result = await getExactBuy(symbol);

      if (result.buy) {
        buys.push(result);
        console.log("    >>> GERCEK BUY ETIKETI: " + symbol);
      }
    } catch (e) {
      errors++;
      console.log("    HATA: " + String(e.message || e));
    }

    await sleep(50);
  }

  console.log("");
  console.log("=".repeat(70));
  console.log("TARAMA TAMAMLANDI");
  console.log("Toplam hisse: " + symbols.length);
  console.log("GERCEK BUY ETIKETI: " + buys.length);
  console.log("Hata: " + errors);
  console.log("=".repeat(70));

  if (buys.length === 0) {
    console.log("BUY etiketi bulunamadi; Telegram gonderilmeyecek.");
    return;
  }

  const lines = [
    "TRADINGVIEW GERCEK BUY ETIKETI",
    "",
    "BIST 2 SAATLİK SUPERTREND",
    "ATR Periyodu: 10",
    "ATR Çarpanı: 2",
    "Kaynak: HL2",
    "",
    "BUY SİNYALI: " + buys.length + " adet",
    ""
  ];

  for (const r of buys) {
    const dt = new Date(r.candle_time * 1000);
    const price = Number.isFinite(r.price) ? r.price.toFixed(2) : "-";
    lines.push(
      "🟢 " + r.symbol.replace("BIST:", "") + "   " + price + " TL"
    );
    lines.push(
      "   Mum: " +
      dt.toLocaleString("tr-TR", {timeZone: "Europe/Istanbul", hour12: false})
    );
  }

  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;

  if (!token || !chatId) {
    throw new Error("Telegram secret eksik.");
  }

  const response = await fetch(
    "https://api.telegram.org/bot" + token + "/sendMessage",
    {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        chat_id: chatId,
        text: lines.join("\n"),
        disable_web_page_preview: true
      })
    }
  );

  const telegram = await response.json();

  if (!response.ok || !telegram.ok) {
    throw new Error("Telegram HTTP " + response.status + ": " + JSON.stringify(telegram));
  }

  console.log("GERCEK BUY ETIKET LISTESI TELEGRAM'A GONDERILDI.");
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
