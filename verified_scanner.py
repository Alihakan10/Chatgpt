"""
BIST Supertrend tek tarama + otomatik BUY dogrulama.

scanner.py normal BIST taramasini yapar. Her BUY adayi icin
ayni TradingView native 2H serisi tekrar alinip bagimsiz
Wilder/RMA + HL2 Supertrend hesabi ile kontrol edilir.
Uyusmayan BUY Telegram'a gonderilmez.

Study YOK.
"""

import scanner
from datetime import datetime
from zoneinfo import ZoneInfo


def label(d):
    return "AL" if d == 1 else "SAT" if d == -1 else "BELIRSIZ"


def independent_directions(candles, period=10, multiplier=2.0):
    n = len(candles)
    if n < period + 2:
        return None

    tr = [None] * n
    atr = [None] * n
    upper = [None] * n
    lower = [None] * n
    direction = [None] * n

    for i, c in enumerate(candles):
        if i == 0:
            tr[i] = c["high"] - c["low"]
        else:
            pc = candles[i - 1]["close"]
            tr[i] = max(
                c["high"] - c["low"],
                abs(c["high"] - pc),
                abs(c["low"] - pc),
            )

    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (
            atr[i - 1] * (period - 1) + tr[i]
        ) / period

    for i in range(period - 1, n):
        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        raw_upper = hl2 + multiplier * atr[i]
        raw_lower = hl2 - multiplier * atr[i]

        if i == period - 1:
            upper[i] = raw_upper
            lower[i] = raw_lower
            direction[i] = -1
            continue

        prev_close = candles[i - 1]["close"]

        upper[i] = (
            raw_upper
            if raw_upper < upper[i - 1] or prev_close > upper[i - 1]
            else upper[i - 1]
        )
        lower[i] = (
            raw_lower
            if raw_lower > lower[i - 1] or prev_close < lower[i - 1]
            else lower[i - 1]
        )

        if direction[i - 1] == -1:
            direction[i] = (
                1 if candles[i]["close"] > upper[i - 1] else -1
            )
        else:
            direction[i] = (
                -1 if candles[i]["close"] < lower[i - 1] else 1
            )

    return direction


_original_scan_symbol = scanner.scan_symbol


def verified_scan_symbol(symbol, state):
    result = _original_scan_symbol(symbol, state)

    # Normal taramada BUY durumu olan her hisseyi dogrula.
    # Hem YENI BUY (buy_results) hem daha once gonderilmis
    # mevcut BUY (all_buy_results) burada kontrol edilir.
    # Boylece her taramada BUY listesinin gercekten SAT -> AL
    # oldugu yeniden kontrol edilmis olur.
    buy_results = result.get("buy_results", [])
    all_buy_results = result.get("all_buy_results", [])
    buy_candidates = buy_results or all_buy_results
    if not buy_candidates:
        return result

    try:
        candles = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"],
        )

        if len(candles) < scanner.ATR_PERIOD + 2:
            raise RuntimeError("dogrulama icin native 2H veri yetersiz")

        completed_index = scanner.get_last_completed_index(candles)
        if completed_index is None or completed_index < 1:
            raise RuntimeError("dogrulama icin tamamlanmis 2H mum yok")

        calc = candles[:completed_index + 1]
        production = scanner.calculate_supertrend_directions(
            calc,
            scanner.ATR_PERIOD,
            scanner.ATR_MULTIPLIER,
        )
        independent = independent_directions(
            calc,
            scanner.ATR_PERIOD,
            scanner.ATR_MULTIPLIER,
        )

        if independent is None:
            raise RuntimeError("bagimsiz Supertrend hesaplanamadi")

        i = completed_index
        p = i - 1

        prod_buy = production[p] == -1 and production[i] == 1
        independent_buy = independent[p] == -1 and independent[i] == 1
        same = (
            production[p] == independent[p]
            and production[i] == independent[i]
        )

        dt = datetime.fromtimestamp(
            calc[i]["time"],
            tz=ZoneInfo("UTC"),
        ).astimezone(ZoneInfo(scanner.TIMEZONE))

        scanner.log(
            "    BUY DOGRULAMA | "
            + symbol
            + " | "
            + dt.strftime("%d.%m.%Y %H:%M")
            + " | PROD="
            + label(production[p])
            + "->"
            + label(production[i])
            + " | INDEPENDENT="
            + label(independent[p])
            + "->"
            + label(independent[i])
            + " | ESLESME="
            + str(same)
            + " | BUY="
            + str(prod_buy and independent_buy)
        )

        if not (prod_buy and independent_buy and same):
            scanner.log(
                "    !!! BUY DOGRULAMA BASARISIZ | "
                + symbol
                + " | TELEGRAM'A GONDERILMEYECEK"
            )

            # State'e yeni BUY olarak yazilmasini da engelle.
            result["status"] = "ok"
            result["buy_results"] = []
            result["all_buy_results"] = []
            result["latest_buy_time"] = None
            result["buy_signal"] = False
            return result

        result["verification"] = {
            "verified": True,
            "candle_time": calc[i]["time"],
            "production_previous": production[p],
            "production_current": production[i],
            "independent_previous": independent[p],
            "independent_current": independent[i],
        }
        return result

    except Exception as exc:
        # Dogrulanamayan BUY'i Telegram'a gonderme.
        scanner.log(
            "    !!! BUY DOGRULAMA HATASI | "
            + symbol
            + " | "
            + str(exc)
            + " | TELEGRAM'A GONDERILMEYECEK"
        )
        result["status"] = "ok"
        result["buy_results"] = []
        result["all_buy_results"] = []
        result["latest_buy_time"] = None
        result["buy_signal"] = False
        return result


# scanner.main() kendi global scan_symbol referansini kullanir.
# Bu nedenle wrapper'i atayip ayni normal taramayi tek workflow'da
# calistiriyoruz.
scanner.scan_symbol = verified_scan_symbol

if __name__ == "__main__":
    scanner.main()
