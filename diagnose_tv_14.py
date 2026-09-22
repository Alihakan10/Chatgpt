import os
from datetime import datetime
from zoneinfo import ZoneInfo
import scanner

SYMBOLS = ["BIST:KENT", "BIST:DEVA"]
TZ = ZoneInfo("Europe/Istanbul")

def show(label, bars):
    bars = sorted(bars, key=lambda x: x["time"])
    print(f"\n--- {label}: {len(bars)} bars ---")
    for b in bars[-12:]:
        dt = datetime.fromtimestamp(b["time"], tz=ZoneInfo("UTC")).astimezone(TZ)
        print(dt.strftime("%Y-%m-%d %H:%M"), f"ts={int(b['time'])}",
              f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")

for symbol in SYMBOLS:
    print("\n================", symbol, "================")
    for session in ("regular", "extended"):
        for mode in ("native_1h", "native_2h"):
            try:
                bars = scanner.get_tv_candles_with_retry(symbol, mode, session)
                show(f"{session.upper()} {mode.upper()}", bars)
            except Exception as e:
                print(f"{session} {mode} ERROR:", e)

print("\nAUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
