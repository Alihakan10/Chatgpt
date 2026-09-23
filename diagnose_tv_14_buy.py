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

print("TEST VERSION: NATIVE_2H_SUPERTREND_LIVE_V3")
print("AUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
print("SETTINGS: ATR=10 MULTIPLIER=2.0 SOURCE=HL2 TIMEFRAME=2H")
print("BUY RULE: previous=-1 (SAT) -> current=+1 (AL)")
print("TEST: native 2H OHLC + two independent Supertrend conventions + history-window sensitivity")
print("NOTE: NO STUDY / NO BROKER / NO 1H->2H MERGE")

def dt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(TZ).strftime("%Y-%m-%d %H:%M")

def buy_times(candles, directions):
    out = []
    for i in range(1, len(candles)):
        if directions[i-1] == -1 and directions[i] == 1:
            out.append(candles[i]["time"])
    return out

for symbol in SYMBOLS:
    print("\n" + "=" * 90)
    print(symbol)
    print("=" * 90)

    try:
        bars = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"]
        )
        idx = scanner.get_last_completed_index(bars)

        if idx is None or idx < 1:
            print("RESULT: INSUFFICIENT COMPLETED BARS")
            continue

        calc = bars[:idx + 1]

        ours = scanner.calculate_supertrend_directions(
            calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
        )
        tv_conv = scanner.calculate_tradingview_supertrend_directions(
            calc, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
        )

        if not ours or not tv_conv or len(ours) < 2 or len(tv_conv) < 2:
            print("RESULT: SUPERTREND CALC FAILED")
            continue

        print(
            f"LAST COMPLETED 2H: {dt(calc[-1]['time'])} "
            f"O={calc[-1]['open']:.2f} H={calc[-1]['high']:.2f} "
            f"L={calc[-1]['low']:.2f} C={calc[-1]['close']:.2f}"
        )

        print(
            f"OUR FORMULA: prev={ours[-2]} cur={ours[-1]} "
            f"BUY={ours[-2] == -1 and ours[-1] == 1}"
        )
        print(
            f"TV CONVENTION: prev={tv_conv[-2]} cur={tv_conv[-1]} "
            f"UP={tv_conv[-2] == 1 and tv_conv[-1] == -1}"
        )

        same = all(
            (ours[i] == 1) == (tv_conv[i] == -1)
            for i in range(len(calc))
            if ours[i] is not None and tv_conv[i] is not None
        )
        print("FORMULA CONVENTION MATCH:", "YES" if same else "NO")

        print("LAST 10 COMPLETED 2H:")
        for i in range(max(0, len(calc) - 10), len(calc)):
            print(
                f"  {dt(calc[i]['time'])} "
                f"O={calc[i]['open']:.2f} H={calc[i]['high']:.2f} "
                f"L={calc[i]['low']:.2f} C={calc[i]['close']:.2f} "
                f"OUR={ours[i]} TVDIR={tv_conv[i]}"
            )

        ours_buys = buy_times(calc, ours)
        print(
            "RECENT OUR SAT->AL:",
            ", ".join(dt(x) for x in ours_buys[-5:]) if ours_buys else "none"
        )

        # History sensitivity: the same native 2H OHLC is recalculated
        # from several starting points. This detects initialization effects.
        print("HISTORY WINDOW TEST (same native 2H OHLC):")
        for size in (3000, 2000, 1000, 500, 250, 100, 50):
            subset = calc[-size:] if len(calc) > size else calc
            d = scanner.calculate_supertrend_directions(
                subset, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
            )
            if not d or len(d) < 2:
                print(f"  {size}: insufficient")
                continue
            b = buy_times(subset, d)
            print(
                f"  {size}: prev={d[-2]} cur={d[-1]} "
                f"BUY={d[-2] == -1 and d[-1] == 1} "
                f"last_buy={dt(b[-1]) if b else 'none'}"
            )

        # Completed-candle decision.
        current_buy = ours[-2] == -1 and ours[-1] == 1
        print(
            "FINAL COMPLETED 2H RESULT:",
            "BUY" if current_buy else "NO BUY"
        )

        # Diagnostic only: test the still-forming 2H candle as seen on a live chart.
        # Production alerts continue to use completed candles only.
        if idx + 1 < len(bars):
            live = bars[:idx + 2]
            live_dirs = scanner.calculate_supertrend_directions(
                live, scanner.ATR_PERIOD, scanner.ATR_MULTIPLIER
            )
            if live_dirs and len(live_dirs) >= 2:
                live_buy = live_dirs[-2] == -1 and live_dirs[-1] == 1
                print(
                    f"LIVE INCOMPLETE 2H: {dt(live[-1]['time'])} "
                    f"O={live[-1]['open']:.2f} H={live[-1]['high']:.2f} "
                    f"L={live[-1]['low']:.2f} C={live[-1]['close']:.2f} "
                    f"prev={live_dirs[-2]} cur={live_dirs[-1]} BUY={live_buy}"
                )
            else:
                print("LIVE INCOMPLETE 2H: CALC FAILED")
        else:
            print("LIVE INCOMPLETE 2H: NOT AVAILABLE")

    except Exception as e:
        print("RESULT: ERROR:", e)

print("\n" + "=" * 90)
print("14 STOCK DIAGNOSTIC FINISHED")
print("=" * 90)
