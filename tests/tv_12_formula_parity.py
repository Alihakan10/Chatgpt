import sys, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, ".")
from scanner import get_tv_candles, wilder_atr

SYMBOLS=["BIST:BAKAB","BIST:BARMA","BIST:BRKO","BIST:DGGYO","BIST:EUHOL","BIST:GSDHO","BIST:LMKDC","BIST:PAGYO","BIST:RNPOL","BIST:SANKO","BIST:SUNTK","BIST:VKFYO"]
PERIOD=10
TARGET=1790344800.0
TZ=ZoneInfo("Europe/Istanbul")

def calc(candles,factor):
    n=len(candles); atr=wilder_atr(candles,PERIOD)
    up=[None]*n; dn=[None]*n; trend=[1]*n; buy=[False]*n
    for i in range(n):
        if atr[i] is None: continue
        hl2=(candles[i]["high"]+candles[i]["low"])/2
        up0=hl2-factor*atr[i]; dn0=hl2+factor*atr[i]
        pu=up[i-1] if i and up[i-1] is not None else up0
        pd=dn[i-1] if i and dn[i-1] is not None else dn0
        pc=candles[i-1]["close"] if i else None
        up[i]=max(up0,pu) if i and pc>pu else up0
        dn[i]=min(dn0,pd) if i and pc<pd else dn0
        if i==PERIOD-1: continue
        pt=trend[i-1]
        if pt==-1:
            if candles[i]["close"]>pd:
                trend[i]=1; buy[i]=True
            else: trend[i]=-1
        else:
            if candles[i]["close"]<pu: trend[i]=-1
            else: trend[i]=1
    return atr,up,dn,trend,buy

for s in SYMBOLS:
    cs=get_tv_candles(s,candle_mode="native_2h",candle_session="regular")
    idx=next((i for i,c in enumerate(cs) if c["time"]==TARGET),None)
    print("\n===",s,"===")
    if idx is None:
        print("NO_TARGET"); continue
    print("target",datetime.fromtimestamp(TARGET,timezone.utc).astimezone(TZ).isoformat(),"index",idx,"history",len(cs))
    for f in (2.0,3.0):
        atr,up,dn,tr,buy=calc(cs[:idx+1],f)
        i=idx
        prev=i-1
        print("factor",f,
              "prev_trend",tr[prev],
              "prev_up",round(up[prev],6) if up[prev] is not None else None,
              "prev_dn",round(dn[prev],6) if dn[prev] is not None else None,
              "atr",round(atr[i],6) if atr[i] is not None else None,
              "close",cs[i]["close"],
              "buy",buy[i],
              "trend",tr[i])
        print("prev_candle",json.dumps(cs[prev],separators=(",",":")))
