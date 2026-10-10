#!/usr/bin/env python3
"""Portfolio-level out-of-sample validation for non-Supertrend BIST Bollinger/RSI strategy.
Virtual research only: no broker orders and no notifications.
"""
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
COMMISSION = 0.001
SLIPPAGE = 0.001
SIDE_COST_FACTOR = 1 + COMMISSION + SLIPPAGE
MAX_WORKERS = 2
REQUEST_GAP = 1.25
STARTING_CASH = 100_000.0
MAX_POSITIONS = 10
POSITION_FRACTION = 0.10
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


def make_symbol_trades(symbol, raw):
    x = normalize_history(raw)
    if len(x) < 120:
        return [], f"Insufficient bars: {len(x)}"
    close = x["Close"].astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    mid = close.rolling(20, min_periods=20).mean()
    std = close.rolling(20, min_periods=20).std(ddof=0)
    lower = mid - 2 * std
    buy = (close < lower) & (rsi < 35)
    sell = (close >= mid) | (rsi >= 55)
    split_time = x.index[int(len(x) * 0.70)]
    trades = []
    holding = None
    for i, ts in enumerate(x.index):
        price = float(close.iloc[i])
        if not np.isfinite(price):
            continue
        if holding is None and bool(buy.iloc[i]) if not pd.isna(buy.iloc[i]) else False:
            holding = (ts, price)
        elif holding is not None and bool(sell.iloc[i]) if not pd.isna(sell.iloc[i]) else False:
            entry_time, entry_price = holding
            gross_factor = price / entry_price
            net_factor = gross_factor / (SIDE_COST_FACTOR ** 2)
            split = "oos" if entry_time >= split_time and ts >= split_time else ("train" if entry_time < split_time and ts < split_time else "crosses_split")
            trades.append({
                "symbol": symbol, "entry_time": entry_time.isoformat(), "exit_time": ts.isoformat(),
                "entry_price": entry_price, "exit_price": price, "net_return": net_factor - 1,
                "split": split, "status": "CLOSED"
            })
            holding = None
    if holding is not None:
        entry_time, entry_price = holding
        final_price = float(close.iloc[-1])
        net_factor = (final_price / entry_price) / (SIDE_COST_FACTOR ** 2)
        trades.append({
            "symbol": symbol, "entry_time": entry_time.isoformat(), "exit_time": x.index[-1].isoformat(),
            "entry_price": entry_price, "exit_price": final_price, "net_return": net_factor - 1,
            "split": "oos" if entry_time >= split_time else "train", "status": "OPEN_MARKED_TO_MARKET"
        })
    return trades, None


def fetch_symbol(symbol):
    global LAST_REQUEST
    try:
        with LOCK:
            wait = REQUEST_GAP - (time.monotonic() - LAST_REQUEST)
            if wait > 0:
                time.sleep(wait)
            LAST_REQUEST = time.monotonic()
        last_error = None
        for attempt in range(5):
            try:
                raw = PROVIDER.get_history(symbol, period=PERIOD, interval="2h", exchange="BIST")
                return make_symbol_trades(symbol, raw)
            except Exception as exc:
                last_error = exc
                message = str(exc)
                if ("429" not in message and "Too Many Requests" not in message) or attempt == 4:
                    break
                time.sleep(min(60, 5 * (2 ** attempt)))
        return [], str(last_error)
    except Exception as exc:
        return [], str(exc)


def simulate_portfolio(trades):
    # Only fully out-of-sample entries. The report uses a deterministic timestamp order.
    candidates = [dict(t) for t in trades if t["split"] == "oos"]
    candidates.sort(key=lambda t: (t["entry_time"], t["symbol"]))
    cash = STARTING_CASH
    active = []
    equity_peak = STARTING_CASH
    max_drawdown = 0.0
    accepted = 0
    skipped_capacity = 0
    closed_returns = []
    curve = [{"time": candidates[0]["entry_time"] if candidates else None, "equity": STARTING_CASH}]
    events = []
    for trade in candidates:
        events.append((trade["entry_time"], 1, trade))  # entry event
        events.append((trade["exit_time"], 0, trade))   # exit/mark event before same-time entries
    events.sort(key=lambda e: (e[0], e[1], e[2]["symbol"]))
    seen_entries = set()
    for timestamp, event_type, trade in events:
        key = (trade["symbol"], trade["entry_time"], trade["exit_time"])
        if event_type == 0:
            position = next((p for p in active if p["key"] == key), None)
            if position is None:
                continue
            cash += position["stake"] * (1 + float(trade["net_return"]))
            active.remove(position)
            if trade["status"] == "CLOSED":
                closed_returns.append(float(trade["net_return"]))
        else:
            if key in seen_entries:
                continue
            seen_entries.add(key)
            if len(active) >= MAX_POSITIONS or cash <= 0:
                skipped_capacity += 1
                continue
            stake = min(cash, max(0.0, (cash + sum(p["stake"] for p in active)) * POSITION_FRACTION))
            if stake <= 0:
                skipped_capacity += 1
                continue
            cash -= stake
            active.append({"key": key, "stake": stake, "trade": trade})
            accepted += 1
        equity = cash + sum(p["stake"] * (1 + max(-1.0, (float(p["trade"]["exit_price"]) / float(p["trade"]["entry_price"]) - 1))) for p in active)
        equity_peak = max(equity_peak, equity)
        if equity_peak > 0:
            max_drawdown = max(max_drawdown, (equity_peak - equity) / equity_peak)
        curve.append({"time": timestamp, "equity": round(equity, 2)})
    final_equity = cash
    # Normally all positions are marked at the data endpoint and have an exit/mark event.
    return {
        "starting_capital_try": round(STARTING_CASH, 2),
        "ending_equity_try": round(final_equity, 2),
        "net_profit_try": round(final_equity - STARTING_CASH, 2),
        "net_return_percent": round((final_equity / STARTING_CASH - 1) * 100, 3),
        "max_drawdown_percent_event_estimate": round(max_drawdown * 100, 3),
        "max_open_positions": MAX_POSITIONS,
        "target_position_size_percent_of_equity": POSITION_FRACTION * 100,
        "accepted_entries": accepted,
        "entries_skipped_position_limit_or_cash": skipped_capacity,
        "closed_trades_accepted": len(closed_returns),
        "closed_trade_win_rate_percent": round(sum(r > 0 for r in closed_returns) / len(closed_returns) * 100, 2) if closed_returns else None,
        "open_positions_at_end": len(active),
        "costs": {"commission_each_side_percent": COMMISSION * 100, "slippage_each_side_percent": SLIPPAGE * 100},
        "curve_sample_first_200_events": curve[:200],
        "method_note": "Chronological event simulation; exits before entries at same timestamp; positions sized to 10% of current cash plus invested stake, capped by available cash; unrealized positions are marked using available exit/endpoint price. Results are historical simulation, not a forecast."
    }


def main():
    start = datetime.now(IST)
    symbols = get_symbols()
    print(f"PORTFOLIO_VALIDATION_START={start.isoformat()}")
    print(f"SYMBOLS_REQUESTED={len(symbols)}; PERIOD={PERIOD}; TIMEFRAME={TIMEFRAME}")
    trades, errors = [], []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_symbol, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            symbol_trades, error = future.result()
            trades.extend(symbol_trades)
            if error:
                errors.append({"symbol": symbol, "error": error})
    oos = [t for t in trades if t["split"] == "oos"]
    closed = [t for t in oos if t["status"] == "CLOSED"]
    returns = [float(t["net_return"]) for t in closed]
    portfolio = simulate_portfolio(trades)
    report = {
        "run_time_istanbul": datetime.now(IST).isoformat(),
        "mode": "VIRTUAL_RESEARCH_ONLY_NO_BROKER_ORDERS_NO_TELEGRAM",
        "strategy": "bollinger_rsi_mean_reversion",
        "rules": {
            "entry": "2H close below 20-period Bollinger lower band (2 standard deviations) AND RSI14 < 35",
            "exit": "2H close >= Bollinger middle band OR RSI14 >= 55",
            "execution_assumption": "signal and execution at same 2H close; this is optimistic and requires forward paper validation"
        },
        "period": PERIOD, "timeframe": TIMEFRAME,
        "symbols_requested": len(symbols), "symbols_with_history": len(symbols) - len({e["symbol"] for e in errors}),
        "symbols_with_errors": len(errors),
        "oos_method": "chronological last 30% of each symbol; trades crossing split excluded",
        "oos_trade_level_diagnostic": {
            "closed_trades": len(closed),
            "win_rate_percent": round(sum(r > 0 for r in returns) / len(returns) * 100, 2) if returns else None,
            "average_net_trade_percent": round(float(np.mean(returns)) * 100, 4) if returns else None,
            "profit_factor": round(sum(r for r in returns if r > 0) / abs(sum(r for r in returns if r < 0)), 3) if any(r < 0 for r in returns) else None,
            "worst_trade_percent": round(min(returns) * 100, 3) if returns else None,
            "note": "Trade-level diagnostic is not a portfolio return."
        },
        "portfolio_simulation": portfolio,
        "deployment_decision": "NO_LIVE_DEPLOYMENT; require realistic paper trading and review of drawdown and fills",
        "limitations": [
            "This run is an independent non-Supertrend research project; existing Termux scanner is not modified.",
            "Signal fills at the same close are optimistic and may not be achievable in live trading.",
            "Corporate actions, liquidity, spread variation, taxes, and survivorship bias may affect results.",
            "No profit is guaranteed; no live orders or Telegram messages are sent."
        ],
        "errors_sample": errors[:30]
    }
    Path("portfolio_validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
