# ============================================================
# BIST SUPERTREND CC 2H SCANNER
# ============================================================
# 620 BIST hissesi | TradingView native 2H
# Supertrend Confirmed Close
# ATR 10 | HL2 | Standard Wilder/RMA | Multiplier 2
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
ALGORITHM_VERSION = "TV_TA_SUPERTREND_NATIVE_2H_V8_SEEDED_BANDS"


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
    """
    TradingView native ta.supertrend() equivalent.

    Direction convention:
      +1 = bearish / SAT
      -1 = bullish / AL

    Pine equivalent:
      [st, direction] = ta.supertrend(ATR_MULTIPLIER, ATR_PERIOD)
      BUY = direction[1] > 0 and direction < 0

    The calculation is performed only on native TradingView 2H OHLC.
    No Study/indicator endpoint is used.
    """
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
        if atr[i] is None:
            direction[i] = 1
            continue

        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        basic_upper = hl2 + ATR_MULTIPLIER * atr[i]
        basic_lower = hl2 - ATR_MULTIPLIER * atr[i]

        # Pine nz(prevBand, currentBasicBand): the first valid ATR bar
        # must seed both bands with its own basic value, not zero.
        prev_upper = upper[i - 1] if i > 0 and upper[i - 1] is not None else basic_upper
        prev_lower = lower[i - 1] if i > 0 and lower[i - 1] is not None else basic_lower

        upper[i] = (
            basic_upper
            if i == 0 or basic_upper < prev_upper or candles[i]["close"] > prev_upper
            else prev_upper
        )

        lower[i] = (
            basic_lower
            if i == 0 or basic_lower > prev_lower or candles[i]["close"] < prev_lower
            else prev_lower
        )

        if i == ATR_PERIOD - 1:
            direction[i] = 1
        else:
            prev_st = supertrend[i - 1]
            prev_upper_band = upper[i - 1]

            if prev_st is None:
                direction[i] = 1
            elif prev_st == prev_upper_band:
                direction[i] = (
                    -1 if candles[i]["close"] > upper[i] else 1
                )
            else:
                direction[i] = (
                    1 if candles[i]["close"] < lower[i] else -1
                )

            if direction[i - 1] == 1 and direction[i] == -1:
                buy[i] = True
            elif direction[i - 1] == -1 and direction[i] == 1:
                sell[i] = True

        supertrend[i] = (
            lower[i] if direction[i] == -1 else upper[i]
        )

    return {
        "direction": direction,
        "buy": buy,
        "sell": sell,
        "upper": upper,
        "lower": lower,
        "supertrend": supertrend,
    }

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
        "✅ BUY: kapanmış mumda TradingView ta.supertrend yönü SAT -> AL döndü",
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
    lines.append("Kaynak: TradingView native 2H + ta.supertrend eşdeğeri (correct band seeding)")
    return "\n".join(lines)


def main():
    log("=" * 70)
    log("BIST SUPERTREND CC 620 HİSSE TARAMASI BAŞLADI")
    log("ATR=10 | HL2 | Wilder/RMA | Çarpan=2 | NATIVE 2H")
    log("BUY = tamamlanmış mumda önceki bearish ST bandının üstünde kapanış")
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

    log("")
    log("=" * 70)
    log(f"Taranan hisse: {len(symbols)}")
    log(f"Başarılı: {len(results) - errors}")
    log(f"Hata: {errors}")
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
