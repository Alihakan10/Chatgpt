#!/usr/bin/env python3
"""Compare non-Supertrend BIST 2H strategies; virtual research only."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from borsapy._providers.tradingview import TradingViewProvider
from tradingview_screener import Query

IST = ZoneInfo("Europe/Istanbul")
PERIOD = "6mo"
TIMEFRAME = "2h"
COMMISSION_PER_SIDE = 0.001
SLIPPAGE_PER_SIDE = 0.001
ROUND_TRIP_COST = (1 + COMMISSION_PER_SIDE + SLIPPAGE_PER_SIDE) * (1 + COMMISSION_PER_SIDE + SLIPPAGE_PER_SIDE) - 1
MAX_WORKERS = 2
MIN_REQUEST_GAP = 1.25
LOCK = threading.Lock()
LAST_REQUEST = 0.0
PROVIDER = TradingViewProvider()
PROVIDER.TIMEFRAMES["2h"] = "120"


def get_symbols():
    _, frame = Query().select("name", "close").set_markets("turkey").limit(1000).get_scanner_data()
    if frame is None or frame.empty or "ticker" not in frame.columns:
        raise RuntimeError("TradingView Screener did not return symbols")
    symbols = []
    for raw in frame["ticker"].dropna().astype(str):
        raw = raw.upper().strip()
        if ":" in raw:
            exchange, symbol = raw.split(":", 1)
            if exchange != "BIST":
                continue
        else:
            symbol = raw
        if symbol:
            symbols.append(symbol)
    return sorted(set(symbols))


def normalize_history(df):
    df = df.copy()
    rename = {}
    for col in df.columns:
        key = str(col).lower()
        if key in {"open", "high", "low", "close", "volume"}:
            rename[col] = key.capitalize()
    df.rename(columns=rename, inplace=True)
    if not {"High", "Low", "Close"}.issubset(df.columns):
        raise ValueError("OHLC columns missing")
    idx = pd.to_datetime(df.index)
    df.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    return df[~df.index.duplicated(keep="last")].sort_index()


def indicators(df):
    x = df.copy()
    close = x["Close"].astype(float)
    high, low = x["High"].astype(float), x["Low"].astype(float)
    x["ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    x["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi14"] = 100 - 100/(1+rs)
    x["prior20_high"] = high.shift(1).rolling(20, min_periods=20).max()
    x["prior10_low"] = low.shift(1).rolling(10, min_periods=10).min()
    x["bb_mid"] = close.rolling(20, min_periods=20).mean()
    x["bb_std"] = close.rolling(20, min_periods=20).std(ddof=0)
    x["bb_lower"] = x["bb_mid"] - 2*x["bb_std"]
    x["bb_upper"] = x["bb_mid"] + 2*x["bb_std"]
    return x


def signals(df):
    x = indicators(df)
    close = x["Close"].astype(float)
    previous_rsi = x["rsi14"].shift(1)
    strategies = {
        "ema_trend_rsi_pullback": (
            (x["ema20"] > x["ema50"]) & (close > x["ema50"]) &
            (previous_rsi < 40) & (x["rsi14"] >= 40),
            (close < x["ema20"]) | (x["rsi14"] >= 70),
        ),
        "donchian_20_10": (
            close > x["prior20_high"],
            close < x["prior10_low"],
        ),
        "bollinger_rsi_mean_reversion": (
            (close < x["bb_lower"]) & (x["rsi14"] < 35),
            (close >= x["bb_mid"]) | (x["rsi14"] >= 55),
        ),
    }
    return x, strategies


def make_trades(symbol, x, buy, sell, split_time):
    rows = []
    holding = None
    close = x["Close"].astype(float)
    for i, ts in enumerate(x.index):
        if pd.isna(close.iloc[i]):
            continue
        if holding is None and bool(buy.iloc[i]):
            holding = (ts, float(close.iloc[i]))
        elif holding is not None and bool(sell.iloc[i]):
            entry_time, entry = holding
            exit_price = float(close.iloc[i])
            net_factor = (exit_price / entry) / (1 + COMMISSION_PER_SIDE + SLIPPAGE_PER_SIDE)**2
            rows.append({
                "symbol": symbol, "entry_time": entry_time.isoformat(),
                "exit_time": ts.isoformat(), "entry_price": entry,
                "exit_price": exit_price, "net_return": net_factor - 1,
                "split": "oos" if entry_time >= split_time and ts >= split_time else
                         ("train" if entry_time < split_time and ts < split_time else "crosses_split"),
                "status": "CLOSED",
            })
            holding = None
    if holding is not None:
        entry_time, entry = holding
        final_price = float(close.iloc[-1])
        net_factor = (final_price / entry) / (1 + COMMISSION_PER_SIDE + SLIPPAGE_PER_SIDE)**2
        rows.append({
            "symbol": symbol, "entry_time": entry_time.isoformat(),
            "exit_time": x.index[-1].isoformat(), "entry_price": entry,
            "exit_price": final_price, "net_return": net_factor - 1,
            "split": "oos" if entry_time >= split_time else "train",
            "status": "OPEN_MARKED_TO_MARKET",
        })
    return rows


def one_symbol(symbol):
    global LAST_REQUEST
    try:
        with LOCK:
            delay = MIN_REQUEST_GAP - (time.monotonic() - LAST_REQUEST)
            if delay > 0:
                time.sleep(delay)
            LAST_REQUEST = time.monotonic()
        error = None
        for attempt in range(5):
            try:
                raw = PROVIDER.get_history(symbol, period=PERIOD, interval="2h", exchange="BIST")
                break
            except Exception as exc:
                error = exc
                msg = str(exc)
                if ("429" not in msg and "Too Many Requests" not in msg) or attempt == 4:
                    raise
                time.sleep(min(60, 5 * (2 ** attempt)))
        df = normalize_history(raw)
        if len(df) < 120:
            return {"symbol": symbol, "error": f"Insufficient bars: {len(df)}"}
        x, strategy_signals = signals(df)
        split_time = x.index[int(len(x) * 0.70)]
        result = {"symbol": symbol, "bars": len(x), "split_time": split_time.isoformat(), "trades": {}}
        for name, (buy, sell) in strategy_signals.items():
            result["trades"][name] = make_trades(symbol, x, buy.fillna(False), sell.fillna(False), split_time)
        return result
    except Exception as exc:
        return {"symbol": symbol, "error": str(exc)}


def summarize(all_trades):
    summary = {}
    for strategy, trades in all_trades.items():
        oos = [t for t in trades if t["split"] == "oos"]
        closed = [t for t in oos if t["status"] == "CLOSED"]
        returns = [float(t["net_return"]) for t in closed]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        compounded = float(np.prod([1+r for r in returns]) - 1) if returns else None
        summary[strategy] = {
            "oos_closed_trades": len(closed),
            "oos_open_marked_positions": sum(1 for t in oos if t["status"] == "OPEN_MARKED_TO_MARKET"),
            "oos_win_rate_percent": round(len(wins)/len(returns)*100, 2) if returns else None,
            "oos_average_net_trade_percent": round(float(np.mean(returns))*100, 4) if returns else None,
            "oos_compounded_trade_return_percent_non_portfolio": round(compounded*100, 2) if compounded is not None else None,
            "oos_profit_factor": round(gross_profit/gross_loss, 3) if gross_loss else (None if not gross_profit else "infinite"),
            "oos_worst_trade_percent": round(min(returns)*100, 3) if returns else None,
            "train_closed_trades": sum(1 for t in trades if t["split"] == "train" and t["status"] == "CLOSED"),
        }
    return summary


def main():
    start = datetime.now(IST)
    symbols = get_symbols()
    print(f"STRATEGY_RESEARCH_START={start.isoformat()}")
    print(f"SYMBOLS_REQUESTED={len(symbols)}")
    print(f"PERIOD={PERIOD}; TIMEFRAME={TIMEFRAME}; OOS=chronological last 30%; cost per side: commission={COMMISSION_PER_SIDE:.3%}, slippage={SLIPPAGE_PER_SIDE:.3%}")
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        jobs = [pool.submit(one_symbol, s) for s in symbols]
        for job in as_completed(jobs):
            item = job.result()
            (errors if "error" in item else results).append(item)
    all_trades = {"ema_trend_rsi_pullback": [], "donchian_20_10": [], "bollinger_rsi_mean_reversion": []}
    for item in results:
        for name, trades in item["trades"].items():
            all_trades[name].extend(trades)
    metrics = summarize(all_trades)
    eligible = []
    for name, m in metrics.items():
        if (m["oos_closed_trades"] >= 100 and
            m["oos_compounded_trade_return_percent_non_portfolio"] is not None and
            m["oos_compounded_trade_return_percent_non_portfolio"] > 0 and
            m["oos_profit_factor"] not in (None, "infinite") and m["oos_profit_factor"] > 1):
            eligible.append(name)
    # This is a research shortlist only, not automatic deployment approval.
    report = {
        "run_time_istanbul": datetime.now(IST).isoformat(),
        "mode": "RESEARCH_ONLY_VIRTUAL_NO_BROKER_ORDERS",
        "period": PERIOD, "timeframe": TIMEFRAME,
        "symbols_requested": len(symbols), "symbols_successful": len(results), "symbols_failed": len(errors),
        "bars_minimum_per_symbol": 120,
        "oos_method": "chronological last 30% per symbol; trades crossing split excluded from OOS summary",
        "cost_assumptions": {"commission_each_side_percent": COMMISSION_PER_SIDE*100, "slippage_each_side_percent": SLIPPAGE_PER_SIDE*100},
        "strategies": metrics,
        "candidate_shortlist": eligible,
        "deployment_decision": "NO_STRATEGY_APPROVED" if not eligible else "REQUIRES_FORWARD_PAPER_TEST_BEFORE_ANY_LIVE_USE",
        "limitations": [
            "All tested strategies are non-Supertrend 2H close-based research rules, not open-candle early signals.",
            "Compounded trade return is a non-portfolio diagnostic and does not account for overlapping capital allocation.",
            "No dividend/rights-adjustment guarantee; data and survivorship bias may remain.",
            "Strategy selection on a finite sample can overfit; no result guarantees future profit.",
            "No real orders or Telegram notifications are sent."
        ],
        "errors_sample": errors[:30],
        "trades": all_trades,
    }
    Path("strategy_research_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"trades","errors_sample"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
