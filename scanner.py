# ============================================================
# BIST SUPERTREND ALARM SISTEMI
# SURUM 2 - FINAL
# ============================================================
#
# OZELLIKLER
#
# 1) Tum BIST hisselerini TradingView Scanner ile bulur
# 2) TradingView WebSocket ile 2 saatlik mumlari alir
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
CANDLE_COUNT = 5000

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

# SAFE_MANUAL_SCAN_PATCH_V2
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

def get_tv_candles(symbol):

    ws = None

    chart_session = random_session("cs")
    quote_session = random_session("qs")

    try:

        log(
            f"    TradingView veri baglantisi: {symbol}"
        )

        # SAFE_WEBSOCKET_PATCH_V3
        ws = websocket.create_connection(

            TV_WS_URL,

            timeout=WS_TIMEOUT,

            origin="https://www.tradingview.com"

        )

        # ----------------------------------------------------
        # AUTH
        # ----------------------------------------------------

        ws.send(
            tv_message(
                "set_auth_token",
                [
                    "unauthorized_user_token"
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
                "session": "regular"
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
                    symbol
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
                    TIMEFRAME,
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

            if (
                len(candles) >= 30
                and
                series_completed
            ):
                break

        if not candles:

            raise RuntimeError(
                "TradingView mum verisi gondermedi."
            )

        result = sorted(
            candles.values(),
            key=lambda x: x["time"]
        )

        if len(result) < 20:

            raise RuntimeError(
                "TradingView'dan sadece "
                + str(len(result))
                + " mum geldi."
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

    if len(candles) < (
        atr_period + 5
    ):
        return None

    atr = calculate_atr(
        candles,
        atr_period
    )

    up_band = [
        None
        for _ in candles
    ]

    down_band = [
        None
        for _ in candles
    ]

    direction = [
        None
        for _ in candles
    ]

    # TradingView / KivancOzbilgic Supertrend:
    # changeATR = true -> Wilder RMA ATR
    # Source = HL2
    # 1 = AL / UpTrend
    # -1 = SAT / DownTrend

    first = atr_period - 1

    if atr[first] is None:
        return None

    hl2 = (
        candles[first]["high"]
        + candles[first]["low"]
    ) / 2.0

    up_band[first] = (
        hl2
        - multiplier * atr[first]
    )

    down_band[first] = (
        hl2
        + multiplier * atr[first]
    )

    # Kivanc script starts with trend = 1.
    direction[first] = 1

    for i in range(
        first + 1,
        len(candles)
    ):

        if atr[i] is None:
            continue

        high = candles[i]["high"]
        low = candles[i]["low"]

        src = (
            high + low
        ) / 2.0

        basic_up = (
            src
            - multiplier * atr[i]
        )

        basic_down = (
            src
            + multiplier * atr[i]
        )

        prev_close = candles[i - 1]["close"]

        prev_up = up_band[i - 1]

        prev_down = down_band[i - 1]

        if prev_up is None:
            prev_up = basic_up

        if prev_down is None:
            prev_down = basic_down

        # up := close[1] > up1 ? max(up, up1) : up
        if prev_close > prev_up:
            up_band[i] = max(
                basic_up,
                prev_up
            )
        else:
            up_band[i] = basic_up

        # dn := close[1] < dn1 ? min(dn, dn1) : dn
        if prev_close < prev_down:
            down_band[i] = min(
                basic_down,
                prev_down
            )
        else:
            down_band[i] = basic_down

        prev_direction = direction[i - 1]

        if prev_direction is None:
            prev_direction = 1

        close = candles[i]["close"]

        # EXACT Kivanc condition:
        # trend == -1 and close > dn1 -> AL
        # trend ==  1 and close < up1 -> SAT
        if (
            prev_direction == -1
            and close > prev_down
        ):
            direction[i] = 1

        elif (
            prev_direction == 1
            and close < prev_up
        ):
            direction[i] = -1

        else:
            direction[i] = prev_direction

    return direction


# ============================================================
# SON TAMAMLANMIS MUM
# ============================================================

def get_last_completed_index(
    candles
):

    if not candles:
        return None

    now = now_istanbul()

    timeframe_seconds = (
        2 * 60 * 60
    )

    candidates = []

    for i, candle in enumerate(
        candles
    ):

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

            # TradingView BIST regular sessioninde 2H barlar
            # son seansta 17:00'de baslayabilir ve 18:00'de biter.
            # Bu son bar nominal olarak 2 saatlik degildir.
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
                candle_end = (
                    candle_time
                    +
                    timedelta(
                        seconds=timeframe_seconds
                    )
                )

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

        candle_dt = (
            datetime.fromtimestamp(
                result["candle_time"],
                tz=ZoneInfo("UTC")
            )
            .astimezone(
                ZoneInfo(TIMEZONE)
            )
        )

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
        "Sinyal: Önceki tamamlanmış "
        "2H mum SAT, son tamamlanmış "
        "2H mum AL."
    )

    return "\n".join(lines)


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
# TEK HISSE TARAMA
# ============================================================

def scan_symbol(
    symbol,
    state
):

    try:

        candles = get_tv_candles(
            symbol
        )

        if not candles:

            return {
                "status": "error",
                "symbol": symbol,
                "error":
                    "Mum verisi yok."
            }

        # ----------------------------------------------------
        # SON TAMAMLANMIS MUM
        # ----------------------------------------------------

        completed_index = (
            get_last_completed_index(
                candles
            )
        )

        if completed_index is None:

            return {
                "status": "skip",
                "symbol": symbol,
                "error":
                    "Tamamlanmis mum yok."
            }

        # En az onceki mum da olmali
        if completed_index < 1:

            return {
                "status": "skip",
                "symbol": symbol,
                "error":
                    "Onceki mum yok."
            }

        calculation_candles = (
            candles[
                :completed_index + 1
            ]
        )

        directions = (
            calculate_supertrend_directions(

                calculation_candles,

                ATR_PERIOD,

                ATR_MULTIPLIER

            )
        )

        if directions is None:

            return {
                "status": "skip",
                "symbol": symbol,
                "error":
                    "Supertrend hesaplanamadi."
            }

        # ----------------------------------------------------
        # SON IKI TAMAMLANMIS MUM
        # ----------------------------------------------------

        current_direction = (
            directions[
                completed_index
            ]
        )

        previous_direction = None

        # Onceki gecerli direction'i bul
        for i in range(
            completed_index - 1,
            -1,
            -1
        ):

            if directions[i] is not None:

                previous_direction = (
                    directions[i]
                )

                break

        if current_direction is None:

            return {
                "status": "skip",
                "symbol": symbol,
                "error":
                    "Son yon bulunamadi."
            }

        if previous_direction is None:

            return {
                "status": "skip",
                "symbol": symbol,
                "error":
                    "Onceki yon bulunamadi."
            }

        current_candle = (
            calculation_candles[
                completed_index
            ]
        )

        previous_candle = (
            calculation_candles[
                completed_index - 1
            ]
        )

        # ----------------------------------------------------
        # DEBUG: TEST MODU
        # ----------------------------------------------------
        if TEST_MODE:
            debug_atr = calculate_atr(
                calculation_candles,
                ATR_PERIOD
            )

            debug_up = [None for _ in calculation_candles]
            debug_dn = [None for _ in calculation_candles]

            debug_first = ATR_PERIOD - 1

            if (
                debug_first < len(calculation_candles)
                and debug_atr[debug_first] is not None
            ):
                debug_src = (
                    calculation_candles[debug_first]["high"]
                    + calculation_candles[debug_first]["low"]
                ) / 2.0

                debug_up[debug_first] = (
                    debug_src
                    - ATR_MULTIPLIER * debug_atr[debug_first]
                )

                debug_dn[debug_first] = (
                    debug_src
                    + ATR_MULTIPLIER * debug_atr[debug_first]
                )

                for debug_i in range(
                    debug_first + 1,
                    len(calculation_candles)
                ):
                    if debug_atr[debug_i] is None:
                        continue

                    debug_src = (
                        calculation_candles[debug_i]["high"]
                        + calculation_candles[debug_i]["low"]
                    ) / 2.0

                    debug_basic_up = (
                        debug_src
                        - ATR_MULTIPLIER * debug_atr[debug_i]
                    )

                    debug_basic_dn = (
                        debug_src
                        + ATR_MULTIPLIER * debug_atr[debug_i]
                    )

                    debug_prev_close = calculation_candles[debug_i - 1]["close"]
                    debug_prev_up = debug_up[debug_i - 1]
                    debug_prev_dn = debug_dn[debug_i - 1]

                    if debug_prev_up is None:
                        debug_prev_up = debug_basic_up

                    if debug_prev_dn is None:
                        debug_prev_dn = debug_basic_dn

                    debug_up[debug_i] = (
                        max(debug_basic_up, debug_prev_up)
                        if debug_prev_close > debug_prev_up
                        else debug_basic_up
                    )

                    debug_dn[debug_i] = (
                        min(debug_basic_dn, debug_prev_dn)
                        if debug_prev_close < debug_prev_dn
                        else debug_basic_dn
                    )

            log("    ===== DEBUG SUPERTREND =====")
            log(
                f"    DEBUG tamamlanmis_index={completed_index} "
                f"mum_sayisi={len(calculation_candles)}"
            )

            debug_start = max(0, completed_index - 5)

            for debug_i in range(
                debug_start,
                completed_index + 1
            ):
                debug_candle = calculation_candles[debug_i]
                debug_dt = (
                    datetime.fromtimestamp(
                        debug_candle["time"],
                        tz=ZoneInfo("UTC")
                    )
                    .astimezone(ZoneInfo(TIMEZONE))
                )

                log(
                    f"    DEBUG {debug_dt.strftime('%d.%m.%Y %H:%M')} | "
                    f"O={debug_candle['open']:.4f} "
                    f"H={debug_candle['high']:.4f} "
                    f"L={debug_candle['low']:.4f} "
                    f"C={debug_candle['close']:.4f} "
                    f"ATR={debug_atr[debug_i]:.6f}"
                    if debug_atr[debug_i] is not None
                    else
                    f"    DEBUG {debug_dt.strftime('%d.%m.%Y %H:%M')} | "
                    f"O={debug_candle['open']:.4f} "
                    f"H={debug_candle['high']:.4f} "
                    f"L={debug_candle['low']:.4f} "
                    f"C={debug_candle['close']:.4f} ATR=None"
                )

                if debug_atr[debug_i] is not None:
                    log(
                        f"    DEBUG direction={directions[debug_i]} "
                        f"up={debug_up[debug_i]:.6f} "
                        f"dn={debug_dn[debug_i]:.6f}"
                    )

            log(
                f"    DEBUG PREV_DIRECTION={previous_direction} "
                f"CURRENT_DIRECTION={current_direction}"
            )
            log("    ===== DEBUG SUPERTREND BITTI =====")

        # ----------------------------------------------------
        # TRADINGVIEW BUY SINYALI
        #
        # Bu, son tamamlanmis 2H mumunda TradingView
        # Supertrend BUY etiketinin kosuludur.
        # State'ten bagimsiz hesaplanir.
        # ----------------------------------------------------

        buy_signal = (
            previous_direction == -1
            and current_direction == 1
        )

        # ----------------------------------------------------
        # GITHUB'TAN ONCEKI DURUM
        # ----------------------------------------------------

        old = state.get(
            symbol
        )

        old_direction = None
        old_candle_time = None

        if isinstance(
            old,
            dict
        ):

            old_direction = old.get(
                "direction"
            )

            old_candle_time = old.get(
                "candle_time"
            )

        # ----------------------------------------------------
        # GERCEK SAT -> AL
        #
        # Onceki taramada SAT
        # Simdiki tamamlanmis mum AL
        #
        # Ayrica mum zamani ilerlemis olmali.
        # ----------------------------------------------------

        new_buy = (

            old_direction == -1

            and

            current_direction == 1

            and

            (
                old_candle_time is None
                or
                float(
                    current_candle["time"]
                )
                >
                float(
                    old_candle_time
                )
            )

        )

        # ----------------------------------------------------
        # ILK KEZ GORULEN HISSE
        #
        # Ilk calismada AL ise alarm verme.
        # Sadece mevcut durumu kaydet.
        # ----------------------------------------------------

        first_seen = (
            old is None
        )

        if first_seen:

            log(
                f"    Ilk durum: "
                f"{'AL' if current_direction == 1 else 'SAT'}"
            )

        elif new_buy:

            log(
                "    >>> YENI SAT -> AL <<<"
            )

        else:

            if (
                old_direction == -1
                and
                current_direction == -1
            ):

                log(
                    "    SAT -> SAT"
                )

            elif (
                old_direction == 1
                and
                current_direction == 1
            ):

                log(
                    "    AL -> AL"
                )

            elif (
                old_direction == 1
                and
                current_direction == -1
            ):

                log(
                    "    >>> YENI SAT"
                )

            else:

                log(
                    "    Durum degismedi."
                )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        return {

            "status":
                "new_buy"
                if new_buy
                else "ok",

            "symbol":
                symbol,

            "price":
                current_candle["close"],

            "candle_time":
                current_candle["time"],

            "direction":
                current_direction,

            "previous_direction":
                previous_direction,

            "buy_signal":
                buy_signal,

            "previous_candle_time":
                previous_candle["time"]

        }

    except Exception as e:

        log(
            f"    {symbol} -> hata: {e}"
        )

        return {

            "status":
                "error",

            "symbol":
                symbol,

            "error":
                str(e)

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

    state[symbol] = {

        "direction":
            result["direction"],

        "candle_time":
            result["candle_time"],

        "updated_at":
            now_istanbul().isoformat()

    }



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

    success_count = 0
    error_count = 0

    # --------------------------------------------------------
    # TARAMA
    # --------------------------------------------------------

    for number, symbol in enumerate(
        symbols,
        start=1
    ):

        log(
            f"[{number}/{total}] {symbol}"
        )

        result = scan_symbol(
            symbol,
            state
        )

        status = result.get(
            "status"
        )

        if status == "error":

            error_count += 1

            log(
                "    >>> HATA"
            )

            continue

        success_count += 1

        # Sadece son tamamlanmis 2H mumunda gercek
        # TradingView BUY kosulu olusanlari rapora al.
        if result.get("buy_signal") is True:
            current_buy_signal_results.append(result)

        if status == "new_buy":

            new_buy_results.append(
                result
            )

            log(
                "    >>>>>> YENI SAT -> AL <<<<<<"
            )

            log(
                "    Fiyat: "
                +
                f"{result['price']:.2f} TL"
            )

        # ----------------------------------------------------
        # STATE GUNCELLE
        # ----------------------------------------------------

        update_state(
            state,
            result
        )

        time.sleep(
            SYMBOL_DELAY
        )

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
                "Sadece TradingView BUY sinyalleri Telegram'a gönderildi."
            )

        else:

            log(
                "Son tamamlanmış 2H mumunda TradingView BUY sinyali bulunamadı."
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
