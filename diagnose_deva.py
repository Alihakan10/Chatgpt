import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

def dt(ts):
    return datetime.fromtimestamp(ts,tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")

def show(name,bars):
    print(name)
    for b in bars:
        d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
        if d.date().isoformat()=="2026-09-22":
            print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")

print("=== DEVA 2H ALIGNMENT FIX TEST ===")
odd=scanner.get_tv_candles_with_retry("BIST:DEVA",candle_mode="session_merged_odd")
show("ODD SESSION 2H",odd)
dirs=scanner.calculate_supertrend_directions(odd)
for i,b in enumerate(odd):
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
    if d.date().isoformat()=="2026-09-22":
        print("ST",dt(b["time"]),dirs[i],f"C={b['close']:.2f}")
