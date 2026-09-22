import os
from datetime import datetime
from zoneinfo import ZoneInfo
import scanner

SYMBOLS = ["BIST:KENT", "BIST:DEVA"]
TZ = ZoneInfo("Europe/Istanbul")

def show(label, bars):
    bars = sorted(bars, key=lambda x: x["time"])
    print(f"\n--- {label}: {len(bars)} bars ---")
    for b in bars[-16:]:
        dt = datetime.fromtimestamp(b["time"], tz=ZoneInfo("UTC")).astimezone(TZ)
        print(dt.strftime("%Y-%m-%d %H:%M"), f"ts={int(b['time'])}",
              f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
    recent = bars[-16:]
    print("GAPS:")
    for a,b in zip(recent, recent[1:]):
        delta = (b["time"]-a["time"])/3600
        if delta != (1 if "1H" in label else 2):
            da=datetime.fromtimestamp(a["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
            db=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
            print(" ", da.strftime("%m-%d %H:%M"), "->", db.strftime("%m-%d %H:%M"), f"{delta:.1f}h")

for symbol in SYMBOLS:
    print("\n================", symbol, "================")
    try:
        h1 = scanner.get_tv_candles_with_retry(symbol, "native_1h")
        show("NATIVE 1H", h1)
    except Exception as e:
        print("1H ERROR:", e)
    try:
        h2 = scanner.get_tv_candles_with_retry(symbol, "native_2h")
        show("NATIVE 2H", h2)
    except Exception as e:
        print("2H ERROR:", e)

print("\nAUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
