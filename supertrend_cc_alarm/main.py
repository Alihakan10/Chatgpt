# ============================================================
# STANDALONE BIST SUPERTREND CONFIRMED CLOSE ALARM
# ============================================================
# Bu dosya mevcut scanner.py / verified_scanner.py sisteminden
# BAGIMSIZDIR. Study kullanmaz.
#
# 620 BIST | native TradingView 2H OHLC
# Supertrend Confirmed Close:
# ATR 10 | HL2 | Wilder/RMA | Multiplier 2
# Freeze/confirmed-close mantigi
#
# Sadece SON TAMAMLANMIS 2H mumdaki yeni BUY Telegram'a gider.
# ============================================================

import json
import math
import os
import random
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import websocket

TV_SCANNER_URL = "https://scanner.tradingview.com/turkey/scan"
TV_WS_URL = "wss://data.tradingview.com/socket.io/websocket"

TIMEZONE = ZoneInfo("Europe/Istanbul")
ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
TIMEFRAME = "120"
CANDLE_COUNT = 300
BATCH_SIZE = 20
WORKERS = 5
SCAN_LIMIT = 620
WS_TIMEOUT = 12
STATE_FILE = "supertrend_cc_alarm/state.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def log(msg):
    print(
        f"[{datetime.now(TIMEZONE):%Y-%m-%d %H:%M:%S}] {msg}",
        flush=True,
    )


def tv_message(method, params):
    payload = json.dumps(
        {"m": method, "p": params},
        separators=(",", ":"),
    )
    return f"~m~{len(payload)}~m~{payload}"


def session_id(prefix):
    chars = string.ascii_lowercase + string.digits
    return prefix + "_" + "".join(random.choice(chars) for _ in range(12))


def extract_messages(raw):
    out = []
    pos = 0

    while True:
        start = raw.find("~m~", pos)
        if start < 0:
            break

        a = start + 3
        b = raw.find("~m~", a)
        if b < 0:
            break

        try:
            length = int(raw[a:b])
        except ValueError:
            pos = b + 3
            continue

        body_start = b + 3
        body_end = body_start + length
        if body_end > len(raw):
            break

        out.append((raw[start:body_end], raw[body_start:body_end]))
        pos = body_end

    return out, raw[pos:]


def get_symbols():
    payload = {
        "columns": [
            "name", "description", "close", "currency",
            "exchange", "type", "typespecs",
        ],
        "filter": [
            {"left": "is_primary", "operation": "equal", "right": True},
            {"left": "typespecs", "operation": "has", "right": "common"},
            {"left": "type", "operation": "equal", "right": "stock"},
            {"left": "name", "operation": "nempty"},
        ],
        "filterOR": [],
        "ignore_unknown_fields": False,
        "options": {"active_symbols_only": True, "lang": "tr"},
        "price_conversion": {},
        "range": [0, 1000],
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "markets": ["turkey"],
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }

    for attempt in range(1, 4):
        try:
            r = requests.post(
                TV_SCANNER_URL,
                json=payload,
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            symbols = sorted({
                x["s"] for x in data
                if isinstance(x, dict)
                and x.get("s", "").startswith("BIST:")
            })
            if symbols:
                return symbols[:SCAN_LIMIT]
            raise RuntimeError("BIST sembol listesi bos.")
        except Exception as exc:
            log(f"Sembol listesi hatasi {attempt}/3: {exc}")
            time.sleep(attempt * 2)

    raise RuntimeError("BIST sembol listesi alinamadi.")


def get_auth_token():
    # Ayrı proje olduğu için sadece opsiyonel TV secrets kullanır.
    sessionid = os.getenv("TV_SESSIONID", "").strip()
    sessionid_sign = os.getenv("TV_SESSIONID_SIGN", "").strip()
    fallback = os.getenv("TRADINGVIEW_AUTH_TOKEN", "").strip()

    if sessionid:
        try:
            cookies = {"sessionid": sessionid}
            if sessionid_sign:
                cookies["sessionid_sign"] = sessionid_sign

            r = requests.post(
                "https://www.tradingview.com/quote_token/",
                headers={
                    "Origin": "https://www.tradingview.com",
                    "Referer": "https://www.tradingview.com/",
                    "User-Agent": "Mozilla/5.0",
                },
                cookies=cookies,
                data={"grabSession": "true"},
                timeout=10,
            )

            if r.ok:
                try:
                    data = r.json()
                    token = data.get("token") if isinstance(data, dict) else None
                except Exception:
                    token = r.text.strip().split(":", 1)[0]

                if token:
                    return token
        except Exception:
            pass

    return fallback or "unauthorized_user_token"


def parse_bar_values(values):
    if not isinstance(values, list) or len(values) < 5:
        return None

    try:
        vals = [float(values[i]) for i in range(5)]
    except Exception:
        return None

    if not all(math.isfinite(x) for x in vals):
        return None

    ts, op, hi, lo, cl = vals
    if hi < lo:
        return None

    volume = 0.0
    if len(values) > 5 and values[5] is not None:
        try:
            volume = float(values[5])
        except Exception:
            pass

    return {
        "time": ts,
        "open": op,
        "high": hi,
        "low": lo,
        "close": cl,
        "volume": volume,
    }


def get_batch_candles(symbols):
    ws = None
    cs = session_id("cs")
    series_to_symbol = {}
    candles = {s: {} for s in symbols}

    try:
        ws = websocket.create_connection(
            TV_WS_URL,
            timeout=WS_TIMEOUT,
            origin="https://www.tradingview.com",
        )

        ws.send(tv_message("set_auth_token", [get_auth_token()]))
        ws.send(tv_message("chart_create_session", [cs, ""]))

        ws.send(tv_message("switch_timezone", [cs, "exchange"]))

        for n, symbol in enumerate(symbols, 1):
            series_id = f"s{n}"
            symbol_id = f"sym{n}"
            series_to_symbol[series_id] = symbol

            config = json.dumps(
                {
                    "symbol": symbol,
                    "adjustment": "splits",
                    "session": "regular",
                },
                separators=(",", ":"),
            )

            ws.send(tv_message(
                "resolve_symbol",
                [cs, symbol_id, "=" + config],
            ))

            ws.send(tv_message(
                "create_series",
                [
                    cs,
                    series_id,
                    series_id,
                    symbol_id,
                    TIMEFRAME,
                    CANDLE_COUNT,
                    "",
                ],
            ))

        raw_buffer = ""
        deadline = time.time() + WS_TIMEOUT
        last_counts = 0

        while time.time() < deadline:
            try:
                packet = ws.recv()
            except websocket.WebSocketTimeoutException:
                break

            if not packet:
                break

            if isinstance(packet, bytes):
                packet = packet.decode("utf-8", errors="ignore")

            raw_buffer += packet
            messages, raw_buffer = extract_messages(raw_buffer)

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

                if obj.get("m") not in ("timescale_update", "du"):
                    continue

                params = obj.get("p", [])
                if len(params) < 2 or not isinstance(params[1], dict):
                    continue

                container = params[1]

                # Her series kendi anahtarıyla gelir.
                for series_id, symbol in series_to_symbol.items():
                    series = container.get(series_id)
                    if not isinstance(series, dict):
                        continue

                    bars = series.get("s", [])
                    if not isinstance(bars, list):
                        continue

                    for bar in bars:
                        if not isinstance(bar, dict):
                            continue
                        parsed = parse_bar_values(bar.get("v"))
                        if parsed:
                            candles[symbol][parsed["time"]] = parsed

            current_counts = sum(len(x) for x in candles.values())
            if current_counts > last_counts:
                last_counts = current_counts

            if all(len(candles[s]) >= 20 for s in symbols):
                break

        return {
            s: sorted(candles[s].values(), key=lambda x: x["time"])
            for s in symbols
        }

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def completed_index(candles):
    now = datetime.now(TIMEZONE)
    good = []

    for i, candle in enumerate(candles):
        try:
            start = datetime.fromtimestamp(
                candle["time"],
                tz=ZoneInfo("UTC"),
            ).astimezone(TIMEZONE)

            if start + __import__("datetime").timedelta(hours=2) <= now:
                good.append(i)
        except Exception:
            pass

    return good[-1] if good else None


def wilder_atr(candles, period=10):
    tr = []

    for i, c in enumerate(candles):
        if i == 0:
            value = c["high"] - c["low"]
        else:
            pc = candles[i - 1]["close"]
            value = max(
                c["high"] - c["low"],
                abs(c["high"] - pc),
                abs(c["low"] - pc),
            )
        tr.append(value)

    atr = [None] * len(candles)
    if len(candles) < period:
        return atr

    atr[period - 1] = sum(tr[:period]) / period

    for i in range(period, len(candles)):
        atr[i] = (
            atr[i - 1] * (period - 1) + tr[i]
        ) / period

    return atr


def supertrend_cc(candles):
    """
    TradingView Supertrend / Supertrend Confirmed Close mantiginin
    disarida birebir uygulanmasi.

    Pine tarafindaki yon kodlamasi:
      -1 = bullish (Supertrend alt bant)
       1 = bearish (Supertrend ust bant)

    BUY:
      onceki yon = bearish (1)
      mevcut kapanmis mumda yon = bullish (-1)

    CC kuralinda sinyal sadece kapanmis mumda degerlendirilir.
    ATR = ta.atr() / Wilder RMA, Source = HL2.
    """
    n = len(candles)
    if n < ATR_PERIOD + 2:
        return None

    # Pine ta.atr() = ta.rma(True Range, period).
    # ta.rma seed'i ilk period TR'nin SMA'sidir.
    tr = [None] * n
    for i, c in enumerate(candles):
        if i == 0:
            tr[i] = c["high"] - c["low"]
        else:
            prev_close = candles[i - 1]["close"]
            tr[i] = max(
                c["high"] - c["low"],
                abs(c["high"] - prev_close),
                abs(c["low"] - prev_close),
            )

    atr = [None] * n
    if n < ATR_PERIOD:
        return None

    atr[ATR_PERIOD - 1] = sum(
        tr[:ATR_PERIOD]
    ) / ATR_PERIOD

    for i in range(ATR_PERIOD, n):
        atr[i] = (
            atr[i - 1] * (ATR_PERIOD - 1) + tr[i]
        ) / ATR_PERIOD

    # TradingView Supertrend bandlari.
    upper = [None] * n
    lower = [None] * n
    direction = [None] * n
    buy = [False] * n
    sell = [False] * n

    for i in range(n):
        if atr[i] is None:
            continue

        src = (
            candles[i]["high"] + candles[i]["low"]
        ) / 2.0

        upper_basic = src + ATR_MULTIPLIER * atr[i]
        lower_basic = src - ATR_MULTIPLIER * atr[i]

        if i == ATR_PERIOD - 1:
            upper[i] = upper_basic
            lower[i] = lower_basic
            direction[i] = 1
            continue

        prev_upper = upper[i - 1]
        prev_lower = lower[i - 1]
        prev_close = candles[i - 1]["close"]

        if prev_upper is None or prev_lower is None:
            upper[i] = upper_basic
            lower[i] = lower_basic
            direction[i] = 1
            continue

        # Pine:
        # up := close[1] > up1 ? max(up, up1) : up
        # dn := close[1] < dn1 ? min(dn, dn1) : dn
        lower[i] = (
            max(lower_basic, prev_lower)
            if prev_close > prev_lower
            else lower_basic
        )

        upper[i] = (
            min(upper_basic, prev_upper)
            if prev_close < prev_upper
            else upper_basic
        )

        prev_direction = direction[i - 1]
        if prev_direction is None:
            prev_direction = 1

        # TradingView Supertrend yon mantigi:
        # direction == 1  -> bearish / upper band
        # direction == -1 -> bullish / lower band
        if (
            prev_direction == -1
            and candles[i]["close"] < lower[i]
        ):
            direction[i] = 1
            sell[i] = True
        elif (
            prev_direction == 1
            and candles[i]["close"] > upper[i]
        ):
            direction[i] = -1
            buy[i] = True
        else:
            direction[i] = prev_direction

    return {
        "direction": direction,
        "buy": buy,
        "sell": sell,
    }

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def send_telegram(buys):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID eksik."
        )

    lines = [
        "🚨 <b>SUPERTREND CC BUY</b>",
        "",
        "⏱ 2H | ATR 10 | HL2 | Wilder/RMA | x2",
        "🧊 Confirmed Close / Freeze",
        "",
    ]

    for item in buys:
        dt = datetime.fromtimestamp(
            item["time"],
            tz=ZoneInfo("UTC"),
        ).astimezone(TIMEZONE)

        ticker = item["symbol"].split(":", 1)[-1]

        lines.append(
            f"🟢 <b>{ticker}</b> — {item['close']:.4f} TL"
        )
        lines.append(
            f"🕒 Mum: {dt:%d.%m.%Y %H:%M}"
        )
        lines.append("")

    lines.append("Kaynak: bağımsız CC alarm motoru")

    response = requests.post(
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "\n".join(lines),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    response.raise_for_status()


def process_symbol(symbol, candles):
    idx = completed_index(candles)
    if idx is None:
        return None

    closed = candles[:idx + 1]
    calc = supertrend_cc(closed)
    if not calc:
        return None

    i = len(closed) - 1

    if not calc["buy"][i]:
        return None

    return {
        "symbol": symbol,
        "time": closed[i]["time"],
        "close": closed[i]["close"],
    }


def main():
    log("=" * 70)
    log("STANDALONE SUPERTREND CC ALARM")
    log("620 BIST | NATIVE 2H | ATR10 | HL2 | WILDER | x2")
    log("SADECE SON TAMAMLANMIS 2H MUM")
    log("=" * 70)

    symbols = get_symbols()

    if len(symbols) < SCAN_LIMIT:
        raise RuntimeError(
            f"{len(symbols)} hisse bulundu; {SCAN_LIMIT} bekleniyordu."
        )

    state = load_state()
    buys = []

    batches = [
        symbols[i:i + BATCH_SIZE]
        for i in range(0, len(symbols), BATCH_SIZE)
    ]

    log(f"{len(symbols)} hisse / {len(batches)} batch taranacak.")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(get_batch_candles, batch): batch
            for batch in batches
        }

        for future in as_completed(futures):
            batch = futures[future]

            try:
                result = future.result()
            except Exception as exc:
                log(f"Batch hata ({len(batch)}): {exc}")
                continue

            for symbol in batch:
                candles = result.get(symbol, [])
                event = process_symbol(symbol, candles)

                if not event:
                    continue

                last_sent = str(
                    state.get(symbol, {}).get("last_buy_candle", "")
                )

                if last_sent == str(event["time"]):
                    continue

                buys.append(event)

    buys.sort(key=lambda x: (x["time"], x["symbol"]))

    log(f"SON TAMAMLANMIS 2H BUY: {len(buys)}")

    if buys:
        send_telegram(buys)

        for event in buys:
            state[event["symbol"]] = {
                "last_buy_candle": event["time"],
                "updated_at": datetime.now(TIMEZONE).isoformat(),
            }

        save_state(state)
        for event in buys:
            log(
                f"TELEGRAM BUY -> {event['symbol']} "
                f"{event['close']}"
            )
    else:
        log("Yeni CC BUY yok.")

    log("CC alarm taramasi tamamlandi.")


if __name__ == "__main__":
    main()
