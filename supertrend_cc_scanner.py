# ============================================================
# BIST SUPERTREND CC SCANNER
# ============================================================
# 620 BIST hissesi | TradingView native 2H | Supertrend CC
# ATR 10 | HL2 | Wilder/RMA ATR | Multiplier 2
# BUY = bearish -> bullish reversal confirmed on completed bar
#
# Bu dosya mevcut scanner.py'nin veri alma altyapisini kullanir,
# fakat eski Supertrend BUY mantigini kullanmaz.
# ============================================================

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import scanner

TIMEZONE = "Europe/Istanbul"
ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
SCAN_LIMIT = 620
WORKERS = 5
STATE_FILE = "state/supertrend_cc_state.json"


def log(message):
    now = datetime.now(ZoneInfo(TIMEZONE))
    print(f"[{now:%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def wilder_atr(candles, period=10):
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            value = c["high"] - c["low"]
        else:
            pc = candles[i - 1]["close"]
            value = max(
                c["high"] - c["low"],
                abs(c["high"] - pc),
                abs(c["low"] - pc),
            )
        tr.append(value)

    atr = [None] * len(candles)
    if len(candles) < period:
        return atr

    # TradingView Wilder/RMA seed.
    atr[period - 1] = sum(tr[:period]) / period

    for i in range(period, len(candles)):
        atr[i] = (
            atr[i - 1] * (period - 1) + tr[i]
        ) / period

    return atr


def supertrend_cc(candles):
    """
    Supertrend Confirmed Close mantigi.

    Settings:
      ATR Period = 10
      Source = HL2
      ATR Multiplier = 2
      ATR = Standard Wilder/RMA
      Freeze line until candle close = ON

    direction:
      +1 = bearish
      -1 = bullish

    BUY:
      previous direction = +1
      current completed bar = -1
    """
    if len(candles) < ATR_PERIOD + 2:
        return None

    atr = wilder_atr(candles, ATR_PERIOD)

    upper = [None] * len(candles)
    lower = [None] * len(candles)
    direction = [None] * len(candles)
    buy = [False] * len(candles)

    # Same initial state convention used by the open-source
    # Supertrend Confirmed Close family: bearish until a
    # confirmed bullish reversal occurs.
    for i in range(len(candles)):
        if atr[i] is None:
            continue

        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        basic_upper = hl2 + ATR_MULTIPLIER * atr[i]
        basic_lower = hl2 - ATR_MULTIPLIER * atr[i]

        if i == 0 or upper[i - 1] is None:
            upper[i] = basic_upper
            lower[i] = basic_lower
            direction[i] = 1
            continue

        prev_upper = upper[i - 1]
        prev_lower = lower[i - 1]
        prev_close = candles[i - 1]["close"]

        # Trailing bands.
        upper[i] = (
            max(basic_upper, prev_upper)
            if prev_close > prev_upper
            else basic_upper
        )
        lower[i] = (
            min(basic_lower, prev_lower)
            if prev_close < prev_lower
            else basic_lower
        )

        previous_direction = direction[i - 1]

        # Confirmed-close reversal:
        # current CLOSED candle must cross the previous
        # confirmed opposite Supertrend band.
        if (
            previous_direction == 1
            and candles[i]["close"] > prev_upper
        ):
            direction[i] = -1
            buy[i] = True
        elif (
            previous_direction == -1
            and candles[i]["close"] < prev_lower
        ):
            direction[i] = 1
        else:
            direction[i] = previous_direction

    return {
        "direction": direction,
        "buy": buy,
        "upper": upper,
        "lower": lower,
    }


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            value = json.load(f)
            return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log(f"State okunamadi: {exc}")
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def completed_2h_candle(candles):
    """
    TradingView native 2H serisindeki son barin kapanisini kontrol eder.
    Sadece kapanisi Istanbul saatine gore simdiki zamandan once olan
    barlar sinyal icin kullanilir.
    """
    now = datetime.now(ZoneInfo(TIMEZONE))
    candidates = []

    for i, candle in enumerate(candles):
        try:
            start = datetime.fromtimestamp(
                candle["time"], tz=ZoneInfo("UTC")
            ).astimezone(ZoneInfo(TIMEZONE))
            end = start.replace(
                tzinfo=ZoneInfo(TIMEZONE)
            ) + __import__("datetime").timedelta(hours=2)

            if end <= now:
                candidates.append(i)
        except Exception:
            continue

    return candidates[-1] if candidates else None


def scan_one(symbol):
    try:
        candles = scanner.get_tv_candles(
            symbol,
            candle_mode="native_2h",
            candle_session="regular",
        )

        idx = completed_2h_candle(candles)
        if idx is None or idx < ATR_PERIOD + 2:
            return {"symbol": symbol, "status": "skip"}

        candles = candles[: idx + 1]
        calc = supertrend_cc(candles)
        if not calc:
            return {"symbol": symbol, "status": "skip"}

        i = len(candles) - 1
        is_buy = bool(calc["buy"][i])

        return {
            "symbol": symbol,
            "status": "ok",
            "buy": is_buy,
            "candle_time": candles[i]["time"],
            "price": candles[i]["close"],
            "direction": calc["direction"][i],
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
        "⚙️ ATR 10 | HL2 | Wilder ATR | Çarpan 2",
        "✅ Mum kapanışı teyitli",
        "",
    ]

    for item in results:
        ticker = item["symbol"].split(":", 1)[-1]
        dt = datetime.fromtimestamp(
            item["candle_time"], tz=ZoneInfo("UTC")
        ).astimezone(ZoneInfo(TIMEZONE))

        lines.append(
            f"🟢 <b>{ticker}</b>  "
            f"{item['price']:.4f} TL  "
            f"🕒 {dt:%d.%m.%Y %H:%M}"
        )

    lines.append("")
    lines.append("Kaynak: TradingView native 2H veri + Supertrend CC")
    return "\n".join(lines)


def main():
    log("=" * 70)
    log("BIST SUPERTREND CC 620 HİSSE TARAMASI BAŞLADI")
    log("ATR=10 | HL2 | Wilder/RMA | Çarpan=2 | 2H")
    log("=" * 70)

    symbols = scanner.get_bist_symbols()
    symbols = symbols[:SCAN_LIMIT]
    log(f"TradingView'dan {len(symbols)} hisse bulundu.")

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
                    f"[{n}/{len(symbols)}] "
                    f"{result['symbol']} HATA: {result['error']}"
                )
            else:
                log(
                    f"[{n}/{len(symbols)}] "
                    f"{result['symbol']} "
                    f"BUY={result.get('buy', False)}"
                )

    results.sort(key=lambda x: x["symbol"])

    new_buys = []
    for item in results:
        if item.get("status") != "ok" or not item.get("buy"):
            continue

        symbol = item["symbol"]
        candle_key = str(item["candle_time"])
        previous = state.get(symbol, {})

        if str(previous.get("last_buy_candle")) == candle_key:
            continue

        new_buys.append(item)
        state[symbol] = {
            "last_buy_candle": item["candle_time"],
            "updated_at": datetime.now(
                ZoneInfo(TIMEZONE)
            ).isoformat(),
        }

    log("")
    log("=" * 70)
    log(f"Taranan hisse: {len(symbols)}")
    log(f"Hata: {errors}")
    log(f"Yeni Supertrend CC BUY: {len(new_buys)}")
    log(f"Süre: {time.time() - started:.1f} sn")
    log("=" * 70)

    if new_buys:
        message = build_message(new_buys)
        scanner.send_telegram(message)
        log("Yeni BUY sinyalleri Telegram'a gönderildi.")
        save_state(state)
    else:
        log("Yeni BUY yok. Telegram gönderilmeyecek.")
        save_state(state)


if __name__ == "__main__":
    main()
