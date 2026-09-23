import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = [
    "BIST:ACSEL","BIST:AKSUE","BIST:ATSYH","BIST:BESLR","BIST:BMSCH",
    "BIST:DMRGD","BIST:EMNIS","BIST:ENPRA","BIST:MOBTL","BIST:PETUN",
]
TARGET = datetime(2026,9,23,17,0,tzinfo=ZoneInfo("Europe/Istanbul")).timestamp()

def kivanc(candles, period=10, mult=2.0):
    n=len(candles)
    tr=[0.0]*n
    for i,c in enumerate(candles):
        if i==0:
            tr[i]=c["high"]-c["low"]
        else:
            pc=candles[i-1]["close"]
            tr[i]=max(c["high"]-c["low"], abs(c["high"]-pc), abs(c["low"]-pc))
    atr=[None]*n
    atr[period-1]=sum(tr[:period])/period
    for i in range(period,n):
        atr[i]=(atr[i-1]*(period-1)+tr[i])/period
    up=[None]*n; dn=[None]*n; trend=[1]*n
    for i,c in enumerate(candles):
        if atr[i] is None:
            continue
        src=(c["high"]+c["low"])/2.0
        up0=src-mult*atr[i]
        up1=up[i-1] if i>0 and up[i-1] is not None else up0
        up[i]=max(up0,up1) if i>0 and candles[i-1]["close"]>up1 else up0
        dn0=src+mult*atr[i]
        dn1=dn[i-1] if i>0 and dn[i-1] is not None else dn0
        dn[i]=min(dn0,dn1) if i>0 and candles[i-1]["close"]<dn1 else dn0
        prev=trend[i-1] if i>0 else 1
        trend[i]=1 if prev==-1 and c["close"]>dn1 else (-1 if prev==1 and c["close"]<up1 else prev)
    return trend

for s in SYMBOLS:
    try:
        cs=sorted(scanner.get_tv_candles_with_retry(s,"native_2h"), key=lambda x:x["time"])
        idx=next(i for i,c in enumerate(cs) if float(c["time"])==TARGET)
        k=kivanc(cs,10,2.0)
        tv=scanner.calculate_tradingview_supertrend_directions(cs,10,2.0)
        app=scanner.calculate_supertrend_directions(cs,10,2.0)
        print(f"{s} | TARGET=23.09.2026 17:00 | OHLC={cs[idx]['open']},{cs[idx]['high']},{cs[idx]['low']},{cs[idx]['close']} | KIVANC={k[idx-1]}->{k[idx]} BUY={k[idx-1]==-1 and k[idx]==1} | OFFICIAL_TV={tv[idx-1]}->{tv[idx]} | APP={app[idx-1]}->{app[idx]} BUY={app[idx-1]==-1 and app[idx]==1}")
    except Exception as e:
        print(f"{s} | ERROR={e}")
