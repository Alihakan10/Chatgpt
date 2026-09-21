const TradingView = require("@mathieuc/tradingview");

const INDICATOR_ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const TIMEFRAME = "120";
const RANGE = 500;
const LIMIT = Number(process.env.SCAN_LIMIT || "620");
const TEST_MODE=process.env.TEST_MODE==="true"; const TEST_SYMBOL=process.env.TEST_SYMBOL||""; const FORCE_SCAN=process.env.FORCE_SCAN==="true"; const SEND_SCAN_REPORT=process.env.SEND_SCAN_REPORT!=="false"; const fs=require("fs"); const STATE_FILE="state/supertrend_state.json"; const TZ="Europe/Istanbul"; const fmt=ts=>new Intl.DateTimeFormat("tr-TR",{timeZone:TZ,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(Number(ts)*1000));

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
  const symbols=TEST_MODE&&TEST_SYMBOL?[TEST_SYMBOL]:await getSymbols();
  const state=(()=>{try{return JSON.parse(fs.readFileSync(STATE_FILE,"utf8"));}catch(_){return {};}})();
  // Free TradingView hesaplarinda chart/study limiti sembol basina degil
  // ayni anda acik chart oturumlarina da uygulanabildigi icin TEK chart + TEK study
  // yeniden kullanilir. Her sembolde sadece chart.setMarket() ile sembol degistirilir.
  const client=new TradingView.Client();
  const chart=new client.Session.Chart();
  const indicator=await TradingView.getIndicator(INDICATOR_ID);
  if(indicator.inputs?.ATR_Multiplier)indicator.setOption("ATR_Multiplier",2.0);
  if(indicator.inputs?.Multiplier)indicator.setOption("Multiplier",2.0);
  if(indicator.inputs?.ATR_Period)indicator.setOption("ATR_Period",10);
  if(indicator.inputs?.Periods)indicator.setOption("Periods",10);
  if(indicator.inputs?.Period)indicator.setOption("Period",10);

  let study=null;
  let studyReady=false;
  let pendingUpdate=null;
  let pendingError=null;

  async function scanOne(symbol){
    return await new Promise((resolve,reject)=>{
      let done=false;
      const finish=(fn,v)=>{if(!done){done=true;fn(v);}};
      const timer=setTimeout(()=>finish(reject,new Error("Study timeout")),25000);
      const waitUpdate=()=>new Promise((res,rej)=>{
        pendingUpdate=res; pendingError=rej;
        setTimeout(()=>{if(pendingUpdate===res){pendingUpdate=null;pendingError=null;rej(new Error("Study update timeout"));}},20000);
      });

      const handlePeriods=()=>{
        try{
          const ps=(Array.isArray(study?.periods)?study.periods:[]).filter(completed);
          if(!ps.length)return finish(reject,new Error("No completed study period"));
          const d=new Date(ps[ps.length-1].$time*1000).toLocaleDateString("en-CA",{timeZone:TZ});
          const out=ps.filter(p=>new Date(p.$time*1000).toLocaleDateString("en-CA",{timeZone:TZ})===d)
            .filter(p=>Number(p.SuperTrend_Buy)===1&&Number(p.SuperTrend_Direction_Change)===1)
            .map(p=>({symbol,candle_time:Number(p.$time),price:Number(p.close)}));
          clearTimeout(timer); finish(resolve,out);
        }catch(e){finish(reject,e);}
      };

      if(!studyReady){
        chart.onSymbolLoaded(async()=>{
          if(studyReady)return;
          try{
            study=new chart.Study(indicator);
            study.onError((...e)=>{if(pendingError)pendingError(new Error("Study: "+JSON.stringify(e)));finish(reject,new Error("Study: "+JSON.stringify(e)));});
            study.onUpdate(()=>{if(pendingUpdate){const r=pendingUpdate;pendingUpdate=null;pendingError=null;r();} if(studyReady)handlePeriods();});
            study.onReady(()=>{studyReady=true;handlePeriods();});
          }catch(e){finish(reject,e);}
        });
        chart.setMarket(symbol,{timeframe:TIMEFRAME,range:RANGE,session:"regular",adjustment:"splits"});
      }else{
        waitUpdate().then(handlePeriods).catch(e=>finish(reject,e));
        chart.setMarket(symbol,{timeframe:TIMEFRAME,range:RANGE,session:"regular",adjustment:"splits"});
      }
    });
  }

  console.log("=".repeat(70));
  console.log("TRADINGVIEW GERCEK BUY ETIKET TARAMASI");
  console.log("Hisse: "+symbols.length+" | ATR 10 | Carp 2.0 | HL2 | 2H");
  console.log("Her hisse icin AYRI chart session + TEK study");
  console.log("=".repeat(70));
  const current=[],fresh=[]; let errors=0;
  for(let i=0;i<symbols.length;i++){
    const symbol=symbols[i]; console.log("["+(i+1)+"/"+symbols.length+"] "+symbol);
    try{
      const results=await scanOne(symbol); const old=state[symbol]&&typeof state[symbol]==="object"?state[symbol]:{}; const oldBuy=Number(old.last_buy_candle_time||0);
      for(const r of results){const already=r.candle_time<=oldBuy; current.push({...r,already}); if(already)console.log("    MEVCUT BUY | "+fmt(r.candle_time)+" | DAHA ONCE GONDERILDI"); else{fresh.push(r);console.log("    >>> GERCEK BUY | "+fmt(r.candle_time));} state[symbol]={...old,direction:1,candle_time:r.candle_time,last_buy_candle_time:Math.max(oldBuy,r.candle_time)};}
    }catch(e){errors++;console.log("    HATA: "+String(e.message||e));}
  }
  console.log("=".repeat(70)); console.log("TARAMA TAMAMLANDI"); console.log("Toplam hisse: "+symbols.length); console.log("Basarili cevap: "+(symbols.length-errors)); console.log("Hata: "+errors); console.log("GERCEK BUY: "+current.length); console.log("YENI BUY: "+fresh.length);
  if(FORCE_SCAN||TEST_MODE){console.log("MANUEL TARAMA BUY RAPORU"); console.log("MEVCUT BUY: "+current.length); for(const x of current)console.log("    MEVCUT BUY | "+x.symbol+" | "+fmt(x.candle_time)+" | "+(x.already?"DAHA ONCE GONDERILDI":"YENI")); console.log("DAHA ONCE TELEGRAM'A GONDERILEN BUY: "+current.filter(x=>x.already).length); console.log("YENI BUY: "+fresh.length);}
  if(fresh.length&&SEND_SCAN_REPORT){const token=process.env.TELEGRAM_BOT_TOKEN,chat=process.env.TELEGRAM_CHAT_ID; if(!token||!chat)throw new Error("Telegram secret eksik."); const lines=["TRADINGVIEW GERCEK BUY ETIKETI","","BIST 2 SAATLIK SUPERTREND","ATR 10 | HL2 | 2.0 | 2H","","BUY SINYALI: "+fresh.length+" adet",""]; for(const x of fresh){lines.push("🟢 "+x.symbol.replace("BIST:","")+"   "+Number(x.price).toFixed(2)+" TL"); lines.push("   Mum: "+fmt(x.candle_time));} const resp=await fetch("https://api.telegram.org/bot"+token+"/sendMessage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chat_id:chat,text:lines.join("\n"),disable_web_page_preview:true})}); const tg=await resp.json(); if(!resp.ok||!tg.ok)throw new Error("Telegram HTTP "+resp.status+": "+JSON.stringify(tg)); console.log("GERCEK BUY LISTESI TELEGRAM'A GONDERILDI.");} else console.log("Yeni gercek BUY yok; Telegram gonderilmeyecek.");
  fs.mkdirSync("state",{recursive:true}); fs.writeFileSync(STATE_FILE,JSON.stringify(state,null,2)+"\n"); try{client.end();}catch(_){}
}

main().catch(e=>{console.error(e);process.exit(1);});