# ============================================================
# BIST SUPERTREND ALARM SISTEMI
# SURUM 2 - TELEGRAM MESAJ BOLME DUZELTMESI
# ============================================================
#
# BIST hisselerini otomatik bulur
#
# Supertrend:
#   Timeframe       = 2 saat
#   ATR Period      = 10
#   Source          = HL2
#   ATR Multiplier  = 2
#
# Son tamamlanmis 2 saatlik mum BUY ise Telegram bildirimi
#
# BUY yoksa Telegram mesaj GONDERILMEZ.
#
# Telegram mesajlari 4096 karakter sinirina gore
# otomatik olarak parcalara ayrilir.
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

ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0

TIMEFRAME = "120"

CANDLE_COUNT = 150

TV_SCANNER_URL = (
    "https://scanner.tradingview.com/turkey/scan"
)

TV_WS_URL = (
    "wss://data.tradingview.com/socket.io/websocket"
)

WS_TIMEOUT = 10

REQUEST_TIMEOUT = 20

SYMBOL_DELAY = 0.10


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

# Telegram maksimum 4096 karakter.
# Guvenli tarafta kalmak icin 3800 kullaniyoruz.
TELEGRAM_MAX_LENGTH = 3800


# ============================================================
# BIST ISLEM SAATLERI
# ============================================================

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

    return messages, raw[position:]


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
        # WebSocket
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
                # SERIES DATA
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

                    series_data = None

                    if "sds_1" in data_container:

                        series_data = (
                            data_container[
                                "sds_1"
                            ]
                        )

                    else:

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

            # ----------------------------------------------------
            # Yeterli veri geldi
            # ----------------------------------------------------

            if len(candles) >= 30:

                if series_completed:

                    break

        # --------------------------------------------------------
        # SON KONTROL
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

    if len(candles) < (
        period + 2
    ):

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
# SUPERTREND
# ============================================================

def calculate_supertrend(
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

    for i in range(
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

        if i == atr_period - 1:

            upper_band[i] = (
                basic_upper
            )

            lower_band[i] = (
                basic_lower
            )

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
        # UPPER BAND
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
        # LOWER BAND
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

    valid_indexes = [

        i

        for i, value in enumerate(
            direction
        )

        if value is not None

    ]

    if not valid_indexes:

        return None

    last_index = (
        valid_indexes[-1]
    )

    return {

        "index":
            last_index,

        "direction":
            direction[
                last_index
            ],

        "supertrend":
            supertrend[
                last_index
            ],

        "close":
            candles[
                last_index
            ]["close"],

        "candle_time":
            candles[
                last_index
            ]["time"]

    }


# ============================================================
# SON TAMAMLANMIS MUM
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
# TELEGRAM MESAJI OLUSTUR
# ============================================================

def build_telegram_lines(
    results
):

    now = now_istanbul()

    lines = []

    # BASLIK
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
        f"BUY veren hisse: "
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

        lines.append(
            f"✅ {symbol}   {price} TL"
        )

    lines.append("")

    lines.append(
        "Sinyal son tamamlanmış "
        "2 saatlik mum üzerinden "
        "hesaplanmıştır."
    )

    return lines


# ============================================================
# TELEGRAM MESAJLARINI BOL
# ============================================================

def split_telegram_messages(
    lines,
    max_length=TELEGRAM_MAX_LENGTH
):

    messages = []

    current_lines = []

    current_length = 0

    for line in lines:

        # Satirin kendisi maksimumdan uzunsa
        # guvenli sekilde parcalara ayir.
        if len(line) > max_length:

            if current_lines:

                messages.append(
                    "\n".join(
                        current_lines
                    )
                )

                current_lines = []

                current_length = 0

            start = 0

            while start < len(line):

                part = line[
                    start:
                    start + max_length
                ]

                messages.append(
                    part
                )

                start += max_length

            continue

        line_length = len(line)

        # Satirlar arasi \n hesabi
        extra = (
            1
            if current_lines
            else 0
        )

        if (
            current_length
            +
            extra
            +
            line_length
            >
            max_length
        ):

            if current_lines:

                messages.append(
                    "\n".join(
                        current_lines
                    )
                )

            current_lines = [
                line
            ]

            current_length = (
                line_length
            )

        else:

            current_lines.append(
                line
            )

            current_length += (
                extra +
                line_length
            )

    if current_lines:

        messages.append(
            "\n".join(
                current_lines
            )
        )

    return messages


# ============================================================
# TELEGRAM GONDER
# ============================================================

def send_telegram(
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
    # Telegram hata detayini gostermesi icin
    # --------------------------------------------------------

    if not response.ok:

        try:

            error_data = response.json()

        except Exception:

            error_data = response.text

        raise RuntimeError(
            "Telegram HTTP "
            + str(response.status_code)
            + ": "
            + str(error_data)
        )

    try:

        result = response.json()

    except Exception:

        raise RuntimeError(
            "Telegram gecersiz JSON cevabi: "
            + response.text
        )

    if not result.get("ok"):

        raise RuntimeError(
            "Telegram hatasi: "
            + str(result)
        )

    return result


# ============================================================
# TELEGRAM'A PARCALI GONDER
# ============================================================

def send_telegram_results(
    results
):

    lines = build_telegram_lines(
        results
    )

    messages = split_telegram_messages(
        lines,
        TELEGRAM_MAX_LENGTH
    )

    log(
        f"Telegram icin {len(messages)} "
        f"mesaj olusturuldu."
    )

    for number, message in enumerate(
        messages,
        start=1
    ):

        log(
            f"Telegram mesaj "
            f"{number}/{len(messages)} "
            f"gonderiliyor..."
        )

        log(
            f"Mesaj karakter sayisi: "
            f"{len(message)}"
        )

        try:

            send_telegram(
                message
            )

            log(
                f"Telegram mesaj "
                f"{number}/{len(messages)} "
                f"basariyla gonderildi."
            )

        except Exception as e:

            log(
                f"Telegram mesaj "
                f"{number}/{len(messages)} "
                f"GONDERILEMEDI: {e}"
            )

            raise

        # Telegram'a arka arkaya cok hizli
        # istek atmamak icin kisa bekleme.
        if number < len(messages):

            time.sleep(1)


# ============================================================
# TEK HISSE TARAMA
# ============================================================

def scan_symbol(symbol):

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
        # TAMAMLANMIS MUMLARA KADAR HESAPLA
        # ----------------------------------------------------

        calculation_candles = (
            candles[
                :completed_index + 1
            ]
        )

        result = calculate_supertrend(

            calculation_candles,

            ATR_PERIOD,

            ATR_MULTIPLIER

        )

        if result is None:

            return None

        # ----------------------------------------------------
        # BUY = +1
        # ----------------------------------------------------

        if result["direction"] != 1:

            return None

        return {

            "symbol":
                symbol,

            "price":
                result["close"],

            "candle_time":
                result["candle_time"]

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
        "BIST SUPERTREND TARAMASI BASLADI"
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
    # BIST SAAT KONTROLU
    # --------------------------------------------------------

    if not is_bist_open_time():

        log(
            "BIST normal islem saatleri disinda."
        )

        log(
            "Tarama yapilmayacak."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM KONTROL
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
    # BIST HISSELERI
    # --------------------------------------------------------

    symbols = get_bist_symbols()

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
                    "    >>> BUY: "
                    +
                    f"{result['price']:.2f} TL"
                )

            else:

                success_count += 1

        except Exception as e:

            error_count += 1

            log(
                f"    >>> TARAMA HATASI: {e}"
            )

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
        f"BUY veren: {len(results)}"
    )

    log("=" * 70)

    # --------------------------------------------------------
    # BUY YOK
    # --------------------------------------------------------

    if not results:

        log(
            "Son tamamlanmis 2 saatlik "
            "mumda BUY veren hisse yok."
        )

        log(
            "Telegram mesaji GONDERILMEYECEK."
        )

        return

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    send_telegram_results(
        results
    )

    log(
        "Tum Telegram bildirimleri "
        "basariyla gonderildi."
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
