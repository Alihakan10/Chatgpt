# ============================================================
# BIST SUPERTREND CC 2H SCANNER
# ============================================================
# 620 BIST hissesi | TradingView native 2H
# Supertrend Confirmed Close
# ATR 10 | HL2 | Standard Wilder/RMA | Multiplier 2
# Freeze Supertrend line until candle close = ON
#
# BUY = bearish -> bullish reversal on a COMPLETED 2H BAR.
# Sadece yeni BUY mumlari Telegram'a gonderilir.
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


def log(message):
    now = datetime.now(ZoneInfo(TIMEZONE))
    print(f"[{now:%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def wilder_atr(candles, period=10):
    """TradingView-style Wilder/RMA ATR."""
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

    # RMA/Wilder seed.
    atr[period - 1] = sum(tr[:period]) / period

    for i in range(period, len(candles)):
        atr[i] = (
            atr[i - 1] * (period - 1) + tr[i]
        ) / period

    return atr


def supertrend_cc(candles):
    """
    Supertrend Confirmed Close.

    Settings exactly requested:
      ATR Period = 10
      Source = HL2
      ATR Multiplier = 2
      ATR Method = Standard Wilder ATR
      Freeze line until candle close = ON

    direction:
      +1 = bearish
      -1 = bullish

    BUY:
      previous state bearish (+1)
      AND current COMPLETED close crosses above previous
      bearish Supertrend band.
    """
    if len(candles) < ATR_PERIOD + 2:
        return None

    atr = wilder_atr(candles, ATR_PERIOD)

    upper = [None] * len(candles)
    lower = [None] * len(candles)
    direction = [None] * len(candles)
    buy = [False] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            continue

        hl2 = (
            candles[i]["high"] + candles[i]["low"]
        ) / 2.0

        basic_upper = (
            hl2 + ATR_MULTIPLIER * atr[i]
        )
        basic_lower = (
            hl2 - ATR_MULTIPLIER * atr[i]
        )

        if i == 0 or upper[i - 1] is None:
            upper[i] = basic_upper
            lower[i] = basic_lower
            direction[i] = 1
            continue

        prev_upper = upper[i - 1]
        prev_lower = lower[i - 1]
        prev_close = candles[i - 1]["close"]

        # TradingView Supertrend band rules:
        # upper = basicUpper < prevUpper OR prevClose > prevUpper
        #         ? basicUpper : prevUpper
        # lower = basicLower > prevLower OR prevClose < prevLower
        #         ? basicLower : prevLower
        if (
            basic_upper < prev_upper
            or prev_close > prev_upper
        ):
            upper[i] = basic_upper
        else:
            upper[i] = prev_upper

        if (
            basic_lower > prev_lower
            or prev_close < prev_lower
        ):
            lower[i] = basic_lower
        else:
            lower[i] = prev_lower

        previous_direction = direction[i - 1]

        # Confirmed-close BUY.
        if (
            previous_direction == 1
            and candles[i]["close"] > prev_upper
        ):
            direction[i] = -1
            buy[i] = True

        # Confirmed-close SELL.
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
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


def completed_2h_indexes(candles):
    """
    Returns indexes whose native 2H bars are already closed.

    The current realtime 2H bar is NEVER used for BUY.
    """
    now = datetime.now(ZoneInfo(TIMEZONE))
    completed = []

    for i, candle in enumerate(candles):
        try:
            start = datetime.fromtimestamp(
                candle["time"],
                tz=ZoneInfo("UTC"),
            ).astimezone(ZoneInfo(TIMEZONE))

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
            return {
                "symbol": symbol,
                "status": "skip",
            }

        last_completed = completed[-1]

        # Exclude the currently forming candle.
        calculation_candles = candles[:last_completed + 1]

        if len(calculation_candles) < ATR_PERIOD + 2:
            return {
                "symbol": symbol,
                "status": "skip",
            }

        calc = supertrend_cc(calculation_candles)

        if not calc:
            return {
                "symbol": symbol,
                "status": "skip",
            }

        # SADECE SON TAMAMLANMIŞ 2H MUM:
        # Kullanıcının istediği BUY etiketi, grafikte son kapanan
        # mumda oluşmuş olmalı. Eski mumlardaki BUY'ları kesinlikle
        # yeni sinyal olarak göndermiyoruz.
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
        "⚙️ ATR 10 | HL2 | Wilder ATR | Çarpan 2",
        "🧊 Freeze: Mum kapanışına kadar",
        "✅ BUY: Tamamlanmış 2H mum teyidi",
        "",
    ]

    for item in results:
        ticker = item["symbol"].split(":", 1)[-1]

        dt = datetime.fromtimestamp(
            item["candle_time"],
            tz=ZoneInfo("UTC"),
        ).astimezone(ZoneInfo(TIMEZONE))

        lines.append(
            f"🟢 <b>{ticker}</b>  "
            f"{item['price']:.4f} TL"
        )
        lines.append(
            f"   Mum kapanışı: {dt:%d.%m.%Y %H:%M}"
        )

    lines.append("")
    lines.append(
        "Kaynak: TradingView native 2H + Supertrend CC"
    )

    return "\n".join(lines)


def main():
    log("=" * 70)
    log("BIST SUPERTREND CC 620 HİSSE TARAMASI BAŞLADI")
    log("ATR=10 | HL2 | Wilder/RMA | Çarpan=2 | NATIVE 2H")
    log("BUY = tamamlanmış mumda bearish -> bullish dönüş")
    log("=" * 70)

    symbols = scanner.get_bist_symbols()

    if len(symbols) < SCAN_LIMIT:
        raise RuntimeError(
            f"TradingView sadece {len(symbols)} BIST hissesi döndürdü; "
            f"{SCAN_LIMIT} bekleniyordu."
        )

    symbols = symbols[:SCAN_LIMIT]

    log(
        f"TradingView'dan {len(symbols)} hisse taranacak."
    )

    state = load_state()

    results = []
    errors = 0
    started = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(scan_one, symbol): symbol
            for symbol in symbols
        }

        for n, future in enumerate(
            as_completed(futures),
            1,
        ):
            result = future.result()
            results.append(result)

            if result.get("status") == "error":
                errors += 1
                log(
                    f"[{n}/{len(symbols)}] "
                    f"{result['symbol']} HATA: "
                    f"{result['error']}"
                )

    results.sort(
        key=lambda x: x["symbol"]
    )

    new_buys = []

    for item in results:
        if item.get("status") != "ok":
            continue

        symbol = item["symbol"]
        previous = state.get(symbol, {})

        last_sent = previous.get(
            "last_buy_candle"
        )

        for event in item.get("buy_events", []):
            candle_key = str(
                event["candle_time"]
            )

            if str(last_sent) == candle_key:
                continue

            new_buys.append(event)

            # State'i hemen ilerletiyoruz; Telegram başarılı
            # olmadan kalıcı dosyaya yazilmiyor.
            last_sent = event["candle_time"]

        state[symbol] = {
            "last_buy_candle": last_sent,
            "updated_at": datetime.now(
                ZoneInfo(TIMEZONE)
            ).isoformat(),
        }

    # Aynı sembol/mum tekrarını temizle.
    unique = {}

    for item in new_buys:
        key = (
            item["symbol"],
            str(item["candle_time"]),
        )
        unique[key] = item

    new_buys = list(unique.values())

    new_buys.sort(
        key=lambda x: (
            x["candle_time"],
            x["symbol"],
        )
    )

    log("")
    log("=" * 70)
    log(f"Taranan hisse: {len(symbols)}")
    log(f"Başarılı: {len(results) - errors}")
    log(f"Hata: {errors}")
    log(f"Yeni Supertrend CC BUY: {len(new_buys)}")
    log(
        f"Süre: {time.time() - started:.1f} sn"
    )
    log("=" * 70)

    if new_buys:
        message = build_message(
            new_buys
        )

        # Telegram başarısız olursa exception oluşur ve
        # state dosyası kaydedilmez; sonraki tarama tekrar dener.
        scanner.send_telegram(message)

        save_state(state)

        log(
            "Yeni BUY sinyalleri Telegram'a gönderildi."
        )
    else:
        save_state(state)
        log(
            "Yeni BUY yok. Telegram gönderilmeyecek."
        )

    log("Tarama tamamlandı.")


if __name__ == "__main__":
    main()
