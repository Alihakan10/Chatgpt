import os
from datetime import datetime
from zoneinfo import ZoneInfo
import scanner

SYMBOLS = [
    "BIST:CLEBI","BIST:EMNIS","BIST:EUHOL","BIST:KENT",
    "BIST:KERVN","BIST:KLYPV","BIST:KRPLS","BIST:KSTUR",
    "BIST:OYLUM","BIST:SODSN","BIST:TUCLK","BIST:TURSG",
    "BIST:ULUFA","BIST:USHOL",
]

TZ = ZoneInfo("Europe/Istanbul")

for symbol in SYMBOLS:
    print("\n===", symbol, "===")
    try:
        bars = scanner.get_tv_candles_with_retry(symbol, "session_merged")
        bars = sorted(bars, key=lambda x: x["time"])
        idx = scanner.get_last_completed_index(bars)\n        if idx is not None and idx >= 1:\n            calc = bars[:idx+1]\n            dirs = scanner.calculate_tradingview_supertrend_directions(calc)\n            print("DIRECTION:", "PREV=", dirs[-2], "CUR=", dirs[-1], "BUY=", dirs[-2] == 1 and dirs[-1] == -1)\n        for b in bars[-5:]:
            d = datetime.fromtimestamp(b["time"], tz=ZoneInfo("UTC")).astimezone(TZ)
            print(d.strftime("%Y-%m-%d %H:%M"), f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
    except Exception as e:
        print("ERROR:", e)

print("\nAUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
