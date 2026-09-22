"""
15 mevcut BUY icin native TradingView 2H birebir matematik kontrolu.
Study kullanmaz. scanner.py'nin Supertrend sonucunu kullanmaz.
Sadece TradingView native 2H OHLC verisini alip bagimsiz Pine-esdeger
Wilder RMA + HL2 Supertrend hesaplar.
"""
import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = [
    "BIST:AKFGY","BIST:ALVES","BIST:BARMA","BIST:BINHO","BIST:BRISA",
    "BIST:DEVA","BIST:EGGUB","BIST:EGPRO","BIST:FLAP","BIST:FZLGY",
    "BIST:KRVGD","BIST:RUZYE","BIST:SRVGY","BIST:SUMAS","BIST:TUREX",
]

PERIOD = 10
MULT = 2.0

def calc(candles):
    tr=[]; atr=[None]*len(candles); ub=[None]*len(candles)
    lb=[None]*len(candles); d=[None]*len(candles)
    for i,c in enumerate(candles):
        if i==0: x=c["high"]-c["low"]
        else:
            pc=candles[i-1]["close"]
            x=max(c["high"]-c["low"],abs(c["high"]-pc),abs(c["low"]-pc))
        tr.append(x)
    atr[PERIOD-1]=sum(tr[:PERIOD])/PERIOD
    for i in range(PERIOD,len(candles)):
        atr[i]=(atr[i-1]*(PERIOD-1)+tr[i])/PERIOD
    for i in range(PERIOD-1,len(candles)):
        hl2=(candles[i]["high"]+candles[i]["low"])/2
        ru=hl2+MULT*atr[i]; rl=hl2-MULT*atr[i]
        if i==PERIOD-1:
            ub[i]=ru; lb[i]=rl; d[i]=-1; continue
        pc=candles[i-1]["close"]
        ub[i]=ru if ru<ub[i-1] or pc>ub[i-1] else ub[i-1]
        lb[i]=rl if rl>lb[i-1] or pc<lb[i-1] else lb[i-1]
        d[i]=1 if d[i-1]==-1 and candles[i]["close"]>ub[i-1] else (-1 if d[i-1]==1 and candles[i]["close"]<lb[i-1] else d[i-1])
    return d,atr,ub,lb

def label(x): return "AL" if x==1 else "SAT" if x==-1 else "?"

def main():
    ok=0; err=0
    print("=== 15 BUY NATIVE TRADINGVIEW KONTROLU ===", flush=True)
    for s in SYMBOLS:
        try:
            candles=sorted(scanner.get_tv_candles(s,"native_2h"),key=lambda x:x["time"])
            i=scanner.get_last_completed_index(candles)
            if i is None or i<PERIOD+1: raise RuntimeError("tamamlanmis 2H mum yok")
            d,atr,ub,lb=calc(candles[:i+1])
            p=i-1
            dt=datetime.fromtimestamp(candles[i]["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(scanner.TIMEZONE))
            c=candles[i]
            buy=d[p]==-1 and d[i]==1
            print(f"{s} | {dt:%d.%m.%Y %H:%M} | O={c['open']:.4f} H={c['high']:.4f} L={c['low']:.4f} C={c['close']:.4f} | ATR={atr[i]:.6f} | UB={ub[i]:.6f} | LB={lb[i]:.6f} | {label(d[p])}->{label(d[i])} | BUY={buy}",flush=True)
            ok+=1
        except Exception as e:
            print(f"{s} | HATA={e}",flush=True); err+=1
    print(f"SONUC | Kontrol={ok}/15 | Hata={err}",flush=True)

if __name__=="__main__": main()
