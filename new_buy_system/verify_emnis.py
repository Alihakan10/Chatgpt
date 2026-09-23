from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import get_tv_candles
from new_buy_system.buy_engine import Candle, latest_result

SYMBOL = "BIST:EMNIS"
PERIOD = 10
MULT = 2.0

def rma(values, period):
    out = [math.nan] * len(values)
    if len(values) < period:
        return out
    out[period - 1] = sum(values[:period]) / period
    a = 1.0 / period
    for i in range(period, len(values)):
        out[i] = a * values[i] + (1.0 - a) * out[i - 1]
    return out

def reference_kivanc(candles):
    # Independent reference implementation of the public Kivanc SuperTrend logic.
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c.high - c.low)
        else:
            pc = candles[i - 1].close
            tr.append(max(c.high-c.low, abs(c.high-pc), abs(c.low-pc)))
    atr = rma(tr, PERIOD)
    up_band = [math.nan] * len(candles)
    dn_band = [math.nan] * len(candles)
    trend = 1
    dirs = [0] * len(candles)
    details = []

    first = PERIOD - 1
    for i, c in enumerate(candles):
        if math.isnan(atr[i]):
            dirs[i] = trend
            continue
        hl2 = (c.high + c.low) / 2.0
        up = hl2 - MULT * atr[i]
        dn = hl2 + MULT * atr[i]
        up1 = up if i == first or math.isnan(up_band[i-1]) else up_band[i-1]
        dn1 = dn if i == first or math.isnan(dn_band[i-1]) else dn_band[i-1]
        prev_close = candles[i-1].close if i else c.close

        if prev_close > up1:
            up = max(up, up1)
        if prev_close < dn1:
            dn = min(dn, dn1)

        up_band[i] = up
        dn_band[i] = dn

        if i > first:
            if trend == -1 and c.close > dn1:
                trend = 1
            elif trend == 1 and c.close < up1:
                trend = -1
        dirs[i] = trend

        if i >= len(candles)-5:
            details.append((i, c, atr[i], up, dn, up1, dn1, trend))

    return dirs, details

def fmt_ts(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Istanbul")
    ).strftime("%d.%m.%Y %H:%M")

def run_window(raw, n):
    candles = [Candle(float(x["time"]), float(x["open"]), float(x["high"]),
                      float(x["low"]), float(x["close"])) for x in raw[-n:]]
    candles.sort(key=lambda x: x.timestamp)
    result = latest_result(candles)
    ref_dirs, details = reference_kivanc(candles)
    ref_buy = len(ref_dirs) >= 2 and ref_dirs[-2] == -1 and ref_dirs[-1] == 1
    return candles, result, ref_buy, details

def main():
    raw = get_tv_candles(SYMBOL, candle_mode="native_2h", candle_session="regular")
    raw = sorted(raw, key=lambda x: float(x["time"]))

    lines = []
    lines.append("=== EMNIS NEW BUY SYSTEM VERIFICATION ===")
    lines.append("SYMBOL=BIST:EMNIS")
    lines.append("DATA=native_2h / regular / TradingView")
    lines.append("PARAMETERS=ATR 10 / MULT 2.0 / HL2 / Wilder RMA")
    lines.append(f"TOTAL_CANDLES={len(raw)}")

    for n in (3000, 1000, 500, 200):
        if len(raw) < n:
            continue
        candles, result, ref_buy, details = run_window(raw, n)
        lines.append("")
        lines.append(f"WINDOW={n}")
        lines.append(
            f"ENGINE PREV={result['previous_direction']} CUR={result['current_direction']} "
            f"BUY={result['buy']} CANDLE={fmt_ts(result['candle_timestamp'])}"
        )
        lines.append(
            f"REFERENCE PREV={ref_dirs[-2] if False else 'see-bars'} CUR={ref_dirs[-1] if False else 'see-bars'} "
            f"BUY={ref_buy}"
        )
        lines.append("LAST_5_BARS:")
        for i, c, atr, up, dn, up1, dn1, trend in details:
            lines.append(
                f"  {fmt_ts(c.timestamp)} O={c.open:.6f} H={c.high:.6f} "
                f"L={c.low:.6f} C={c.close:.6f} ATR={atr:.8f} "
                f"UP={up:.8f} DN={dn:.8f} TREND={trend}"
            )

    # Final full-window consistency check against independent reference.
    candles = [Candle(float(x["time"]), float(x["open"]), float(x["high"]),
                      float(x["low"]), float(x["close"])) for x in raw]
    candles.sort(key=lambda x: x.timestamp)
    engine = latest_result(candles)
    ref_dirs, _ = reference_kivanc(candles)
    ref_prev, ref_cur = ref_dirs[-2], ref_dirs[-1]
    ref_buy = ref_prev == -1 and ref_cur == 1

    lines.append("")
    lines.append("FINAL_CHECK")
    lines.append(f"ENGINE_PREV={engine['previous_direction']}")
    lines.append(f"ENGINE_CUR={engine['current_direction']}")
    lines.append(f"ENGINE_BUY={engine['buy']}")
    lines.append(f"REFERENCE_PREV={ref_prev}")
    lines.append(f"REFERENCE_CUR={ref_cur}")
    lines.append(f"REFERENCE_BUY={ref_buy}")
    lines.append(f"MATCH={engine['buy'] == ref_buy and engine['previous_direction'] == ref_prev and engine['current_direction'] == ref_cur}")
    lines.append(f"LAST_CANDLE={fmt_ts(candles[-1].timestamp)}")

    out = Path("new_buy_system/emnis_verification_result.txt")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
