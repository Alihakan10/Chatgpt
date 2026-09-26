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

def atr(c):
    tr=tr_values(c); n=len(c); a=[None]*n
    if n<PERIOD: return a
    a[PERIOD-1]=sum(tr[:PERIOD])/PERIOD
    for i in range(PERIOD,n):
        a[i]=(a[i-1]*(PERIOD-1)+tr[i])/PERIOD
    return a

def kivanc_cc(c,factor=2.0):
    n=len(c); a=atr(c); up=[None]*n; dn=[None]*n; trend=[1]*n; buy=[False]*n
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
    return trend,buy

def tv_builtin(c,factor=2.0):
    n=len(c); a=atr(c); upper=[None]*n; lower=[None]*n; st=[None]*n; direction=[None]*n; buy=[False]*n
    for i in range(n):
        if a[i] is None:
            direction[i]=1
            continue
        h=(c[i]["high"]+c[i]["low"])/2
        bu=h+factor*a[i]; bl=h-factor*a[i]
        pu=upper[i-1] if i and upper[i-1] is not None else 0.0
        pl=lower[i-1] if i and lower[i-1] is not None else 0.0
        upper[i]=bu if i==0 or bu<pu or c[i]["close"]>pu else pu
        lower[i]=bl if i==0 or bl>pl or c[i]["close"]<pl else pl
        if i==PERIOD-1:
            direction[i]=1
        else:
            prev_st=st[i-1]
            prev_upper=upper[i-1]
            if prev_st is None:
                direction[i]=1
            elif prev_st == prev_upper:
                direction[i]=-1 if c[i]["close"]>upper[i] else 1
            else:
                direction[i]=1 if c[i]["close"]<lower[i] else -1
        st[i]=lower[i] if direction[i]==-1 else upper[i]
        if i>0 and direction[i-1]==1 and direction[i]==-1:
            buy[i]=True
    return direction,buy

for s in SYMBOLS:
    cs=get_tv_candles(s,candle_mode="native_2h",candle_session="regular")
    idx=next((i for i,c in enumerate(cs) if c["time"]==TARGET),None)
    print("\n===",s,"===")
    if idx is None:
        print("NO_TARGET")
        continue
    c=cs[:idx+1]
    kt,kb=kivanc_cc(c,2.0)
    vt,vb=tv_builtin(c,2.0)
    print(json.dumps({
        "target_close":c[-1]["close"],
        "kivanc_cc_buy":kb[-1],
        "kivanc_cc_direction":kt[-1],
        "tv_builtin_buy":vb[-1],
        "tv_builtin_direction":vt[-1],
        "kivanc_prev_direction":kt[-2],
        "tv_builtin_prev_direction":vt[-2]
    },separators=(",",":")))
