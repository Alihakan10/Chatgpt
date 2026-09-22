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

print("AUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
print("SETTINGS: ATR=10 MULTIPLIER=2.0 SOURCE=HL2 TIMEFRAME=2H")
print("BUY RULE: previous=-1 (SAT) -> current=+1 (AL)")

for symbol in SYMBOLS:
    print("\n===", symbol, "===")
    try:
        bars = sorted(scanner.get_tv_candles_with_retry(symbol, "native_2h"), key=lambda x:x["time"])
        idx = scanner.get_last_completed_index(bars)
        if idx is None or idx < 1:
            print("RESULT: INSUFFICIENT COMPLETED BARS")
            continue
        calc = bars[:idx+1]
        dirs = scanner.calculate_supertrend_directions(calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER)
        if not dirs or len(dirs) < 2:
            print("RESULT: SUPERTREND CALC FAILED")
            continue
        cur = dirs[-1]
        prev = dirs[-2]
        dt = datetime.fromtimestamp(calc[-1]["time"], tz=ZoneInfo("UTC")).astimezone(TZ)
        label = "AL" if cur == 1 else "SAT" if cur == -1 else str(cur)
        buy = prev == -1 and cur == 1
        print(f"LAST COMPLETED 2H: {dt:%Y-%m-%d %H:%M} O={calc[-1]['open']:.2f} H={calc[-1]['high']:.2f} L={calc[-1]['low']:.2f} C={calc[-1]['close']:.2f}")
        print(f"PREVIOUS DIRECTION: {prev} | CURRENT DIRECTION: {cur} ({label})")
        print("RESULT:", "BUY" if buy else "NO BUY")
        recent=[]
        start=max(1,len(dirs)-10)
        for i in range(start,len(dirs)):
            if dirs[i-1] == -1 and dirs[i] == 1:
                t=datetime.fromtimestamp(calc[i]["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
                recent.append(t.strftime("%Y-%m-%d %H:%M"))
        print("RECENT SAT->AL:", ", ".join(recent[-5:]) if recent else "none")
    except Exception as e:
        print("RESULT: ERROR:", e)
