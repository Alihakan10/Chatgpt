const TradingView = require("@mathieuc/tradingview");
const WebSocket = require("ws");
const fs = require("fs");

const INDICATOR_ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const TIMEFRAME = "120";
const RANGE = 500;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");
const TEST_MODE = process.env.TEST_MODE === "true";
const TEST_SYMBOLS = (process.env.TEST_SYMBOLS || "").split(",").map(s => s.trim()).filter(Boolean);
const FORCE_SCAN = process.env.FORCE_SCAN === "true";
const SEND_SCAN_REPORT = process.env.SEND_SCAN_REPORT !== "false";
const STATE_FILE = "state/supertrend_state.json";
const TZ = "Europe/Istanbul";

const sleep = ms => new Promise(r => setTimeout(r, ms));

function fmt(ts) {
  return new Intl.DateTimeFormat("tr-TR", {
    timeZone: TZ, year:"numeric", month:"2-digit", day:"2-digit",
    hour:"2-digit", minute:"2-digit", hour12:false
  }).format(new Date(Number(ts) * 1000));
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
    const n0 = m + 3;
    const m2 = text.indexOf("~m~", n0);
    if (m2 < 0) break;
    const len = Number(text.slice(n0, m2));
    const start = m2 + 3;
    const payload = text.slice(start, start + len);
    if (payload === "" || payload.startsWith("~h~")) {
      i = start + len;
      continue;
    }
    try { out.push(JSON.parse(payload)); } catch (_) {}
    i = start + len;
  }
  return out;
}

async function getSymbols() {
  const response = await fetch("https://scanner.tradingview.com/turkey/scan", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({
      filter:[], options:{lang:"tr"},
      symbols:{query:{types:[]},tickers:[]},
      columns:["name"], sort:{sortBy:"name",sortOrder:"asc"}, range:[0,1000]
    })
  });
  if (!response.ok) throw new Error("Scanner HTTP " + response.status);
  const data = await response.json();
  return [...new Set((data.data || []).map(x => x.s)
    .filter(x => typeof x === "string" && x.startsWith("BIST:")))].slice(0,LIMIT);
}

function indicatorInputs(indicator) {
  const result = { text: indicator.script };
  if (indicator.pineId) result.pineId = indicator.pineId;
  if (indicator.pineVersion) result.pineVersion = indicator.pineVersion;

  for (const [id, input] of Object.entries(indicator.inputs || {})) {
    let value = input.value;
    if (id === "in_0" || input.internalID === "ATR_Period") value = 10;
    if (id === "in_1" || input.internalID === "Source") value = "hl2";
    if (id === "in_2" || input.internalID === "ATR_Multiplier") value = 2.0;
    if (id === "in_3" || input.internalID === "Change_ATR_Calculation_Method_") value = true;
    if (id === "in_4" || input.internalID === "Show_BuySell_Signals_") value = true;
    if (id === "in_5" || input.internalID === "Highlighter_OnOff_") value = true;
    // Indicator Timeframe = chart timeframe: leave its fake resolution input empty.
    result[id] = { v:value, f:!!input.isFake, t:input.type };
  }
  return result;
}

function createClient(indicator) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket("wss://data.tradingview.com/socket.io/websocket?from=chart&type=chart", {
      origin:"https://www.tradingview.com",
      headers:{
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language":"en-US,en;q=0.9"
      }
    });

    const cs = "cs_" + Math.random().toString(36).slice(2,14);
    const st = "st_" + Math.random().toString(36).slice(2,14);
    const sym = "symbol_1";
    let buffer = "";
    let currentSymbol = null;
    let studyReady = false;
    let completed = false;
    let periods = new Map();
    let failed = false;

    const send = (m,p) => { if (ws.readyState === WebSocket.OPEN) ws.send(frame({m,p})); };

    const fail = err => {
      if (failed) return;
      failed = true;
      reject(err instanceof Error ? err : new Error(String(err)));
    };

    const resetPeriods = () => {
      periods = new Map();
      completed = false;
    };

    ws.on("open", () => {
      send("set_auth_token", ["unauthorized_user_token"]);
      send("chart_create_session", [cs, ""]);
      send("switch_timezone", [cs, TZ]);
      send("resolve_symbol", [cs, sym, "=" + JSON.stringify({
        symbol:"BIST:ASTOR", adjustment:"splits", session:"regular"
      })]);
      send("create_series", [cs, "s1", "s1", sym, TIMEFRAME, RANGE]);
      send("create_study", [cs, st, "st1", "s1", "Script@tv-scripting-101!", indicatorInputs(indicator)]);
    });

    ws.on("message", data => {
      const text = data.toString();
      buffer += text;
      for (const packet of parseFrames(buffer)) {
        if (packet.m === "critical_error" || packet.m === "series_error" || packet.m === "study_error") {
          const p = packet.p || [];
          fail(new Error(packet.m + ": " + JSON.stringify(p)));
          return;
        }
        if (packet.m === "study_completed" || packet.m === "study_loading") {
          studyReady = packet.m === "study_completed" || studyReady;
        }
        if (packet.m === "timescale_update" || packet.m === "du") {
          const dataObj = packet.p && packet.p[1];
          const studyData = dataObj && dataObj[st];
          if (studyData && Array.isArray(studyData.st)) {
            for (const p of studyData.st) {
              if (Array.isArray(p.v) && p.v.length >= 4) periods.set(Number(p.v[0]), p.v);
            }
          }
          if (periods.size) completed = true;
        }
      }
    });

    ws.on("error", fail);
    ws.on("close", () => { if (!failed && !completed) fail(new Error("TradingView websocket closed")); });

    const api = {
      async setSymbol(symbol) {
        return new Promise((res, rej) => {
          resetPeriods();
          currentSymbol = symbol;
          const timer = setTimeout(() => rej(new Error("Symbol timeout")), 15000);
          const check = () => {
            if (failed) return rej(new Error("TradingView failed"));
            if (completed) {
              clearTimeout(timer);
              res();
            } else setTimeout(check, 250);
          };
          send("resolve_symbol", [cs, sym, "=" + JSON.stringify({
            symbol, adjustment:"splits", session:"regular"
          })]);
          send("modify_series", [cs, "s1", "s2", sym, TIMEFRAME, RANGE]);
          check();
        });
      },
      readBuys() {
        const arr = [...periods.values()].filter(v => v.length >= 4);
        const latestDay = arr.length
          ? new Date(Number(arr[arr.length - 1][0]) * 1000).toLocaleDateString("en-CA",{timeZone:TZ})
          : null;
        return arr.filter(v => {
          const ts = Number(v[0]);
          return latestDay &&
            new Date(ts * 1000).toLocaleDateString("en-CA",{timeZone:TZ}) === latestDay &&
            Number.isFinite(Number(v[3])) && Number(v[3]) !== 0;
        }).map(v => ({
          candle_time:Number(v[0]),
          price:Number(v[4] || 0)
        }));
      },
      close() { try { ws.close(); } catch (_) {} }
    };

    // First symbol is ASTOR only to initialize the series/study; caller changes it immediately.
    setTimeout(() => resolve(api), 8000);
  });
}

async function main() {
  const symbols = TEST_MODE && TEST_SYMBOLS.length ? TEST_SYMBOLS : await getSymbols();
  const state = (() => { try { return JSON.parse(fs.readFileSync(STATE_FILE,"utf8")); } catch (_) { return {}; } })();

  console.log("=".repeat(70));
  console.log("TRADINGVIEW GERCEK BUY ETIKET TARAMASI");
  console.log("Hisse: " + symbols.length + " | ATR 10 | Carp 2.0 | HL2 | 2H");
  console.log("TEK STUDY + AYNI SERIES + modify_series | study parent=s1");
  console.log("=".repeat(70));

  const indicator = await TradingView.getIndicator(INDICATOR_ID);
  const tv = await createClient(indicator);

  const current = [], fresh = [];
  let errors = 0;

  for (let i=0; i<symbols.length; i++) {
    const symbol = symbols[i];
    try {
      await tv.setSymbol(symbol);
      const buys = tv.readBuys();
      const old = state[symbol] && typeof state[symbol] === "object" ? state[symbol] : {};
      const oldBuy = Number(old.last_buy_candle_time || 0);

      for (const r of buys) {
        const x = {...r, symbol, already:r.candle_time <= oldBuy};
        current.push(x);
        console.log("["+(i+1)+"/"+symbols.length+"] GERCEK BUY | "+symbol+" | "+fmt(r.candle_time)+" | "+(x.already?"MEVCUT":"YENI"));
        if (!x.already) fresh.push(x);
      }
      if (!buys.length) console.log("["+(i+1)+"/"+symbols.length+"] "+symbol+" | BUY yok");
    } catch (e) {
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
  console.log("GERCEK VISIBLE BUY: "+current.length);
  console.log("YENI BUY: "+fresh.length);

  if (FORCE_SCAN || TEST_MODE) {
    console.log("MANUEL TARAMA BUY RAPORU");
    for (const x of current) console.log("    "+x.symbol+" | "+fmt(x.candle_time)+" | "+(x.already?"DAHA ONCE GONDERILDI":"YENI"));
  }

  if (fresh.length && SEND_SCAN_REPORT) {
    const token=process.env.TELEGRAM_BOT_TOKEN, chat=process.env.TELEGRAM_CHAT_ID;
    if (!token || !chat) throw new Error("Telegram secret eksik.");
    const lines=["TRADINGVIEW GERCEK BUY ETIKETI","","BIST 2 SAATLIK SUPERTREND","ATR 10 | HL2 | 2.0 | 2H","","BUY SINYALI: "+fresh.length+" adet",""];
    for (const x of fresh) {
      lines.push("🟢 "+x.symbol.replace("BIST:","")+"   "+Number(x.price).toFixed(2)+" TL");
      lines.push("   Mum: "+fmt(x.candle_time));
    }
    const resp=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:lines.join("\n"),disable_web_page_preview:true})});
    const tg=await resp.json();
    if (!resp.ok || !tg.ok) throw new Error("Telegram HTTP "+resp.status+": "+JSON.stringify(tg));
    console.log("GERCEK BUY LISTESI TELEGRAM'A GONDERILDI.");
  } else console.log("Yeni gercek BUY yok; Telegram gonderilmeyecek.");

  fs.mkdirSync("state",{recursive:true});
  for (const x of current) {
    const old=state[x.symbol]&&typeof state[x.symbol]==="object"?state[x.symbol]:{};
    state[x.symbol]={...old,last_buy_candle_time:Math.max(Number(old.last_buy_candle_time||0),x.candle_time)};
  }
  fs.writeFileSync(STATE_FILE,JSON.stringify(state,null,2)+"\n");
}

main().catch(e=>{console.error(e);process.exit(1);});
