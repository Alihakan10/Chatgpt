import os
from datetime import datetime
from zoneinfo import ZoneInfo
import scanner

SYMBOL="BIST:KENT"
TZ=ZoneInfo("Europe/Istanbul")

print("AUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
print("KENT EXACT FEED COMPARISON")
print("A) native TradingView 120")
print("B) TradingView 60 -> existing session merge")
print("No Study.")

def show(label, bars):
    bars=sorted(bars,key=lambda x:x["time"])
    print("\n###",label,"COUNT",len(bars))
    for b in bars[-8:]:
        d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
        print(f"{d:%Y-%m-%d %H:%M} O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")

for mode in ("native_2h","session_merged"):
    try:
        bars=scanner.get_tv_candles_with_retry(SYMBOL,mode)
        show(mode,bars)
        idx=scanner.get_last_completed_index(bars)
        if idx is not None and idx>=1:
            calc=bars[:idx+1]
            dirs=scanner.calculate_supertrend_directions(calc,scanner.ATR_PERIOD,scanner.ATR_MULTIPLIER)
            print("LAST COMPLETED:",datetime.fromtimestamp(calc[-1]["time"],tz=ZoneInfo("UTC")).astimezone(TZ))
            print("PREV/CUR:",dirs[-2],dirs[-1],"BUY" if dirs[-2]==-1 and dirs[-1]==1 else "NO BUY")
    except Exception as e:
        print("ERROR",mode,repr(e))
