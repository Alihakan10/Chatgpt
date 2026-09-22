# ============================================================
# BIST SUPERTREND ALARM SISTEMI
# SURUM 2 - FINAL
# ============================================================
#
# OZELLIKLER
#
# 1) Tum BIST hisselerini TradingView Scanner ile bulur
# 2) TradingView WebSocket ile native 2 saatlik (120 dakika) mum verisini alir
# 3) Supertrend:
#       ATR Period     = 10
#       Source         = HL2
#       Multiplier     = 2
#       Timeframe      = 2H
#
# 4) SADECE gercek SAT -> AL donusunu yakalar
# 5) Ayni sinyali tekrar gondermez
# 6) Son durum GitHub state dosyasinda saklanir
# 7) Telegram bildirimi gonderir
# 8) TEST MODU vardir
# 9) Normal modda BIST saatleri disinda tarama yapmaz
# 10) Normal modda tum 619+ BIST hissesini tarar
#
# ============================================================

import os
import json
import time
import random
import string
import math
import base64
import requests
import websocket
from concurrent.futures import ThreadPoolExecutor, as_completed

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


# ============================================================
# AYARLAR
# ============================================================

TIMEZONE = "Europe/Istanbul"

# ------------------------------------------------------------
# SUPERTREND
# ------------------------------------------------------------

ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
TIMEFRAME = "120"
CANDLE_COUNT = 3000
HISTORY_TARGET = 3000
HISTORY_REQUEST_SIZE = 1000
DATA_TIMEFRAME = "60"


# ------------------------------------------------------------
# TRADINGVIEW
# ------------------------------------------------------------

TV_SCANNER_URL = (
    "https://scanner.tradingview.com/turkey/scan"
)

TV_WS_URL = (
    "wss://data.tradingview.com/socket.io/websocket"
)

WS_TIMEOUT = 10
REQUEST_TIMEOUT = 20
SYMBOL_DELAY = 0.05

# ------------------------------------------------------------
# TEST MODU
#
# GitHub Actions workflow'undan ayarlanabilir.
#
# TEST_MODE = true:
#   - BIST saat kontrolunu bypass eder
#   - TEST_SYMBOLS listesini tarar
#   - State dosyasini DEGISTIRMEZ
#
# ------------------------------------------------------------

TEST_MODE = (
    os.getenv(
        "TEST_MODE",
        "false"
    ).lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)

TEST_SYMBOLS_TEXT = os.getenv(
    "TEST_SYMBOLS",
    "BIST:ZOREN"
)

TEST_SYMBOLS = [
    x.strip()
    for x in TEST_SYMBOLS_TEXT.split(",")
    if x.strip()
]

SEND_TEST_TELEGRAM = (
    os.getenv(
        "SEND_TEST_TELEGRAM",
        "false"
    ).lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)

SEND_SCAN_REPORT = (
    os.getenv(
        "SEND_SCAN_REPORT",
        "false"
    ).lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)

SCAN_LIMIT_TEXT = os.getenv(
    "SCAN_LIMIT",
    "620"
)

try:
    SCAN_LIMIT = int(SCAN_LIMIT_TEXT)
except ValueError:
    SCAN_LIMIT = 620

# ------------------------------------------------------------
# MANUEL TARAMA
#
# GitHub Actions workflow_dispatch ile calistirildiginda
# BIST saatleri disinda da tam tarama yapilabilmesini saglar.
# ------------------------------------------------------------

# NATIVE_2H_ONLY
# Tum taramalar TradingView native 120 dakikalik seri ile yapilir.
# 1H -> 2H manuel birlestirme KULLANILMAZ.
MANUAL_TEST_RUN = (
    os.getenv(
        "MANUAL_TEST_RUN",
        "false"
    ).lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)

FORCE_SCAN = (
    os.getenv(
        "FORCE_SCAN",
        "false"
    ).lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

# ------------------------------------------------------------
# BIST SAATLERI
# ------------------------------------------------------------

MARKET_OPEN_HOUR = 10
MARKET_OPEN_MINUTE = 0

MARKET_CLOSE_HOUR = 18
MARKET_CLOSE_MINUTE = 0

# ------------------------------------------------------------
# GITHUB STATE
# ------------------------------------------------------------

GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN",
    ""
)

GITHUB_REPOSITORY = os.getenv(
    "GITHUB_REPOSITORY",
    ""
)

GITHUB_REF_NAME = os.getenv(
    "GITHUB_REF_NAME",
    "main"
)

STATE_FILE = (
    "state/supertrend_state.json"
)


# ============================================================
# ZAMAN
# ============================================================

def now_istanbul():

    return datetime.now(
        ZoneInfo(TIMEZONE)
    )


def log(message):

    print(
        f"[{now_istanbul().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{message}",
        flush=True
    )


# ============================================================
# RANDOM SESSION
# ============================================================

def random_session(prefix):

    chars = (
        string.ascii_lowercase +
        string.digits
    )

    return (
        prefix
        + "_"
        + "".join(
            random.choice(chars)
            for _ in range(12)
        )
    )


# ============================================================
# TRADINGVIEW AUTH TOKEN
# ============================================================

def get_tradingview_auth_token():
    """
    Session cookie varsa her workflow calismasinda taze WebSocket
    auth token almaya calisir. Basarisiz olursa secret olarak verilen
    TRADINGVIEW_AUTH_TOKEN'a geri doner.
    """
    sessionid = os.getenv("TV_SESSIONID", "").strip()
    sessionid_sign = os.getenv("TV_SESSIONID_SIGN", "").strip()
    fallback = os.getenv("TRADINGVIEW_AUTH_TOKEN", "").strip()

    if sessionid:
        try:
            headers = {
                "Origin": "https://www.tradingview.com",
                "Referer": "https://www.tradingview.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
                ),
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            cookies = {"sessionid": sessionid}
            if sessionid_sign:
                cookies["sessionid_sign"] = sessionid_sign

            # TradingView'in guncel quote_token endpointi GET ile
            # de sunuluyor. Once GET dene; eski istemciler icin POST fallback.
            response = requests.get(
                "https://www.tradingview.com/quote_token",
                headers=headers,
                cookies=cookies,
                timeout=REQUEST_TIMEOUT,
            )

            if not response.ok:
                response = requests.post(
                    "https://www.tradingview.com/quote_token/",
                    headers=headers,
                    cookies=cookies,
                    json={"grabSession": True},
                    timeout=REQUEST_TIMEOUT,
                )

            if response.ok:
                token = None
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        token = data.get("token")
                    elif isinstance(data, str):
                        token = data.split(":", 1)[0].strip()
                except Exception:
                    raw = response.text.strip()
                    if raw:
                        token = raw.split(":", 1)[0].strip()

                if token:
                    log("TradingView auth token session cookie'dan yenilendi.")
                    return token

            log(
                "TradingView auth token yenileme basarisiz; "
                "mevcut TRADINGVIEW_AUTH_TOKEN kullanilacak."
            )

        except Exception as exc:
            log(
                "TradingView auth token yenileme hatasi; "
                "mevcut token kullanilacak: "
                + str(exc)
            )

    if fallback:
        log("TradingView auth: secret token kullaniliyor.")
        return fallback

    if sessionid:
        log("TradingView auth: session cookie mevcut, token alinamadi.")
    else:
        log("TradingView auth: anonim mod.")
    return "unauthorized_user_token"


# ============================================================
# TRADINGVIEW MESAJI
# ============================================================

def tv_message(
    method,
    params
):

    payload = json.dumps(
        {
            "m": method,
            "p": params
        },
        separators=(",", ":")
    )

    return (
        "~m~"
        + str(len(payload))
        + "~m~"
        + payload
    )


# ============================================================
# TRADINGVIEW FRAME AYIRICI
# ============================================================

def extract_tv_messages(raw):

    messages = []
    position = 0

    while True:

        start = raw.find(
            "~m~",
            position
        )

        if start == -1:
            break

        length_start = start + 3

        length_end = raw.find(
            "~m~",
            length_start
        )

        if length_end == -1:
            break

        try:

            length = int(
                raw[
                    length_start:length_end
                ]
            )

        except ValueError:

            position = length_end + 3
            continue

        json_start = length_end + 3
        json_end = (
            json_start + length
        )

        if json_end > len(raw):
            break

        full_frame = raw[
            start:json_end
        ]

        payload = raw[
            json_start:json_end
        ]

        messages.append(
            (
                full_frame,
                payload
            )
        )

        position = json_end

    return (
        messages,
        raw[position:]
    )


# ============================================================
# BIST HISSelerini BUL
# ============================================================

def get_bist_symbols():

    log(
        "BIST hisse listesi TradingView'dan aliniyor..."
    )

    payload = {

        "columns": [
            "name",
            "description",
            "close",
            "currency",
            "exchange",
            "type",
            "typespecs"
        ],

        "filter": [

            {
                "left": "is_primary",
                "operation": "equal",
                "right": True
            },

            {
                "left": "typespecs",
                "operation": "has",
                "right": "common"
            },

            {
                "left": "type",
                "operation": "equal",
                "right": "stock"
            },

            {
                "left": "name",
                "operation": "nempty"
            }

        ],

        "filterOR": [],

        "ignore_unknown_fields": False,

        "options": {

            "active_symbols_only": True,
            "lang": "tr"

        },

        "price_conversion": {},

        "range": [
            0,
            1000
        ],

        "sort": {

            "sortBy": "name",
            "sortOrder": "asc"

        },

        "symbols": {

            "query": {
                "types": []
            },

            "tickers": []

        },

        "markets": [
            "turkey"
        ]

    }

    headers = {

        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/128.0 Safari/537.36",

        "Accept":
            "application/json",

        "Content-Type":
            "application/json",

        "Origin":
            "https://www.tradingview.com",

        "Referer":
            "https://www.tradingview.com/"

    }

    last_error = None

    for attempt in range(1, 4):

        try:

            response = requests.post(

                TV_SCANNER_URL,

                json=payload,

                headers=headers,

                timeout=REQUEST_TIMEOUT

            )

            log(
                "TradingView scanner HTTP: "
                + str(response.status_code)
            )

            response.raise_for_status()

            result = response.json()

            data = result.get(
                "data",
                []
            )

            symbols = []

            for item in data:

                if not isinstance(
                    item,
                    dict
                ):
                    continue

                symbol = item.get("s")

                if not symbol:
                    continue

                if symbol.startswith(
                    "BIST:"
                ):
                    symbols.append(symbol)

            symbols = sorted(
                set(symbols)
            )

            if symbols:

                log(
                    f"Toplam {len(symbols)} "
                    f"BIST hissesi bulundu."
                )

                return symbols

            raise RuntimeError(
                "TradingView bos hisse listesi dondurdu."
            )

        except Exception as e:

            last_error = e

            log(
                f"Hisse listesi hatasi "
                f"({attempt}/3): {e}"
            )

            time.sleep(
                attempt * 2
            )

    raise RuntimeError(
        "BIST hisse listesi alinamadi: "
        + str(last_error)
    )


# ============================================================
# TRADINGVIEW MUM VERISI
# ============================================================

def get_tv_candles(symbol, candle_mode="native_2h", candle_session="regular"):

    if candle_mode not in ("native_2h", "native_1h"):
        raise RuntimeError("Desteklenmeyen TradingView candle modu: " + str(candle_mode))

    ws = None

    chart_session = random_session("cs")
    quote_session = random_session("qs")

    try:

        log(
            f"    TradingView native veri ({candle_mode}): {symbol}"
        )

        # TradingView el sikma korumasi: baglantiyi kontrollu yeniden dene.
        ws = None
        for connect_attempt in range(1, 4):
            try:
                ws_headers = []
                tv_sessionid = os.getenv("TV_SESSIONID", "").strip()
                tv_sessionid_sign = os.getenv("TV_SESSIONID_SIGN", "").strip()
                if tv_sessionid:
                    cookie = "sessionid=" + tv_sessionid
                    if tv_sessionid_sign:
                        cookie += "; sessionid_sign=" + tv_sessionid_sign
                    ws_headers.append("Cookie: " + cookie)

                ws = websocket.create_connection(
                    TV_WS_URL,
                    timeout=WS_TIMEOUT,
                    origin="https://www.tradingview.com",
                    header=ws_headers
                )
                break
            except Exception as connect_error:
                error_text = str(connect_error)
                if "429" not in error_text or connect_attempt >= 3:
                    raise
                wait_seconds = 3 * connect_attempt
                log(
                    f"    TradingView 429: {symbol} | "
                    f"{wait_seconds}s sonra tekrar deneme "
                    f"({connect_attempt}/3)"
                )
                time.sleep(wait_seconds)

        if ws is None:
            raise RuntimeError("TradingView WebSocket baglantisi kurulamadi.")

        # ----------------------------------------------------
        # AUTH
        # ----------------------------------------------------

        tv_auth_token = get_tradingview_auth_token()
        ws.send(
            tv_message(
                "set_auth_token",
                [
                    tv_auth_token
                ]
            )
        )

        # ----------------------------------------------------
        # CHART SESSION
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "chart_create_session",
                [
                    chart_session,
                    ""
                ]
            )
        )

        # ----------------------------------------------------
        # QUOTE SESSION
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "quote_create_session",
                [
                    quote_session
                ]
            )
        )

        # ----------------------------------------------------
        # QUOTE FIELDS
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "quote_set_fields",
                [
                    quote_session,
                    "lp",
                    "volume",
                    "ch",
                    "chp"
                ]
            )
        )

        # ----------------------------------------------------
        # SYMBOL CONFIG
        # ----------------------------------------------------

        symbol_config = json.dumps(

            {
                "symbol": symbol,
                "adjustment": "splits",
                "session": candle_session
            },

            separators=(",", ":")

        )

        resolve_symbol = (
            "=" + symbol_config
        )

        # ----------------------------------------------------
        # QUOTE SYMBOL
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "quote_add_symbols",
                [
                    quote_session,
                    symbol,
                ]
            )
        )

        # ----------------------------------------------------
        # RESOLVE SYMBOL
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "resolve_symbol",
                [
                    chart_session,
                    "sds_sym_1",
                    resolve_symbol
                ]
            )
        )

        # ----------------------------------------------------
        # CREATE SERIES
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "create_series",
                [
                    chart_session,
                    "sds_1",
                    "s1",
                    "sds_sym_1",
                    ("120" if candle_mode == "native_2h" else "60"),
                    CANDLE_COUNT,
                    ""
                ]
            )
        )

        # TradingView chart ile aynı borsa saat dilimini kullan.
        ws.send(
            tv_message(
                "switch_timezone",
                [
                    chart_session,
                    "exchange"
                ]
            )
        )

        candles = {}
        raw_buffer = ""

        start_time = time.time()
        series_completed = False
        history_requests = 0

        while (
            time.time() - start_time
            < WS_TIMEOUT
        ):

            try:

                packet = ws.recv()

            except websocket.WebSocketTimeoutException:

                break

            except Exception as e:

                raise RuntimeError(
                    "WebSocket recv hatasi: "
                    + str(e)
                )

            if packet is None:
                break

            if isinstance(
                packet,
                bytes
            ):

                packet = packet.decode(
                    "utf-8",
                    errors="ignore"
                )

            raw_buffer += packet

            messages, raw_buffer = (
                extract_tv_messages(
                    raw_buffer
                )
            )

            for full_frame, payload in messages:

                # ------------------------------------------------
                # HEARTBEAT
                # ------------------------------------------------

                if payload.startswith("~h~"):

                    try:
                        ws.send(
                            full_frame
                        )
                    except Exception:
                        pass

                    continue

                # ------------------------------------------------
                # JSON
                # ------------------------------------------------

                try:

                    obj = json.loads(
                        payload
                    )

                except Exception:

                    continue

                method = obj.get("m")
                params = obj.get("p", [])

                # ------------------------------------------------
                # DU
                # ------------------------------------------------

                if method == "du":

                    if len(params) < 2:
                        continue

                    data_container = params[1]

                    if not isinstance(
                        data_container,
                        dict
                    ):
                        continue

                    series_data = (
                        data_container.get(
                            "sds_1"
                        )
                    )

                    if series_data is None:

                        for value in (
                            data_container.values()
                        ):

                            if isinstance(
                                value,
                                dict
                            ):

                                if "s" in value:

                                    series_data = value
                                    break

                    if not isinstance(
                        series_data,
                        dict
                    ):
                        continue

                    bars = series_data.get(
                        "s",
                        []
                    )

                    if not isinstance(
                        bars,
                        list
                    ):
                        continue

                    for bar in bars:

                        if not isinstance(
                            bar,
                            dict
                        ):
                            continue

                        values = bar.get("v")

                        if not isinstance(
                            values,
                            list
                        ):
                            continue

                        if len(values) < 5:
                            continue

                        try:

                            timestamp = float(
                                values[0]
                            )

                            open_price = float(
                                values[1]
                            )

                            high_price = float(
                                values[2]
                            )

                            low_price = float(
                                values[3]
                            )

                            close_price = float(
                                values[4]
                            )

                            volume = 0.0

                            if (
                                len(values) > 5
                                and
                                values[5] is not None
                            ):

                                try:

                                    volume = float(
                                        values[5]
                                    )

                                except Exception:

                                    volume = 0.0

                            numbers = [
                                timestamp,
                                open_price,
                                high_price,
                                low_price,
                                close_price
                            ]

                            if not all(
                                math.isfinite(x)
                                for x in numbers
                            ):
                                continue

                            if (
                                high_price <
                                low_price
                            ):
                                continue

                            candles[timestamp] = {

                                "time":
                                    timestamp,

                                "open":
                                    open_price,

                                "high":
                                    high_price,

                                "low":
                                    low_price,

                                "close":
                                    close_price,

                                "volume":
                                    volume

                            }

                        except Exception:

                            continue

                # ------------------------------------------------
                # TIMESCALE UPDATE
                # ------------------------------------------------

                elif method == "timescale_update":

                    if len(params) < 2:
                        continue

                    data_container = params[1]

                    if not isinstance(
                        data_container,
                        dict
                    ):
                        continue

                    series_data = (
                        data_container.get(
                            "sds_1"
                        )
                    )

                    if series_data is None:

                        for value in (
                            data_container.values()
                        ):

                            if isinstance(
                                value,
                                dict
                            ):

                                if "s" in value:

                                    series_data = value
                                    break

                    if not isinstance(
                        series_data,
                        dict
                    ):
                        continue

                    bars = series_data.get(
                        "s",
                        []
                    )

                    if not isinstance(
                        bars,
                        list
                    ):
                        continue

                    for bar in bars:

                        if not isinstance(
                            bar,
                            dict
                        ):
                            continue

                        values = bar.get("v")

                        if not isinstance(
                            values,
                            list
                        ):
                            continue

                        if len(values) < 5:
                            continue

                        try:

                            timestamp = float(
                                values[0]
                            )

                            open_price = float(
                                values[1]
                            )

                            high_price = float(
                                values[2]
                            )

                            low_price = float(
                                values[3]
                            )

                            close_price = float(
                                values[4]
                            )

                            volume = 0.0

                            if (
                                len(values) > 5
                                and
                                values[5] is not None
                            ):

                                volume = float(
                                    values[5]
                                )

                            candles[timestamp] = {

                                "time":
                                    timestamp,

                                "open":
                                    open_price,

                                "high":
                                    high_price,

                                "low":
                                    low_price,

                                "close":
                                    close_price,

                                "volume":
                                    volume

                            }

                        except Exception:

                            continue

                # ------------------------------------------------
                # SERIES COMPLETED
                # ------------------------------------------------

                elif method == "series_completed":

                    series_completed = True

                # ------------------------------------------------
                # HATALAR
                # ------------------------------------------------

                elif method == "symbol_error":

                    raise RuntimeError(
                        "TradingView symbol_error: "
                        + str(params)
                    )

                elif method == "series_error":

                    raise RuntimeError(
                        "TradingView series_error: "
                        + str(params)
                    )

                elif method == "critical_error":

                    raise RuntimeError(
                        "TradingView critical_error: "
                        + str(params)
                    )

            if series_completed:
                if (
                    len(candles) < HISTORY_TARGET
                    and history_requests < 3
                ):
                    history_requests += 1
                    series_completed = False
                    try:
                        ws.send(
                            tv_message(
                                "request_more_data",
                                [
                                    chart_session,
                                    "sds_1",
                                    HISTORY_REQUEST_SIZE
                                ]
                            )
                        )
                        log(
                            f"    TradingView gecmis veri genisletiliyor: "
                            f"{len(candles)} mum -> istek {history_requests}/3"
                        )
                        continue
                    except Exception:
                        pass

                if len(candles) >= 30:
                    break

        if not candles:

            raise RuntimeError(
                "TradingView mum verisi gondermedi."
            )

        result = sorted(
            candles.values(),
            key=lambda x: x["time"]
        )
        if candle_mode not in ("native_2h", "native_1h"):
            raise RuntimeError("Gecersiz TradingView native veri modu: " + str(candle_mode))

        if len(result) < 20:
            raise RuntimeError(
                "TradingView native 2H verisi yetersiz: "
                + str(len(result)) + " mum"
            )

        return result

    finally:

        if ws is not None:

            try:
                ws.close()
            except Exception:
                pass


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    candles,
    period=10
):

    if len(candles) < period:

        return [
            None
            for _ in candles
        ]

    true_ranges = []

    for i, candle in enumerate(candles):

        high = candle["high"]
        low = candle["low"]

        if i == 0:

            tr = high - low

        else:

            previous_close = (
                candles[i - 1]["close"]
            )

            tr = max(

                high - low,

                abs(
                    high -
                    previous_close
                ),

                abs(
                    low -
                    previous_close
                )

            )

        true_ranges.append(tr)

    atr = [
        None
        for _ in candles
    ]

    first_atr = (
        sum(
            true_ranges[:period]
        )
        / period
    )

    atr[period - 1] = first_atr

    for i in range(
        period,
        len(candles)
    ):

        previous_atr = (
            atr[i - 1]
        )

        if previous_atr is None:
            continue

        atr[i] = (

            (
                previous_atr *
                (period - 1)
            )

            +

            true_ranges[i]

        ) / period

    return atr


def calculate_atr_sma(candles, period=10):

    if len(candles) < period:
        return [None for _ in candles]

    tr = []
    for i, candle in enumerate(candles):
        if i == 0:
            value = candle["high"] - candle["low"]
        else:
            pc = candles[i - 1]["close"]
            value = max(
                candle["high"] - candle["low"],
                abs(candle["high"] - pc),
                abs(candle["low"] - pc)
            )
        tr.append(value)

    out = [None for _ in candles]
    for i in range(period - 1, len(candles)):
        out[i] = sum(tr[i - period + 1:i + 1]) / period
    return out


# ============================================================
# SUPERTREND YONLERI
#
#  1  = AL
# -1  = SAT
# ============================================================

def calculate_supertrend_directions(
    candles,
    atr_period=10,
    multiplier=2.0
):
    """
    TradingView/Kivanc SuperTrend formulu.
    Study kullanilmaz; yalnizca TradingView OHLC verisi kullanilir.

    Settings:
      ATR = RMA (Wilder)
      Source = HL2
      ATR length = 10
      Multiplier = 2.0

    Pine mantiginin Python karsiligi:
      up = hl2 - multiplier * ATR
      up1 = nz(up[1], up)
      up := close[1] > up1 ? max(up, up1) : up

      dn = hl2 + multiplier * ATR
      dn1 = nz(dn[1], dn)
      dn := close[1] < dn1 ? min(dn, dn1) : dn

      trend = 1
      trend := trend == -1 and close > dn1 ? 1 :
               trend == 1 and close < up1 ? -1 :
               trend

      BUY = trend == 1 and trend[1] == -1
    """

    if len(candles) < (atr_period + 2):
        return None

    atr = calculate_atr(candles, atr_period)

    up = [None for _ in candles]
    dn = [None for _ in candles]
    trend = [None for _ in candles]

    for i in range(len(candles)):
        if atr[i] is None:
            # Pine'daki "trend = 1" baslangic durumunu koru.
            trend[i] = 1 if i == 0 else trend[i - 1]
            continue

        src = (
            candles[i]["high"]
            + candles[i]["low"]
        ) / 2.0

        raw_up = src - multiplier * atr[i]
        raw_dn = src + multiplier * atr[i]

        if i == 0 or up[i - 1] is None:
            up1 = raw_up
        else:
            up1 = up[i - 1]

        if i == 0:
            up[i] = raw_up
        else:
            up[i] = (
                max(raw_up, up1)
                if candles[i - 1]["close"] > up1
                else raw_up
            )

        if i == 0 or dn[i - 1] is None:
            dn1 = raw_dn
        else:
            dn1 = dn[i - 1]

        if i == 0:
            dn[i] = raw_dn
        else:
            dn[i] = (
                min(raw_dn, dn1)
                if candles[i - 1]["close"] < dn1
                else raw_dn
            )

        previous_trend = (
            1
            if i == 0 or trend[i - 1] is None
            else trend[i - 1]
        )

        close = candles[i]["close"]

        if (
            previous_trend == -1
            and close > dn1
        ):
            trend[i] = 1
        elif (
            previous_trend == 1
            and close < up1
        ):
            trend[i] = -1
        else:
            trend[i] = previous_trend

    return trend



# ============================================================
# TRADINGVIEW RESMI SUPERTREND YONU
#
# TradingView ta.supertrend() convention:
#   -1 = UP / AL
#   +1 = DOWN / SAT
#
# Formula follows TradingView's documented Supertrend logic.
# ============================================================

def calculate_tradingview_supertrend_directions(
    candles,
    atr_period=10,
    multiplier=2.0
):
    if len(candles) < (atr_period + 2):
        return None

    atr = calculate_atr(candles, atr_period)

    upper = [None for _ in candles]
    lower = [None for _ in candles]
    direction = [None for _ in candles]

    for i in range(len(candles)):
        if atr[i] is None:
            direction[i] = 1  # TradingView: initial/down trend
            continue

        hl2 = (
            candles[i]["high"] + candles[i]["low"]
        ) / 2.0

        basic_upper = hl2 + multiplier * atr[i]
        basic_lower = hl2 - multiplier * atr[i]

        if i == 0 or upper[i - 1] is None:
            upper[i] = basic_upper
        else:
            prev_upper = upper[i - 1]
            prev_close = candles[i - 1]["close"]
            upper[i] = (
                basic_upper
                if (
                    basic_upper < prev_upper
                    or prev_close > prev_upper
                )
                else prev_upper
            )

        if i == 0 or lower[i - 1] is None:
            lower[i] = basic_lower
        else:
            prev_lower = lower[i - 1]
            prev_close = candles[i - 1]["close"]
            lower[i] = (
                basic_lower
                if (
                    basic_lower > prev_lower
                    or prev_close < prev_lower
                )
                else prev_lower
            )

        if i == 0 or direction[i - 1] is None:
            direction[i] = 1
            continue

        prev_direction = direction[i - 1]
        prev_supertrend = (
            upper[i - 1]
            if prev_direction == 1
            else lower[i - 1]
        )

        if prev_supertrend == upper[i - 1]:
            direction[i] = (
                -1 if candles[i]["close"] > upper[i] else 1
            )
        else:
            direction[i] = (
                1 if candles[i]["close"] < lower[i] else -1
            )

    return direction


# ============================================================
# TRADINGVIEW TARIHCE BASLANGICI DIAGNOSTIGI
#
# Supertrend stateful oldugu icin, TradingView chartinin
# yukledigi tarih miktari ile fark olusup olusmadigini TEST_MODE'da
# ayni veri setinin farkli tarihce pencerelerinde karsilastirir.
# ============================================================

def history_window_buy_times(candles, window_sizes=(3000, 5000, 10000, 15000, 20000)):
    if not candles:
        return {}

    results = {}

    for size in window_sizes:
        subset = candles[-size:] if len(candles) > size else candles

        directions = calculate_supertrend_directions(
            subset,
            ATR_PERIOD,
            ATR_MULTIPLIER
        )

        if not directions:
            results[size] = []
            continue

        buys = []

        for i in range(1, len(subset)):
            if (
                directions[i - 1] == -1
                and directions[i] == 1
            ):
                buys.append(subset[i]["time"])

        results[size] = buys

    return results


# ============================================================
# SON TAMAMLANMIS MUM
# ============================================================

def get_last_completed_index(
    candles
):
    """
    Native TradingView 2H serisinde BIST regular seansinin son parcali
    2H barini da tamamlanmis kabul eder.

    BIST seansi 10:00-18:00 oldugu icin 17:00 barinin gercek seans
    kapanisi 18:00'dir; 19:00'i beklemek yanlistir.
    """

    if not candles:
        return None

    now = now_istanbul()
    candidates = []

    for i, candle in enumerate(candles):
        try:
            candle_time = (
                datetime.fromtimestamp(
                    candle["time"],
                    tz=ZoneInfo("UTC")
                )
                .astimezone(
                    ZoneInfo(TIMEZONE)
                )
            )

            # TradingView session bazli barlarda son bar, seans
            # bitiminde kapanir. 17:00 -> 18:00 parcali 2H bardir.
            if (
                candle_time.hour == 17
                and candle_time.minute == 0
            ):
                candle_end = candle_time.replace(
                    hour=18,
                    minute=0,
                    second=0,
                    microsecond=0
                )
            else:
                candle_end = candle_time + timedelta(hours=2)

            if candle_end <= now:
                candidates.append(i)

        except Exception:
            continue

    if not candidates:
        return None

    return candidates[-1]


# ============================================================
# BIST SAAT KONTROLU
# ============================================================

def is_bist_open_time():

    now = now_istanbul()

    if now.weekday() >= 5:
        return False

    current_minutes = (
        now.hour * 60
        +
        now.minute
    )

    open_minutes = (
        MARKET_OPEN_HOUR * 60
        +
        MARKET_OPEN_MINUTE
    )

    close_minutes = (
        MARKET_CLOSE_HOUR * 60
        +
        MARKET_CLOSE_MINUTE
    )

    return (
        open_minutes
        <= current_minutes
        <
        close_minutes
    )


# ============================================================
# GITHUB STATE OKUMA
# ============================================================

def github_headers():

    return {

        "Authorization":
            f"Bearer {GITHUB_TOKEN}",

        "Accept":
            "application/vnd.github+json",

        "X-GitHub-Api-Version":
            "2022-11-28"

    }


def load_state():

    # TEST MODUNDA STATE OKUNABILIR
    # fakat degistirilmez.

    if (
        not GITHUB_TOKEN
        or
        not GITHUB_REPOSITORY
    ):

        log(
            "UYARI: GitHub state bilgileri yok."
        )

        return {}

    url = (
        "https://api.github.com/repos/"
        +
        GITHUB_REPOSITORY
        +
        "/contents/"
        +
        STATE_FILE
        +
        "?ref="
        +
        GITHUB_REF_NAME
    )

    try:

        response = requests.get(
            url,
            headers=github_headers(),
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 404:

            log(
                "State dosyasi henuz yok. "
                "Ilk durumlar olusturulacak."
            )

            return {}

        response.raise_for_status()

        data = response.json()

        encoded = data.get(
            "content",
            ""
        )

        if not encoded:
            return {}

        content = base64.b64decode(
            encoded
        ).decode(
            "utf-8"
        )

        state = json.loads(content)

        if not isinstance(
            state,
            dict
        ):

            return {}

        log(
            f"GitHub state okundu: "
            f"{len(state)} hisse"
        )

        return state

    except Exception as e:

        log(
            "GitHub state okuma hatasi: "
            + str(e)
        )

        return {}


# ============================================================
# GITHUB STATE KAYDET
# ============================================================

def save_state(state):

    if TEST_MODE:

        log(
            "TEST MODU: State dosyasi "
            "DEGISTIRILMEYECEK."
        )

        return

    if (
        not GITHUB_TOKEN
        or
        not GITHUB_REPOSITORY
    ):

        raise RuntimeError(
            "GitHub state icin "
            "GITHUB_TOKEN/GITHUB_REPOSITORY "
            "eksik."
        )

    # Once mevcut dosyanin SHA'sini al.
    url = (
        "https://api.github.com/repos/"
        +
        GITHUB_REPOSITORY
        +
        "/contents/"
        +
        STATE_FILE
    )

    get_response = requests.get(

        url
        +
        "?ref="
        +
        GITHUB_REF_NAME,

        headers=github_headers(),

        timeout=REQUEST_TIMEOUT

    )

    existing_sha = None

    if get_response.status_code == 200:

        existing_sha = (
            get_response.json().get(
                "sha"
            )
        )

    content = json.dumps(
        state,
        ensure_ascii=False,
        indent=2,
        sort_keys=True
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("ascii")

    payload = {

        "message":
            "Update Supertrend state",

        "content":
            encoded,

        "branch":
            GITHUB_REF_NAME

    }

    if existing_sha:

        payload["sha"] = existing_sha

    response = requests.put(

        url,

        headers=github_headers(),

        json=payload,

        timeout=REQUEST_TIMEOUT

    )

    if response.status_code not in (
        200,
        201
    ):

        raise RuntimeError(
            "GitHub state kaydedilemedi: "
            +
            str(response.status_code)
            +
            " "
            +
            response.text[:500]
        )

    log(
        "GitHub state basariyla kaydedildi."
    )


# ============================================================
# TELEGRAM
# ============================================================


# SAFE_TELEGRAM_STATE_PATCH_V1
TELEGRAM_RETRY_DELAYS = (2, 5, 10)


def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN bulunamadi."
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID bulunamadi."
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    max_length = 3900
    chunks = []
    current = ""

    for line in message.splitlines(keepends=True):

        if len(current) + len(line) > max_length:

            if current:
                chunks.append(current)

            current = line

        else:
            current += line

    if current:
        chunks.append(current)

    if not chunks:
        chunks = [""]

    for chunk_no, chunk in enumerate(chunks, 1):

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        last_error = None

        for attempt in range(len(TELEGRAM_RETRY_DELAYS) + 1):

            try:

                response = requests.post(
                    url,
                    json=payload,
                    timeout=REQUEST_TIMEOUT
                )

                if response.ok:

                    try:
                        result = response.json()
                    except Exception as exc:
                        last_error = RuntimeError(
                            "Telegram JSON cevabi okunamadi: "
                            + str(exc)
                        )
                    else:
                        if result.get("ok"):
                            last_error = None
                            break

                        last_error = RuntimeError(
                            "Telegram hatasi: "
                            + str(result)
                        )

                else:

                    try:
                        detail = response.json()
                    except Exception:
                        detail = response.text

                    last_error = RuntimeError(
                        "Telegram HTTP "
                        + str(response.status_code)
                        + ": "
                        + str(detail)
                    )

                    if response.status_code not in (
                        429, 500, 502, 503, 504
                    ):
                        raise last_error

            except requests.RequestException as exc:
                last_error = exc

            if attempt < len(TELEGRAM_RETRY_DELAYS):

                delay = TELEGRAM_RETRY_DELAYS[attempt]

                log(
                    "Telegram chunk "
                    + str(chunk_no)
                    + "/"
                    + str(len(chunks))
                    + " basarisiz; "
                    + str(delay)
                    + " saniye sonra tekrar denenecek."
                )

                time.sleep(delay)

        if last_error is not None:

            raise RuntimeError(
                "Telegram gonderilemedi (chunk "
                + str(chunk_no)
                + "/"
                + str(len(chunks))
                + "): "
                + str(last_error)
            )

        if chunk_no < len(chunks):
            time.sleep(0.3)


# ============================================================
# FIYAT FORMAT
# ============================================================

def format_price(price):

    text = f"{price:,.2f}"

    text = text.replace(
        ",",
        "X"
    )

    text = text.replace(
        ".",
        ","
    )

    text = text.replace(
        "X",
        "."
    )

    return text


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def build_telegram_message(
    results
):

    now = now_istanbul()

    lines = []

    # BASLIK TAM OLARAK BU
    lines.append(
        "TRADINGVIEW BUY SİNYALİ VEREN HİSSELER"
    )

    lines.append("")

    lines.append(
        "📊 BIST 2 SAATLİK SUPERTREND"
    )

    lines.append(
        f"ATR Periyodu: {ATR_PERIOD}"
    )

    lines.append(
        f"ATR Çarpanı: {ATR_MULTIPLIER:g}"
    )

    lines.append(
        "Kaynak: HL2 = (Yüksek + Düşük) / 2"
    )

    lines.append("")

    lines.append(
        "🕒 Tarama: "
        +
        now.strftime(
            "%d.%m.%Y %H:%M"
        )
    )

    lines.append(
        f"🟢 BUY SİNYALI: "
        f"{len(results)} adet"
    )

    lines.append("")

    for result in results:

        symbol = (
            result["symbol"]
            .replace(
                "BIST:",
                ""
            )
        )

        price = format_price(
            result["price"]
        )

        candle_dt = candle_close_datetime(result["candle_time"])

        ticker = symbol.split(":", 1)[-1]
        tradingview_url = (
            "https://www.tradingview.com/chart/"
            + "?symbol=BIST%3A"
            + ticker
            + "&interval=120"
        )

        lines.append(
            '<a href="' + tradingview_url + '">'
            + "🟢 "
            + symbol
            + "</a>   "
            + price
            + " TL"
        )

        lines.append(
            "   Mum: "
            +
            candle_dt.strftime(
                "%d.%m.%Y %H:%M"
            )
        )

    lines.append("")

    lines.append(
        "Sinyal: Yalnızca SON TAMAMLANMIŞ 2H mumunda "
        "SAT -> AL (BUY) dönüşü."
    )

    return "\n".join(lines)


def candle_close_datetime(candle_time):

    dt = (
        datetime.fromtimestamp(
            candle_time,
            tz=ZoneInfo("UTC")
        )
        .astimezone(ZoneInfo(TIMEZONE))
    )

    # BIST'in 17:00-18:00 son parcali 2H bari 18:00'de kapanir.
    if dt.hour == 17 and dt.minute == 0:
        return dt + timedelta(hours=1)

    return dt + timedelta(hours=2)


# ============================================================
# TEST TELEGRAM MESAJI
# ============================================================

def build_test_message():

    now = now_istanbul()

    return (
        "SUPERTREND AL SİNYALİ VEREN HİSSELER\n"
        "\n"
        "🧪 TEST MODU\n"
        "\n"
        "Telegram bağlantısı başarıyla "
        "çalışıyor.\n"
        "\n"
        "Tarama zamanı: "
        +
        now.strftime(
            "%d.%m.%Y %H:%M:%S"
        )
        +
        "\n"
        "\n"
        "Bu mesaj gerçek SAT → AL sinyali "
        "değildir."
    )


# ============================================================
# TRADINGVIEW KONTROLLU VERI RETRY
# ============================================================

DATA_RETRY_COUNT = 3
DATA_RETRY_DELAYS = (2, 5, 10)


def get_tv_candles_with_retry(symbol, candle_mode="native_2h", candle_session="regular"):
    """
    TradingView gecici veri/429 sorunlarinda ayni hissenin verisini
    kontrollu sekilde tekrar ister.

    Kalici veri yetersizligini sonsuza kadar denemez:
      1. deneme -> 2 sn
      2. deneme -> 5 sn
      3. deneme -> hata
    """
    last_error = None

    for attempt in range(1, DATA_RETRY_COUNT + 1):
        try:
            candles = get_tv_candles(symbol, candle_mode, candle_session)

            if candles:
                return candles

            last_error = "TradingView mum verisi gondermedi."

        except Exception as exc:
            last_error = str(exc)

        error_text = str(last_error)

        transient = (
            "429" in error_text
            or "Too Many Requests" in error_text
            or "mum verisi gondermedi" in error_text
            or "verisi yetersiz" in error_text
            or "WebSocket" in error_text
            or "timed out" in error_text
            or "timeout" in error_text.lower()
        )

        if not transient or attempt >= DATA_RETRY_COUNT:
            break

        delay = DATA_RETRY_DELAYS[attempt - 1]
        log(
            f"    TradingView gecici veri hatasi: {symbol} | "
            f"{delay}s sonra tekrar deneme ({attempt}/{DATA_RETRY_COUNT}) | "
            f"{error_text}"
        )
        time.sleep(delay)

    raise RuntimeError(last_error or "TradingView verisi alinamadi.")


# ============================================================
# TEK HISSE TARAMA
# ============================================================

def scan_symbol(
    symbol,
    state
):

    try:

        # TradingView'in kendi native 120 dakikalik serisini kullan.
        # 1H mumlari manuel olarak birlestirmiyoruz; boylece TradingView
        # grafigindeki 2H bar sinirlarini bozmayiz.
        candle_mode = "native_2h"
        candles = get_tv_candles_with_retry(symbol, candle_mode)



        if not candles:
            return {
                "status": "error",
                "symbol": symbol,
                "error": "Mum verisi yok."
            }

        # Tum gun icindeki TAMAMLANMIS 2H mumlari hesaba kat.
        # Sadece son muma bakma: gun icinde daha once olusan
        # SAT -> AL (BUY) mumlarini da yakala.
        completed_index = get_last_completed_index(candles)

        if completed_index is None or completed_index < 1:
            return {
                "status": "skip",
                "symbol": symbol,
                "error": "Tamamlanmis mum yok."
            }

        calculation_candles = candles[:completed_index + 1]

        directions = calculate_supertrend_directions(
            calculation_candles,
            ATR_PERIOD,
            ATR_MULTIPLIER
        )

        if directions is None:
            return {
                "status": "skip",
                "symbol": symbol,
                "error": "Supertrend hesaplanamadi."
            }

        if TEST_MODE:
            history_buys = history_window_buy_times(calculation_candles)
            log("    HISTORY WINDOW BUY KARSILASTIRMA | " + symbol)
            for hw in (3000, 5000, 10000, 15000, 20000):
                if hw not in history_buys:
                    continue
                times = []
                for ts in history_buys[hw][-5:]:
                    dt = datetime.fromtimestamp(
                        ts, tz=ZoneInfo("UTC")
                    ).astimezone(ZoneInfo(TIMEZONE))
                    times.append(dt.strftime("%d.%m.%Y %H:%M"))
                log("      " + str(hw) + " BAR | " + (", ".join(times) if times else "YOK"))

        # TradingView BUY kosulu:
        # onceki yon SAT (-1), sonraki yon AL (+1).
        # Gun icindeki tum tamamlanmis mumlarda ara.
        buy_signal_indexes = []

        for i in range(1, len(directions)):

            if (
                directions[i - 1] == -1
                and directions[i] == 1
            ):
                buy_signal_indexes.append(i)

        # En son tamamlanmis mumun ait oldugu BIST islem gununu kullan.
        # Manuel tarama hafta sonu yapilsa bile onceki cuma gibi
        # son islem gunundeki gun ici BUY sinyalleri taranir.
        latest_candle_dt = (
            datetime.fromtimestamp(
                calculation_candles[completed_index]["time"],
                tz=ZoneInfo("UTC")
            ).astimezone(ZoneInfo(TIMEZONE))
        )

        latest_session_date = latest_candle_dt.date()

        session_start = datetime(
            latest_session_date.year,
            latest_session_date.month,
            latest_session_date.day,
            0,
            0,
            0,
            tzinfo=ZoneInfo(TIMEZONE)
        ).timestamp()

        next_session_start = (
            session_start + 24 * 60 * 60
        )

        today_buy_indexes = [
            i
            for i in buy_signal_indexes
            if (
                session_start
                <= calculation_candles[i]["time"]
                < next_session_start
            )
        ]

        old = state.get(symbol)
        if not isinstance(old, dict):
            old = {}

        old_direction = old.get("direction")
        old_candle_time = old.get("candle_time")
        old_buy_time = old.get("last_buy_candle_time")

        # Ilk kurulumda eski state'te BUY zamani yoksa,
        # mevcut gunun BUY sinyallerini degerlendir.
        if old_buy_time is None:
            old_buy_time = 0.0
        else:
            try:
                old_buy_time = float(old_buy_time)
            except Exception:
                old_buy_time = 0.0

        # KRITIK: SADECE SON TAMAMLANMIS 2H MUMU BUY ISE SINYAL KABUL ET.
        # Gun icindeki daha eski SAT -> AL donusleri CURRENT BUY degildir.
        current_candle = calculation_candles[completed_index]
        previous_candle = calculation_candles[completed_index - 1]

        current_direction = directions[completed_index]
        previous_direction = directions[completed_index - 1]

        current_buy_signal = (
            previous_direction == -1
            and current_direction == 1
        )

        if current_buy_signal:
            if TEST_MODE:
                new_buy_indexes = [completed_index]
            else:
                new_buy_indexes = (
                    [completed_index]
                    if float(current_candle["time"]) > old_buy_time
                    else []
                )
        else:
            new_buy_indexes = []

        # TradingView Kivanc scriptindeki alternatif ATR (SMA) yolunu
        # da aynı OHLC üzerinde hesapla; hangi hesap yolunun grafikteki
        # dönüşe uyduğunu doğrudan logdan karşılaştır.
        sma_atr = calculate_atr_sma(
            calculation_candles, ATR_PERIOD
        )
        sma_dirs = [None for _ in calculation_candles]
        up_sma = [None for _ in calculation_candles]
        dn_sma = [None for _ in calculation_candles]
        tr_sma = [None for _ in calculation_candles]
        for si in range(len(calculation_candles)):
            if sma_atr[si] is None:
                tr_sma[si] = 1 if si == 0 else tr_sma[si - 1]
                continue
            src_s = (calculation_candles[si]["high"] + calculation_candles[si]["low"]) / 2.0
            ru = src_s - ATR_MULTIPLIER * sma_atr[si]
            rd = src_s + ATR_MULTIPLIER * sma_atr[si]
            if si == 0 or up_sma[si - 1] is None:
                up1_s = ru
            else:
                up1_s = up_sma[si - 1]
            up_sma[si] = max(ru, up1_s) if si > 0 and calculation_candles[si - 1]["close"] > up1_s else ru
            if si == 0 or dn_sma[si - 1] is None:
                dn1_s = rd
            else:
                dn1_s = dn_sma[si - 1]
            dn_sma[si] = min(rd, dn1_s) if si > 0 and calculation_candles[si - 1]["close"] < dn1_s else rd
            prev_s = 1 if si == 0 or tr_sma[si - 1] is None else tr_sma[si - 1]
            close_s = calculation_candles[si]["close"]
            tr_sma[si] = 1 if (prev_s == -1 and close_s > dn1_s) else (-1 if (prev_s == 1 and close_s < up1_s) else prev_s)
            sma_dirs[si] = tr_sma[si]

        # TEST MODU icin TradingView mum zamanlamasi ve
        # Supertrend gecisini birebir incelemeye yarayan tanilama.
        debug_bars = []
        debug_start = max(0, completed_index - 5)

        for debug_i in range(
            debug_start,
            completed_index + 1
        ):
            debug_dt = (
                datetime.fromtimestamp(
                    calculation_candles[debug_i]["time"],
                    tz=ZoneInfo("UTC")
                )
                .astimezone(ZoneInfo(TIMEZONE))
            )

            debug_bars.append({
                "time": debug_dt.strftime("%d.%m.%Y %H:%M"),
                "open": calculation_candles[debug_i]["open"],
                "high": calculation_candles[debug_i]["high"],
                "low": calculation_candles[debug_i]["low"],
                "close": calculation_candles[debug_i]["close"],
                "direction": directions[debug_i],
                "buy": (
                    debug_i in buy_signal_indexes
                ),
                "sma_direction": sma_dirs[debug_i] if debug_i < len(sma_dirs) else None,
                "sma_buy": (
                    debug_i > 0 and debug_i < len(sma_dirs)
                    and sma_dirs[debug_i - 1] == -1
                    and sma_dirs[debug_i] == 1
                )
            })

        # State'e yalnizca SON TAMAMLANMIS mumdaki BUY'i kaydet.
        # Eski gun ici BUY'ler tekrar current signal olarak kullanilmaz.
        latest_buy_time = None

        if current_buy_signal:
            latest_buy_time = current_candle["time"]

        buy_results = []

        for i in new_buy_indexes:
            buy_results.append({
                "status": "new_buy",
                "symbol": symbol,
                "price": calculation_candles[i]["close"],
                "candle_time": calculation_candles[i]["time"],
                "direction": 1,
                "previous_direction": -1,
                "buy_signal": True,
                "previous_candle_time": calculation_candles[i - 1]["time"]
            })

        # Manuel rapor icin SADECE SON TAMAMLANMIS mumdaki BUY'i goster.
        all_buy_results = []

        if current_buy_signal:
            candle_time = float(current_candle["time"])
            already_sent = candle_time <= float(old_buy_time)

            all_buy_results.append({
                "status": "previously_sent" if already_sent else "new_buy",
                "symbol": symbol,
                "price": current_candle["close"],
                "candle_time": current_candle["time"],
                "direction": 1,
                "previous_direction": -1,
                "buy_signal": True,
                "previous_candle_time": previous_candle["time"],
                "already_sent": already_sent
            })

        new_buy = bool(buy_results)

        if old:
            if new_buy:
                log(
                    f"    >>> {len(buy_results)} YENI BUY: "
                    + ", ".join(
                        datetime.fromtimestamp(
                            r["candle_time"],
                            tz=ZoneInfo("UTC")
                        ).astimezone(ZoneInfo(TIMEZONE)).strftime("%H:%M")
                        for r in buy_results
                    )
                )
            elif old_direction == -1 and current_direction == -1:
                log("    SAT -> SAT")
            elif old_direction == 1 and current_direction == 1:
                log("    AL -> AL")
            elif old_direction == 1 and current_direction == -1:
                log("    >>> YENI SAT")
            else:
                log("    Durum degismedi.")
        else:
            log(
                f"    Ilk durum: "
                f"{'AL' if current_direction == 1 else 'SAT'}"
            )

        return {
            "status": "new_buy" if new_buy else "ok",
            "symbol": symbol,
            "price": current_candle["close"],
            "candle_time": current_candle["time"],
            "direction": current_direction,
            "previous_direction": previous_direction,
            "buy_signal": current_buy_signal,
            "previous_candle_time": previous_candle["time"],
            "buy_results": buy_results,
            "all_buy_results": all_buy_results,
            "latest_buy_time": latest_buy_time,
            "debug_bars": debug_bars
        }

    except Exception as e:

        log(
            f"    {symbol} -> hata: {e}"
        )

        return {
            "status": "error",
            "symbol": symbol,
            "error": str(e)
        }


# ============================================================
# STATE'E YENI DURUMU YAZ
# ============================================================

def update_state(
    state,
    result
):

    if result.get("status") not in (
        "ok",
        "new_buy"
    ):
        return

    symbol = result["symbol"]

    old = state.get(symbol)
    if not isinstance(old, dict):
        old = {}

    new_state = {
        "direction": result["direction"],
        "candle_time": result["candle_time"],
        "updated_at": now_istanbul().isoformat()
    }

    # Son yakalanmis BUY mumunu ayri sakla.
    # Boylece ayni gun icindeki daha eski BUY tekrar gonderilmez.
    previous_buy_time = old.get("last_buy_candle_time")
    latest_buy_time = result.get("latest_buy_time")

    if latest_buy_time is not None:
        try:
            latest_buy_time = float(latest_buy_time)
            if (
                previous_buy_time is None
                or latest_buy_time > float(previous_buy_time)
            ):
                new_state["last_buy_candle_time"] = latest_buy_time
            else:
                new_state["last_buy_candle_time"] = float(previous_buy_time)
        except Exception:
            if previous_buy_time is not None:
                new_state["last_buy_candle_time"] = previous_buy_time
    elif previous_buy_time is not None:
        new_state["last_buy_candle_time"] = previous_buy_time

    state[symbol] = new_state



# ============================================================
# MEVCUT AL DURUMU RAPORU
# ============================================================

def build_current_report_message(results):

    now = now_istanbul()

    lines = [
        "TRADINGVIEW BUY SINYALLERI",
        "",
        "📊 BIST 2 SAATLİK SUPERTREND",
        "ATR Periyodu: " + str(ATR_PERIOD),
        "ATR Çarpanı: " + f"{ATR_MULTIPLIER:g}",
        "Kaynak: HL2 = (Yüksek + Düşük) / 2",
        "",
        "🕒 Tarama: " + now.strftime("%d.%m.%Y %H:%M"),
        f"🟢 BUY SINYALI: {len(results)} adet",
        "",
    ]

    for result in results:

        symbol = result["symbol"]
        price = format_price(result["price"])

        ticker = symbol.split(":", 1)[-1]
        tradingview_url = (
            "https://www.tradingview.com/chart/"
            + "?symbol=BIST%3A"
            + ticker
            + "&interval=120"
        )

        lines.append(
            '<a href="' + tradingview_url + '">'
            + "🟢 "
            + symbol
            + "</a>   "
            + price
            + " TL"
        )

        candle_dt = (
            datetime.fromtimestamp(
                result["candle_time"],
                tz=ZoneInfo("UTC")
            ).astimezone(
                ZoneInfo(TIMEZONE)
            )
        )

        lines.append(
            "   Mum: " + candle_dt.strftime("%d.%m.%Y %H:%M")
        )

    lines.append("")
    lines.append("Bu rapor yalnızca son tamamlanmış 2H mumunda BUY etiketi oluşanları gösterir.")
    lines.append("Ayarlar: ATR 10 | HL2 | 2.0 | RMA | 2H")

    return "\n".join(lines)


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    log("")
    log("=" * 70)
    log(
        "BIST SUPERTREND FINAL TARAMASI BASLADI"
    )
    log("=" * 70)

    current_time = now_istanbul()

    log(
        "Turkiye saati: "
        +
        current_time.strftime(
            "%d.%m.%Y %H:%M:%S"
        )
    )

    # --------------------------------------------------------
    # TEST MODU
    # --------------------------------------------------------

    if TEST_MODE:

        log(
            "========================================"
        )

        log(
            "TEST MODU AKTIF"
        )

        log(
            "BIST saat kontrolu BYPASS edildi."
        )

        log(
            "Test hisseleri: "
            +
            ", ".join(TEST_SYMBOLS)
        )

        log(
            "========================================"
        )

        if SEND_TEST_TELEGRAM:

            log(
                "Telegram test mesaji gonderiliyor..."
            )

            send_telegram(
                build_test_message()
            )

            log(
                "Telegram test mesaji basariyla gonderildi."
            )

        # TEST MODU sadece baglantiyi ve
        # Supertrend sonucunu kontrol eder.
        #
        # State degistirilmez.

        test_state = load_state()

        success = 0
        errors = 0

        for symbol in TEST_SYMBOLS:

            log("")
            log(
                f"[TEST] {symbol}"
            )

            result = scan_symbol(
                symbol,
                test_state
            )

            if result.get("status") == "error":

                errors += 1

                log(
                    "    TEST HATASI: "
                    +
                    str(
                        result.get(
                            "error"
                        )
                    )
                )

            else:

                success += 1

                direction = result.get(
                    "direction"
                )

                debug_bars = result.get(
                    "debug_bars",
                    []
                )

                for debug_bar in debug_bars:
                    log(
                        "    MUM | "
                        + debug_bar["time"]
                        + " | O="
                        + format_price(debug_bar["open"])
                        + " H="
                        + format_price(debug_bar["high"])
                        + " L="
                        + format_price(debug_bar["low"])
                        + " C="
                        + format_price(debug_bar["close"])
                        + " | ST="
                        + str(debug_bar["direction"])
                        + " | BUY="
                        + str(debug_bar["buy"])
                        + " | SMA_ST="
                        + str(debug_bar["sma_direction"])
                        + " | SMA_BUY="
                        + str(debug_bar["sma_buy"])
                    )

                if direction == 1:

                    log(
                        "    TEST SONUCU: AL"
                    )

                elif direction == -1:

                    log(
                        "    TEST SONUCU: SAT"
                    )

                else:

                    log(
                        "    TEST SONUCU: BELIRSIZ"
                    )

        log("")
        log(
            "TEST MODU TAMAMLANDI."
        )

        log(
            f"Basarili: {success}"
        )

        log(
            f"Hata: {errors}"
        )

        return

    # --------------------------------------------------------
    # NORMAL MOD
    # --------------------------------------------------------

    if not FORCE_SCAN and not is_bist_open_time():

        log(
            "BIST normal islem saatleri disinda."
        )

        log(
            "Tarama yapilmayacak."
        )

        return

    if FORCE_SCAN:

        log(
            "MANUEL TARAMA: BIST saat kontrolu BYPASS edildi."
        )

    # --------------------------------------------------------
    # TELEGRAM KONTROL
    # --------------------------------------------------------

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN bulunamadi."
        )

    if not TELEGRAM_CHAT_ID:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID bulunamadi."
        )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # BIST HISSELERI
    # --------------------------------------------------------

    symbols = get_bist_symbols()

    if SCAN_LIMIT > 0:
        symbols = symbols[:SCAN_LIMIT]

    total = len(symbols)

    log(
        f"Toplam {total} hisse taranacak."
    )

    log(
        "Supertrend ayarlari:"
    )

    log(
        f"ATR Period = {ATR_PERIOD}"
    )

    log(
        f"ATR Multiplier = {ATR_MULTIPLIER}"
    )

    log(
        "Source = HL2"
    )

    log(
        "Timeframe = 2H"
    )

    log(
        "Alarm = SAT -> AL"
    )

    log("")

    new_buy_results = []
    current_buy_signal_results = []
    existing_buy_results = []
    previously_sent_buy_results = []

    success_count = 0
    error_count = 0

    # --------------------------------------------------------
    # TARAMA
    # --------------------------------------------------------
    # TradingView baglantilari paralel calisir. State guncellemesi
    # sonuclar geldikten sonra tek thread'de yapilir.

    # TradingView 429 baskisini azaltmak icin kontrollu paralellik.
    scan_workers = 5
    scan_results = []

    scan_started = time.time()

    with ThreadPoolExecutor(max_workers=scan_workers) as executor:
        future_map = {
            executor.submit(scan_symbol, symbol, state): (number, symbol)
            for number, symbol in enumerate(symbols, start=1)
        }

        for future in as_completed(future_map):
            number, symbol = future_map[future]

            try:
                result = future.result()
            except Exception as e:
                result = {
                    "status": "error",
                    "symbol": symbol,
                    "error": str(e)
                }

            scan_results.append((number, symbol, result))

    # Sonuclari hisse sirasina gore isle; state yazimi deterministic kalir.
    scan_results.sort(key=lambda x: x[0])

    for number, symbol, result in scan_results:

        status = result.get("status")

        if status == "error":
            error_count += 1
            log(f"[{number}/{total}] {symbol} -> HATA: {result.get('error')}")
            continue

        success_count += 1

        buy_results = result.get("buy_results", [])
        all_buy_results = result.get("all_buy_results", [])

        for buy_result in all_buy_results:
            if buy_result.get("already_sent"):
                previously_sent_buy_results.append(buy_result)
            else:
                existing_buy_results.append(buy_result)

        if buy_results:
            new_buy_results.extend(buy_results)
            current_buy_signal_results.extend(buy_results)

            for buy_result in buy_results:
                log(
                    f"[{number}/{total}] {symbol} >>>>>> YENI BUY <<<<<< "
                    + candle_close_datetime(buy_result["candle_time"]).strftime("%d.%m.%Y %H:%M")
                    + " KAPANIS"
                )

        update_state(state, result)

    # --------------------------------------------------------
    # SONUCLAR
    # --------------------------------------------------------

    new_buy_results.sort(
        key=lambda x:
            x["symbol"]
    )

    log("")
    log("=" * 70)

    log(
        "TARAMA TAMAMLANDI"
    )

    log(
        f"Toplam hisse: {total}"
    )

    log(
        f"Basarili cevap: {success_count}"
    )

    log(
        f"Hata: {error_count}"
    )

    log(
        f"YENI SAT -> AL: "
        f"{len(new_buy_results)}"
    )

    # Manuel taramada BUY durumlarini acikca ayir.
    if FORCE_SCAN:
        all_current_buys = (
            existing_buy_results
            +
            previously_sent_buy_results
        )

        log("")
        log("MANUEL TARAMA BUY RAPORU")
        log(f"MEVCUT BUY: {len(all_current_buys)}")

        for item in sorted(all_current_buys, key=lambda x: x["symbol"]):
            dt = datetime.fromtimestamp(
                item["candle_time"], tz=ZoneInfo("UTC")
            ).astimezone(ZoneInfo(TIMEZONE))

            if item.get("already_sent"):
                label = "DAHA ONCE GONDERILDI"
            else:
                label = "YENI"

            log(
                f"    MEVCUT BUY | {item['symbol']} | "
                f"{dt.strftime('%d.%m.%Y %H:%M')} | {label}"
            )

        log(
            f"DAHA ONCE TELEGRAM'A GONDERILEN BUY: "
            f"{len(previously_sent_buy_results)}"
        )

        log(
            f"YENI BUY: {len(new_buy_results)}"
        )

        for item in sorted(new_buy_results, key=lambda x: x["symbol"]):
            dt = datetime.fromtimestamp(
                item["candle_time"], tz=ZoneInfo("UTC")
            ).astimezone(ZoneInfo(TIMEZONE))

            log(
                f"    YENI BUY | {item['symbol']} | "
                f"{dt.strftime('%d.%m.%Y %H:%M')} | "
                f"TELEGRAM'A GONDERILECEK"
            )

    log("=" * 70)

    # --------------------------------------------------------
    # SADECE TRADINGVIEW BUY RAPORU MODU
    # --------------------------------------------------------
    # SEND_SCAN_REPORT=true iken yalnızca son tamamlanmış 2H mumunda
    # gerçek BUY sinyali bulunan hisseler Telegram'a gönderilir.
    if SEND_SCAN_REPORT:

        if current_buy_signal_results:

            send_telegram(
                build_telegram_message(
                    current_buy_signal_results
                )
            )

            log(
                "Sadece yeni TradingView BUY sinyalleri Telegram'a gönderildi."
            )

        else:

            log(
                "Yeni TradingView BUY sinyali yok; Telegram gönderilmeyecek."
            )

        save_state(state)

        log("BUY raporu modu tamamlandı.")
        return

    # --------------------------------------------------------
    # STATE KAYDET
    # --------------------------------------------------------

    # --------------------------------------------------------
    # YENI AL YOK
    # --------------------------------------------------------

    if not new_buy_results:

        save_state(
            state
        )

        log(
            "Son taramada yeni "
            "SAT -> AL donusu bulunamadi."
        )

        log(
            "Telegram mesaji GONDERILMEYECEK."
        )

        log(
            "PROGRAM BASARIYLA TAMAMLANDI."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    # Yeni AL varsa once Telegram basarili olmali.
    # Telegram basarisiz olursa save_state calismaz.
    # Boylece sonraki taramada sinyal yeniden yakalanabilir.

    message = build_telegram_message(
        new_buy_results
    )

    send_telegram(
        message
    )

    # Telegram basarili olduktan sonra state kaydedilir.
    save_state(
        state
    )

    log(
        "Telegram bildirimi basariyla gonderildi."
    )

    log(
        "PROGRAM BASARIYLA TAMAMLANDI."
    )


# ============================================================
# BASLAT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        log("")
        log("=" * 70)
        log(
            "PROGRAM HATASI"
        )
        log("=" * 70)
        log(
            str(e)
        )
        log("=" * 70)

        raise