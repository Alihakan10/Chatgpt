const TradingView = require("@mathieuc/tradingview");

const INDICATOR = "PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45";
const SYMBOLS = ["BIST:CLEBI","BIST:EMNIS","BIST:EUHOL"];
const TIMEFRAME = "120";

function completed(p) {
  if (!p || p.$time == null) return false;
  const d = new Date(Number(p.$time) * 1000);
  const end = new Date(d.getTime() + 2 * 3600 * 1000);
  return end.getTime() <= Date.now();
}
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

(async()=>{
  const client = new TradingView.Client();
  try {
    const indicator = await TradingView.getIndicator(INDICATOR);
    indicator.setOption("ATR_Multiplier", 2.0);
    const chart = new client.Session.Chart();

    console.log("ONE CHART / ONE STUDY / SEQUENTIAL setMarket TEST");
    console.log("ATR=10 | MULTIPLIER=2 | HL2 | NATIVE 2H | REGULAR | SPLITS");

    let study = null;
    let first = true;

    for (const symbol of SYMBOLS) {
      console.log("\nSET MARKET:", symbol);
      chart.setMarket(symbol, {
        timeframe: TIMEFRAME,
        range: 500,
        session: "regular",
        adjustment: "splits"
      });

      if (first) {
        first = false;
        study = new chart.Study(indicator);
        study.onError((...e)=>console.log("STUDY ERROR", JSON.stringify(e)));
      }

      const result = await new Promise((resolve,reject)=>{
        let timer=setTimeout(()=>reject(new Error("timeout")),20000);
        let lastLen=0;
        const handler=(changes)=>{
          if(!changes || !changes.includes("plots")) return;
          const periods=Array.isArray(study.periods)?study.periods:[];
          if(periods.length===lastLen) return;
          lastLen=periods.length;
          const c=periods.filter(completed);
          if(c.length<2) return;
          const cur=c[0];
          clearTimeout(timer);
          resolve({
            symbol,
            count: periods.length,
            curTime:Number(cur.$time),
            close:Number(cur.close),
            buy:cur.SuperTrend_Buy,
            change:cur.SuperTrend_Direction_Change,
            direction:cur.SuperTrend_Direction
          });
        };
        study.onUpdate(handler);
      }).catch(e=>({symbol,error:e.message}));
      console.log(JSON.stringify(result));
      await sleep(1000);
    }
  } finally { try{client.end();}catch(_){} }
})().catch(e=>{console.error(e);process.exit(1);});
