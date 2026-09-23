from datetime import datetime
from zoneinfo import ZoneInfo
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from new_buy_system.buy_engine import Candle, latest_result
from scanner import get_tv_candles

SYMBOLS = [
    "BIST:CLEBI", "BIST:EMNIS", "BIST:EUHOL", "BIST:KENT",
    "BIST:KERVN", "BIST:KLYPV", "BIST:KRPLS", "BIST:KSTUR",
    "BIST:OYLUM", "BIST:SODSN", "BIST:TUCLK", "BIST:TURSG",
    "BIST:ULUFA", "BIST:USHOL",
]

def fmt(ts):
    return datetime.fromtimestamp(ts, tz=ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Istanbul")
    ).strftime("%d.%m.%Y %H:%M")

def main():
    print("=== NEW BUY SYSTEM / 14 STOCK TEST ===")
    print("Native 2H | ATR 10 | Multiplier 2.0 | HL2 | RMA")
    print("Production scanner/state/Telegram are NOT modified.")
    print()

    ok = errors = buys = 0

    for symbol in SYMBOLS:
        try:
            raw = get_tv_candles(symbol, candle_mode="native_2h", candle_session="regular")
            candles = [
                Candle(
                    timestamp=float(x["time"]),
                    open=float(x["open"]),
                    high=float(x["high"]),
                    low=float(x["low"]),
                    close=float(x["close"]),
                )
                for x in raw
            ]
            candles.sort(key=lambda x: x.timestamp)

            result = latest_result(candles)
            ok += 1
            buys += int(result["buy"])

            print(
                f"{symbol}: PREV={result['previous_direction']} "
                f"CUR={result['current_direction']} BUY={result['buy']} "
                f"CANDLE={fmt(result['candle_timestamp']) if result['candle_timestamp'] else '-'} "
                f"CANDLES={len(candles)}"
            )
        except Exception as exc:
            errors += 1
            print(f"{symbol}: ERROR={exc}")

    print()
    print(f"SUMMARY: OK={ok} ERRORS={errors} BUY={buys} TOTAL={len(SYMBOLS)}")

if __name__ == "__main__":
    main()
