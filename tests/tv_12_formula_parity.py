import sys, json
sys.path.insert(0, ".")
from scanner import get_tv_candles

SYMBOLS=["BIST:BAKAB","BIST:BARMA","BIST:BRKO","BIST:DGGYO","BIST:EUHOL","BIST:GSDHO","BIST:LMKDC","BIST:PAGYO","BIST:RNPOL","BIST:SANKO","BIST:SUNTK","BIST:VKFYO"]
PERIOD=10
TARGET=1790344800.0

def tr_values(c):
    out=[]
    for i,x in enumerate(c):
        if i==0: out.append(x["high"]-x["low"])
        else:
            pc=c[i-1]["close"]
            out.append(max(x["high"]-x["low"],abs(x["high"]-pc),abs(x["low"]-pc)))
    return out

def atr(c,method):
    tr=tr_values(c); n=len(c); a=[None]*n
    if n<PERIOD: return a
    a[PERIOD-1]=sum(tr[:PERIOD])/PERIOD
    if method=="SMA":
        for i in range(PERIOD,n): a[i]=sum(tr[i-PERIOD+1:i+1])/PERIOD
    else:
        for i in range(PERIOD,n): a[i]=(a[i-1]*(PERIOD-1)+tr[i])/PERIOD
    return a

def calc(c,factor,method):
    n=len(c); a=atr(c,method); up=[None]*n; dn=[None]*n; trend=[1]*n; buy=[False]*n
    for i in range(n):
        if a[i] is None: continue
        h=(c[i]["high"]+c[i]["low"])/2
        u=h-factor*a[i]; d=h+factor*a[i]
        pu=up[i-1] if i and up[i-1] is not None else u
        pd=dn[i-1] if i and dn[i-1] is not None else d
        pc=c[i-1]["close"] if i else None
        up[i]=max(u,pu) if i and pc>pu else u
        dn[i]=min(d,pd) if i and pc<pd else d
        if i==PERIOD-1: continue
        pt=trend[i-1]
        if pt==-1:
            trend[i]=1 if c[i]["close"]>pd else -1
            buy[i]=trend[i]==1
        else:
            trend[i]=-1 if c[i]["close"]<pu else 1
    return a,up,dn,trend,buy

for s in SYMBOLS:
    cs=get_tv_candles(s,candle_mode="native_2h",candle_session="regular")
    idx=next((i for i,c in enumerate(cs) if c["time"]==TARGET),None)
    print("\n===",s,"===")
    if idx is None: print("NO_TARGET"); continue
    for method in ("RMA","SMA"):
        for f in (2.0,3.0):
            a,u,d,t,b=calc(cs[:idx+1],f,method); p=idx-1
            print(json.dumps({"method":method,"factor":f,"prev_trend":t[p],"prev_dn":round(d[p],6),"atr":round(a[idx],6),"close":cs[idx]["close"],"buy":b[idx]},separators=(",",":")))
