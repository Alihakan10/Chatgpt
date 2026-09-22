import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOL = "BIST:DEVA"

def tv_official(candles, period=10, mult=2.0):
    # TradingView help-center band logic, with Wilder/RMA ATR.
    atr = scanner.calculate_atr(candles, period)
    upper = [None] * len(candles)
    lower = [None] * len(candles)
    direction = [None] * len(candles)
    st = [None] * len(candles)

    for i, c in enumerate(candles):
        if atr[i] is None:
            direction[i] = -1
            continue
        hl2 = (c["high"] + c["low"]) / 2.0
        basic_upper = hl2 + mult * atr[i]
        basic_lower = hl2 - mult * atr[i]

        if i == 0 or upper[i-1] is None:
            upper[i] = basic_upper
            lower[i] = basic_lower
        else:
            prev_upper = upper[i-1]
            prev_lower = lower[i-1]
            prev_close = candles[i-1]["close"]
            upper[i] = basic_upper if (basic_upper < prev_upper or prev_close > prev_upper) else prev_upper
            lower[i] = basic_lower if (basic_lower > prev_lower or prev_close < prev_lower) else prev_lower

        if i == 0 or direction[i-1] is None:
            direction[i] = -1
        elif st[i-1] == upper[i-1]:
            direction[i] = 1 if c["close"] > upper[i] else -1
        else:
            direction[i] = -1 if c["close"] < lower[i] else 1

        st[i] = lower[i] if direction[i] == 1 else upper[i]

    return direction, st, atr, upper, lower

def dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")

candles = scanner.get_tv_candles_with_retry(SYMBOL, candle_mode="native_2h")
idx = scanner.get_last_completed_index(candles)
if idx is None or idx < 1:
    raise RuntimeError("Tamamlanmis mum bulunamadi")

# Current production/Kivanc logic.
k = scanner.calculate_supertrend_directions(candles)
o_dir, o_st, o_atr, o_upper, o_lower = tv_official(candles)

print("=== DEVA SUPERTREND FARK DIAGNOSTIGI ===")
print("Mum sayisi:", len(candles))
print("Son tamamlanmis:", dt(candles[idx]["time"]))
print("Onceki:", dt(candles[idx-1]["time"]))

for j in [idx-2, idx-1, idx]:
    c = candles[j]
    print(
        f"MUM {dt(c['time'])} | O={c['open']:.4f} H={c['high']:.4f} "
        f"L={c['low']:.4f} C={c['close']:.4f} | "
        f"KIVANC={k[j]} | OFFICIAL={o_dir[j]} | "
        f"ATR={o_atr[j] if o_atr[j] is not None else None}"
    )

print(
    "KIVANC DONUS:",
    k[idx-1], "->", k[idx],
    "BUY=", (k[idx-1] == -1 and k[idx] == 1)
)
print(
    "OFFICIAL DONUS:",
    o_dir[idx-1], "->", o_dir[idx],
    "BUY=", (o_dir[idx-1] == -1 and o_dir[idx] == 1)
)

# History-window sensitivity: same Kivanc formula, different available history.
for size in [300, 500, 1000, 2000, 3000]:
    sub = candles[-size:] if len(candles) > size else candles
    d = scanner.calculate_supertrend_directions(sub)
    if len(d) >= 2:
        print(
            f"HISTORY {size}: last={d[-1]} prev={d[-2]} "
            f"BUY={d[-2] == -1 and d[-1] == 1}"
        )

# Print exact bands for the two latest bars.
print(
    "CURRENT CLOSE:",
    candles[idx]["close"],
    "KIVANC BUY FORMULU: previous/current SAT->AL"
)
