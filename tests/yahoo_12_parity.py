import json, urllib.request, urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SYMBOLS = ["BAKAB","BARMA","BRKO","DGGYO","EUHOL","GSDHO","LMKDC","PAGYO","RNPOL","SANKO","SUNTK","VKFYO"]
TZ=ZoneInfo("Europe/Istanbul")
ATR_PERIOD=10
FACTOR=2.0

def yahoo(sym):
    p1=int(datetime(2026,9,20,tzinfo=timezone.utc).timestamp())
    p2=int(datetime(2026,9,27,tzinfo=timezone.utc).timestamp())
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}.IS?period1={p1}&period2={p2}&interval=1h&events=history&includeAdjustedClose=true"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=20) as r:
        d=json.load(r)["chart"]["result"][0]
    q=d["indicators"]["quote"][0]
    out=[]
    for i,t in enumerate(d["timestamp"]):
        if q["open"][i] is None: continue
        out.append({"time":t,"open":q["open"][i],"high":q["high"][i],"low":q["low"][i],"close":q["close"][i],"volume":q["volume"][i]})
    return out

def agg_2h(xs):
    # TradingView BIST 2H chart alignment visible in the reference charts:
    # 11:00, 13:00, 15:00, 17:00 anchors (with the final 17:00 bar
    # shortened by the session close). Build the 2H bars from hourly OHLC
    # without shifting timestamps.
    by={}
    for x in xs:
        dt=datetime.fromtimestamp(x["time"],timezone.utc).astimezone(TZ)
        if dt.weekday()>=5 or dt.hour<9 or dt.hour>=18: continue
        if dt.hour == 17:
            key=(dt.date(),17)
        elif dt.hour in (9,10):
            key=(dt.date(),9)
        elif dt.hour in (11,12):
            key=(dt.date(),11)
        elif dt.hour in (13,14):
            key=(dt.date(),13)
        elif dt.hour in (15,16):
            key=(dt.date(),15)
        else:
            continue
        by.setdefault(key,[]).append(x)
    out=[]
    for (day,start), bars in sorted(by.items()):
        bars=sorted(bars,key=lambda z:z["time"])
        if start==17:
            if len(bars)!=1: continue
        elif len(bars)!=2:
            continue
        out.append({
            "time":bars[0]["time"],
            "open":bars[0]["open"],
            "high":max(x["high"] for x in bars),
            "low":min(x["low"] for x in bars),
            "close":bars[-1]["close"],
            "volume":sum(x["volume"] or 0 for x in bars)
        })
    return out

def atr(cs):
    tr=[]
    for i,c in enumerate(cs):
        if i==0: v=c["high"]-c["low"]
        else:
            pc=cs[i-1]["close"]
            v=max(c["high"]-c["low"],abs(c["high"]-pc),abs(c["low"]-pc))
        tr.append(v)
    a=[None]*len(cs)
    if len(cs)<ATR_PERIOD:return a
    a[ATR_PERIOD-1]=sum(tr[:ATR_PERIOD])/ATR_PERIOD
    for i in range(ATR_PERIOD,len(cs)):
        a[i]=(a[i-1]*(ATR_PERIOD-1)+tr[i])/ATR_PERIOD
    return a

def cc(cs):
    a=atr(cs)
    up=[None]*len(cs); dn=[None]*len(cs)
    trend=[1]*len(cs); buy=[False]*len(cs)
    for i,c in enumerate(cs):
        if a[i] is None: continue
        h=(c["high"]+c["low"])/2
        u0=h-FACTOR*a[i]; d0=h+FACTOR*a[i]
        u1=up[i-1] if i and up[i-1] is not None else u0
        d1=dn[i-1] if i and dn[i-1] is not None else d0
        if i:
            up[i]=max(u0,u1) if cs[i-1]["close"]>u1 else u0
            dn[i]=min(d0,d1) if cs[i-1]["close"]<d1 else d0
        else:
            up[i]=u0; dn[i]=d0
        if i<ATR_PERIOD: continue
        if trend[i-1]==-1:
            if c["close"]>d1:
                trend[i]=1; buy[i]=True
            else:
                trend[i]=-1
        else:
            trend[i]=-1 if c["close"]<u1 else 1
    return buy

results={}
for s in SYMBOLS:
    try:
        cs=agg_2h(yahoo(s))
        b=cc(cs)
        row=None
        for i,c in enumerate(cs):
            dt=datetime.fromtimestamp(c["time"],timezone.utc).astimezone(TZ)
            if dt.date().isoformat()=="2026-09-25" and dt.hour==17:
                row={
                    "bars":len(cs),
                    "time":dt.isoformat(),
                    "open":c["open"],"high":c["high"],
                    "low":c["low"],"close":c["close"],
                    "buy":bool(b[i])
                }
        results[s]=row or {"bars":len(cs),"error":"25 Sep 17:00 bar not found"}
    except Exception as e:
        results[s]={"error":str(e)}
print(json.dumps(results,indent=2,ensure_ascii=False))
