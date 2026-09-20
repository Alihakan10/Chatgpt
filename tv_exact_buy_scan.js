const TradingView = require("@mathieuc/tradingview");

const INDICATOR_ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const TIMEFRAME = "120";
const RANGE = 500;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");

const sleep = ms => new Promise(r => setTimeout(r, ms));

function completed(period) {
  if (!period || period.$time == null) return false;
  const t = Number(period.$time);
  return t + 2 * 60 * 60 <= Math.floor(Date.now() / 1000);
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
  return [...new Set((data.data || []).map(x => x.s).filter(x => typeof x === "string" && x.startsWith("BIST:")))].slice(0, LIMIT);
}

async function main() {
  const symbols = await getSymbols();
  const client = new TradingView.Client();
  const chart = new client.Session.Chart();
  const indicator = await TradingView.getIndicator(INDICATOR_ID);

  // Public Kivanc SuperTrend defaults: ATR period 10, HL2, RMA.
  if (indicator.inputs && indicator.inputs.ATR_Multiplier) indicator.setOption("ATR_Multiplier", 2.0);
  if (indicator.inputs && indicator.inputs.Multiplier) indicator.setOption("Multiplier", 2.0);

  let study = null;
  let waiting = null;
  let currentSymbol = "";

  chart.onError((...err) => {
    if (waiting) { const w = waiting; waiting = null; w.reject(new Error("Chart: " + JSON.stringify(err))); }
  });

  async function loadSymbol(symbol) {
    await new Promise((resolve, reject) => {
      let done = false;
      const finish = (fn, value) => { if (!done) { done = true; fn(value); } };
      const timer = setTimeout(() => finish(reject, new Error("Symbol timeout")), 15000);
      const handler = () => { clearTimeout(timer); finish(resolve); };
      chart.onSymbolLoaded(handler);
      chart.setMarket(symbol, {timeframe:TIMEFRAME, range:RANGE, session:"regular", adjustment:"splits"});
    });

    if (study) {
      try { study.remove(); } catch (_) {}
      study = null;
    }

    study = new chart.Study(indicator);

    return await new Promise((resolve, reject) => {
      let done = false;
      const finish = (fn, value) => { if (!done) { done = true; fn(value); } };

      const timer = setTimeout(() => finish(reject, new Error("Study timeout")), 15000);

      study.onReady(() => {
        clearTimeout(timer);
        const periods = Array.isArray(study.periods) ? study.periods : [];
        const p = periods.find(completed);
        if (!p) return finish(reject, new Error("No completed study period"));

        const buy = Number(p.SuperTrend_Buy) === 1 &&
                    Number(p.SuperTrend_Direction_Change) === 1;

        finish(resolve, {
          symbol: currentSymbol,
          buy,
          candle_time: Number(p.$time),
          price: Number(p.close),
          raw: p
        });
      });

      study.onError((...err) => {
        clearTimeout(timer);
        finish(reject, new Error(JSON.stringify(err)));
      });
    });
  }


  console.log("=".repeat(70));
  console.log("TRADINGVIEW GERCEK BUY ETIKET TESTI");
  console.log("Hisse: " + symbols.length);
  console.log("ATR Period: 10 | Multiplier: 2.0 | Source: HL2 | Timeframe: 2H");
  console.log("KAYNAK: TradingView Kivanc SuperTrend study output");
  console.log("Tek study/chart oturumu kullaniliyor.");
  console.log("=".repeat(70));

  const buys=[]; let errors=0;
  for (let i=0;i<symbols.length;i++) {
    const symbol=symbols[i];
    console.log("["+(i+1)+"/"+symbols.length+"] "+symbol);
    try {
      const r=await loadSymbol(symbol);
      if (r.buy) { buys.push(r); console.log("    >>> GERCEK BUY ETIKETI: "+symbol); }
    } catch(e) { errors++; console.log("    HATA: "+String(e.message||e)); }
    await sleep(50);
  }

  console.log("");
  console.log("=".repeat(70));
  console.log("TARAMA TAMAMLANDI");
  console.log("Toplam hisse: "+symbols.length);
  console.log("GERCEK BUY ETIKETI: "+buys.length);
  console.log("Hata: "+errors);
  console.log("=".repeat(70));

  if (buys.length) {
    const token=process.env.TELEGRAM_BOT_TOKEN, chat=process.env.TELEGRAM_CHAT_ID;
    if (!token || !chat) throw new Error("Telegram secret eksik.");
    const lines=["TRADINGVIEW GERCEK BUY ETIKETI","","BIST 2 SAATLIK SUPERTREND","ATR 10 | HL2 | 2.0 | 2H","", "BUY SINYALI: "+buys.length+" adet",""];
    for (const x of buys) { lines.push("🟢 "+x.symbol.replace("BIST:","")+"   "+Number(x.price).toFixed(2)+" TL"); lines.push("   Mum: "+new Date(x.candle_time*1000).toLocaleString("tr-TR",{timeZone:"Europe/Istanbul",hour12:false})); }
    const resp=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:lines.join("\n"),disable_web_page_preview:true})});
    const tg=await resp.json(); if (!resp.ok || !tg.ok) throw new Error("Telegram HTTP "+resp.status+": "+JSON.stringify(tg));
    console.log("GERCEK BUY ETIKET LISTESI TELEGRAM’A GONDERILDI.");
  } else console.log("BUY etiketi yok; Telegram gonderilmeyecek.");

  try { chart.delete(); } catch (_) {}
  try { client.end(); } catch (_) {}
}

main().catch(e=>{console.error(e);process.exit(1);});