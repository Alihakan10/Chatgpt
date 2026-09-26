import sys, json
sys.path.insert(0, ".")
from scanner import get_tv_candles, wilder_atr
SYMBOLS=["BIST:BAKAB","BIST:BARMA","BIST:BRKO","BIST:DGGYO","BIST:EUHOL","BIST:GSDHO","BIST:LMKDC","BIST:PAGYO","BIST:RNPOL","BIST:SANKO","BIST:SUNTK","BIST:VKFYO"]
PERIOD=10
def calc(candles,factor,mode):
    n=len(candles); atr=wilder_atr(candles,PERIOD)
    up=[None]*n; dn=[None]*n; trend=[1]*n; buy=[False]*n
    for i in range(n):
        if atr[i] is None: continue
        h=(candles[i]["high"]+candles[i]["low"])/2
        u=h-factor*atr[i]; d=h+factor*atr[i]
        pu=up[i-1] if i and up[i-1] is not None else u
        pd=dn[i-1] if i and dn[i-1] is not None else d
        pc=candles[i-1]["close"] if i else None
        up[i]=max(u,pu) if i and pc>pu else u
        dn[i]=min(d,pd) if i and pc<pd else d
        if i==PERIOD-1: continue
        pt=trend[i-1]
        band=pd if pt==-1 else pu
        if pt==-1 and candles[i]["close"]>band: trend[i]=1; buy[i]=True
        elif pt==1 and candles[i]["close"]<band: trend[i]=-1
        else: trend[i]=pt
    return buy[-1]
for s in SYMBOLS:
    cs=get_tv_candles(s,candle_mode="native_2h",candle_session="regular")
    idx=next((i for i,c in enumerate(cs) if c["time"]==1790344800.0),None)
    if idx is None: print(s,"NO_TARGET"); continue
    out={}
    for f in (2.0,3.0):
        out[str(f)]=calc(cs[:idx+1],f,"x")
    print(s,json.dumps(out))
