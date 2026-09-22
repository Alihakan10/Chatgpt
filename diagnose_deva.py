import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

def dt(ts):
    return datetime.fromtimestamp(ts,tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")

print("=== DEVA SESSION MERGED VS NATIVE ===")
m=scanner.get_tv_candles_with_retry("BIST:DEVA",candle_mode="session_merged")
n=scanner.get_tv_candles_with_retry("BIST:DEVA",candle_mode="native_2h")
print("SESSION_MERGED")
for b in m:
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
    if d.date().isoformat()=="2026-09-22":
        print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
print("NATIVE_2H")
for b in n:
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
    if d.date().isoformat()=="2026-09-22":
        print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
