const WebSocket = require("ws");
const fs = require("fs");

const TIMEFRAME = "120";
const RANGE = 3000;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");
const TEST_MODE = process.env.TEST_MODE === "true";
const TEST_SYMBOLS = (process.env.TEST_SYMBOLS || "").split(",").map(s => s.trim()).filter(Boolean);
const FORCE_SCAN = process.env.FORCE_SCAN === "true";
const SEND_SCAN_REPORT = process.env.SEND_SCAN_REPORT !== "false";
const STATE_FILE = "state/supertrend_state.json";
const TZ = "Europe/Istanbul";
const WS_URL = "wss://data.tradingview.com/socket.io/websocket?from=chart&type=chart";
const sleep = ms => new Promise(r => setTimeout(r, ms));

function fmt(ts) {
  return new Intl.DateTimeFormat("tr-TR", {
    timeZone: TZ, year:"numeric", month:"2-digit", day:"2-digit",
    hour:"2-digit", minute:"2-digit", hour12:false
  }).format(new Date(ts * 1000));
}

function localDate(ts) {
  return new Date(ts * 1000).toLocaleDateString("en-CA", {timeZone:TZ});
}

function frame(obj) {
  const s = JSON.stringify(obj);
  return "~m~" + Buffer.byteLength(s) + "~m~" + s;
}

function parseFrames(text) {
  const out = [];
  let i = 0;
  while (i < text.length) {
    const m = text.indexOf("~m~", i);
    if (m < 0) break;
    const a = m + 3, b = text.indexOf("~m~", a);
    if (b < 0) break;
    const len = Number(text.slice(a, b));
    const start = b + 3, end = start + len;
    if (end > text.length) break;
    const payload = text.slice(start, end);
    if (payload.startsWith("~h~")) { i = end; continue; }
    try { out.push(JSON.parse(payload)); } catch (_) {}
    i = end;
  }
  return {messages:out, rest:text.slice(i)};
}

async function getSymbols() {
  const response = await fetch("https://scanner.tradingview.com/turkey/scan", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({
      filter:[
        {left:"is_primary",operation:"equal",right:true},
        {left:"typespecs",operation:"has",right:"common"},
        {left:"type",operation:"equal",right:"stock"},
        {left:"name",operation:"nempty"}
      ],
      options:{active_symbols_only:true,lang:"tr"},
      symbols:{query:{types:[]},tickers:[]},
      markets:["turkey"],
      columns:["name"],
      sort:{sortBy:"name",sortOrder:"asc"},
      range:[0,1000]
    })
  });
  if (!response.ok) throw new Error("Scanner HTTP " + response.status);
  const data = await response.json();
  return [...new Set((data.data || []).map(x=>x.s)
    .filter(x=>typeof x==="string" && x.startsWith("BIST:")))].slice(0,LIMIT);
}

function calculateBuySignals(candles) {
  const period = 10, mult = 2.0;
  if (candles.length < period + 2) return [];
  const tr = candles.map((c,i) => {
    if (i === 0) return c.high - c.low;
    const pc = candles[i-1].close;
    return Math.max(c.high-c.low, Math.abs(c.high-pc), Math.abs(c.low-pc));
  });
  const atr = new Array(candles.length).fill(null);
  atr[period-1] = tr.slice(0,period).reduce((a,b)=>a+b,0) / period;
  for (let i=period;i<candles.length;i++) {
    atr[i] = (atr[i-1] * (period-1) + tr[i]) / period;
  }

  const up = new Array(candles.length).fill(null);
  const dn = new Array(candles.length).fill(null);
  const trend = new Array(candles.length).fill(null);
  const buys = [];

  for (let i=0;i<candles.length;i++) {
    if (atr[i] == null) {
      trend[i] = i === 0 ? 1 : trend[i-1];
      continue;
    }
    const src = (candles[i].high + candles[i].low) / 2;
    const rawUp = src - mult * atr[i];
    const rawDn = src + mult * atr[i];

    const up1 = (i === 0 || up[i-1] == null) ? rawUp : up[i-1];
    const dn1 = (i === 0 || dn[i-1] == null) ? rawDn : dn[i-1];

    up[i] = i === 0 ? rawUp : (candles[i-1].close > up1 ? Math.max(rawUp,up1) : rawUp);
    dn[i] = i === 0 ? rawDn : (candles[i-1].close < dn1 ? Math.min(rawDn,dn1) : rawDn);

    const prevTrend = i === 0 || trend[i-1] == null ? 1 : trend[i-1];
    trend[i] = prevTrend === -1 && candles[i].close > dn1
      ? 1
      : prevTrend === 1 && candles[i].close < up1
        ? -1
        : prevTrend;

    if (trend[i] === 1 && prevTrend === -1) {
      buys.push({candle_time:candles[i].time, price:candles[i].close});
    }
  }
  return buys;
}

function createClient() {
  return new Promise((resolve,reject) => {
    const ws = new WebSocket(WS_URL, {
      origin:"https://www.tradingview.com",
      headers:{
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language":"en-US,en;q=0.9"
      }
    });

    const cs = "cs_" + Math.random().toString(36).slice(2,14);
    const sym = "symbol_1";
    const series = "s1";
    let buffer = "";
    let candles = new Map();
    let ready = false;
    let failed = false;
    let moreRequests = 0;
    let waiting = null;

    const send = (m,p) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(frame({m,p}));
    };

    const fail = e => {
      if (failed) return;
      failed = true;
      if (waiting) waiting.reject(e instanceof Error ? e : new Error(String(e)));
      reject(e instanceof Error ? e : new Error(String(e)));
    };

    const finishWait = () => {
      if (waiting) {
        const w = waiting;
        waiting = null;
        clearTimeout(w.timer);
        w.resolve();
      }
    };

    ws.on("open", () => {
      send("set_auth_token", ["unauthorized_user_token"]);
      send("chart_create_session", [cs, ""]);
      send("switch_timezone", [cs, TZ]);
      send("resolve_symbol", [cs, sym, "=" + JSON.stringify({symbol:"BIST:ASTOR",adjustment:"splits",session:"regular"})]);
      send("create_series", [cs, series, "s1", sym, TIMEFRAME, RANGE, ""]);
    });

    ws.on("message", data => {
      buffer += data.toString();
      const parsed = parseFrames(buffer);
      buffer = parsed.rest;

      for (const packet of parsed.messages) {
        const p = packet.p || [];
        if (packet.m === "critical_error" || packet.m === "series_error" || packet.m === "symbol_error") {
          fail(new Error(packet.m + ": " + JSON.stringify(p)));
          return;
        }
        if (packet.m === "series_completed") {
          if (candles.size < 100 && moreRequests < 3) {
            moreRequests++;
            send("request_more_data", [cs, series, 1000]);
          } else {
            ready = true;
            finishWait();
          }
        }
        if (packet.m === "timescale_update" || packet.m === "du") {
          const box = p[1];
          const sd = box && box[series];
          const bars = sd && sd.s;
          if (!Array.isArray(bars)) continue;
          for (const bar of bars) {
            const v = bar && bar.v;
            if (!Array.isArray(v) || v.length < 5) continue;
            const t = Number(v[0]), o=Number(v[1]), h=Number(v[2]), l=Number(v[3]), c=Number(v[4]);
            if ([t,o,h,l,c].every(Number.isFinite)) candles.set(t,{time:t,open:o,high:h,low:l,close:c});
          }
        }
      }
    });

    ws.on("error", fail);
    ws.on("close", () => {
      if (!failed && waiting) fail(new Error("TradingView websocket closed"));
    });

    const api = {
      async setSymbol(symbol) {
        candles = new Map();
        ready = false;
        moreRequests = 0;
        await new Promise((resolve,reject) => {
          waiting = {resolve,reject,timer:setTimeout(()=>{waiting=null;reject(new Error("Symbol timeout"));},20000)};
          // Aynı symbol node'u tekrar resolve etmek TradingView'da "duplicate id" üretir.
          // Tek resolve_symbol yeterli; sonraki hisselerde sadece mevcut series modify edilir.
          send("modify_series", [cs, series, "s1", symbol, TIMEFRAME, RANGE, ""]);
        });
        await sleep(150);
      },
      getCandles() {
        return [...candles.values()].sort((a,b)=>a.time-b.time);
      },
      close() { try { ws.close(); } catch (_) {} }
    };

    setTimeout(() => {
      if (!failed) resolve(api);
    }, 1000);
  });
}

async function main() {
  const symbols = TEST_MODE && TEST_SYMBOLS.length ? TEST_SYMBOLS : await getSymbols();
  const state = (() => { try { return JSON.parse(fs.readFileSync(STATE_FILE,"utf8")); } catch (_) { return {}; } })();

  console.log("=".repeat(70));
  console.log("TRADINGVIEW GERCEK BUY TARAMASI - STUDY YOK");
  console.log("Hisse: " + symbols.length + " | ATR 10 | Carp 2.0 | HL2 | 2H");
  console.log("Pine SuperTrend mantigi dogrudan TradingView OHLC verisine uygulanir.");
  console.log("TEK WEBSOCKET + TEK SERIES + modify_series");
  console.log("=".repeat(70));

  const tv = await createClient();
  const current=[], fresh=[];
  let errors=0;

  for (let i=0;i<symbols.length;i++) {
    const symbol=symbols[i];
    try {
      await tv.setSymbol(symbol);
      const candles=tv.getCandles();
      if (candles.length < 20) throw new Error("Yetersiz 2H mum: " + candles.length);

      const now=Math.floor(Date.now()/1000);
      const completed=candles.filter(c=>c.time + 7200 <= now);
      const buys=calculateBuySignals(completed);
      const day=completed.length ? localDate(completed[completed.length-1].time) : null;
      const todays=buys.filter(x=>localDate(x.candle_time)===day);

      const old=state[symbol]&&typeof state[symbol]==="object"?state[symbol]:{};
      const oldBuy=Number(old.last_buy_candle_time||0);

      for (const r of todays) {
        const x={...r,symbol,already:r.candle_time<=oldBuy};
        current.push(x);
        console.log("["+(i+1)+"/"+symbols.length+"] GERCEK BUY | "+symbol+" | "+fmt(r.candle_time)+" | "+(x.already?"MEVCUT":"YENI"));
        if (!x.already) fresh.push(x);
      }
      if (!todays.length) console.log("["+(i+1)+"/"+symbols.length+"] "+symbol+" | BUY yok");
    } catch(e) {
      errors++;
      console.log("["+(i+1)+"/"+symbols.length+"] "+symbol+" | HATA: "+String(e.message||e));
    }
  }

  tv.close();

  console.log("=".repeat(70));
  console.log("TARAMA TAMAMLANDI");
  console.log("Toplam hisse: "+symbols.length);
  console.log("Basarili cevap: "+(symbols.length-errors));
  console.log("Hata: "+errors);
  console.log("GERCEK BUY: "+current.length);
  console.log("YENI BUY: "+fresh.length);

  if (FORCE_SCAN || TEST_MODE) {
    console.log("MANUEL TARAMA BUY RAPORU");
    for (const x of current) console.log("    "+x.symbol+" | "+fmt(x.candle_time)+" | "+(x.already?"DAHA ONCE GONDERILDI":"YENI"));
  }

  if (fresh.length && SEND_SCAN_REPORT) {
    const token=process.env.TELEGRAM_BOT_TOKEN, chat=process.env.TELEGRAM_CHAT_ID;
    if (!token || !chat) throw new Error("Telegram secret eksik.");
    const lines=["TRADINGVIEW SUPERTREND BUY","","BIST 2 SAATLIK SUPERTREND","ATR 10 | HL2 | 2.0 | 2H","","BUY SINYALI: "+fresh.length+" adet",""];
    for (const x of fresh) {
      lines.push("🟢 "+x.symbol.replace("BIST:","")+"   "+Number(x.price).toFixed(2)+" TL");
      lines.push("   Mum: "+fmt(x.candle_time));
    }
    const resp=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:lines.join("\n"),disable_web_page_preview:true})});
    const tg=await resp.json();
    if (!resp.ok || !tg.ok) throw new Error("Telegram HTTP "+resp.status+": "+JSON.stringify(tg));
    console.log("BUY LISTESI TELEGRAM'A GONDERILDI.");
  } else console.log("Yeni BUY yok; Telegram gonderilmeyecek.");

  fs.mkdirSync("state",{recursive:true});
  for (const x of current) {
    const old=state[x.symbol]&&typeof state[x.symbol]==="object"?state[x.symbol]:{};
    state[x.symbol]={...old,last_buy_candle_time:Math.max(Number(old.last_buy_candle_time||0),x.candle_time)};
  }
  fs.writeFileSync(STATE_FILE,JSON.stringify(state,null,2)+"\n");
}

main().catch(e=>{console.error(e);process.exit(1);});
