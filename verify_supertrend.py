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
CANDLE_COUNT = 150
ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
TIMEZONE = "Europe/Istanbul"

DEFAULT_SYMBOLS = [
    "BIST:ARFYE",
    "BIST:ATEKS",
    "BIST:AYES",
    "BIST:AYGAZ",
    "BIST:DGNMO",
    "BIST:MSGYO",
    "BIST:PSGYO",
    "BIST:RNPOL",
    "BIST:RODRG",
    "BIST:SANFM",
    "BIST:SEKFK",
    "BIST:SOKM",
    "BIST:YBTAS",
    "BIST:YGGYO",
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


def get_tv_candles(symbol):
    ws = None
    chart_session = random_session("cs")

    try:
        ws = websocket.create_connection(
            TV_WS_URL,
            timeout=10,
            origin="https://data.tradingview.com"
        )

        ws.send(tv_message(
            "set_auth_token",
            ["unauthorized_user_token"]
        ))

        ws.send(tv_message(
            "chart_create_session",
            [chart_session, ""]
        ))

        symbol_config = json.dumps(
            {
                "symbol": symbol,
                "adjustment": "splits"
            },
            separators=(",", ":")
        )

        ws.send(tv_message(
            "resolve_symbol",
            [
                chart_session,
                "sds_sym_1",
                "=" + symbol_config
            ]
        ))

        ws.send(tv_message(
            "create_series",
            [
                chart_session,
                "sds_1",
                "s1",
                "sds_sym_1",
                TIMEFRAME,
                CANDLE_COUNT,
                ""
            ]
        ))

        candles = {}
        raw_buffer = ""
        started = time.time()

        while time.time() - started < 10:
            try:
                packet = ws.recv()
            except websocket.WebSocketTimeoutException:
                break

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

                if obj.get("m") != "timescale_update":
                    continue

                params = obj.get("p", [])
                if len(params) < 2:
                    continue

                container = params[1]
                if not isinstance(container, dict):
                    continue

                series_data = container.get("sds_1")

                if series_data is None:
                    for value in container.values():
                        if isinstance(value, dict) and "s" in value:
                            series_data = value
                            break

                if not isinstance(series_data, dict):
                    continue

                bars = series_data.get("s", [])
                if not isinstance(bars, list):
                    continue

                for bar in bars:
                    if not isinstance(bar, dict):
                        continue

                    values = bar.get("v")
                    if not isinstance(values, list) or len(values) < 5:
                        continue

                    try:
                        t = float(values[0])
                        o = float(values[1])
                        h = float(values[2])
                        l = float(values[3])
                        c = float(values[4])
                    except Exception:
                        continue

                    candles[t] = {
                        "time": t,
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                    }

            if len(candles) >= 20:
                # Once we have a healthy batch, allow one short pause for
                # the final update packet, then continue.
                if time.time() - started > 2:
                    break

        result = sorted(candles.values(), key=lambda x: x["time"])
        return result

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


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


def main():
    import os

    text = os.getenv("VERIFY_SYMBOLS", "")
    symbols = [
        x.strip() for x in text.split(",") if x.strip()
    ] if text.strip() else DEFAULT_SYMBOLS

    print("=" * 78)
    print("SUPERTREND FORMUL KARSILASTIRMA")
    print("scanner.py DEGISTIRILMIYOR")
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
            candles = get_tv_candles(symbol)

            if len(candles) < ATR_PERIOD + 5:
                print(
                    f"YETERSIZ MUM: {len(candles)}"
                )
                continue

            idx = last_completed_index(candles)

            if idx is None:
                print("TAMAMLANMIS MUM YOK")
                continue

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

            if obuy == kbuy:
                print(
                    "BUY ESLESMESI         : AYNI"
                )
            else:
                print(
                    "BUY ESLESMESI         : FARKLI"
                )

            # Son 5 tamamlanmis mumun yonleri.
            start = max(0, idx - 4)
            print("Son 5 yon:")
            for j in range(start, idx + 1):
                print(
                    "  "
                    + candle_label(candles[j]["time"])
                    + " | "
                    + direction_text(
                        official["direction"][j],
                        "official"
                    )
                    + " | "
                    + direction_text(
                        kivanc["trend"][j],
                        "kivanc"
                    )
                )

        except Exception as exc:
            print("HATA:", exc)

    print("")
    print("=" * 78)
    print("TEST BITTI")
    print(
        "Not: Bu rapor TradingView grafik ekranindaki "
        "yesil BUY etiketini otomatik okuyamaz."
    )
    print(
        "Ama iki matematiksel Supertrend algoritmasini "
        "ayni OHLC mumlarinda birebir yan yana verir."
    )
    print("=" * 78)


if __name__ == "__main__":
    main()
