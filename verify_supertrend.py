# ============================================================
# SUPERTREND FORMUL KARSILASTIRMA TESTI
# ============================================================
# BU DOSYA scanner.py'yi DEGISTIRMEZ.
#
# Amac:
# 1) TradingView'dan ayni 2H OHLC mumlarini almak
# 2) Iki farkli Supertrend hesabini ayni mumlarda calistirmak
#    A) TradingView resmi Supertrend band/trend mantigi
#    B) KivancOzbilgic acik kaynak SuperTrend mantigi
# 3) SAT -> AL donuslerini yan yana gostermek
# 4) BUY etiketinin "trend flip" mi yoksa "fiyatin Supertrend
#    cizgisini yukari kesmesi" mi oldugunu ayirmak
#
# Ayarlar:
# ATR = 10
# Multiplier = 2
# Source = HL2
# Timeframe = 2H
# ============================================================

import json
import time
import random
import string
from datetime import datetime
from zoneinfo import ZoneInfo

import websocket


TV_WS_URL = "wss://data.tradingview.com/socket.io/websocket"
TIMEFRAME = "120"
CANDLE_COUNT = 300
ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
TIMEZONE = "Europe/Istanbul"

DEFAULT_SYMBOLS = [
    "BIST:ATEKS",
    "BIST:ARFYE",
    "BIST:GESAN",
    "BIST:GLRMK",
    "BIST:SEGMN",
    "BIST:AKFIS",
]


def random_session(prefix):
    chars = string.ascii_lowercase + string.digits
    return prefix + "_" + "".join(random.choice(chars) for _ in range(12))


def tv_message(method, params):
    payload = json.dumps(
        {"m": method, "p": params},
        separators=(",", ":")
    )
    return "~m~" + str(len(payload)) + "~m~" + payload


def extract_tv_messages(raw):
    messages = []
    position = 0

    while True:
        start = raw.find("~m~", position)
        if start == -1:
            break

        length_start = start + 3
        length_end = raw.find("~m~", length_start)
        if length_end == -1:
            break

        try:
            length = int(raw[length_start:length_end])
        except ValueError:
            position = length_end + 3
            continue

        json_start = length_end + 3
        json_end = json_start + length

        if json_end > len(raw):
            break

        full_frame = raw[start:json_end]
        payload = raw[json_start:json_end]
        messages.append((full_frame, payload))
        position = json_end

    return messages, raw[position:]


def get_tv_candles(symbol, timeframe=TIMEFRAME, candle_count=CANDLE_COUNT):
    """Verifier icin TradingView WebSocket veri cekimi."""
    last_error = None

    for attempt in range(1, 4):
        ws = None
        chart_session = random_session("cs")
        try:
            # TradingView ornek istemcilerinde Origin header olarak gonderiliyor.
            # GitHub Actions ortaminda origin= parametresi bazi edge noktalarinda
            # baglantinin hemen kapatilmasina yol acabiliyor.
            ws = websocket.create_connection(
                TV_WS_URL,
                timeout=20,
                header=[
                    "Origin: https://data.tradingview.com",
                    "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
                ],
            )

            def send(method, params):
                ws.send(tv_message(method, params))

            send("set_auth_token", ["unauthorized_user_token"])
            send("chart_create_session", [chart_session, ""])
            send("switch_timezone", ["exchange"])

            symbol_config = json.dumps(
                {
                    "symbol": symbol,
                    "adjustment": "splits",
                    "session": "regular",
                },
                separators=(",", ":"),
            )

            send(
                "resolve_symbol",
                [chart_session, "sds_sym_1", "=" + symbol_config],
            )
            send(
                "create_series",
                [
                    chart_session,
                    "sds_1",
                    "s1",
                    "sds_sym_1",
                    timeframe,
                    candle_count,
                    "",
                ],
            )

            candles = {}
            raw_buffer = ""
            started = time.time()

            while time.time() - started < 20:
                packet = ws.recv()
                if packet is None:
                    break

                if isinstance(packet, bytes):
                    packet = packet.decode("utf-8", errors="ignore")

                raw_buffer += packet
                messages, raw_buffer = extract_tv_messages(raw_buffer)

                for full_frame, payload in messages:
                    if payload.startswith("~h~"):
                        try:
                            ws.send(full_frame)
                        except Exception:
                            pass
                        continue

                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue

                    method = obj.get("m")
                    params = obj.get("p", [])

                    if method in ("critical_error", "series_error"):
                        raise RuntimeError(
                            f"TradingView {method}: {params}"
                        )

                    if (
                        method != "timescale_update"
                        or len(params) < 2
                        or not isinstance(params[1], dict)
                    ):
                        continue

                    container = params[1]
                    series_data = container.get("sds_1")

                    if not isinstance(series_data, dict):
                        for value in container.values():
                            if isinstance(value, dict) and "s" in value:
                                series_data = value
                                break

                    if not isinstance(series_data, dict):
                        continue

                    for bar in series_data.get("s", []):
                        if not isinstance(bar, dict):
                            continue

                        values = bar.get("v")
                        if not isinstance(values, list) or len(values) < 5:
                            continue

                        # TV protokolunun bazi varyantlarinda v[0] index,
                        # v[1] timestamp olabilir. Once epoch timestamp'i
                        # tespit ediyoruz; normal formatta v[0] timestamp'tir.
                        try:
                            raw = [float(x) for x in values]
                        except Exception:
                            continue

                        if raw[0] >= 1_000_000_000:
                            t, o, h, low, close = raw[:5]
                        elif len(raw) >= 6 and raw[1] >= 1_000_000_000:
                            t, o, h, low, close = raw[1:6]
                        else:
                            continue

                        candles[t] = {
                            "time": t,
                            "open": o,
                            "high": h,
                            "low": low,
                            "close": close,
                        }

                if len(candles) >= min(30, candle_count):
                    break

            if candles:
                return sorted(candles.values(), key=lambda x: x["time"])

            raise RuntimeError("TradingView mum verisi gondermedi.")

        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * attempt)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    raise RuntimeError(
        "TradingView WebSocket baglantisi basarisiz: " + str(last_error)
    )

def aggregate_1h_to_direct_2h(one_hour, direct_2h):
    """
    TradingView 1H mumlarini, TradingView'in kendi 2H mum acilis
    zamanlarini referans alarak birlestirir.

    Boylece 09:00-11:00 gibi varsayilan bir seans baslangici uydurmak
    yerine, dogrudan TV'nin 2H bar zamanlarini anchor olarak kullaniriz.
    """
    by_time = {int(round(c["time"])): c for c in one_hour}
    result = []
    hour = 60 * 60

    for bar2 in direct_2h:
        t = int(round(bar2["time"]))
        first = by_time.get(t)
        second = by_time.get(t + hour)

        if first is None or second is None:
            continue

        result.append({
            "time": bar2["time"],
            "open": first["open"],
            "high": max(first["high"], second["high"]),
            "low": min(first["low"], second["low"]),
            "close": second["close"],
        })

    return result


def compare_direct_and_merged(direct_2h, merged_2h, count=10):
    print("")
    print("2H DOGRUDAN TV vs 1H -> 2H BIRLESTIRME:")
    print("  TARIH/Saat          DIRECT_OHLC                 MERGED_OHLC                 FARK")

    direct_map = {int(round(c["time"])): c for c in direct_2h}
    merged_map = {int(round(c["time"])): c for c in merged_2h}
    times = sorted(set(direct_map) & set(merged_map))[-count:]

    for t in times:
        d = direct_map[t]
        m = merged_map[t]
        diff = max(
            abs(d["open"] - m["open"]),
            abs(d["high"] - m["high"]),
            abs(d["low"] - m["low"]),
            abs(d["close"] - m["close"]),
        )
        print(
            f"  {candle_label(d['time'])}  "
            f"{d['open']:.4f}/{d['high']:.4f}/{d['low']:.4f}/{d['close']:.4f}   "
            f"{m['open']:.4f}/{m['high']:.4f}/{m['low']:.4f}/{m['close']:.4f}   "
            f"{diff:.6f}"
        )

    print(
        "  NOT: FARK=0 ise 1H'den kurulan 2H mum, TV'nin dogrudan 2H mumuyla ayni."
    )


def true_ranges(candles):
    tr = []
    for i, candle in enumerate(candles):
        h = candle["high"]
        l = candle["low"]

        if i == 0:
            tr.append(h - l)
        else:
            prev_close = candles[i - 1]["close"]
            tr.append(max(
                h - l,
                abs(h - prev_close),
                abs(l - prev_close)
            ))
    return tr


def atr_rma(candles, period):
    tr = true_ranges(candles)
    atr = [None] * len(candles)

    if len(tr) < period:
        return atr

    first = sum(tr[:period]) / period
    atr[period - 1] = first

    for i in range(period, len(tr)):
        atr[i] = (
            atr[i - 1] * (period - 1) + tr[i]
        ) / period

    return atr


def official_tv_supertrend(candles, period=10, multiplier=2.0):
    """
    TradingView Help Center'daki resmi Supertrend mantigi.

    Yon:
      -1 = UP / AL
      +1 = DOWN / SAT
    """
    atr = atr_rma(candles, period)

    upper = [None] * len(candles)
    lower = [None] * len(candles)
    direction = [None] * len(candles)
    line = [None] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            continue

        hl2 = (
            candles[i]["high"] + candles[i]["low"]
        ) / 2.0

        basic_upper = hl2 + multiplier * atr[i]
        basic_lower = hl2 - multiplier * atr[i]

        if i == period - 1:
            upper[i] = basic_upper
            lower[i] = basic_lower
            direction[i] = 1
            line[i] = upper[i]
            continue

        prev_upper = upper[i - 1]
        prev_lower = lower[i - 1]
        prev_close = candles[i - 1]["close"]

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

        prev_direction = direction[i - 1]

        if prev_direction == 1:
            if candles[i]["close"] > upper[i]:
                direction[i] = -1
            else:
                direction[i] = 1
        else:
            if candles[i]["close"] < lower[i]:
                direction[i] = 1
            else:
                direction[i] = -1

        line[i] = (
            lower[i] if direction[i] == -1
            else upper[i]
        )

    return {
        "atr": atr,
        "upper": upper,
        "lower": lower,
        "direction": direction,
        "line": line,
    }


def atr_sma(candles, period):
    """Kivanc'taki 'Change ATR Calculation Method' acik oldugunda
    kullanilan alternatif ATR: SMA(True Range, period)."""
    tr = true_ranges(candles)
    atr = [None] * len(candles)
    for i in range(period - 1, len(candles)):
        atr[i] = sum(tr[i - period + 1:i + 1]) / period
    return atr


def kivanc_supertrend_sma(candles, period=10, multiplier=2.0):
    """Ekrandaki ayarlara gore Kivanc SuperTrend: ATR SMA."""
    atr = atr_sma(candles, period)
    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [None] * len(candles)
    line = [None] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            continue
        hl2 = (candles[i]["high"] + candles[i]["low"]) / 2.0
        raw_up = hl2 - multiplier * atr[i]
        raw_dn = hl2 + multiplier * atr[i]

        if i == period - 1:
            up[i] = raw_up
            dn[i] = raw_dn
            trend[i] = 1
            line[i] = up[i]
            continue

        prev_up = up[i - 1]
        prev_dn = dn[i - 1]
        prev_close = candles[i - 1]["close"]

        up[i] = max(raw_up, prev_up) if prev_close > prev_up else raw_up
        dn[i] = min(raw_dn, prev_dn) if prev_close < prev_dn else raw_dn

        prev_trend = trend[i - 1]
        if prev_trend == -1 and candles[i]["close"] > prev_dn:
            trend[i] = 1
        elif prev_trend == 1 and candles[i]["close"] < prev_up:
            trend[i] = -1
        else:
            trend[i] = prev_trend

        line[i] = up[i] if trend[i] == 1 else dn[i]

    return {"atr": atr, "up": up, "dn": dn, "trend": trend, "line": line}


def kivanc_supertrend(candles, period=10, multiplier=2.0):
    """
    KivancOzbilgic SuperTrend mantigi.

    Kivanc acik kaynak scriptinde varsayilan ATR metodu RMA'dir.
    Kaynak HL2 yapilabilir.
    
    Kritik fark:
      - up/dn bandlari onceki barin close'una gore korunur.
      - trend flip kontrolu onceki band (up1/dn1) ile yapilir.

    Yon:
      +1 = UP / AL
      -1 = DOWN / SAT
    """
    atr = atr_rma(candles, period)

    up = [None] * len(candles)
    dn = [None] * len(candles)
    trend = [None] * len(candles)
    line = [None] * len(candles)

    for i in range(len(candles)):
        if atr[i] is None:
            continue

        hl2 = (
            candles[i]["high"] + candles[i]["low"]
        ) / 2.0

        raw_up = hl2 - multiplier * atr[i]
        raw_dn = hl2 + multiplier * atr[i]

        if i == period - 1:
            up[i] = raw_up
            dn[i] = raw_dn
            trend[i] = 1
            line[i] = up[i]
            continue

        prev_up = up[i - 1]
        prev_dn = dn[i - 1]
        prev_close = candles[i - 1]["close"]

        up[i] = (
            max(raw_up, prev_up)
            if prev_close > prev_up
            else raw_up
        )

        dn[i] = (
            min(raw_dn, prev_dn)
            if prev_close < prev_dn
            else raw_dn
        )

        prev_trend = trend[i - 1]

        if (
            prev_trend == -1
            and candles[i]["close"] > prev_dn
        ):
            trend[i] = 1
        elif (
            prev_trend == 1
            and candles[i]["close"] < prev_up
        ):
            trend[i] = -1
        else:
            trend[i] = prev_trend

        line[i] = (
            up[i] if trend[i] == 1
            else dn[i]
        )

    return {
        "atr": atr,
        "up": up,
        "dn": dn,
        "trend": trend,
        "line": line,
    }


def last_completed_index(candles):
    now = datetime.now(ZoneInfo(TIMEZONE)).timestamp()
    frame_seconds = 2 * 60 * 60

    completed = [
        i for i, candle in enumerate(candles)
        if candle["time"] + frame_seconds <= now
    ]

    return completed[-1] if completed else None


def candle_label(timestamp):
    dt = datetime.fromtimestamp(
        timestamp,
        tz=ZoneInfo("UTC")
    ).astimezone(ZoneInfo(TIMEZONE))
    return dt.strftime("%d.%m.%Y %H:%M")


def direction_text(value, mode):
    if value is None:
        return "NA"

    if mode == "official":
        return "AL" if value == -1 else "SAT"

    return "AL" if value == 1 else "SAT"


def find_flips(direction, mode, idx):
    if idx is None or idx < 1:
        return False, None

    current = direction[idx]
    previous = direction[idx - 1]

    if current is None or previous is None:
        return False, None

    if mode == "official":
        buy = previous == 1 and current == -1
        sell = previous == -1 and current == 1
    else:
        buy = previous == -1 and current == 1
        sell = previous == 1 and current == -1

    if buy:
        return True, "BUY"
    if sell:
        return True, "SELL"

    return False, None



def cross_above_supertrend_line(candles, line, idx):
    """
    Fiyatin Supertrend cizgisini yukari kestigi bar.

    Bu, "trend flip" ile ayni sey degildir.
    TradingView'daki bazi BUY etiketli scriptler BUY'i
    fiyat/Supertrend crossover olarak tanimlar.
    """
    if idx is None or idx < 1:
        return False

    current_close = candles[idx]["close"]
    previous_close = candles[idx - 1]["close"]
    current_line = line[idx]
    previous_line = line[idx - 1]

    if (
        current_line is None
        or previous_line is None
    ):
        return False

    return (
        current_close > current_line
        and previous_close <= previous_line
    )


def print_last_bars(candles, official, kivanc, idx, count=8):
    start = max(1, idx - count + 1)

    print("")
    print(f"Son {idx - start + 1} tamamlanmis mum icin aday BUY sinyalleri:")
    print(
        "  TARIH/Saat          CLOSE       TV-FLIP  KIVANC-FLIP  "
        "TV-CROSS-UP"
    )

    for j in range(start, idx + 1):
        tv_flip, _ = find_flips(
            official["direction"],
            "official",
            j
        )
        kv_flip, _ = find_flips(
            kivanc["trend"],
            "kivanc",
            j
        )
        cross = cross_above_supertrend_line(
            candles,
            official["line"],
            j
        )

        print(
            f"  {candle_label(candles[j]['time'])}  "
            f"{candles[j]['close']:.4f}   "
            f"{'BUY' if tv_flip else '-':7}   "
            f"{'BUY' if kv_flip else '-':10}   "
            f"{'BUY' if cross else '-'}"
        )



def print_detailed_values(candles, official, kivanc, idx, count=8):
    start = max(1, idx - count + 1)
    print("")
    print("DETAYLI BANT/CLOSE KONTROLU:")
    print(
        "  TARIH/Saat          CLOSE    TV_LOWER   TV_UPPER   "
        "TV_LINE    TV_DIR   KV_UP      KV_DN      KV_TREND"
    )
    for j in range(start, idx + 1):
        print(
            f"  {candle_label(candles[j]['time'])}  "
            f"{candles[j]['close']:8.4f} "
            f"{official['lower'][j]:9.4f} "
            f"{official['upper'][j]:9.4f} "
            f"{official['line'][j]:9.4f} "
            f"{direction_text(official['direction'][j], 'official'):6} "
            f"{kivanc['up'][j]:9.4f} "
            f"{kivanc['dn'][j]:9.4f} "
            f"{direction_text(kivanc['trend'][j], 'kivanc')}"
        )


def main():
    import os

    text = os.getenv("VERIFY_SYMBOLS", "")
    symbols = [
        x.strip() for x in text.split(",") if x.strip()
    ] if text.strip() else DEFAULT_SYMBOLS

    print("=" * 78)
    print("SUPERTREND FORMUL KARSILASTIRMA")
    print("scanner.py DEGISTIRILMIYOR")
    print("EKRAN: Change ATR Calculation Method = ACIK -> ATR = RMA(TR,10)")
    print("=" * 78)
    print(
        f"ATR={ATR_PERIOD}  MULT={ATR_MULTIPLIER}  "
        f"SOURCE=HL2  TF=2H"
    )
    print("")

    for symbol in symbols:
        print("-" * 78)
        print(symbol)

        try:
            # Scanner ile ayni calisan TradingView veri katmanindan
            # dogrudan 2H mumlari al.
            candles = get_tv_candles(symbol, TIMEFRAME, CANDLE_COUNT)
            merged = candles[:]

            if len(candles) < ATR_PERIOD + 5:
                print(
                    f"YETERSIZ MUM: {len(candles)}"
                )
                continue

            idx = last_completed_index(candles)

            if idx is None:
                print("TAMAMLANMIS MUM YOK")
                continue

            compare_direct_and_merged(candles, merged, count=3)

            official = official_tv_supertrend(
                candles,
                ATR_PERIOD,
                ATR_MULTIPLIER
            )

            kivanc = kivanc_supertrend(
                candles,
                ATR_PERIOD,
                ATR_MULTIPLIER
            )
            kivanc_sma = kivanc_supertrend_sma(
                candles,
                ATR_PERIOD,
                ATR_MULTIPLIER
            )

            oi = official["direction"][idx]
            op = official["direction"][idx - 1]
            ki = kivanc["trend"][idx]
            kp = kivanc["trend"][idx - 1]

            obuy, osignal = find_flips(
                official["direction"],
                "official",
                idx
            )

            kbuy, ksignal = find_flips(
                kivanc["trend"],
                "kivanc",
                idx
            )
            ks_buy, ks_signal = find_flips(
                kivanc_sma["trend"],
                "kivanc",
                idx
            )

            close = candles[idx]["close"]

            print(
                "Son tamamlanmis mum : "
                + candle_label(candles[idx]["time"])
            )
            print(
                f"Close                 : {close:.4f}"
            )
            print(
                "TradingView resmi     : "
                f"{direction_text(op, 'official')} -> "
                f"{direction_text(oi, 'official')} "
                f"{'<<< BUY' if obuy else ''}"
            )
            print(
                "Kivanc/RMA            : "
                f"{direction_text(kp, 'kivanc')} -> "
                f"{direction_text(ki, 'kivanc')} "
                f"{'<<< BUY' if kbuy else ''}"
            )
            ks_prev = kivanc_sma["trend"][idx - 1]
            ks_now = kivanc_sma["trend"][idx]
            print(
                "Kivanc/SMA            : "
                f"{direction_text(ks_prev, 'kivanc')} -> "
                f"{direction_text(ks_now, 'kivanc')} "
                f"{'<<< BUY' if ks_buy else ''}"
            )

            print(
                "EKRAN AYARI           : Change ATR Calculation Method = ACIK"
            )
            print(
                "Kivanc SMA BUY        : "
                + ("VAR" if ks_buy else "YOK")
            )

            # Son 8 tamamlanmis mumda uc farkli BUY adayini yan yana ver.
            # Boylece kullanici TradingView grafiğindeki yesil BUY
            # etiketinin hangi mantiga denk geldigini dogrudan kontrol edebilir.
            print_last_bars(
                candles,
                official,
                kivanc,
                idx,
                count=8
            )
            print_detailed_values(
                candles,
                official,
                kivanc,
                idx,
                count=8
            )

        except Exception as exc:
            print("HATA:", exc)

    print("")
    print("=" * 78)
    print("TEST BITTI")
    print(
        "ONEMLI: Bu test TradingView grafik ekranindaki "
        "yesil BUY etiketini otomatik okuyamaz."
    )
    print(
        "Bu test scanner.py ile ayni TradingView WebSocket veri katmanini kullanir."
    )
    print(
        "Son 8 tamamlanmis mum icin TV trend flip, Kivanc/RMA trend flip "
        "ve fiyat/Supertrend cross adaylari gosterilir."
    )
    print(
        "Amaç: ATEKS/AKFIS'teki gorunen BUY etiketi ile hangi adayın "
        "mum/saat olarak ayni oldugunu bulmak. scanner.py bu testte "
        "DEGISTIRILMEZ."
    )
    print("=" * 78)


if __name__ == "__main__":
    main()
