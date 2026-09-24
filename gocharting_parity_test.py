import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = [
"BIST:AKBNK","BIST:ASELS","BIST:THYAO","BIST:EREGL","BIST:TUPRS",
"BIST:SISE","BIST:KCHOL","BIST:SAHOL","BIST:YKBNK","BIST:GARAN",
"BIST:ISCTR","BIST:PETKM","BIST:TOASO","BIST:ZOREN",
]

def gocharting_style(candles, period=10, multiplier=2.0):
    # GoCharting docs: Supertrend uses multiplier + ATR length;
    # source HL2 is the documented midpoint for the bands.
    n=len(candles)
    if n < period+2: return None
    tr=[]
    for i,c in enumerate(candles):
        if i==0: tr.append(c["high"]-c["low"])
        else:
            pc=candles[i-1]["close"]
            tr.append(max(c["high"]-c["low"],abs(c["high"]-pc),abs(c["low"]-pc)))
    atr=[None]*n
    atr[period-1]=sum(tr[:period])/period
    for i in range(period,n):
        atr[i]=(atr[i-1]*(period-1)+tr[i])/period
    upper=[None]*n; lower=[None]*n; direction=[1]*n
    for i,c in enumerate(candles):
        if atr[i] is None: continue
        hl2=(c["high"]+c["low"])/2.0
        bu=hl2+multiplier*atr[i]; bl=hl2-multiplier*atr[i]
        if i==0:
            upper[i]=bu; lower[i]=bl; direction[i]=1; continue
        pu=upper[i-1]; pl=lower[i-1]; pc=candles[i-1]["close"]
        upper[i]=bu if bu < pu or pc > pu else pu
        lower[i]=bl if bl > pl or pc < pl else pl
        prev=direction[i-1]
        direction[i]=1 if prev==-1 and c["close"]>pu else -1 if prev==1 and c["close"]<pl else prev
    return direction

def main():
    print("GOCHARTING FORMULA PARITY TEST - ISOLATED")
    print("Study YOK | ana otomatik tarama branch'i degistirilmedi")
    for symbol in SYMBOLS:
        try:
            candles=sorted(scanner.get_tv_candles_with_retry(symbol,"native_2h"),key=lambda x:x["time"])
            idx=scanner.get_last_completed_index(candles)
            if idx is None or idx<1: raise RuntimeError("tamamlanmis 2H mum yok")
            candles=candles[:idx+1]
            tv=scanner.calculate_supertrend_directions(candles,10,2.0)
            gc=gocharting_style(candles,10,2.0)
            p=idx-1
            tv_flip=(tv[p],tv[idx]); gc_flip=(gc[p],gc[idx])
            same=tv_flip==gc_flip
            dt=datetime.fromtimestamp(candles[idx]["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
            print(f"{symbol} | {dt:%Y-%m-%d %H:%M} | TV={tv_flip[0]}->{tv_flip[1]} | GC-FORMULA={gc_flip[0]}->{gc_flip[1]} | SAME={same} | BUY={tv_flip==(-1,1)}")
        except Exception as e:
            print(f"{symbol} | ERROR | {e}")
if __name__=="__main__": main()
