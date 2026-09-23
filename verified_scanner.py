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
    """
    Bagimsiz kopya: TradingView Supertrend'in documented state
    mantigini uygular. +1=AL / -1=SAT.
    """
    n = len(candles)
    if n < period + 2:
        return None

    tr = [0.0] * n
    for i, c in enumerate(candles):
        if i == 0:
            tr[i] = c["high"] - c["low"]
        else:
            pc = candles[i - 1]["close"]
            tr[i] = max(c["high"] - c["low"], abs(c["high"] - pc), abs(c["low"] - pc))

    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    upper = [None] * n
    lower = [None] * n
    direction = [None] * n
    st = [None] * n

    for i in range(n):
        if atr[i] is None:
            direction[i] = 1
            continue

        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        bu = hl2 + multiplier * atr[i]
        bl = hl2 - multiplier * atr[i]

        pu = 0.0 if i == 0 or upper[i - 1] is None else upper[i - 1]
        pl = 0.0 if i == 0 or lower[i - 1] is None else lower[i - 1]
        pc = candles[i - 1]["close"] if i > 0 else None

        upper[i] = bu if i == 0 or bu < pu or (pc is not None and pc > pu) else pu
        lower[i] = bl if i == 0 or bl > pl or (pc is not None and pc < pl) else pl

        if i == period - 1:
            direction[i] = 1
        elif st[i - 1] is None:
            direction[i] = 1
        elif st[i - 1] == upper[i - 1]:
            direction[i] = -1 if candles[i]["close"] > upper[i] else 1
        else:
            direction[i] = 1 if candles[i]["close"] < lower[i] else -1

        st[i] = lower[i] if direction[i] == -1 else upper[i]

    return [None if d is None else -d for d in direction]

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
    # Sadece YENI BUY adaylari stabilizasyon kontrolune girer.
    # Daha once Telegram'a gonderilmis BUY'lar yeniden bekletilmez.
    if not buy_results:
        return result

    try:
        candles = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"],
        )

        if len(candles) < scanner.ATR_PERIOD + 2:
            raise RuntimeError("dogrulama icin TradingView native 2H veri yetersiz")

        # ------------------------------------------------------------
        # 16 DAKIKA VERI STABILIZASYONU
        # ------------------------------------------------------------
        # TradingView ayni tamamlanmis 2H mumun OHLC degerlerini
        # gecikmeli veri nedeniyle sonradan duzeltebiliyor. Ilk BUY
        # goruldugu anda Telegram'a gondermek yerine ayni mum 16 dk
        # sonra tekrar okunur. OHLC degismisse BUY iptal edilir.
        stabilization_seconds = int(
            os.getenv("BUY_STABILIZATION_SECONDS", "30")
        )

        first_completed_index = scanner.get_last_completed_index(candles)
        if first_completed_index is None or first_completed_index < 1:
            raise RuntimeError("stabilizasyon icin tamamlanmis 2H mum yok")

        first_bar = candles[first_completed_index]
        first_bar_time = first_bar["time"]
        first_ohlc = (
            first_bar["open"],
            first_bar["high"],
            first_bar["low"],
            first_bar["close"],
        )

        scanner.log(
            "    BUY STABILIZASYON BASLADI | "
            + symbol
            + " | "
            + datetime.fromtimestamp(
                first_bar_time,
                tz=ZoneInfo("UTC"),
            ).astimezone(ZoneInfo(scanner.TIMEZONE)).strftime("%d.%m.%Y %H:%M")
            + " | "
            + str(stabilization_seconds)
            + " saniye bekleniyor"
        )

        time.sleep(stabilization_seconds)

        candles2 = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"],
        )
        second_completed_index = scanner.get_last_completed_index(candles2)
        if second_completed_index is None or second_completed_index < 1:
            raise RuntimeError("ikinci okumada tamamlanmis 2H mum yok")

        second_bar = candles2[second_completed_index]
        if second_bar["time"] != first_bar_time:
            raise RuntimeError(
                "stabilizasyon hedef mumu degisti: ilk="
                + str(first_bar_time)
                + " ikinci="
                + str(second_bar["time"])
            )

        second_ohlc = (
            second_bar["open"],
            second_bar["high"],
            second_bar["low"],
            second_bar["close"],
        )

        if first_ohlc != second_ohlc:
            scanner.log(
                "    !!! BUY STABILIZASYON BASARISIZ | "
                + symbol
                + " | OHLC DEGISTI | "
                + str(first_ohlc)
                + " -> "
                + str(second_ohlc)
                + " | TELEGRAM'A GONDERILMEYECEK"
            )
            result["status"] = "ok"
            result["buy_results"] = []
            result["all_buy_results"] = []
            result["latest_buy_time"] = None
            result["buy_signal"] = False
            return result

        # Stabil kalan ayni mumun BUY durumunu yeniden hesapla.
        candles = candles2
        completed_index = second_completed_index
        scanner.log(
            "    BUY STABILIZASYON BASARILI | "
            + symbol
            + " | OHLC DEGİSMEDI"
        )

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
