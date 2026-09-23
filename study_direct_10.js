const TradingView = require("@mathieuc/tradingview");

const INDICATOR_ID = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const SYMBOLS = ["BIST:ACSEL","BIST:AKSUE","BIST:ATSYH","BIST:BESLR","BIST:BMSCH","BIST:DMRGD","BIST:EMNIS","BIST:ENPRA","BIST:MOBTL","BIST:PETUN"];
const TIMEFRAME = "120";
const RANGE = 500;

const sleep = ms => new Promise(r => setTimeout(r, ms));

function completed(p) {
  const t = Number(p?.$time);
  return Number.isFinite(t) && t + 7200 <= Math.floor(Date.now()/1000);
}

function fmt(ts) {
  return new Intl.DateTimeFormat("tr-TR",{timeZone:"Europe/Istanbul",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(Number(ts)*1000));
}

async function one(symbol) {
  const client = new TradingView.Client();
  try {
    const chart = new client.Session.Chart();
    const indicator = await TradingView.getIndicator(INDICATOR_ID);

    if (indicator.inputs?.ATR_Multiplier) indicator.setOption("ATR_Multiplier", 2.0);
    if (indicator.inputs?.Multiplier) indicator.setOption("Multiplier", 2.0);
    if (indicator.inputs?.ATR_Period) indicator.setOption("ATR_Period", 10);
    if (indicator.inputs?.Periods) indicator.setOption("Periods", 10);
    if (indicator.inputs?.Period) indicator.setOption("Period", 10);
    if (indicator.inputs?.Source) indicator.setOption("Source", "hl2");
    if (indicator.inputs?.src) indicator.setOption("src", "hl2");

    return await new Promise((resolve,reject)=>{
      let settled=false;
      const timer=setTimeout(()=>finish(reject,new Error("timeout")),30000);
      const finish=(fn,v)=>{ if(settled)return; settled=true; clearTimeout(timer); fn(v); };

      chart.onSymbolLoaded(()=>{
        let study;
        try {
          study = new chart.Study(indicator);
          study.onError((...e)=>finish(reject,new Error("Study error: "+JSON.stringify(e))));
          const read=()=>{
            try {
              const periods=(Array.isArray(study.periods)?study.periods:[]).filter(completed);
              if(!periods.length) return;
              const last=periods[periods.length-1];
              const buy=Number(last.SuperTrend_Buy);
              const change=Number(last.SuperTrend_Direction_Change);
              const direction=Number(last.SuperTrend_Direction);
              console.log(symbol+" | "+fmt(last.$time)+" | Buy="+buy+" | DirectionChange="+change+" | Direction="+direction+" | "+(buy===1&&change===1?"BUY":"NO BUY"));
              finish(resolve,{symbol,time:Number(last.$time),close:Number(last.close),buy,change,direction,periods:periods.length});
            } catch(e) { finish(reject,e); }
          };
          study.onReady(read);
          study.onUpdate(read);
          chart.setMarket(symbol,{timeframe:TIMEFRAME,range:RANGE,session:"regular",adjustment:"splits"});
        } catch(e) { finish(reject,e); }
      });
      chart.setMarket(symbol,{timeframe:TIMEFRAME,range:RANGE,session:"regular",adjustment:"splits"});
    });
  } finally {
    try { client.end(); } catch (_) {}
    await sleep(1500);
  }
}

(async()=>{
  console.log("TRADINGVIEW PUBLIC STUDY DIRECT BUY TEST");
  console.log("ATR 10 | MULTIPLIER 2.0 | HL2 | 2H | "+SYMBOLS.length+" SYMBOLS");
  console.log("Each symbol uses a fresh Client/Chart/Study; one Study at a time.");
  let ok=0, errors=0, buys=0;
  for (const s of SYMBOLS) {
    try {
      const r=await one(s);
      ok++;
      if(r.buy===1 && r.change===1) buys++;
    } catch(e) {
      errors++;
      console.log(s+" | ERROR | "+(e?.message||e));
    }
  }
  console.log("SUMMARY | OK="+ok+" | ERRORS="+errors+" | REAL_STUDY_BUY="+buys);
  if(errors) process.exit(2);
})().catch(e=>{console.error(e);process.exit(1);});
