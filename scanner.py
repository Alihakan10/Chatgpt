# ============================================================
# BIST SUPERTREND ALARM SISTEMI
# SURUM 2
# GERCEK SAT -> AL DONUSU
# ============================================================
#
# OZELLIKLER
#
# 1) BIST hisselerini TradingView Scanner ile otomatik bulur
# 2) TradingView WebSocket ile 2 saatlik mumlari alir
# 3) Supertrend:
#       ATR Period    = 10
#       Source        = HL2
#       Multiplier    = 2
#       Timeframe     = 2H
# 4) SADECE gercek SAT -> AL donuslerini yakalar
# 5) Son tamamlanmis 2 saatlik mum kullanilir
# 6) Telegram bildirimi gonderir
# 7) Telegram 4096 karakter siniri icin mesajlari boler
# 8) TEST_MODE ile once tek hisse test edilebilir
#
# GERCEK AL:
#
#       ONCEKI MUM       SON MUM
#          SAT     ->       AL
#          -1      ->       +1
#
# BUY trendinde kalmis hisseler bildirilmez.
#
# ============================================================

import os
import json
import time
import random
import string
import math
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

CANDLE_COUNT = 150


# ------------------------------------------------------------
# TEST MODU
# ------------------------------------------------------------
#
# ILK TESTTE:
#
# TEST_MODE = True
#
# Sadece TEST_SYMBOLS icindeki hisseler taranir.
#
# Ornek:
# BIST:ZOREN
#
# Test basarili olduktan sonra:
#
# TEST_MODE = False
#
# yapilarak tum BIST taranir.
#
# ------------------------------------------------------------

TEST_MODE = True

TEST_SYMBOLS = [
    "BIST:ZOREN"
]


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

SYMBOL_DELAY = 0.10


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

# Telegram maksimum mesaj uzunlugu
TELEGRAM_MAX_LENGTH = 4000


# ------------------------------------------------------------
# BIST ISLEM SAATLERI
# ------------------------------------------------------------

MARKET_OPEN_HOUR = 10
MARKET_OPEN_MINUTE = 0

MARKET_CLOSE_HOUR = 18
MARKET_CLOSE_MINUTE = 0


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
        prefix +
        "_" +
        "".join(
            random.choice(chars)
            for _ in range(12)
        )
    )


# ============================================================
# TRADINGVIEW MESAJI
# ============================================================

def tv_message(method, params):

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
            json_start +
            length
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
# BIST HISSelerini OTOMATIK BUL
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

                symbol = item.get(
                    "s"
                )

                if not symbol:
                    continue

                if symbol.startswith(
                    "BIST:"
                ):

                    symbols.append(
                        symbol
                    )

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

    chart_session = random_session(
        "cs"
    )

    quote_session = random_session(
        "qs"
    )

    try:

        log(
            f"    TradingView veri baglantisi: {symbol}"
        )

        # ----------------------------------------------------
        # WEBSOCKET
        # ----------------------------------------------------

        ws = websocket.create_connection(

            TV_WS_URL,

            timeout=WS_TIMEOUT,

            origin="https://data.tradingview.com"

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
                "adjustment": "splits"
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

        candles = {}

        raw_buffer = ""

        start_time = time.time()

        series_completed = False

        # ----------------------------------------------------
        # VERI BEKLE
        # ----------------------------------------------------

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

                if payload.startswith(
                    "~h~"
                ):

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

                method = obj.get(
                    "m"
                )

                params = obj.get(
                    "p",
                    []
                )

                # ------------------------------------------------
                # DU
                # ------------------------------------------------

                if method == "du":

                    if len(params) < 2:
                        continue

                    data_container = (
                        params[1]
                    )

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

                        values = bar.get(
                            "v"
                        )

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

                            if not all(
                                math.isfinite(x)
                                for x in [
                                    timestamp,
                                    open_price,
                                    high_price,
                                    low_price,
                                    close_price
                                ]
                            ):

                                continue

                            if high_price < low_price:
                                continue

                            candles[
                                timestamp
                            ] = {

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

                    data_container = (
                        params[1]
                    )

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

                        values = bar.get(
                            "v"
                        )

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

                            if not all(
                                math.isfinite(x)
                                for x in [
                                    timestamp,
                                    open_price,
                                    high_price,
                                    low_price,
                                    close_price
                                ]
                            ):
                                continue

                            if high_price < low_price:
                                continue

                            candles[
                                timestamp
                            ] = {

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
                # SYMBOL ERROR
                # ------------------------------------------------

                elif method == "symbol_error":

                    raise RuntimeError(
                        "TradingView symbol_error: "
                        + str(params)
                    )

                # ------------------------------------------------
                # SERIES ERROR
                # ------------------------------------------------

                elif method == "series_error":

                    raise RuntimeError(
                        "TradingView series_error: "
                        + str(params)
                    )

                # ------------------------------------------------
                # CRITICAL ERROR
                # ------------------------------------------------

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

        # --------------------------------------------------------
        # SON KONTROLLER
        # --------------------------------------------------------

        if not candles:

            raise RuntimeError(
                "TradingView mum verisi gondermedi."
            )

        result = sorted(
            candles.values(),
            key=lambda x:
                x["time"]
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

    for i, candle in enumerate(
        candles
    ):

        high = candle["high"]
        low = candle["low"]

        if i == 0:

            tr = (
                high -
                low
            )

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

        true_ranges.append(
            tr
        )

    atr = [
        None
        for _ in candles
    ]

    first_atr = (
        sum(
            true_ranges[
                :period
            ]
        )
        /
        period
    )

    atr[
        period - 1
    ] = first_atr

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
# SUPERTREND - BUTUN VERILER
# ============================================================

def calculate_supertrend_all(
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

    upper_band = [
        None
        for _ in candles
    ]

    lower_band = [
        None
        for _ in candles
    ]

    supertrend = [
        None
        for _ in candles
    ]

    direction = [
        None
        for _ in candles
    ]

    # --------------------------------------------------------
    # ILK GECERLI ATR NOKTASI
    # --------------------------------------------------------

    first_index = None

    for i in range(
        len(candles)
    ):

        if atr[i] is not None:

            first_index = i
            break

    if first_index is None:
        return None

    # --------------------------------------------------------
    # SUPERTREND
    # --------------------------------------------------------

    for i in range(
        first_index,
        len(candles)
    ):

        if atr[i] is None:
            continue

        high = candles[i]["high"]
        low = candles[i]["low"]
        close = candles[i]["close"]

        # ----------------------------------------------------
        # HL2
        # ----------------------------------------------------

        hl2 = (
            high +
            low
        ) / 2.0

        basic_upper = (
            hl2 +
            multiplier * atr[i]
        )

        basic_lower = (
            hl2 -
            multiplier * atr[i]
        )

        # ----------------------------------------------------
        # ILK DEGER
        # ----------------------------------------------------

        if i == first_index:

            upper_band[i] = (
                basic_upper
            )

            lower_band[i] = (
                basic_lower
            )

            # Ilk baslangic SAT kabul edilir.
            direction[i] = -1

            supertrend[i] = (
                upper_band[i]
            )

            continue

        previous_close = (
            candles[i - 1]["close"]
        )

        previous_upper = (
            upper_band[i - 1]
        )

        previous_lower = (
            lower_band[i - 1]
        )

        previous_direction = (
            direction[i - 1]
        )

        if previous_upper is None:

            previous_upper = (
                basic_upper
            )

        if previous_lower is None:

            previous_lower = (
                basic_lower
            )

        if previous_direction is None:

            previous_direction = -1

        # ----------------------------------------------------
        # FINAL UPPER BAND
        # ----------------------------------------------------

        if (

            basic_upper <
            previous_upper

            or

            previous_close >
            previous_upper

        ):

            upper_band[i] = (
                basic_upper
            )

        else:

            upper_band[i] = (
                previous_upper
            )

        # ----------------------------------------------------
        # FINAL LOWER BAND
        # ----------------------------------------------------

        if (

            basic_lower >
            previous_lower

            or

            previous_close <
            previous_lower

        ):

            lower_band[i] = (
                basic_lower
            )

        else:

            lower_band[i] = (
                previous_lower
            )

        # ----------------------------------------------------
        # TREND
        #
        # +1 = AL / YUKARI TREND
        # -1 = SAT / ASAGI TREND
        # ----------------------------------------------------

        if previous_direction == -1:

            if (
                close >
                upper_band[i]
            ):

                direction[i] = 1

            else:

                direction[i] = -1

        else:

            if (
                close <
                lower_band[i]
            ):

                direction[i] = -1

            else:

                direction[i] = 1

        # ----------------------------------------------------
        # SUPERTREND
        # ----------------------------------------------------

        if direction[i] == 1:

            supertrend[i] = (
                lower_band[i]
            )

        else:

            supertrend[i] = (
                upper_band[i]
            )

    return {

        "directions":
            direction,

        "supertrend":
            supertrend,

        "upper_band":
            upper_band,

        "lower_band":
            lower_band

    }


# ============================================================
# SON TAMAMLANMIS 2 SAATLIK MUM
# ============================================================

def get_last_completed_candle(
    candles
):

    if not candles:
        return None

    now = now_istanbul()

    completed = []

    timeframe_seconds = (
        2 * 60 * 60
    )

    for candle in candles:

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

            candle_end = (
                candle_time +
                timedelta(
                    seconds=timeframe_seconds
                )
            )

            if candle_end <= now:

                completed.append(
                    candle
                )

        except Exception:

            continue

    if not completed:
        return None

    completed.sort(
        key=lambda x:
            x["time"]
    )

    return completed[-1]


# ============================================================
# BIST ISLEM SAATI
# ============================================================

def is_bist_open_time():

    now = now_istanbul()

    if now.weekday() >= 5:

        return False

    current_minutes = (
        now.hour * 60 +
        now.minute
    )

    open_minutes = (
        MARKET_OPEN_HOUR * 60 +
        MARKET_OPEN_MINUTE
    )

    close_minutes = (
        MARKET_CLOSE_HOUR * 60 +
        MARKET_CLOSE_MINUTE
    )

    return (
        open_minutes
        <=
        current_minutes
        <
        close_minutes
    )


# ============================================================
# TELEGRAM TEK MESAJ
# ============================================================

def send_telegram_single(
    message
):

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
        +
        TELEGRAM_BOT_TOKEN
        +
        "/sendMessage"
    )

    payload = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            message,

        "disable_web_page_preview":
            True

    }

    response = requests.post(

        url,

        json=payload,

        timeout=REQUEST_TIMEOUT

    )

    # --------------------------------------------------------
    # Telegram 400 hatasinda gercek cevabi yaz
    # --------------------------------------------------------

    if response.status_code != 200:

        try:
            telegram_result = response.json()
        except Exception:
            telegram_result = response.text

        raise RuntimeError(
            "Telegram API hatasi "
            + str(response.status_code)
            + ": "
            + str(telegram_result)
        )

    result = response.json()

    if not result.get("ok"):

        raise RuntimeError(
            "Telegram hatasi: "
            + str(result)
        )


# ============================================================
# TELEGRAM MESAJ PARCALAMA
# ============================================================

def split_message(
    message,
    max_length=TELEGRAM_MAX_LENGTH
):

    if len(message) <= max_length:

        return [
            message
        ]

    lines = message.split(
        "\n"
    )

    chunks = []

    current = ""

    for line in lines:

        candidate = (
            current
            +
            (
                "\n"
                if current
                else ""
            )
            +
            line
        )

        if len(candidate) <= max_length:

            current = candidate

        else:

            if current:

                chunks.append(
                    current
                )

            # Tek satir limitten uzunsa
            # guvenli sekilde bol.

            if len(line) > max_length:

                start = 0

                while (
                    start <
                    len(line)
                ):

                    end = (
                        start +
                        max_length
                    )

                    chunks.append(
                        line[
                            start:end
                        ]
                    )

                    start = end

                current = ""

            else:

                current = line

    if current:

        chunks.append(
            current
        )

    return chunks


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

    chunks = split_message(
        message
    )

    log(
        f"Telegram mesaj parca sayisi: "
        f"{len(chunks)}"
    )

    for index, chunk in enumerate(
        chunks,
        start=1
    ):

        send_telegram_single(
            chunk
        )

        log(
            f"Telegram mesaj {index}/"
            f"{len(chunks)} gonderildi."
        )

        if index < len(chunks):

            time.sleep(
                0.5
            )


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
# MUM ZAMANI FORMAT
# ============================================================

def format_candle_time(
    timestamp
):

    try:

        dt = (
            datetime.fromtimestamp(
                timestamp,
                tz=ZoneInfo("UTC")
            )
            .astimezone(
                ZoneInfo(TIMEZONE)
            )
        )

        return dt.strftime(
            "%d.%m.%Y %H:%M"
        )

    except Exception:

        return "-"


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def build_telegram_message(
    results
):

    now = now_istanbul()

    lines = []

    # --------------------------------------------------------
    # BASLIK
    # --------------------------------------------------------

    lines.append(
        "SUPERTREND AL SİNYALİ VEREN HİSSELER"
    )

    lines.append("")

    lines.append(
        "BIST 2 SAATLİK SUPERTREND"
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
        "Tarama: "
        +
        now.strftime(
            "%d.%m.%Y %H:%M"
        )
    )

    lines.append(
        f"Yeni SAT → AL sinyali: "
        f"{len(results)} adet"
    )

    lines.append("")

    # --------------------------------------------------------
    # HISSELER
    # --------------------------------------------------------

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

        candle_time = (
            format_candle_time(
                result["candle_time"]
            )
        )

        lines.append(
            f"{symbol} | "
            f"{price} TL | "
            f"SAT → AL | "
            f"{candle_time}"
        )

    lines.append("")

    lines.append(
        "Sinyal: Önceki tamamlanmış "
        "2H mum SAT (-1), son tamamlanmış "
        "2H mum AL (+1)."
    )

    return "\n".join(
        lines
    )


# ============================================================
# TEK HISSE TARAMA
# ============================================================

def scan_symbol(
    symbol
):

    try:

        candles = get_tv_candles(
            symbol
        )

        if not candles:

            return None

        # ----------------------------------------------------
        # SON TAMAMLANMIS MUM
        # ----------------------------------------------------

        completed = (
            get_last_completed_candle(
                candles
            )
        )

        if completed is None:

            log(
                f"{symbol} -> "
                "Tamamlanmis 2H mum bulunamadi."
            )

            return None

        completed_time = (
            completed["time"]
        )

        completed_index = None

        for i, candle in enumerate(
            candles
        ):

            if (
                candle["time"]
                ==
                completed_time
            ):

                completed_index = i
                break

        if completed_index is None:

            return None

        # ----------------------------------------------------
        # SADECE TAMAMLANMIS MUMLAR
        # ----------------------------------------------------

        calculation_candles = (
            candles[
                :completed_index + 1
            ]
        )

        # ----------------------------------------------------
        # SUPERTREND
        # ----------------------------------------------------

        trend_data = (
            calculate_supertrend_all(
                calculation_candles,
                ATR_PERIOD,
                ATR_MULTIPLIER
            )
        )

        if trend_data is None:

            return None

        directions = (
            trend_data[
                "directions"
            ]
        )

        # ----------------------------------------------------
        # GECERLI TREND INDEKSLERINI BUL
        # ----------------------------------------------------

        valid_indexes = [

            i

            for i, value in enumerate(
                directions
            )

            if value is not None

        ]

        if len(valid_indexes) < 2:

            return None

        current_index = (
            valid_indexes[-1]
        )

        previous_index = (
            valid_indexes[-2]
        )

        previous_trend = (
            directions[
                previous_index
            ]
        )

        current_trend = (
            directions[
                current_index
            ]
        )

        # ----------------------------------------------------
        # GERCEK SAT -> AL
        # ----------------------------------------------------

        is_new_buy = (

            previous_trend == -1

            and

            current_trend == 1

        )

        # ----------------------------------------------------
        # TEST ICIN DETAY
        # ----------------------------------------------------

        log(
            f"    Trend: "
            f"{previous_trend} -> "
            f"{current_trend}"
        )

        log(
            f"    Mum: "
            f"{format_candle_time(completed_time)}"
        )

        log(
            f"    Kapanis: "
            f"{format_price(completed['close'])} TL"
        )

        # ----------------------------------------------------
        # YENI AL DEGILSE
        # ----------------------------------------------------

        if not is_new_buy:

            return None

        # ----------------------------------------------------
        # YENI AL
        # ----------------------------------------------------

        return {

            "symbol":
                symbol,

            "price":
                completed["close"],

            "candle_time":
                completed_time,

            "previous_trend":
                previous_trend,

            "current_trend":
                current_trend

        }

    except Exception as e:

        log(
            f"{symbol} -> hata: {e}"
        )

        return None


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    log("")
    log("=" * 70)

    log(
        "BIST SUPERTREND TARAMASI "
        "SURUM 2 BASLADI"
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
    # TEST MODU BILGISI
    # --------------------------------------------------------

    if TEST_MODE:

        log("")
        log(
            "******** TEST MODU AKTIF ********"
        )

        log(
            "Sadece su hisseler taranacak:"
        )

        for symbol in TEST_SYMBOLS:

            log(
                "    "
                + symbol
            )

        log(
            "**********************************"
        )

    else:

        log(
            "NORMAL MOD: Tum BIST hisseleri taranacak."
        )

    # --------------------------------------------------------
    # BIST SAAT KONTROLU
    #
    # TEST MODUNDA BU KONTROLU DEVRE DISI BIRAKIYORUZ.
    # Boylece GitHub Actions MANUEL calistirildiginda
    # hafta sonu/gece de test yapilabilir.
    # --------------------------------------------------------

    if not TEST_MODE:

        if not is_bist_open_time():

            log(
                "BIST normal islem saatleri disinda."
            )

            log(
                "Tarama yapilmayacak."
            )

            return

    else:

        log(
            "TEST MODU: BIST saat kontrolu atlandi."
        )

    # --------------------------------------------------------
    # TELEGRAM AYARLARI
    # --------------------------------------------------------

    if not TELEGRAM_BOT_TOKEN:

        log(
            "UYARI: TELEGRAM_BOT_TOKEN yok."
        )

    if not TELEGRAM_CHAT_ID:

        log(
            "UYARI: TELEGRAM_CHAT_ID yok."
        )

    # --------------------------------------------------------
    # HISSE LISTESI
    # --------------------------------------------------------

    if TEST_MODE:

        symbols = sorted(
            set(
                TEST_SYMBOLS
            )
        )

    else:

        symbols = get_bist_symbols()

    total = len(symbols)

    log(
        f"Toplam {total} hisse taranacak."
    )

    log("")
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
        "Sinyal = SAT (-1) -> AL (+1)"
    )

    log("")

    results = []

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

        try:

            result = scan_symbol(
                symbol
            )

            if result is not None:

                results.append(
                    result
                )

                success_count += 1

                log(
                    "    >>> YENI AL SINYALI!"
                )

                log(
                    "    >>> "
                    +
                    symbol
                )

                log(
                    "    >>> "
                    +
                    f"{format_price(result['price'])} TL"
                )

            else:

                success_count += 1

                log(
                    "    -> Yeni SAT -> AL yok."
                )

        except Exception as e:

            error_count += 1

            log(
                f"    >>> TARAMA HATASI: {e}"
            )

        if SYMBOL_DELAY > 0:

            time.sleep(
                SYMBOL_DELAY
            )

    # --------------------------------------------------------
    # SONUCLAR
    # --------------------------------------------------------

    results.sort(
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
        f"YENI SAT -> AL: {len(results)}"
    )

    log("=" * 70)

    # --------------------------------------------------------
    # BUY YOK
    # --------------------------------------------------------

    if not results:

        log(
            "Son tamamlanmis 2 saatlik "
            "mumlarda yeni SAT -> AL "
            "donusu bulunamadi."
        )

        log(
            "Telegram mesaji GONDERILMEYECEK."
        )

        log(
            "PROGRAM BASARIYLA TAMAMLANDI."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM MESAJI
    # --------------------------------------------------------

    message = build_telegram_message(
        results
    )

    send_telegram(
        message
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
