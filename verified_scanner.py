"""
BIST Supertrend tek tarama + otomatik BUY dogrulama.

scanner.py normal BIST taramasini yapar. Her BUY adayi icin
ayni TradingView native 2H serisi tekrar alinip bagimsiz
TradingView public Supertrend (Kivanc) mantigi ile kontrol edilir.
Uyusmayan BUY Telegram'a gonderilmez.

Study YOK.
"""

import scanner
import os
import time
import math
from datetime import datetime
from zoneinfo import ZoneInfo

# Otomatik BUY teyit katmani:
# 2H momentum > 0% | RVOL >= 1.20 | govde >= %50 | 4H AL | 1D AL
# Bu fonksiyonlar Study kullanmaz; native TradingView OHLC verisiyle calisir.
from new_buy_system.verify_14 import tv_native, trend_from_rows


def label(d):
    return "AL" if d == 1 else "SAT" if d == -1 else "BELIRSIZ"


def mark_filtered_candidate(result, reason):
    """Gercek SAT -> AL adayi teyit filtrelerinden gecmediyse Telegram'a ayir."""
    candidates = result.get("buy_results", [])
    if not candidates:
        return
    candidate = dict(candidates[0])
    candidate["filter_reason"] = reason
    candidate["filter_failed"] = True
    candidate["confirmation"] = result.get("confirmation", {})
    result["filtered_buy_results"] = [candidate]


def independent_directions(candles, period=10, multiplier=2.0):
    """
    Bagimsiz kopya: TradingView public Supertrend
    (PUB;VfOPXWDHDPhORvJYRTcuHOyeqpOcRR45) BUY mantigi.

    Indicator metadata:
      ATR Period=10, Source=HL2, ATR Multiplier=2,
      Change ATR Calculation Method=true.

    KivancOzbilgic state mantigi:
      atr=RMA/Wilder
      up=HL2-mult*ATR; up := close[1] > up1 ? max(up,up1) : up
      dn=HL2+mult*ATR; dn := close[1] < dn1 ? min(dn,dn1) : dn
      trend flipleri kapanisa gore.

    +1=AL, -1=SAT.
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
            tr[i] = max(
                c["high"] - c["low"],
                abs(c["high"] - pc),
                abs(c["low"] - pc),
            )

    atr = [None] * n
    atr[period - 1] = sum(tr[:period]) / period
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    up = [None] * n
    dn = [None] * n
    trend = [1] * n

    for i, c in enumerate(candles):
        if atr[i] is None:
            trend[i] = 1
            continue

        src = (c["high"] + c["low"]) / 2.0

        up0 = src - multiplier * atr[i]
        up1 = up[i - 1] if i > 0 and up[i - 1] is not None else up0
        up[i] = max(up0, up1) if i > 0 and candles[i - 1]["close"] > up1 else up0

        dn0 = src + multiplier * atr[i]
        dn1 = dn[i - 1] if i > 0 and dn[i - 1] is not None else dn0
        dn[i] = min(dn0, dn1) if i > 0 and candles[i - 1]["close"] < dn1 else dn0

        prev = trend[i - 1] if i > 0 else 1
        trend[i] = (
            1 if prev == -1 and c["close"] > dn1
            else -1 if prev == 1 and c["close"] < up1
            else prev
        )

    return trend


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

    # KRITIK: Dogrulama sadece scanner.py'nin GERCEK BUY adayi
    # olarak buldugu mum icin calisir.
    #
    # BUY adayi yoksa burada kesinlikle mum zamani okumaya veya
    # dogrulama yapmaya calisilmaz. Bu, onceki hatadaki
    # AL -> AL / SAT -> SAT durumlarinin yanlislikla
    # "BUY ADAY MUM ZAMANI OKUNAMADI" olarak raporlanmasini engeller.
    result["filtered_buy_results"] = []

    if not buy_results:
        return result

    # BUY adayi varsa hedef mum zamani zorunludur.
    # Refetch sirasinda baska bir "son tamamlanmis" muma kaymak
    # kesinlikle kabul edilmez.
    target_buy_time = None
    try:
        target_buy_time = float(buy_results[0]["candle_time"])
    except Exception:
        target_buy_time = None

    if target_buy_time is None:
        scanner.log(
            "    !!! GERCEK BUY ADAYINDA MUM ZAMANI OKUNAMADI | "
            + symbol
            + " | TELEGRAM'A GONDERILMEYECEK"
        )
        result["status"] = "ok"
        result["buy_results"] = []
        result["all_buy_results"] = []
        result["latest_buy_time"] = None
        result["buy_signal"] = False
        return result

    # Buraya gelindiyse scanner.py gercekten SAT -> AL BUY adayi
    # uretmistir. Bundan sonra stabilizasyon + bagimsiz Supertrend
    # + 4H/1D teyit katmani calisir.

    try:
        candles = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"],
        )

        if len(candles) < scanner.ATR_PERIOD + 2:
            raise RuntimeError("dogrulama icin TradingView native 2H veri yetersiz")

        # ------------------------------------------------------------
        # 30 SANIYE VERI STABILIZASYONU
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

        target_indexes = [
            i for i, c in enumerate(candles)
            if float(c["time"]) == target_buy_time
        ]
        if not target_indexes:
            raise RuntimeError("BUY adayi hedef mum refetch verisinde yok")

        first_target_index = target_indexes[-1]
        if first_target_index > first_completed_index:
            raise RuntimeError(
                "BUY adayi hedef mum henuz tamamlanmamis"
            )

        first_bar = candles[first_target_index]
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

        # 2. OKUMA: ayni mumun ikinci snapshot'i.
        candles2 = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"],
        )
        second_completed_index = scanner.get_last_completed_index(candles2)
        if second_completed_index is None or second_completed_index < 1:
            raise RuntimeError("ikinci okumada tamamlanmis 2H mum yok")

        second_target_indexes = [
            i for i, c in enumerate(candles2)
            if float(c["time"]) == target_buy_time
        ]
        if not second_target_indexes:
            raise RuntimeError("BUY adayi hedef mum ikinci okumada yok")

        second_target_index = second_target_indexes[-1]
        if second_target_index > second_completed_index:
            raise RuntimeError(
                "BUY adayi hedef mum ikinci okumada tamamlanmamis"
            )

        second_bar = candles2[second_target_index]
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

        # 3. OKUMA / FREEZE: ilk iki snapshot ayniysa ayni mum bir kez daha
        # okunur. Uc snapshot'in OHLC fingerprint'i ayni olmadan sinyal
        # Telegram'a gecmez. Boylece tek bir gecici TradingView snapshot'i
        # uzerinden alarm uretilmez.
        candles3 = sorted(
            scanner.get_tv_candles_with_retry(symbol, "native_2h"),
            key=lambda x: x["time"],
        )
        third_completed_index = scanner.get_last_completed_index(candles3)
        if third_completed_index is None or third_completed_index < 1:
            raise RuntimeError("ucuncu okumada tamamlanmis 2H mum yok")

        third_target_indexes = [
            i for i, c in enumerate(candles3)
            if float(c["time"]) == target_buy_time
        ]
        if not third_target_indexes:
            raise RuntimeError("BUY adayi hedef mum ucuncu okumada yok")

        third_target_index = third_target_indexes[-1]
        if third_target_index > third_completed_index:
            raise RuntimeError(
                "BUY adayi hedef mum ucuncu okumada tamamlanmamis"
            )

        third_bar = candles3[third_target_index]
        third_ohlc = (
            third_bar["open"],
            third_bar["high"],
            third_bar["low"],
            third_bar["close"],
        )

        if third_bar["time"] != first_bar_time or third_ohlc != first_ohlc:
            scanner.log(
                "    !!! BUY FREEZE BASARISIZ | "
                + symbol
                + " | 3 SNAPSHOT AYNI DEGIL | TELEGRAM'A GONDERILMEYECEK"
            )
            result["status"] = "ok"
            result["buy_results"] = []
            result["all_buy_results"] = []
            result["latest_buy_time"] = None
            result["buy_signal"] = False
            return result

        scanner.log(
            "    BUY FREEZE BASARILI | "
            + symbol
            + " | AYNI MUM + AYNI OHLC x3 | SINYAL DONDURULDU"
        )

        # Stabil kalan ayni mumun BUY durumunu yeniden hesapla.
        candles = candles3
        completed_index = third_target_index
        scanner.log(
            "    BUY STABILIZASYON BASARILI | "
            + symbol
            + " | OHLC DEGİSMEDI"
        )

        # Burada tekrar "son tamamlanmis mum" aranmaz.
        # Dogrulanan indeks, ilk BUY adayinin ayni candle_time'idir.
        completed_index = third_target_index
        if completed_index < 1:
            raise RuntimeError("dogrulama icin hedef BUY mumundan once mum yok")

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

        # ------------------------------------------------------------
        # OTOMATIK BUY TEYIT KATMANI
        # ------------------------------------------------------------
        # Ham SAT -> AL sinyali, ek olarak su bes kosulu saglanmadan
        # Telegram'a gonderilmez:
        #   1) 2H momentum > 0%
        #   2) RVOL >= 1.20
        #   3) 2H mum govdesi >= %50
        #   4) native 4H Supertrend = AL
        #   5) native 1D Supertrend = AL
        #
        # Boylece uretim alarmi, daha once 10 BUY adayi uzerinde
        # test edilen ayni teyit katmanini kullanir.
        try:
            target = calc[i]
            previous = calc[i - 1]

            momentum = (
                float(target["close"]) / float(previous["close"]) - 1.0
            )

            volume_window = [
                float(x.get("volume", 0.0))
                for x in calc[max(0, i - 20):i]
                if float(x.get("volume", 0.0)) > 0
            ]
            average_volume = (
                sum(volume_window) / len(volume_window)
                if volume_window else 0.0
            )
            current_volume = float(target.get("volume", 0.0))
            rvol = (
                current_volume / average_volume
                if average_volume > 0 and current_volume > 0
                else None
            )

            candle_range = float(target["high"]) - float(target["low"])
            candle_body = abs(
                float(target["close"]) - float(target["open"])
            )
            body_ratio = (
                candle_body / candle_range
                if candle_range > 0
                else 0.0
            )

            rows_4h = tv_native(symbol, "240", 300)
            rows_1d = tv_native(symbol, "1D", 300)

            trend_4h = trend_from_rows(rows_4h)
            trend_1d = trend_from_rows(rows_1d)

            confirmed = (
                momentum > 0.0
                and rvol is not None
                and rvol >= 1.20
                and body_ratio >= 0.50
                and trend_4h == 1
                and trend_1d == 1
            )

            result["confirmation"] = {
                "confirmed": confirmed,
                "momentum": momentum,
                "rvol": rvol,
                "body_ratio": body_ratio,
                "trend_4h": trend_4h,
                "trend_1d": trend_1d,
            }

            scanner.log(
                "    BUY TEYIT | "
                + symbol
                + " | MOM="
                + f"{momentum * 100:+.2f}%"
                + " | RVOL="
                + (f"{rvol:.2f}" if rvol is not None else "N/A")
                + " | GOVDE="
                + f"{body_ratio * 100:.0f}%"
                + " | 4H="
                + ("AL" if trend_4h == 1 else "SAT")
                + " | 1D="
                + ("AL" if trend_1d == 1 else "SAT")
                + " | TEYIT="
                + str(confirmed)
            )

            if not confirmed:
                scanner.log(
                    "    !!! BUY TEYIT FILTRE DISI | "
                    + symbol
                    + " | TELEGRAM'A GONDERILMEYECEK"
                )
                mark_filtered_candidate(
                    result,
                    "BUY TEYIT FILTRELERINDEN GECEMEDI"
                )
                result["status"] = "ok"
                result["buy_results"] = []
                result["all_buy_results"] = []
                result["latest_buy_time"] = None
                result["buy_signal"] = False
                return result

        except Exception as exc:
            scanner.log(
                "    !!! BUY TEYIT HATASI | "
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

        result["verification"] = {
            "verified": True,
            "frozen": True,
            "snapshot_count": 3,
            "ohlc_fingerprint": [calc[i]["open"], calc[i]["high"], calc[i]["low"], calc[i]["close"]],
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


def build_filtered_telegram_message(results):
    """
    Uretim Telegram mesajini yalnızca tum teyit filtrelerini gecen
    BUY adaylarini gosterecek sekilde olusturur.
    """
    now = scanner.now_istanbul()
    lines = [
        "🔔 <b>BIST BUY + YÜKSELİŞ TEYİT TARAMASI</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "⏱ <b>2H BUY</b> | ATR 10 | Çarpan 2.0 | HL2",
        "🔎 <b>FİLTRELER</b>",
        "• Momentum &gt; 0%",
        "• RVOL ≥ 1.20",
        "• Gövde ≥ %50",
        "• 4H Supertrend = AL",
        "• 1D Supertrend = AL",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🕒 Tarama: <b>{now.strftime('%d.%m.%Y %H:%M')}</b>",
        f"⭐ <b>TEYİTLİ BUY: {len(results)} adet</b>",
        "",
    ]

    for index, result in enumerate(results, 1):
        symbol = result["symbol"].split(":", 1)[-1]
        price = scanner.format_price(result["price"])
        verification = result.get("confirmation", {})

        momentum = float(verification.get("momentum", 0.0))
        rvol = verification.get("rvol")
        body_ratio = float(verification.get("body_ratio", 0.0))
        trend_4h = verification.get("trend_4h")
        trend_1d = verification.get("trend_1d")

        url = (
            "https://www.tradingview.com/chart/"
            "?symbol=BIST%3A"
            + symbol
            + "&interval=120"
        )

        candle_dt = scanner.candle_close_datetime(
            result["candle_time"]
        )

        lines.append(
            f'{index}. <a href="{url}"><b>{symbol}</b></a> — {price} TL'
        )
        lines.append(
            f"   📈 Momentum: <b>{momentum * 100:+.2f}%</b> | "
            f"📊 RVOL: <b>{rvol:.2f}</b> | "
            f"🕯 Gövde: <b>%{body_ratio * 100:.0f}</b>"
        )
        lines.append(
            "   2H: <b>SAT → AL</b> | "
            "4H: <b>AL</b> | 1D: <b>AL</b>"
        )
        lines.append(
            f'   🕯 Mum: <b>{candle_dt.strftime("%d.%m.%Y %H:%M")}</b>'
        )
        lines.append("")

    if not results:
        lines.append("⭐ <b>Bu taramada tüm teyit filtrelerini geçen BUY yok.</b>")
        lines.append("")

    lines.append("🔍 BUY motoru: SAT → AL")
    lines.append("⚙️ Study kullanılmadı.")
    lines.append("ℹ️ Bu filtreler sinyal kalitesini sıkılaştırır; yükselişi garanti etmez.")

    return "\n".join(lines)


scanner.build_telegram_message = build_filtered_telegram_message

if __name__ == "__main__":
    scanner.main()
