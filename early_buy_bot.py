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
MAX_WORKERS = 8
MIN_REQUEST_GAP = 0.35
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
        df = TV_PROVIDER.get_history(
            symbol, period=PERIOD, interval="2h", exchange="BIST"
        )
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
        if not (df.index == expected_time).any():
            return {"symbol": symbol, "error": "Beklenen açık 2H mum bulunamadı"}
        df = df.loc[:expected_time].copy()
        if df.empty or df.index[-1] != expected_time:
            return {"symbol": symbol, "error": "Açık mum son satır değil"}
        result = calculate_pine_supertrend(df)
        last = result.iloc[-1]
        return {
            "symbol": symbol,
            "early_buy": bool(last["buy"]),
            "close": float(last["Close"]),
            "time": result.index[-1].isoformat(),
            "trend": int(last["trend"]),
        }
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}


def main():
    now = datetime.now(IST)
    print(f"RUN_TIME_IST={now.isoformat()}")
    if now.weekday() >= 5:
        print("VIRTUAL_TEST: hafta sonu; tarama yapılmadı.")
        return
    expected_time = active_bar_start(now)
    if expected_time is None:
        print("VIRTUAL_TEST: aktif 2H seans dışında; tarama yapılmadı.")
        return
    # Check that the market data provider has data for the current local date.
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

    symbols = get_symbols()
    print(f"SYMBOL_COUNT={len(symbols)}")
    print(f"EXPECTED_OPEN_BAR={expected_time.isoformat()}")
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        jobs = {pool.submit(check_symbol, symbol, expected_time): symbol for symbol in symbols}
        for job in as_completed(jobs):
            item = job.result()
            (errors if "error" in item else results).append(item)
    buys = sorted((x for x in results if x.get("early_buy")), key=lambda x: x["symbol"])
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
        if not isinstance(state, dict):
            state = {}
    except Exception:
        state = {}
    new_buys = []
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
    report = {
        "run_time_istanbul": now.isoformat(),
        "expected_open_bar": expected_time.isoformat(),
        "symbols": len(symbols),
        "successful": len(results),
        "errors": len(errors),
        "early_buy_candidates_now": len(buys),
        "new_virtual_buy_events": new_buys,
        "mode": "VIRTUAL_ONLY_NO_TELEGRAM_NO_BROKER_ORDERS",
    }
    Path("latest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    for item in errors[:20]:
        print(f'ERROR {item["symbol"]}: {item["error"]}')


if __name__ == "__main__":
    main()
