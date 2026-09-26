import sys, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, ".")
from scanner import get_tv_candles

SYMBOLS=["BIST:BAKAB","BIST:BARMA","BIST:BRKO","BIST:DGGYO","BIST:EUHOL","BIST:GSDHO","BIST:LMKDC","BIST:PAGYO","BIST:RNPOL","BIST:SANKO","BIST:SUNTK","BIST:VKFYO"]
PERIOD=10
TARGET=1790344800.0
TZ=ZoneInfo("Europe/Istanbul")

def wilder_atr(candles, period=10):
    tr=[]
    for i,c in enumerate(candles):
        if i==0: v=c["high"]-c["low"]
        else:
            pc=candles[i-1]["close"]
            v=max(c["high"]-c["low"],abs(c["high"]-pc),abs(c["low"]-pc))
        tr.append(v)
    atr=[None]*len(candles)
    if len(candles)<period: return atr
    atr[period-1]=sum(tr[:period])/period
    for i in range(period,len(candles)):
        atr[i]=(atr[i-1]*(period-1)+tr[i])/period
    return atr

def calc(candles,factor):
    n=len(candles); atr=wilder_atr(candles,PERIOD)
    up=[None]*n; dn=[None]*n; trend=[1]*n; buy=[False]*n
    for i in range(n):
        if atr[i] is None: continue
        hl2=(candles[i]["high"]+candles[i]["low"])/2
        u=hl2-factor*atr[i]; d=hl2+factor*atr[i]
        pu=up[i-1] if i and up[i-1] is not None else u
        pd=dn[i-1] if i and dn[i-1] is not None else d
        pc=candles[i-1]["close"] if i else None
        up[i]=max(u,pu) if i and pc>pu else u
        dn[i]=min(d,pd) if i and pc<pd else d
        if i==PERIOD-1: continue
        pt=trend[i-1]
        if pt==-1:
            trend[i]=1 if candles[i]["close"]>pd else -1
            buy[i]=trend[i]==1
        else:
            trend[i]=-1 if candles[i]["close"]<pu else 1
    return atr,up,dn,trend,buy

for s in SYMBOLS:
    cs=get_tv_candles(s,candle_mode="native_2h",candle_session="regular")
    idx=next((i for i,c in enumerate(cs) if c["time"]==TARGET),None)
    print("\n===",s,"===")
    if idx is None: print("NO_TARGET"); continue
    for f in (2.0,3.0):
        atr,up,dn,tr,buy=calc(cs[:idx+1],f)
        i=idx; p=i-1
        print(json.dumps({
            "factor":f,
            "prev_trend":tr[p],
            "prev_up":round(up[p],6),
            "prev_dn":round(dn[p],6),
            "atr_17":round(atr[i],6),
            "close_17":cs[i]["close"],
            "prev_band_for_buy":round(dn[p],6),
            "buy":buy[i],
            "trend_17":tr[i]
        },separators=(",",":")))
