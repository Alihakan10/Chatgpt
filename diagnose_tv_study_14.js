const TradingView = require("@mathieuc/tradingview");

const INDICATOR = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const SYMBOLS = [
  "BIST:CLEBI","BIST:EMNIS","BIST:EUHOL","BIST:KENT","BIST:KERVN",
  "BIST:KLYPV","BIST:KRPLS","BIST:KSTUR","BIST:OYLUM","BIST:SODSN",
  "BIST:TUCLK","BIST:TURSG","BIST:ULUFA","BIST:USHOL"
];
const TIMEFRAME = "120";
const RANGE = 500;
const MULTIPLIER = 2.0;

function completed(p) {
  if (!p || p.$time == null) return false;
  const d = new Date(Number(p.$time) * 1000);
  let end = new Date(d.getTime() + 2 * 3600 * 1000);
  if (d.getHours() === 17 && d.getMinutes() === 0) {
    end = new Date(d);
    end.setHours(18,0,0,0);
  }
  return end.getTime() <= Date.now();
}

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

async function check(symbol) {
  const client = new TradingView.Client();
  try {
    const indicator = await TradingView.getIndicator(INDICATOR);
    indicator.setOption("ATR_Multiplier", MULTIPLIER);

    const chart = new client.Session.Chart();
    chart.setMarket(symbol, {
      timeframe: TIMEFRAME,
      range: RANGE,
      session: "regular",
      adjustment: "splits"
    });

    const study = new chart.Study(indicator);

    return await new Promise((resolve,reject)=>{
      let done=false;
      const finish=v=>{ if(!done){done=true;resolve(v);} };
      study.onError((...e)=>{ if(!done) reject(new Error(JSON.stringify(e))); });
      study.onUpdate((changes)=>{
        if(!changes || !changes.includes("plots")) return;
        const periods = Array.isArray(study.periods) ? study.periods : [];
        const c = periods.filter(completed);
        if(c.length < 2) return;
        const cur=c[0], prev=c[1];
        const buy=Number(cur.SuperTrend_Buy)===1 && Number(cur.SuperTrend_Direction_Change)===1;
        finish({
          symbol,
          buy,
          curTime:Number(cur.$time),
          curClose:Number(cur.close),
          curBuy:cur.SuperTrend_Buy,
          curChange:cur.SuperTrend_Direction_Change,
          prevTime:Number(prev.$time),
          prevBuy:prev.SuperTrend_Buy,
          prevChange:prev.SuperTrend_Direction_Change,
          direction:cur.SuperTrend_Direction
        });
      });
      setTimeout(()=>{if(!done) reject(new Error("Study timeout"));},20000);
    });
  } finally { try{client.end();}catch(_){} }
}

(async()=>{
  console.log("STUDY TEST - 14 HISSE - NATIVE 2H");
  console.log("ATR=10 | MULTIPLIER=2 | HL2 | REGULAR | SPLITS");
  console.log("NO BROKER");
  console.log("=".repeat(70));
  let buys=0, errors=0;
  for(let i=0;i<SYMBOLS.length;i++){
    const s=SYMBOLS[i];
    try{
      const r=await check(s);
      const dt=new Date(r.curTime*1000).toLocaleString("tr-TR",{timeZone:"Europe/Istanbul",hour12:false});
      console.log(`[${i+1}/${SYMBOLS.length}] ${s} | ${dt} | close=${r.curClose} | curBuy=${r.curBuy} | change=${r.curChange} | dir=${r.direction} | BUY=${r.buy}`);
      if(r.buy) buys++;
    }catch(e){
      errors++;
      console.log(`[${i+1}/${SYMBOLS.length}] ${s} | STUDY ERROR: ${e.message||e}`);
    }
    await sleep(250);
  }
  console.log("=".repeat(70));
  console.log(`STUDY BUY COUNT: ${buys}`);
  console.log(`STUDY ERRORS: ${errors}`);
})().catch(e=>{console.error(e);process.exit(1);});
