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
ALGORITHM_VERSION = "TV_CC_PREVIOUS_BAND_V4"

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


def get_batch_candles(symbols, timeframe=None, candle_count=None):
    timeframe = timeframe or TIMEFRAME
    candle_count = candle_count or CANDLE_COUNT
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
                    timeframe,
                    candle_count,
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
    """
    TradingView BIST 2H mumlarinin seans sonundaki kisa barini da
    tamamlanmis kabul eder. BIST regular seans 18:00 Istanbul'da biter;
    bu nedenle 17:00 baslangicli son 2H parcasi 18:00'de kapanir ve
    19:00'u beklemek yanlistir.
    """
    now = datetime.now(TIMEZONE)
    good = []

    for i, candle in enumerate(candles):
        try:
            start = datetime.fromtimestamp(
                candle["time"],
                tz=ZoneInfo("UTC"),
            ).astimezone(TIMEZONE)

            # Normal 2H bar.
            end = start + __import__("datetime").timedelta(hours=2)

            # BIST'in son regular seans parcasi: 17:00 -> 18:00.
            if start.weekday() < 5 and start.hour == 17:
                end = start.replace(hour=18, minute=0, second=0, microsecond=0)

            if end <= now:
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
    TradingView Supertrend Confirmed Close (CC) logic.

    CC confirmation uses the PREVIOUS confirmed Supertrend band:
      BUY  = previous bearish state AND current completed close
             > previous bearish Supertrend band
      SELL = previous bullish state AND current completed close
             < previous bullish Supertrend band

    This is deliberately not the native ta.supertrend() current-band
    direction test.
    """
    n = len(candles)
    if n < ATR_PERIOD + 2:
        return None

    tr = [None] * n
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
    atr[ATR_PERIOD - 1] = sum(tr[:ATR_PERIOD]) / ATR_PERIOD
    for i in range(ATR_PERIOD, n):
        atr[i] = (
            atr[i - 1] * (ATR_PERIOD - 1) + tr[i]
        ) / ATR_PERIOD

    upper_band = [None] * n
    lower_band = [None] * n
    supertrend = [None] * n
    direction = [None] * n
    buy = [False] * n
    sell = [False] * n

    for i in range(n):
        if atr[i] is None:
            continue

        src = (
            candles[i]["high"] + candles[i]["low"]
        ) / 2.0

        basic_upper = src + ATR_MULTIPLIER * atr[i]
        basic_lower = src - ATR_MULTIPLIER * atr[i]

        if i > 0 and upper_band[i - 1] is not None:
            prev_upper = upper_band[i - 1]
            prev_lower = lower_band[i - 1]
            prev_close = candles[i - 1]["close"]

            upper_band[i] = (
                basic_upper
                if basic_upper < prev_upper or prev_close > prev_upper
                else prev_upper
            )
            lower_band[i] = (
                basic_lower
                if basic_lower > prev_lower or prev_close < prev_lower
                else prev_lower
            )
        else:
            upper_band[i] = basic_upper
            lower_band[i] = basic_lower

        if i == ATR_PERIOD - 1:
            direction[i] = 1
        else:
            prev_st = supertrend[i - 1]
            prev_direction = direction[i - 1]

            if prev_st is None or prev_direction is None:
                direction[i] = 1
            elif prev_direction == 1:
                if candles[i]["close"] > prev_st:
                    direction[i] = -1
                    buy[i] = True
                else:
                    direction[i] = 1
            else:
                if candles[i]["close"] < prev_st:
                    direction[i] = 1
                    sell[i] = True
                else:
                    direction[i] = -1

        supertrend[i] = (
            lower_band[i]
            if direction[i] == -1
            else upper_band[i]
        )

    return {
        "direction": direction,
        "buy": buy,
        "sell": sell,
        "supertrend": supertrend,
        "upper": upper_band,
        "lower": lower_band,
    }

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
    except Exception:
        return {}

    if data.get("_algorithm_version") != ALGORITHM_VERSION:
        migrated = {"_algorithm_version": ALGORITHM_VERSION}
        for symbol, value in data.items():
            if symbol.startswith("_") or not isinstance(value, dict):
                continue
            clean = dict(value)
            clean.pop("last_buy_candle", None)
            migrated[symbol] = clean
        return migrated

    return data


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

        tv_url = "https://www.tradingview.com/chart/?symbol=BIST%3A" + ticker
        lines.append(
            f'🟢 <a href="{tv_url}"><b>{ticker}</b></a> — {item["close"]:.4f} TL'
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



def aggregate_1h_to_2h(candles):
    """Parity diagnostic only: 1H TradingView bars -> BIST 2H session blocks."""
    if not candles:
        return []

    groups = {}
    for c in candles:
        dt = datetime.fromtimestamp(c["time"], tz=ZoneInfo("UTC")).astimezone(TIMEZONE)
        if dt.weekday() >= 5 or dt.hour < 9 or dt.hour > 17:
            continue

        if dt.hour == 17:
            key_hour = 17
        else:
            key_hour = 9 + ((dt.hour - 9) // 2) * 2

        key = (dt.date().isoformat(), key_hour)
        groups.setdefault(key, []).append(c)

    out = []
    for (date_str, hour), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda x: x["time"])
        if hour != 17 and len(rows) < 2:
            continue
        out.append({
            "time": rows[0]["time"],
            "open": rows[0]["open"],
            "high": max(x["high"] for x in rows),
            "low": min(x["low"] for x in rows),
            "close": rows[-1]["close"],
            "volume": sum(x.get("volume", 0.0) for x in rows),
        })

    return out

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

    if "BIST:VRGYO" in symbols:
        vrg = get_batch_candles(["BIST:VRGYO"]).get("BIST:VRGYO", [])
        vi = completed_index(vrg)
        if vi is not None:
            vc = vrg[:vi + 1]
            vcalc = supertrend_cc(vc)
            j = len(vc) - 1
            log(
                "VRGYO CC DEBUG | "
                f"mum={datetime.fromtimestamp(vc[j]['time'], tz=ZoneInfo('UTC')).astimezone(TIMEZONE):%Y-%m-%d %H:%M} "
                f"close={vc[j]['close']:.4f} "
                f"dir_prev={vcalc['direction'][j-1]} "
                f"dir={vcalc['direction'][j]} "
                f"buy={vcalc['buy'][j]} "
                f"st={vcalc['supertrend'][j]:.6f} "
                f"upper={vcalc['upper'][j]:.6f} "
                f"lower={vcalc['lower'][j]:.6f}"
            )
            # VRGYO icin son barlarin OHLC + ATR + bantlarini yaz.
            detail_start = max(0, j - 8)
            for k in range(detail_start, j + 1):
                dtk = datetime.fromtimestamp(vc[k]['time'], tz=ZoneInfo('UTC')).astimezone(TIMEZONE)
                atr_k = (vcalc['upper'][k] - ((vc[k]['high'] + vc[k]['low']) / 2.0)) / ATR_MULTIPLIER if vcalc['upper'][k] is not None else None
                log(
                    'VRGYO BAR | '
                    f'{dtk:%Y-%m-%d %H:%M} '
                    f'O={vc[k]["open"]:.4f} H={vc[k]["high"]:.4f} L={vc[k]["low"]:.4f} C={vc[k]["close"]:.4f} '
                    f'ATR={atr_k:.6f} upper={vcalc["upper"][k]:.6f} lower={vcalc["lower"][k]:.6f} '
                    f'st={vcalc["supertrend"][k]:.6f} dir={vcalc["direction"][k]} buy={vcalc["buy"][k]}'
                )

            # PARITY DIAGNOSTIC: ayni VRGYO icin native 2H ile
            # 1H -> 2H birlestirilmis veriyi karsilastir.
            try:
                vrg_1h = get_batch_candles(
                    ["BIST:VRGYO"],
                    timeframe="60",
                    candle_count=500,
                ).get("BIST:VRGYO", [])
                vrg_2h_from_1h = aggregate_1h_to_2h(vrg_1h)
                if len(vrg_2h_from_1h) >= ATR_PERIOD + 2:
                    a1 = supertrend_cc(vrg_2h_from_1h)
                    q = len(vrg_2h_from_1h) - 1
                    dtq = datetime.fromtimestamp(
                        vrg_2h_from_1h[q]["time"], tz=ZoneInfo("UTC")
                    ).astimezone(TIMEZONE)
                    log(
                        "VRGYO 1H->2H PARITY | "
                        f"mum={dtq:%Y-%m-%d %H:%M} "
                        f"O={vrg_2h_from_1h[q]['open']:.4f} "
                        f"H={vrg_2h_from_1h[q]['high']:.4f} "
                        f"L={vrg_2h_from_1h[q]['low']:.4f} "
                        f"C={vrg_2h_from_1h[q]['close']:.4f} "
                        f"dir_prev={a1['direction'][q-1]} "
                        f"dir={a1['direction'][q]} "
                        f"buy={a1['buy'][q]} "
                        f"st={a1['supertrend'][q]:.6f} "
                        f"upper={a1['upper'][q]:.6f} "
                        f"lower={a1['lower'][q]:.6f}"
                    )
                    for k in range(max(1, q - 4), q + 1):
                        dtk = datetime.fromtimestamp(
                            vrg_2h_from_1h[k]["time"], tz=ZoneInfo("UTC")
                        ).astimezone(TIMEZONE)
                        log(
                            "VRGYO 1H2H BAR | "
                            f"{dtk:%Y-%m-%d %H:%M} "
                            f"O={vrg_2h_from_1h[k]['open']:.4f} "
                            f"H={vrg_2h_from_1h[k]['high']:.4f} "
                            f"L={vrg_2h_from_1h[k]['low']:.4f} "
                            f"C={vrg_2h_from_1h[k]['close']:.4f} "
                            f"dir={a1['direction'][k]} buy={a1['buy'][k]}"
                        )
                else:
                    log("VRGYO 1H->2H PARITY | yeterli 1H verisi yok")
            except Exception as exc:
                log(f"VRGYO 1H->2H PARITY HATA | {exc}")

            recent_buys = []
            start_j = max(1, j - 20)
            for k in range(start_j, j + 1):
                if vcalc['buy'][k]:
                    dtk = datetime.fromtimestamp(
                        vc[k]['time'], tz=ZoneInfo('UTC')
                    ).astimezone(TIMEZONE)
                    recent_buys.append(
                        f"{dtk:%Y-%m-%d %H:%M} close={vc[k]['close']:.4f} "
                        f"prev_dir={vcalc['direction'][k-1]} "
                        f"dir={vcalc['direction'][k]} "
                        f"prev_st={vcalc['supertrend'][k-1]:.6f}"
                    )
            if recent_buys:
                log("VRGYO SON 20 MUM BUYLAR | " + " || ".join(recent_buys))
            else:
                log("VRGYO SON 20 MUM BUYLAR | yok")

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
