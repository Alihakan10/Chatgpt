import json
from scanner import get_tv_candles

SYMBOLS = [
    "BIST:BAKAB","BIST:BARMA","BIST:BRKO","BIST:DGGYO",
    "BIST:EUHOL","BIST:GSDHO","BIST:LMKDC","BIST:PAGYO",
    "BIST:RNPOL","BIST:SANKO","BIST:SUNTK","BIST:VKFYO"
]
PERIOD = 10
FACTOR = 2.0
TARGET = 1790344800.0

def exact_tv(c):
    n=len(c)
    tr=[]
    for i,x in enumerate(c):
        if i==0:
            tr.append(x["high"]-x["low"])
        else:
            pc=c[i-1]["close"]
            tr.append(max(x["high"]-x["low"],abs(x["high"]-pc),abs(x["low"]-pc)))
    atr=[None]*n
    if n >= PERIOD:
        atr[PERIOD-1]=sum(tr[:PERIOD])/PERIOD
        for i in range(PERIOD,n):
            atr[i]=(atr[i-1]*(PERIOD-1)+tr[i])/PERIOD

    upper=[None]*n; lower=[None]*n; st=[None]*n; direction=[None]*n
    buy=[False]*n
    for i in range(n):
        if atr[i] is None:
            continue
        hl2=(c[i]["high"]+c[i]["low"])/2.0
        bu=hl2+FACTOR*atr[i]
        bl=hl2-FACTOR*atr[i]
        prev_u=upper[i-1] if i>0 and upper[i-1] is not None else 0.0
        prev_l=lower[i-1] if i>0 and lower[i-1] is not None else 0.0
        prev_close=c[i-1]["close"] if i>0 else None
        upper[i]=bu if bu < prev_u or prev_close > prev_u else prev_u
        lower[i]=bl if bl > prev_l or prev_close < prev_l else prev_l

        # TradingView ta.supertrend: until ATR is calculated = downtrend (+1).
        if i == PERIOD-1 or atr[i-1] is None:
            direction[i]=1
        elif st[i-1] == upper[i-1]:
            direction[i]=-1 if c[i]["close"] > upper[i] else 1
        else:
            direction[i]=1 if c[i]["close"] < lower[i] else -1
        st[i]=lower[i] if direction[i] == -1 else upper[i]
        if i>0:
            buy[i]=direction[i-1] > 0 and direction[i] < 0
    return direction,buy,upper,lower,st

for s in SYMBOLS:
    c=get_tv_candles(s,candle_mode="native_2h",candle_session="regular")
    idx=next((i for i,x in enumerate(c) if x["time"]==TARGET),None)
    print("\n===",s,"===")
    if idx is None:
        print("NO_TARGET")
        continue
    d,b,u,l,st=exact_tv(c[:idx+1])
    print(json.dumps({
        "target_time":TARGET,
        "close":c[idx]["close"],
        "prev_direction":d[-2],
        "direction":d[-1],
        "BUY":b[-1],
        "prev_st":st[-2],
        "prev_upper":u[-2],
        "upper":u[-1],
        "lower":l[-1]
    },separators=(",",":")))
