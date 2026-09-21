const TradingView = require("@mathieuc/tradingview");
const fs = require("fs");

const INDICATOR_ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const TIMEFRAME = "120";
const RANGE = 500;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");
const WORKERS = 4;
const TEST_MODE = process.env.TEST_MODE === "true";
const TEST_SYMBOLS = (process.env.TEST_SYMBOLS || "").split(",").map(s => s.trim()).filter(Boolean);
const FORCE_SCAN = process.env.FORCE_SCAN === "true";
const SEND_SCAN_REPORT = process.env.SEND_SCAN_REPORT !== "false";
const STATE_FILE = "state/supertrend_state.json";
const TZ = "Europe/Istanbul";

const sleep = ms => new Promise(r => setTimeout(r, ms));

function fmt(ts) {
  return new Intl.DateTimeFormat("tr-TR", {
    timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false
  }).format(new Date(Number(ts) * 1000));
}

function completed(period) {
  if (!period || period.$time == null) return false;
  return Number(period.$time) + 2 * 60 * 60 <= Math.floor(Date.now() / 1000);
}

async function getSymbols() {
  const response = await fetch("https://scanner.tradingview.com/turkey/scan", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      filter: [], options: {lang:"tr"},
      symbols: {query:{types:[]}, tickers:[]},
      columns: ["name"],
      sort: {sortBy:"name", sortOrder:"asc"},
      range: [0,1000]
    })
  });
  if (!response.ok) throw new Error("Scanner HTTP " + response.status);
  const data = await response.json();
  return [...new Set((data.data || []).map(x => x.s)
    .filter(x => typeof x === "string" && x.startsWith("BIST:")))].slice(0, LIMIT);
}

function applyIndicatorOptions(indicator) {
  indicator.setOption("ATR_Period", 10);
  indicator.setOption("Source", "hl2");
  indicator.setOption("ATR_Multiplier", 2.0);
  indicator.setOption("Change_ATR_Calculation_Method_", true);
  indicator.setOption("Show_BuySell_Signals_", true);
  indicator.setOption("Highlighter_OnOff_", true);
}

async function scanOne(symbol, attempt = 1) {
  let client = null, chart = null, study = null;
  try {
    client = new TradingView.Client();
    client.onError(() => {});
    chart = new client.Session.Chart();

    const indicator = await TradingView.getIndicator(INDICATOR_ID);
    applyIndicatorOptions(indicator);

    return await new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (!settled) { settled = true; reject(new Error("Study timeout")); }
      }, 20000);

      const fail = err => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          reject(err instanceof Error ? err : new Error(String(err)));
        }
      };

      chart.onSymbolLoaded(() => {
        try {
          study = new chart.Study(indicator);

          study.onError((...err) => fail(new Error("Study: " + JSON.stringify(err))));

          const readStudy = () => {
            setTimeout(() => {
              if (settled) return;
              try {
                const periods = (Array.isArray(study.periods) ? study.periods : []).filter(completed);
                if (!periods.length) return;

                const latestDay = new Date(Number(periods[periods.length - 1].$time) * 1000)
                  .toLocaleDateString("en-CA", {timeZone: TZ});

                const buys = periods
                  .filter(p => new Date(Number(p.$time) * 1000)
                    .toLocaleDateString("en-CA", {timeZone: TZ}) === latestDay)
                  .filter(p => Number.isFinite(Number(p.Buy)) && Number(p.Buy) !== 0)
                  .map(p => ({
                    symbol,
                    candle_time: Number(p.$time),
                    price: Number(p.close)
                  }));

                settled = true;
                clearTimeout(timer);
                resolve(buys);
              } catch (e) {
                fail(e);
              }
            }, 800);
          };

          study.onUpdate(() => {
            if (Array.isArray(study.periods) && study.periods.length) readStudy();
          });
          study.onReady(readStudy);
        } catch (e) {
          fail(e);
        }
      });

      // setMarket must happen first; onSymbolLoaded is triggered by resolve_symbol.
      chart.setMarket(symbol, {
        timeframe: TIMEFRAME,
        range: RANGE,
        session: "regular",
        adjustment: "splits"
      });
    });
  } catch (e) {
    const msg = String(e && e.message ? e.message : e);
    if (attempt < 3 && /429|Too Many|rate limit|study_limit/i.test(msg)) {
      await sleep(attempt * 5000);
      return scanOne(symbol, attempt + 1);
    }
    throw e;
  } finally {
    try { if (study) study.remove(); } catch (_) {}
    try { if (chart) chart.delete(); } catch (_) {}
    try { if (client) await client.end(); } catch (_) {}
  }
}

async function main() {
  const symbols = TEST_MODE && TEST_SYMBOLS.length ? TEST_SYMBOLS : await getSymbols();
  const state = (() => {
    try { return JSON.parse(fs.readFileSync(STATE_FILE, "utf8")); }
    catch (_) { return {}; }
  })();

  const current = [], fresh = [];
  let errors = 0, next = 0;

  console.log("=".repeat(70));
  console.log("TRADINGVIEW GERCEK BUY ETIKET TARAMASI");
  console.log("Hisse: " + symbols.length + " | ATR 10 | Carp 2.0 | HL2 | 2H");
  console.log("VISIBLE BUY PLOT: Buy | AYRI CLIENT/CHART/STUDY");
  console.log("=".repeat(70));

  async function worker() {
    while (true) {
      const i = next++;
      if (i >= symbols.length) return;
      const symbol = symbols[i];

      try {
        const results = await scanOne(symbol);
        const old = state[symbol] && typeof state[symbol] === "object" ? state[symbol] : {};
        const oldBuy = Number(old.last_buy_candle_time || 0);

        for (const r of results) {
          const already = r.candle_time <= oldBuy;
          current.push({...r, already});
          console.log("[" + (i + 1) + "/" + symbols.length + "] GERCEK BUY | " +
            symbol + " | " + fmt(r.candle_time) + " | " + (already ? "MEVCUT" : "YENI"));
          if (!already) fresh.push(r);
        }
        if (!results.length) console.log("[" + (i + 1) + "/" + symbols.length + "] " + symbol + " | BUY yok");
      } catch (e) {
        errors++;
        console.log("[" + (i + 1) + "/" + symbols.length + "] " + symbol +
          " | HATA: " + String(e.message || e));
      }
      await sleep(500);
    }
  }

  await Promise.all(Array.from({length: Math.min(WORKERS, symbols.length)}, worker));

  current.sort((a,b) => a.candle_time - b.candle_time || a.symbol.localeCompare(b.symbol));
  fresh.sort((a,b) => a.candle_time - b.candle_time || a.symbol.localeCompare(b.symbol));

  console.log("=".repeat(70));
  console.log("TARAMA TAMAMLANDI");
  console.log("Toplam hisse: " + symbols.length);
  console.log("Basarili cevap: " + (symbols.length - errors));
  console.log("Hata: " + errors);
  console.log("GERCEK VISIBLE BUY: " + current.length);
  console.log("YENI BUY: " + fresh.length);

  if (FORCE_SCAN || TEST_MODE) {
    console.log("MANUEL TARAMA BUY RAPORU");
    for (const x of current) {
      console.log("    " + x.symbol + " | " + fmt(x.candle_time) +
        " | " + (x.already ? "DAHA ONCE GONDERILDI" : "YENI"));
    }
  }

  if (fresh.length && SEND_SCAN_REPORT) {
    const token = process.env.TELEGRAM_BOT_TOKEN, chat = process.env.TELEGRAM_CHAT_ID;
    if (!token || !chat) throw new Error("Telegram secret eksik.");

    const lines = [
      "TRADINGVIEW GERCEK BUY ETIKETI", "",
      "BIST 2 SAATLIK SUPERTREND",
      "ATR 10 | HL2 | 2.0 | 2H", "",
      "BUY SINYALI: " + fresh.length + " adet", ""
    ];
    for (const x of fresh) {
      lines.push("🟢 " + x.symbol.replace("BIST:", "") + "   " + Number(x.price).toFixed(2) + " TL");
      lines.push("   Mum: " + fmt(x.candle_time));
    }

    const resp = await fetch("https://api.telegram.org/bot" + token + "/sendMessage", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({chat_id: chat, text: lines.join("\n"), disable_web_page_preview: true})
    });
    const tg = await resp.json();
    if (!resp.ok || !tg.ok) throw new Error("Telegram HTTP " + resp.status + ": " + JSON.stringify(tg));
    console.log("GERCEK BUY LISTESI TELEGRAM'A GONDERILDI.");
  } else {
    console.log("Yeni gercek BUY yok; Telegram gonderilmeyecek.");
  }

  fs.mkdirSync("state", {recursive:true});
  for (const x of current) {
    const old = state[x.symbol] && typeof state[x.symbol] === "object" ? state[x.symbol] : {};
    state[x.symbol] = {...old, last_buy_candle_time: Math.max(Number(old.last_buy_candle_time || 0), x.candle_time)};
  }
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2) + "\n");
}

main().catch(e => { console.error(e); process.exit(1); });
