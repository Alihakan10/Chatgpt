#!/usr/bin/env python3
"""Historical virtual BUY/SELL backtest. Never sends broker orders."""
import json, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from borsapy._providers.tradingview import TradingViewProvider
from tradingview_screener import Query

ATR_PERIOD = 10
MULTIPLIER = 2.0
PERIOD = "3mo"
IST = ZoneInfo("Europe/Istanbul")
MAX_WORKERS = 2
MIN_REQUEST_GAP = 1.25
LOCK = threading.Lock()
LAST_REQUEST = 0.0
PROVIDER = TradingViewProvider()
PROVIDER.TIMEFRAMES["2h"] = "120"


def get_symbols():
    _, frame = Query().select("name", "close").set_markets("turkey").limit(1000).get_scanner_data()
    if frame is None or frame.empty or "ticker" not in frame.columns:
        raise RuntimeError("TradingView Screener sembol listesi döndürmedi")
    result = []
    for raw in frame["ticker"].dropna().astype(str):
        raw = raw.upper().strip()
        if ":" in raw:
            exchange, symbol = raw.split(":", 1)
            if exchange != "BIST":
                continue
        else:
            symbol = raw
        if symbol:
            result.append(symbol)
    return sorted(set(result))


def calculate(df):
    high = df["High"].astype(float).to_numpy()
    low = df["Low"].astype(float).to_numpy()
    close = df["Close"].astype(float).to_numpy()
    n = len(df)
    src = (high + low) / 2
    tr = np.full(n, np.nan)
    for i in range(n):
        tr[i] = high[i] - low[i] if i == 0 else max(
            high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr = np.full(n, np.nan)
    if n >= ATR_PERIOD:
        atr[ATR_PERIOD-1] = np.mean(tr[:ATR_PERIOD])
        for i in range(ATR_PERIOD, n):
            atr[i] = (atr[i-1] * (ATR_PERIOD-1) + tr[i]) / ATR_PERIOD
    raw_up, raw_dn = src - MULTIPLIER * atr, src + MULTIPLIER * atr
    up, dn = np.full(n, np.nan), np.full(n, np.nan)
    trend = np.full(n, np.nan)
    buy, sell = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    current = 1
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        up_prev = raw_up[i] if i == 0 or np.isnan(up[i-1]) else up[i-1]
        dn_prev = raw_dn[i] if i == 0 or np.isnan(dn[i-1]) else dn[i-1]
        if i == 0:
            up[i], dn[i] = raw_up[i], raw_dn[i]
        else:
            up[i] = max(raw_up[i], up_prev) if close[i-1] > up_prev else raw_up[i]
            dn[i] = min(raw_dn[i], dn_prev) if close[i-1] < dn_prev else raw_dn[i]
        prev = current
        ready = not np.isnan(up_prev) and not np.isnan(dn_prev)
        buy[i] = ready and prev == -1 and close[i] > dn_prev
        sell[i] = ready and prev == 1 and close[i] < up_prev
        current = 1 if buy[i] else (-1 if sell[i] else prev)
        trend[i] = current
    out = df.copy()
    out["buy"], out["sell"], out["trend"] = buy, sell, trend
    return out


def one_symbol(symbol):
    global LAST_REQUEST
    try:
        with LOCK:
            delay = MIN_REQUEST_GAP - (time.monotonic() - LAST_REQUEST)
            if delay > 0:
                time.sleep(delay)
            LAST_REQUEST = time.monotonic()
        last_error = None
        df = None
        for attempt in range(5):
            try:
                df = PROVIDER.get_history(symbol, period=PERIOD, interval="2h", exchange="BIST")
                break
            except Exception as exc:
                last_error = exc
                msg = str(exc)
                if ("429" not in msg and "Too Many Requests" not in msg) or attempt == 4:
                    raise
                wait = min(60, 5 * (2 ** attempt))
                print(f"RATE_LIMIT {symbol}: {wait}s bekleniyor")
                time.sleep(wait)
        if df is None or df.empty:
            return {"symbol": symbol, "error": "Veri yok"}
        df = df.copy()
        ren = {col: str(col).lower().capitalize() for col in df.columns
               if str(col).lower() in {"open", "high", "low", "close", "volume"}}
        df.rename(columns=ren, inplace=True)
        if not {"High", "Low", "Close"}.issubset(df.columns):
            return {"symbol": symbol, "error": "OHLC eksik"}
        idx = pd.to_datetime(df.index)
        df.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        if len(df) < ATR_PERIOD + 5:
            return {"symbol": symbol, "error": "Yetersiz geçmiş"}
        out = calculate(df)
        trades, position = [], None
        for ts, row in out.iterrows():
            price = float(row["Close"])
            stamp = ts.isoformat()
            if bool(row["buy"]) and position is None:
                position = {"symbol": symbol, "buy_time": stamp, "buy_price": price}
            elif bool(row["sell"]) and position is not None:
                pnl = price - position["buy_price"]
                trades.append({**position, "sell_time": stamp, "sell_price": price,
                               "pnl_per_share": round(pnl, 6),
                               "pnl_percent": round((price / position["buy_price"] - 1) * 100, 4),
                               "status": "CLOSED_HISTORICAL_VIRTUAL"})
                position = None
        open_position = None
        if position is not None:
            price = float(out["Close"].iloc[-1])
            open_position = {**position, "last_time": out.index[-1].isoformat(),
                             "last_price": price,
                             "unrealized_pnl_per_share": round(price-position["buy_price"], 6),
                             "unrealized_pnl_percent": round((price/position["buy_price"]-1)*100, 4),
                             "status": "OPEN_HISTORICAL_VIRTUAL"}
        return {"symbol": symbol, "bars": len(out), "trades": trades, "open_position": open_position,
                "last_bar": out.index[-1].isoformat()}
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}


def main():
    started = datetime.now(IST)
    print("BACKTEST_START_IST=" + started.isoformat())
    symbols = get_symbols()
    print("SYMBOL_COUNT=" + str(len(symbols)))
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        jobs = [pool.submit(one_symbol, symbol) for symbol in symbols]
        for job in as_completed(jobs):
            item = job.result()
            (errors if "error" in item else results).append(item)
    trades = [trade for item in results for trade in item["trades"]]
    open_positions = [item["open_position"] for item in results if item.get("open_position")]
    trades.sort(key=lambda x: x["sell_time"])
    wins = [t for t in trades if t["pnl_per_share"] > 0]
    losses = [t for t in trades if t["pnl_per_share"] < 0]
    report = {
        "run_time_istanbul": datetime.now(IST).isoformat(),
        "status": "HISTORICAL_BACKTEST_ONLY",
        "period": PERIOD, "timeframe": "2h", "atr_period": ATR_PERIOD,
        "multiplier": MULTIPLIER, "source": "HL2",
        "entry_rule": "BUY reversal at signal candle close",
        "exit_rule": "SELL reversal at signal candle close",
        "symbols_requested": len(symbols), "symbols_successful": len(results),
        "symbols_failed": len(errors), "total_closed_virtual_trades": len(trades),
        "profitable_trades": len(wins), "losing_trades": len(losses),
        "win_rate_percent": round(len(wins)/len(trades)*100, 2) if trades else None,
        "sum_pnl_per_share": round(sum(t["pnl_per_share"] for t in trades), 6),
        "open_historical_positions": len(open_positions),
        "closed_trades": trades, "open_positions": open_positions,
        "errors": errors[:30],
        "warning": "Historical simulation only; no commissions, slippage, position sizing, or broker orders. Not proof of live signal parity."
    }
    Path("historical_backtest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"closed_trades","open_positions","errors"}}, ensure_ascii=False, indent=2))
    for item in errors[:20]:
        print(f'ERROR {item["symbol"]}: {item["error"]}')

if __name__ == "__main__":
    main()
