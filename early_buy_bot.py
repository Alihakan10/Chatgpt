#!/usr/bin/env python3
"""Independent virtual-only BIST early BUY scanner. No Telegram or broker orders."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import borsapy
from borsapy._providers.tradingview import TradingViewProvider
from tradingview_screener import Query

ATR_PERIOD = 10
MULTIPLIER = 2.0
PERIOD = "3mo"
IST = ZoneInfo("Europe/Istanbul")
STATE_FILE = Path("state/early_signals.json")
MAX_WORKERS = 2
MIN_REQUEST_GAP = 1.25
MAX_DATA_RETRIES = 4
REQUEST_LOCK = threading.Lock()
LAST_REQUEST = 0.0

TV_PROVIDER = TradingViewProvider()
TV_PROVIDER.TIMEFRAMES["2h"] = "120"


def get_symbols():
    _, frame = (
        Query()
        .select("name", "close")
        .set_markets("turkey")
        .limit(1000)
        .get_scanner_data()
    )
    if frame is None or frame.empty or "ticker" not in frame.columns:
        raise RuntimeError("TradingView Screener sembol listesi döndürmedi")
    symbols = []
    for item in frame["ticker"].dropna().astype(str):
        item = item.upper().strip()
        if ":" in item:
            exchange, symbol = item.split(":", 1)
            if exchange != "BIST":
                continue
        else:
            symbol = item
        if symbol.strip():
            symbols.append(symbol.strip())
    return sorted(set(symbols))


def calculate_pine_supertrend(df):
    """Same ATR(10), HL2, multiplier 2.0 BUY/SELL math as local scanner."""
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    close = df["Close"].astype(float).to_numpy()
    n = len(df)
    period = ATR_PERIOD
    multiplier = MULTIPLIER
    src = (high + low) / 2.0
    tr = np.full(n, np.nan)
    for i in range(n):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
    atr = np.full(n, np.nan)
    if n >= period:
        atr[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    raw_up = src - multiplier * atr
    raw_dn = src + multiplier * atr
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    trend = np.full(n, np.nan)
    buy = np.zeros(n, dtype=bool)
    sell = np.zeros(n, dtype=bool)
    current_trend = 1
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        up_prev = raw_up[i] if i == 0 or np.isnan(up[i - 1]) else up[i - 1]
        dn_prev = raw_dn[i] if i == 0 or np.isnan(dn[i - 1]) else dn[i - 1]
        if i == 0:
            up[i] = raw_up[i]
            dn[i] = raw_dn[i]
        else:
            up[i] = max(raw_up[i], up_prev) if close[i - 1] > up_prev else raw_up[i]
            dn[i] = min(raw_dn[i], dn_prev) if close[i - 1] < dn_prev else raw_dn[i]
        previous_trend = current_trend
        ready = not np.isnan(atr[i]) and not np.isnan(up_prev) and not np.isnan(dn_prev)
        buy_signal = ready and previous_trend == -1 and close[i] > dn_prev
        sell_signal = ready and previous_trend == 1 and close[i] < up_prev
        current_trend = 1 if buy_signal else (-1 if sell_signal else previous_trend)
        trend[i] = current_trend
        buy[i] = buy_signal
        sell[i] = sell_signal
    out = df.copy()
    out["trend"] = trend
    out["buy"] = buy
    out["sell"] = sell
    return out


def active_bar_start(now):
    if now.hour < 9 or now.hour >= 19:
        return None
    if now.hour < 11:
        hour = 9
    elif now.hour < 13:
        hour = 11
    elif now.hour < 15:
        hour = 13
    elif now.hour < 17:
        hour = 15
    else:
        hour = 17
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


def check_symbol(symbol, expected_time):
    global LAST_REQUEST
    try:
        with REQUEST_LOCK:
            wait = MIN_REQUEST_GAP - (time.monotonic() - LAST_REQUEST)
            if wait > 0:
                time.sleep(wait)
            LAST_REQUEST = time.monotonic()
        df = None
        for attempt in range(MAX_DATA_RETRIES + 1):
            try:
                df = TV_PROVIDER.get_history(
                    symbol, period=PERIOD, interval="2h", exchange="BIST"
                )
                break
            except Exception as exc:
                message = str(exc)
                rate_limited = "429" in message or "Too Many Requests" in message
                if not rate_limited or attempt >= MAX_DATA_RETRIES:
                    raise
                delay = min(60, 5 * (2 ** attempt))
                print(f"RATE_LIMIT {symbol}: deneme {attempt + 1}/{MAX_DATA_RETRIES}; {delay}s bekleniyor")
                time.sleep(delay)
                with REQUEST_LOCK:
                    LAST_REQUEST = time.monotonic()
        if df is None or df.empty:
            return {"symbol": symbol, "error": "Veri alınamadı"}
        df = df.copy()
        rename = {}
        for col in df.columns:
            name = str(col).lower()
            if name in {"open", "high", "low", "close", "volume"}:
                rename[col] = name.capitalize()
        if rename:
            df.rename(columns=rename, inplace=True)
        if not {"High", "Low", "Close"}.issubset(df.columns):
            return {"symbol": symbol, "error": "OHLC kolonları eksik"}
        if len(df) < ATR_PERIOD + 5:
            return {"symbol": symbol, "error": f"Yetersiz mum: {len(df)}"}
        idx = pd.to_datetime(df.index)
        idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
        df.index = idx
        if expected_time is None:
            # Weekend diagnostic: latest available candle only, not a live signal.
            diagnostic_candle = True
        else:
            if not (df.index == expected_time).any():
                return {"symbol": symbol, "error": "Beklenen açık 2H mum bulunamadı"}
            df = df.loc[:expected_time].copy()
            if df.empty or df.index[-1] != expected_time:
                return {"symbol": symbol, "error": "Açık mum son satır değil"}
            diagnostic_candle = False
        result = calculate_pine_supertrend(df)
        last = result.iloc[-1]
        return {
            "symbol": symbol,
            "early_buy": bool(last["buy"]),
            "early_sell": bool(last["sell"]),
            "close": float(last["Close"]),
            "time": result.index[-1].isoformat(),
            "trend": int(last["trend"]),
            "diagnostic_candle": diagnostic_candle,
        }
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}


def write_skip_report(now, reason):
    report = {
        "run_time_istanbul": now.isoformat(),
        "status": "SKIPPED",
        "reason": reason,
        "symbols": 0,
        "successful": 0,
        "errors": 0,
        "early_buy_candidates_now": 0,
        "new_virtual_buy_events": [],
        "mode": "VIRTUAL_ONLY_NO_TELEGRAM_NO_BROKER_ORDERS",
    }
    Path("latest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    now = datetime.now(IST)
    print(f"RUN_TIME_IST={now.isoformat()}")
    weekend_diagnostic = now.weekday() >= 5
    expected_time = active_bar_start(now) if not weekend_diagnostic else None
    if not weekend_diagnostic and expected_time is None:
        write_skip_report(now, "Aktif 2H seans dışında; tarama yapılmadı.")
        return
    # On weekdays require current-date data; weekends test only historical data.
    if not weekend_diagnostic:
        try:
            check = borsapy.Ticker("THYAO").history(period="3d", interval="1h")
            if check is None or check.empty:
                raise RuntimeError("THYAO 1H verisi yok")
            last_ts = pd.Timestamp(check.index[-1])
            last_date = last_ts.tz_convert(IST).date() if last_ts.tzinfo else last_ts.date()
            if last_date != now.date():
                raise RuntimeError(f"Bugünün verisi yok; son veri tarihi={last_date}")
        except Exception as exc:
            raise RuntimeError(f"BIST işlem günü/veri kontrolü başarısız: {exc}") from exc
    else:
        print("WEEKEND_DIAGNOSTIC=True; son mevcut tarihsel 2H mumlar kontrol edilecek.")

    symbols = get_symbols()
    print(f"SYMBOL_COUNT={len(symbols)}")
    print(f"EXPECTED_OPEN_BAR={expected_time.isoformat() if expected_time is not None else 'LATEST_AVAILABLE_HISTORICAL_BAR'}")
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        jobs = {pool.submit(check_symbol, symbol, expected_time): symbol for symbol in symbols}
        for job in as_completed(jobs):
            item = job.result()
            (errors if "error" in item else results).append(item)
    buys = sorted((x for x in results if x.get("early_buy")), key=lambda x: x["symbol"])
    sells = sorted((x for x in results if x.get("early_sell")), key=lambda x: x["symbol"])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}
    new_buys = []
    if not weekend_diagnostic:
        for item in buys:
            key = f'{item["symbol"]}|{item["time"]}'
            if key not in state:
                new_buys.append(item)
                state[key] = {
                    "symbol": item["symbol"],
                    "time": item["time"],
                    "close": item["close"],
                    "status": "VIRTUAL_ONLY",
                    "first_seen_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
                }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # Independent virtual portfolio: BUY opens one virtual position; SELL closes it.
    positions_file = Path("state/virtual_positions.json")
    trades_file = Path("state/virtual_trades.json")
    try:
        positions = json.loads(positions_file.read_text(encoding="utf-8")) if positions_file.exists() else {"open": {}}
        if not isinstance(positions, dict) or not isinstance(positions.get("open"), dict):
            positions = {"open": {}}
    except Exception:
        positions = {"open": {}}
    try:
        trades = json.loads(trades_file.read_text(encoding="utf-8")) if trades_file.exists() else []
        if not isinstance(trades, list):
            trades = []
    except Exception:
        trades = []
    virtual_buys, virtual_sells = [], []
    if not weekend_diagnostic:
        for item in buys:
            symbol = item["symbol"]
            if symbol in positions["open"]:
                continue
            event_key = f'{symbol}|BUY|{item["time"]}'
            if event_key in state:
                continue
            position = {
                "symbol": symbol,
                "buy_time": item["time"],
                "buy_price": item["close"],
                "status": "OPEN_VIRTUAL",
            }
            positions["open"][symbol] = position
            virtual_buys.append({**position, "event": "VIRTUAL_BUY"})
            state[event_key] = {
                "symbol": symbol, "side": "BUY", "time": item["time"],
                "close": item["close"], "status": "VIRTUAL_ONLY",
                "first_seen_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
            }
        for item in sells:
            symbol = item["symbol"]
            position = positions["open"].get(symbol)
            if not position:
                continue
            event_key = f'{symbol}|SELL|{item["time"]}'
            if event_key in state:
                continue
            sell_price = item["close"]
            buy_price = float(position["buy_price"])
            trade = {
                "symbol": symbol,
                "buy_time": position["buy_time"],
                "buy_price": buy_price,
                "sell_time": item["time"],
                "sell_price": sell_price,
                "pnl_per_share": round(sell_price - buy_price, 6),
                "pnl_percent": round((sell_price / buy_price - 1) * 100, 4) if buy_price else None,
                "status": "CLOSED_VIRTUAL",
            }
            trades.append(trade)
            virtual_sells.append({**trade, "event": "VIRTUAL_SELL"})
            del positions["open"][symbol]
            state[event_key] = {
                "symbol": symbol, "side": "SELL", "time": item["time"],
                "close": sell_price, "status": "VIRTUAL_ONLY",
                "first_seen_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
            }
    positions_file.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding="utf-8")
    trades_file.write_text(json.dumps(trades, ensure_ascii=False, indent=2), encoding="utf-8")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "run_time_istanbul": now.isoformat(),
        "expected_open_bar": expected_time.isoformat() if expected_time is not None else None,
        "status": "WEEKEND_DIAGNOSTIC_ONLY" if weekend_diagnostic else "LIVE_SESSION_SCAN",
        "note": "Historical candle diagnostic only; candidates are not recorded as live events." if weekend_diagnostic else "Active 2H candle scan.",
        "symbols": len(symbols),
        "successful": len(results),
        "errors": len(errors),
        "early_buy_candidates_now": len(buys),
        "early_sell_candidates_now": len(sells),
        "new_virtual_buy_events": virtual_buys,
        "new_virtual_sell_events": virtual_sells,
        "open_virtual_positions": len(positions["open"]),
        "closed_virtual_trades": len(trades),
        "mode": "VIRTUAL_ONLY_NO_TELEGRAM_NO_BROKER_ORDERS",
    }
    Path("latest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for item in errors[:20]:
        print(f'ERROR {item["symbol"]}: {item["error"]}')


if __name__ == "__main__":
    main()
