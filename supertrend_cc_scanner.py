# ============================================================
# BIST SUPERTREND CC 2H SCANNER
# ============================================================
# 620 BIST hissesi | TradingView native 2H
# Supertrend Confirmed Close
# ATR 10 | HL2 | Standard Wilder/RMA | Multiplier 3
# Freeze = only completed native 2H bar
#
# TradingView ta.supertrend direction:
#   +1 = bearish
#   -1 = bullish
#
# BUY = completed bar closes above the PREVIOUS confirmed bearish Supertrend band.
# ============================================================

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import scanner

TIMEZONE = "Europe/Istanbul"
ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
SCAN_LIMIT = 620
WORKERS = 5
STATE_FILE = "state/supertrend_cc_state.json"
ALGORITHM_VERSION = "TV_TA_SUPERTREND_ATR10_HL2_2_CURRENT_CLOSE_V15"
# Production lock: exact TradingView ta.supertrend(2.0, 10) semantics.


def log(message):
    now = datetime.now(ZoneInfo(TIMEZONE))
    print(f"[{now:%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def wilder_atr(candles, period=10):
    tr = []
    for i, candle in enumerate(candles):
        if i == 0:
            value = candle["high"] - candle["low"]
        else:
            previous_close = candles[i - 1]["close"]
            value = max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous_close),
                abs(candle["low"] - previous_close),
            )
        tr.append(value)

    atr = [None] * len(candles)
    if len(candles) < period:
        return atr

    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, len(candles)):
        atr[i] = (
            atr[i - 1] * (period - 1) + tr[i]
        ) / period

    return atr


def supertrend_cc(candles):
    """Behavioral replica of TradingView ta.supertrend(2.0, 10)."""
    n = len(candles)
    if n < ATR_PERIOD + 2:
        return None

    atr = wilder_atr(candles, ATR_PERIOD)
    upper = [None] * n
    lower = [None] * n
    supertrend = [None] * n
    direction = [None] * n
    buy = [False] * n
    sell = [False] * n

    for i in range(n):
        # Pine ta.supertrend() waits until the previous ATR value exists.
        if atr[i] is None:
            continue

        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        basic_upper = hl2 + ATR_MULTIPLIER * atr[i]
        basic_lower = hl2 - ATR_MULTIPLIER * atr[i]

        if i == 0:
            upper[i] = basic_upper
            lower[i] = basic_lower
            direction[i] = 1
            supertrend[i] = upper[i]
            continue

        # Exact TradingView built-in semantics use nz(previous band),
        # i.e. 0.0 when the previous band is na.
        prev_upper = upper[i - 1] if i > 0 and upper[i - 1] is not None else 0.0
        prev_lower = lower[i - 1] if i > 0 and lower[i - 1] is not None else 0.0
        # TradingView ta.supertrend() compares the CURRENT close\n        # with the previous confirmed band when carrying the band forward.\n        # This is intentionally not previous-close logic.\n        current_close = candles[i]["close"]\n\n        upper[i] = (\n            basic_upper\n            if basic_upper < prev_upper\n            or current_close > prev_upper\n            else prev_upper\n        )\n        lower[i] = (\n            basic_lower\n            if basic_lower > prev_lower\n            or current_close < prev_lower\n            else prev_lower\n        )

        # First valid ATR bar: previous ATR is still undefined.
        if atr[i - 1] is None:
            direction[i] = 1
        else:
            prev_supertrend = supertrend[i - 1]
            if prev_supertrend is None:
                direction[i] = 1
            elif prev_supertrend == prev_upper:
                direction[i] = -1 if candles[i]["close"] > upper[i] else 1
            else:
                direction[i] = 1 if candles[i]["close"] < lower[i] else -1

        supertrend[i] = lower[i] if direction[i] == -1 else upper[i]

        if i > 0 and direction[i] is not None and direction[i - 1] is not None:
            buy[i] = direction[i - 1] > 0 and direction[i] < 0
            sell[i] = direction[i - 1] < 0 and direction[i] > 0

    return {
        "direction": direction,
        "buy": buy,
        "sell": sell,
        "upper": upper,
        "lower": lower,
        "supertrend": supertrend,
    }

PARITY_SYMBOLS = {
    "BIST:BAKAB", "BIST:BARMA", "BIST:BRKO", "BIST:DGGYO",
    "BIST:EUHOL", "BIST:GSDHO", "BIST:LMKDC", "BIST:PAGYO",
    "BIST:RNPOL", "BIST:SANKO", "BIST:SUNTK", "BIST:VKFYO",
}
PARITY_TARGET = 1790344800.0


def parity_kivanc(candles, factor):
    """Independent Kivanc-style candidate, fed by the SAME TV candles."""
    n = len(candles)
    atr = wilder_atr(candles, ATR_PERIOD)
    up = [None] * n
    dn = [None] * n
    trend = [1] * n
    buy = [False] * n

    for i in range(n):
        if atr[i] is None:
            continue
        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        basic_up = hl2 - factor * atr[i]
        basic_dn = hl2 + factor * atr[i]
        prev_up = up[i - 1] if i > 0 and up[i - 1] is not None else basic_up
        prev_dn = dn[i - 1] if i > 0 and dn[i - 1] is not None else basic_dn
        prev_close = candles[i - 1]["close"] if i > 0 else None

        up[i] = max(basic_up, prev_up) if i > 0 and prev_close is not None and prev_close > prev_up else basic_up
        dn[i] = min(basic_dn, prev_dn) if i > 0 and prev_close is not None and prev_close < prev_dn else basic_dn

        if i == ATR_PERIOD - 1:
            trend[i] = 1
            continue

        if trend[i - 1] == -1:
            trend[i] = 1 if candles[i]["close"] <= prev_dn else -1
        else:
            trend[i] = -1 if candles[i]["close"] >= prev_up else 1
        buy[i] = trend[i - 1] == 1 and trend[i] == -1

    return trend, buy


def run_parity_diagnostic(symbol, candles):
    """Use only candles already fetched by the 620 production scan."""
    if symbol not in PARITY_SYMBOLS:
        return
    idx = next((i for i, x in enumerate(candles) if x["time"] == PARITY_TARGET), None)
    if idx is None:
        log(f"PARITY {symbol}: target candle bulunamadi")
        return

    c = candles[:idx + 1]
    rows = []
    for factor in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
        trend, buy = parity_kivanc(c, factor)
        rows.append(f"K{factor:g}:prev={trend[-2]} dir={trend[-1]} BUY={buy[-1]}")

    log(
        f"PARITY {symbol} target={PARITY_TARGET:.0f} "
        f"close={c[-1]['close']:.4f} | " + " | ".join(rows)
    )


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            value = json.load(f)
            data = value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log(f"State okunamadi: {exc}")
        return {}

    # Signal logic was corrected from native direction-flip to
    # confirmed-close previous-band logic. Do not let stale BUY candles
    # from the old algorithm suppress the first correct result.
    if data.get("_algorithm_version") != ALGORITHM_VERSION:
        migrated = {"_algorithm_version": ALGORITHM_VERSION}
        for symbol, value in data.items():
            if symbol.startswith("_") or not isinstance(value, dict):
                continue
            clean = dict(value)
            clean.pop("last_buy_candle", None)
            migrated[symbol] = clean
        return migrated

    return data


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def completed_2h_indexes(candles):
    """
    Native TradingView 2H bars.

    IMPORTANT:
    BIST's final trading/closing process continues until 18:10 Istanbul.
    Therefore the native 17:00 bar must NOT be treated as confirmed at 18:00.
    The final bar is eligible only after 18:10.

    Earlier native bars use their normal 2-hour boundary. We never rebuild
    or shift the OHLC data; the timestamps supplied by TradingView remain
    authoritative.
    """
    now = datetime.now(ZoneInfo(TIMEZONE))
    completed = []

    for i, candle in enumerate(candles):
        try:
            start = datetime.fromtimestamp(
                candle["time"],
                tz=ZoneInfo("UTC"),
            ).astimezone(ZoneInfo(TIMEZONE))

            # The final BIST native intraday bar can remain open through
            # the closing process until 18:10.
            if start.weekday() < 5 and start.hour >= 17:
                end = start.replace(
                    hour=18, minute=10, second=0, microsecond=0
                )
            else:
                end = start + timedelta(hours=2)

            if end <= now:
                completed.append(i)
        except Exception:
            continue

    return completed


def scan_one(symbol):
    try:
        candles = scanner.get_tv_candles(
            symbol,
            candle_mode="native_2h",
            candle_session="regular",
        )

        run_parity_diagnostic(symbol, candles)

        completed = completed_2h_indexes(candles)
        if not completed:
            return {"symbol": symbol, "status": "skip"}

        last_completed = completed[-1]
        calculation_candles = candles[:last_completed + 1]

        if len(calculation_candles) < ATR_PERIOD + 2:
            return {"symbol": symbol, "status": "skip"}

        calc = supertrend_cc(calculation_candles)
        if not calc:
            return {"symbol": symbol, "status": "skip"}

        latest_index = len(calculation_candles) - 1
        buy_events = []

        if calc["buy"][latest_index]:
            buy_events.append({
                "symbol": symbol,
                "candle_time": calculation_candles[latest_index]["time"],
                "price": calculation_candles[latest_index]["close"],
                "direction": calc["direction"][latest_index],
            })

        return {
            "symbol": symbol,
            "status": "ok",
            "latest_candle_time": calculation_candles[-1]["time"],
            "latest_price": calculation_candles[-1]["close"],
            "direction": calc["direction"][-1],
            "buy_events": buy_events,
        }

    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "error",
            "error": str(exc),
        }


def build_message(results):
    lines = [
        "🚨 <b>SUPERTREND CC BUY</b>",
        "",
        "📊 BIST — 2 SAATLİK",
        "⚙️ ATR 10 | HL2 | Wilder/RMA | Çarpan 2",
        "🧊 Freeze: sadece kapanmış native 2H mum",
        "✅ BUY: direction +1 → -1 (TradingView ta.supertrend)",
        "",
    ]

    for item in results:
        ticker = item["symbol"].split(":", 1)[-1]
        dt = datetime.fromtimestamp(
            item["candle_time"],
            tz=ZoneInfo("UTC"),
        ).astimezone(ZoneInfo(TIMEZONE))

        tv_url = "https://www.tradingview.com/chart/?symbol=BIST%3A" + ticker
        lines.append(
            f'🟢 <a href="{tv_url}"><b>{ticker}</b></a> {item["price"]:.4f} TL'
        )
        lines.append(
            f"   Mum: {dt:%d.%m.%Y %H:%M}"
        )

    lines.append("")
    lines.append("Kaynak: TradingView native 2H + exact ta.supertrend")
    return "\n".join(lines)


def main():
    log("=" * 70)
    log("BIST SUPERTREND CC 620 HİSSE TARAMASI BAŞLADI")
    log("ATR=10 | HL2 | Wilder/RMA | Çarpan=2.0 | NATIVE 2H")
    log("BUY = tamamlanmış mumda TradingView direction +1 → -1")
    log("=" * 70)

    symbols = scanner.get_bist_symbols()

    if len(symbols) < SCAN_LIMIT:
        raise RuntimeError(
            f"TradingView sadece {len(symbols)} BIST hissesi döndürdü; "
            f"{SCAN_LIMIT} bekleniyordu."
        )

    symbols = symbols[:SCAN_LIMIT]
    log(f"TradingView'dan {len(symbols)} hisse taranacak.")

    state = load_state()
    results = []
    errors = 0
    started = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(scan_one, symbol): symbol
            for symbol in symbols
        }

        for n, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)

            if result.get("status") == "error":
                errors += 1
                log(
                    f"[{n}/{len(symbols)}] {result['symbol']} HATA: "
                    f"{result['error']}"
                )

    results.sort(key=lambda x: x["symbol"])

    new_buys = []

    for item in results:
        if item.get("status") != "ok":
            continue

        symbol = item["symbol"]
        previous = state.get(symbol, {})
        last_sent = previous.get("last_buy_candle")

        for event in item.get("buy_events", []):
            candle_key = str(event["candle_time"])
            if str(last_sent) == candle_key:
                continue

            new_buys.append(event)
            last_sent = event["candle_time"]

        state[symbol] = {
            "last_buy_candle": last_sent,
            "updated_at": datetime.now(
                ZoneInfo(TIMEZONE)
            ).isoformat(),
        }

    unique = {}
    for item in new_buys:
        key = (item["symbol"], str(item["candle_time"]))
        unique[key] = item

    new_buys = sorted(
        unique.values(),
        key=lambda x: (x["candle_time"], x["symbol"]),
    )

    raw_buys = []
    for item in results:
        if item.get("status") != "ok":
            continue
        raw_buys.extend(item.get("buy_events", []))

    raw_buys.sort(key=lambda x: (x["candle_time"], x["symbol"]))

    log("")
    log("=" * 70)
    log(f"Taranan hisse: {len(symbols)}")
    log(f"Başarılı: {len(results) - errors}")
    log(f"Hata: {errors}")
    log(f"RAW BUY (state/Telegram ÖNCESİ): {len(raw_buys)}")
    for event in raw_buys:
        ticker = event["symbol"].split(":", 1)[-1]
        log(
            f"RAW BUY | {ticker} | candle={event['candle_time']} "
            f"| close={event['price']:.4f} | direction={event['direction']}"
        )
    log(f"Yeni Supertrend CC BUY: {len(new_buys)}")
    log(f"Süre: {time.time() - started:.1f} sn")
    log("=" * 70)

    if new_buys:
        scanner.send_telegram(build_message(new_buys))
        save_state(state)
        log("Yeni BUY sinyalleri Telegram'a gönderildi.")
    else:
        save_state(state)
        log("Yeni BUY yok. Telegram gönderilmeyecek.")

    log("Tarama tamamlandı.")


if __name__ == "__main__":
    main()
