import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOL = "BIST:DEVA"

def calculate_atr_sma(candles, period=10):
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c["high"] - c["low"])
        else:
            pc = candles[i-1]["close"]
            tr.append(max(
                c["high"] - c["low"],
                abs(c["high"] - pc),
                abs(c["low"] - pc),
            ))
    atr = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        atr[i] = sum(tr[i-period+1:i+1]) / period
    return atr

def kivanc_with_atr(candles, atr, period=10, mult=2.0):
    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [None] * len(candles)

    for i, c in enumerate(candles):
        if atr[i] is None:
            trend[i] = 1 if i == 0 else trend[i-1]
            continue

        src = (c["high"] + c["low"]) / 2.0
        raw_up = src - mult * atr[i]
        raw_dn = src + mult * atr[i]

        up1 = raw_up if i == 0 or up[i-1] is None else up[i-1]
        dn1 = raw_dn if i == 0 or dn[i-1] is None else dn[i-1]

        up[i] = raw_up if i == 0 else (
            max(raw_up, up1) if candles[i-1]["close"] > up1 else raw_up
        )
        dn[i] = raw_dn if i == 0 else (
            min(raw_dn, dn1) if candles[i-1]["close"] < dn1 else raw_dn
        )

        prev = 1 if i == 0 or trend[i-1] is None else trend[i-1]
        if prev == -1 and c["close"] > dn1:
            trend[i] = 1
        elif prev == 1 and c["close"] < up1:
            trend[i] = -1
        else:
            trend[i] = prev

    return trend, up, dn, atr

def tv_official(candles, atr, mult=2.0):
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
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Istanbul")
    ).strftime("%d.%m.%Y %H:%M")

candles = scanner.get_tv_candles_with_retry(SYMBOL, candle_mode="native_2h")
idx = scanner.get_last_completed_index(candles)
if idx is None or idx < 2:
    raise RuntimeError("Yeterli tamamlanmis mum bulunamadi")

k_rma, k_up, k_dn, rma_atr = kivanc_with_atr(
    candles, scanner.calculate_atr(candles, 10), 10, 2.0
)
k_sma, s_up, s_dn, sma_atr = kivanc_with_atr(
    candles, calculate_atr_sma(candles, 10), 10, 2.0
)
o_rma, _, _, o_up, o_low = tv_official(
    candles, scanner.calculate_atr(candles, 10), 2.0
)
o_sma, _, _, _, _ = tv_official(candles, calculate_atr_sma(candles, 10), 2.0)
prod = scanner.calculate_supertrend_directions(candles)

print("=== DEVA SUPERTREND FARK TESTI 2 ===")
print("Mum sayisi:", len(candles))
print("Son tamamlanmis:", dt(candles[idx]["time"]))
print("NOT: Study yok. Sadece TradingView OHLC + yerel hesap.")

for j in [idx-2, idx-1, idx]:
    c = candles[j]
    print(
        f"MUM {dt(c['time'])} | O={c['open']:.4f} H={c['high']:.4f} "
        f"L={c['low']:.4f} C={c['close']:.4f}"
    )
    print(
        f"  PROD/KIVANC-RMA={prod[j]} | KIVANC-SMA={k_sma[j]} | "
        f"OFFICIAL-RMA={o_rma[j]} | OFFICIAL-SMA={o_sma[j]}"
    )
    print(
        f"  RMA_ATR={rma_atr[j]:.9f} | SMA_ATR={sma_atr[j]:.9f} | "
        f"RMA_UP={k_up[j]} | RMA_DN={k_dn[j]} | "
        f"SMA_UP={s_up[j]} | SMA_DN={s_dn[j]}"
    )

for name, arr in [
    ("PROD/KIVANC-RMA", prod),
    ("KIVANC-SMA", k_sma),
    ("OFFICIAL-RMA", o_rma),
    ("OFFICIAL-SMA", o_sma),
]:
    print(
        f"{name} 11->13: {arr[idx-2]} -> {arr[idx-1]} "
        f"BUY={arr[idx-2] == -1 and arr[idx-1] == 1}"
    )
    print(
        f"{name} 13->15: {arr[idx-1]} -> {arr[idx]} "
        f"BUY={arr[idx-1] == -1 and arr[idx] == 1}"
    )
