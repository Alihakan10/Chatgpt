# ============================================================
# 30M SUPERTREND PARITY DIAGNOSTIC
# ADEL / BORSK / EUYO
# ============================================================
#
# URETIM KODUNA DOKUNMAZ.
# scanner_30m.py icindeki native TradingView 30M OHLC verisini
# kullanarak birden fazla Supertrend hesaplama yolunu ayni
# mumlar uzerinde karsilastirir.
#
# Amac:
#   TradingView grafikte gorulen BUY etiketi ile Python BUY
#   kararinin nerede ayrildigini bulmak.
# ============================================================

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import scanner_30m as sc


TZ = ZoneInfo("Europe/Istanbul")
SYMBOLS = [
    x.strip()
    for x in os.getenv("TEST_SYMBOLS", "BIST:ADEL,BIST:BORSK,BIST:EUYO").split(",")
    if x.strip()
]

TARGET_HOUR = int(os.getenv("TARGET_HOUR", "15"))
TARGET_MINUTE = int(os.getenv("TARGET_MINUTE", "0"))
REQUEST_BARS = int(os.getenv("REQUEST_BARS", "10000"))


def local_dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(TZ)


def fmt(x):
    if x is None:
        return "-"
    return f"{x:.6f}"


def calc_kivanc_debug(candles, period=10, multiplier=2.0):
    atr = sc.calculate_atr(candles, period)
    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [1] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            trend[i] = 1
            continue

        src = (candles[i]["high"] + candles[i]["low"]) / 2.0
        up0 = src - multiplier * atr[i]
        up1 = up[i - 1] if i > 0 and up[i - 1] is not None else up0
        up[i] = max(up0, up1) if i > 0 and candles[i - 1]["close"] > up1 else up0

        dn0 = src + multiplier * atr[i]
        dn1 = dn[i - 1] if i > 0 and dn[i - 1] is not None else dn0
        dn[i] = min(dn0, dn1) if i > 0 and candles[i - 1]["close"] < dn1 else dn0

        prev = trend[i - 1] if i > 0 else 1
        if prev == -1 and candles[i]["close"] > dn1:
            trend[i] = 1
        elif prev == 1 and candles[i]["close"] < up1:
            trend[i] = -1
        else:
            trend[i] = prev

    return atr, up, dn, trend


def calc_kivanc_sma_debug(candles, period=10, multiplier=2.0):
    atr = sc.calculate_atr_sma(candles, period)
    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [1] * len(candles)
    for i in range(len(candles)):
        if atr[i] is None:
            trend[i] = 1
            continue
        src = (candles[i]["high"] + candles[i]["low"]) / 2.0
        up0 = src - multiplier * atr[i]
        up1 = up[i - 1] if i > 0 and up[i - 1] is not None else up0
        up[i] = max(up0, up1) if i > 0 and candles[i - 1]["close"] > up1 else up0
        dn0 = src + multiplier * atr[i]
        dn1 = dn[i - 1] if i > 0 and dn[i - 1] is not None else dn0
        dn[i] = min(dn0, dn1) if i > 0 and candles[i - 1]["close"] < dn1 else dn0
        prev = trend[i - 1] if i > 0 else 1
        if prev == -1 and candles[i]["close"] > dn1:
            trend[i] = 1
        elif prev == 1 and candles[i]["close"] < up1:
            trend[i] = -1
        else:
            trend[i] = prev
    return atr, up, dn, trend


def calc_builtin_debug(candles, period=10, multiplier=2.0):
    # TradingView ta.supertrend() direction convention:
    # -1 = UP, +1 = DOWN.
    atr = sc.calculate_atr(candles, period)
    upper = [None] * len(candles)
    lower = [None] * len(candles)
    st = [None] * len(candles)
    direction = [None] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            direction[i] = 1
            continue

        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        bu = hl2 + multiplier * atr[i]
        bl = hl2 - multiplier * atr[i]

        pu = upper[i - 1] if i > 0 and upper[i - 1] is not None else bu
        pl = lower[i - 1] if i > 0 and lower[i - 1] is not None else bl
        pc = candles[i - 1]["close"] if i > 0 else None

        upper[i] = bu if i == 0 or bu < pu or (pc is not None and pc > pu) else pu
        lower[i] = bl if i == 0 or bl > pl or (pc is not None and pc < pl) else pl

        if i == period - 1:
            direction[i] = 1
        else:
            prev_st = st[i - 1]
            prev_up = upper[i - 1]
            if prev_st is None:
                direction[i] = 1
            elif prev_st == prev_up:
                direction[i] = -1 if candles[i]["close"] > upper[i] else 1
            else:
                direction[i] = 1 if candles[i]["close"] < lower[i] else -1

        st[i] = lower[i] if direction[i] == -1 else upper[i]

    # Convert built-in convention to production convention:
    # +1 = AL, -1 = SAT.
    converted = [
        None if x is None else (-1 if x == 1 else 1)
        for x in direction
    ]
    return atr, upper, lower, converted


def calc_signal_variants(candles, period=10, multiplier=2.0):
    """
    Production koduna dokunmadan, ayni OHLC serisinde yaygin
    BUY plot kosullarini ayristirir.
    """
    atr = sc.calculate_atr(candles, period)
    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [1] * len(candles)
    st = [None] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            continue

        src = (candles[i]["high"] + candles[i]["low"]) / 2.0
        up0 = src - multiplier * atr[i]
        up1 = up[i - 1] if i > 0 and up[i - 1] is not None else up0
        up[i] = max(up0, up1) if i > 0 and candles[i - 1]["close"] > up1 else up0

        dn0 = src + multiplier * atr[i]
        dn1 = dn[i - 1] if i > 0 and dn[i - 1] is not None else dn0
        dn[i] = min(dn0, dn1) if i > 0 and candles[i - 1]["close"] < dn1 else dn0

        prev = trend[i - 1] if i > 0 else 1
        if prev == -1 and candles[i]["close"] > dn1:
            trend[i] = 1
        elif prev == 1 and candles[i]["close"] < up1:
            trend[i] = -1
        else:
            trend[i] = prev

        # Kivanc source code: trend==1 -> UP Trend plot = lower band (up).
        # trend==-1 -> Down Trend plot = upper band (dn).
        st[i] = up[i] if trend[i] == 1 else dn[i]

    return atr, up, dn, trend, st




def calc_source_variant(candles, source_name="hl2", atr_mode="rma", period=10, multiplier=2.0):
    """Isolated diagnostic: source and ATR smoothing variants."""
    atr = sc.calculate_atr(candles, period) if atr_mode == "rma" else sc.calculate_atr_sma(candles, period)
    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [1] * len(candles)

    def src_at(i):
        c = candles[i]
        if source_name == "hl2": return (c["high"] + c["low"]) / 2.0
        if source_name == "close": return c["close"]
        if source_name == "open": return c["open"]
        if source_name == "high": return c["high"]
        if source_name == "low": return c["low"]
        if source_name == "hlc3": return (c["high"] + c["low"] + c["close"]) / 3.0
        if source_name == "ohlc4": return (c["open"] + c["high"] + c["low"] + c["close"]) / 4.0
        raise ValueError(source_name)

    for i in range(len(candles)):
        if atr[i] is None:
            continue
        src = src_at(i)
        up0 = src - multiplier * atr[i]
        up1 = up[i - 1] if i > 0 and up[i - 1] is not None else up0
        up[i] = max(up0, up1) if i > 0 and candles[i - 1]["close"] > up1 else up0
        dn0 = src + multiplier * atr[i]
        dn1 = dn[i - 1] if i > 0 and dn[i - 1] is not None else dn0
        dn[i] = min(dn0, dn1) if i > 0 and candles[i - 1]["close"] < dn1 else dn0
        prev = trend[i - 1] if i > 0 else 1
        if prev == -1 and candles[i]["close"] > dn1:
            trend[i] = 1
        elif prev == 1 and candles[i]["close"] < up1:
            trend[i] = -1
        else:
            trend[i] = prev
    return atr, up, dn, trend


def to_heikin_ashi(candles):
    """Convert native OHLC to TradingView-style Heikin Ashi OHLC."""
    out = []
    prev_ha_open = None
    prev_ha_close = None
    for i, c in enumerate(candles):
        ha_close = (c["open"] + c["high"] + c["low"] + c["close"]) / 4.0
        if i == 0:
            ha_open = (c["open"] + c["close"]) / 2.0
        else:
            ha_open = (prev_ha_open + prev_ha_close) / 2.0
        ha_high = max(c["high"], ha_open, ha_close)
        ha_low = min(c["low"], ha_open, ha_close)
        out.append({
            "time": c["time"],
            "open": ha_open,
            "high": ha_high,
            "low": ha_low,
            "close": ha_close,
            "volume": c.get("volume", 0.0),
        })
        prev_ha_open = ha_open
        prev_ha_close = ha_close
    return out



def calc_everget_debug(candles, period=10, multiplier=2.0, wicks=True):
    """Isolated diagnostic of the Everget/ATR trailing-stop SuperTrend family."""
    atr0 = sc.calculate_atr(candles, period)
    atr = [None if x is None else multiplier * x for x in atr0]
    long_stop = [None] * len(candles)
    short_stop = [None] * len(candles)
    direction = [1] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            continue
        src = (candles[i]["high"] + candles[i]["low"]) / 2.0
        high_price = candles[i]["high"] if wicks else candles[i]["close"]
        low_price = candles[i]["low"] if wicks else candles[i]["close"]
        doji = (
            candles[i]["open"] == candles[i]["close"]
            and candles[i]["open"] == candles[i]["low"]
            and candles[i]["open"] == candles[i]["high"]
        )

        long0 = src - atr[i]
        prev_long = long_stop[i - 1] if i > 0 and long_stop[i - 1] is not None else long0
        if doji:
            long_stop[i] = prev_long
        else:
            long_stop[i] = max(long0, prev_long) if i > 0 and low_price > prev_long else long0

        short0 = src + atr[i]
        prev_short = short_stop[i - 1] if i > 0 and short_stop[i - 1] is not None else short0
        if doji:
            short_stop[i] = prev_short
        else:
            short_stop[i] = min(short0, prev_short) if i > 0 and high_price < prev_short else short0

        prev_dir = direction[i - 1] if i > 0 else 1
        if prev_dir == -1 and high_price > prev_short:
            direction[i] = 1
        elif prev_dir == 1 and low_price < prev_long:
            direction[i] = -1
        else:
            direction[i] = prev_dir

    return atr0, long_stop, short_stop, direction


def find_target_index(candles):
    matches = []
    for i, c in enumerate(candles):
        dt = local_dt(c["time"])
        if dt.hour == TARGET_HOUR and dt.minute == TARGET_MINUTE:
            matches.append(i)
    return matches[-1] if matches else None


def report_symbol(symbol):
    print("")
    print("=" * 90)
    print(symbol)
    print("=" * 90)

    # TradingView docs note that stateful intraday scripts can depend on their history start.
    # Pull a much longer native history here; production code is untouched.
    sc.CANDLE_COUNT = REQUEST_BARS
    candles = sc.get_tv_candles_with_retry(symbol, "native_30m")
    if not candles:
        print("VERI YOK")
        return

    completed = sc.get_last_completed_index(candles)
    if completed is None:
        print("TAMAMLANMIS MUM YOK")
        return

    calc = candles[:completed + 1]
    ha_calc = to_heikin_ashi(calc)
    ha_atr, ha_up, ha_dn, ha_trend = calc_kivanc_debug(ha_calc)
    k_atr, k_up, k_dn, k_trend = calc_kivanc_debug(calc)
    b_atr, b_up, b_dn, b_trend = calc_builtin_debug(calc)
    s_atr, s_up, s_dn, s_trend = calc_kivanc_sma_debug(calc)
    v_atr, v_up, v_dn, v_trend, v_st = calc_signal_variants(calc)
    e_atr, e_long, e_short, e_dir_wicks = calc_everget_debug(calc, wicks=True)
    _, _, _, e_dir_close = calc_everget_debug(calc, wicks=False)

    target = find_target_index(calc)
    if target is None:
        print("15:00 acilisli hedef mum bulunamadi.")
        print("Son 10 mum:")
        target = max(0, len(calc) - 5)
    else:
        print("HEDEF MUM INDEX:", target)

    start = max(1, target - 3)
    end = min(len(calc), target + 3)

    print("")
    print("MUM | O | H | L | C | K_ATR | K_UP | K_DN | K_DIR | K_BUY | TVDIR | TVBUY")
    for i in range(start, end):
        c = calc[i]
        kbuy = k_trend[i - 1] == -1 and k_trend[i] == 1
        tvbuy = b_trend[i - 1] == -1 and b_trend[i] == 1
        sbuy = s_trend[i - 1] == -1 and s_trend[i] == 1
        mark = "  <== HEDEF" if i == target else ""
        print(
            local_dt(c["time"]).strftime("%d.%m.%Y %H:%M")
            + " | " + fmt(c["open"])
            + " | " + fmt(c["high"])
            + " | " + fmt(c["low"])
            + " | " + fmt(c["close"])
            + " | " + fmt(k_atr[i])
            + " | " + fmt(k_up[i])
            + " | " + fmt(k_dn[i])
            + " | " + str(k_trend[i])
            + " | " + str(kbuy)
            + " | " + str(b_trend[i])
            + " | " + str(tvbuy)
            + " | SMA=" + str(s_trend[i])
            + " | SMA_BUY=" + str(sbuy)
            + mark
        )

    if target is not None and target > 0:
        print("")
        print("HEDEF OZET")
        print("Tarih:", local_dt(calc[target]["time"]).strftime("%d.%m.%Y %H:%M"))
        print("Kapanis:", fmt(calc[target]["close"]))
        print("Kivanc onceki/yeni:", k_trend[target - 1], "->", k_trend[target])
        print("Kivanc BUY:", k_trend[target - 1] == -1 and k_trend[target] == 1)
        print("Built-in onceki/yeni:", b_trend[target - 1], "->", b_trend[target])
        print("Built-in BUY:", b_trend[target - 1] == -1 and b_trend[target] == 1)
        print("SMA onceki/yeni:", s_trend[target - 1], "->", s_trend[target])
        print("SMA BUY:", s_trend[target - 1] == -1 and s_trend[target] == 1)
        print("EVERGET/WICKS onceki/yeni:", e_dir_wicks[target - 1], "->", e_dir_wicks[target])
        print("EVERGET/WICKS BUY:", e_dir_wicks[target - 1] == -1 and e_dir_wicks[target] == 1)
        print("EVERGET/CLOSE onceki/yeni:", e_dir_close[target - 1], "->", e_dir_close[target])
        print("EVERGET/CLOSE BUY:", e_dir_close[target - 1] == -1 and e_dir_close[target] == 1)
        print("ACTIVE ST(prev):", fmt(v_st[target - 1]))
        print("ACTIVE ST(now):", fmt(v_st[target]))
        print("CLOSE(prev):", fmt(calc[target - 1]["close"]))
        print("CLOSE(now):", fmt(calc[target]["close"]))
        print("CLOSE>ST(prev):", calc[target]["close"] > v_st[target - 1] if v_st[target - 1] is not None else None)
        print("CLOSE>ST(now):", calc[target]["close"] > v_st[target] if v_st[target] is not None else None)
        print("FLIP_BY_CLOSE_VS_ACTIVE_ST:", (
            calc[target - 1]["close"] <= v_st[target - 1]
            and calc[target]["close"] > v_st[target]
        ) if v_st[target - 1] is not None and v_st[target] is not None else None)
        print("SMA ATR:", fmt(s_atr[target]))
        print("HEIKIN ASHI OZET")
        print("HA O/H/L/C:", fmt(ha_calc[target]["open"]), fmt(ha_calc[target]["high"]), fmt(ha_calc[target]["low"]), fmt(ha_calc[target]["close"]))
        print("HA onceki/yeni:", ha_trend[target - 1], "->", ha_trend[target])
        print("HA BUY:", ha_trend[target - 1] == -1 and ha_trend[target] == 1)
        print("HA ATR:", fmt(ha_atr[target]))
        print("HA UP(now):", fmt(ha_up[target]))
        print("HA DN(now):", fmt(ha_dn[target]))
        print("Kivanc ATR:", fmt(k_atr[target]))
        print("Kivanc UP(prev):", fmt(k_up[target - 1]))
        print("Kivanc DN(prev):", fmt(k_dn[target - 1]))


    print("")
    print("KAYNAK + ATR VARYANT MATRISI")
    print("Her hucre: onceki->yeni / BUY")
    for atr_mode in ("rma", "sma"):
        print(f"ATR={atr_mode.upper()}")
        for source_name in ("hl2", "close", "open", "high", "low", "hlc3", "ohlc4"):
            _, _, _, dirs = calc_source_variant(calc, source_name, atr_mode)
            prev = dirs[target - 1] if target > 0 else None
            cur = dirs[target] if target is not None else None
            buy = prev == -1 and cur == 1
            print(f"  {source_name:6s}: {prev:+d} -> {cur:+d} | BUY={buy}")

    print("")
    print("CARPAN TARAMASI (RMA + HL2)")
    sweep = []
    for m10 in range(10, 41):
        m = m10 / 10.0
        _, _, _, dirs = calc_source_variant(calc, "hl2", "rma", 10, m)
        prev = dirs[target - 1]
        cur = dirs[target]
        buy = prev == -1 and cur == 1
        sweep.append((m, buy))
    print("  " + " ".join(f"{m:.1f}:{'B' if buy else '-'}" for m, buy in sweep))

    # History-window stability check. This tests whether the flip depends
    # on how much historical data is fed into the stateful calculation.
    print("")
    print("TARIHCE PENCERE KONTROLU")
    for size in (500, 1000, 2000, 3000, 5000, 7500, 10000):
        subset = calc[-size:] if len(calc) > size else calc
        dirs = sc.calculate_supertrend_directions(subset, 10, 2.0)
        if dirs and len(dirs) >= 2:
            buys = []
            for j in range(1, len(dirs)):
                if dirs[j - 1] == -1 and dirs[j] == 1:
                    buys.append(local_dt(subset[j]["time"]).strftime("%H:%M"))
            last = dirs[-1]
            print(f"{size:5d} bar | son yon={last:+d} | son 5 BUY={buys[-5:]}")
        else:
            print(f"{size:5d} bar | hesaplanamadi")


def main():
    print("30M SUPERTREND PARITY DIAGNOSTIC")
    print("Ayarlar: ATR=10 | HL2 | multiplier=2.0 | RMA/Wilder")
    print("Hedef:", f"{TARGET_HOUR:02d}:{TARGET_MINUTE:02d}", "Istanbul")
    print("Hisseler:", ", ".join(SYMBOLS))
    print("DIAGNOSTIC BAR TALEBI:", REQUEST_BARS)

    for symbol in SYMBOLS:
        try:
            report_symbol(symbol)
        except Exception as exc:
            print(symbol, "HATA:", repr(exc))


if __name__ == "__main__":
    main()
