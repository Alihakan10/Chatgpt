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



# Hypothetical portfolio assumptions for a comparable, transparent simulation.
STARTING_CAPITAL = 100_000.0
MAX_OPEN_POSITIONS = 10
POSITION_FRACTION = 0.10
COMMISSION_RATE = 0.001   # 0.10% each side
SLIPPAGE_RATE = 0.001     # 0.10% adverse price each side


def simulate_portfolio(closed_trades):
    """Chronological portfolio simulation; skips entries when all slots are occupied."""
    events = []
    for trade in closed_trades:
        events.append((trade["buy_time"], 1, "BUY", trade))
        events.append((trade["sell_time"], 0, "SELL", trade))
    # SELL before BUY at identical timestamps; then stable symbol ordering.
    events.sort(key=lambda e: (e[0], e[1], e[3]["symbol"]))
    cash = STARTING_CAPITAL
    open_positions = {}
    completed = []
    skipped_entries = 0
    equity_points = [(None, STARTING_CAPITAL)]
    for stamp, _, side, trade in events:
        symbol = trade["symbol"]
        if side == "SELL":
            pos = open_positions.pop(symbol, None)
            if pos is None:
                continue
            raw_sell = float(trade["sell_price"])
            executed_sell = raw_sell * (1 - SLIPPAGE_RATE)
            gross_proceeds = pos["shares"] * executed_sell
            sell_fee = gross_proceeds * COMMISSION_RATE
            cash += gross_proceeds - sell_fee
            net_pnl = cash - pos["cash_before_entry"] - sum(
                p["cash_before_entry"] for p in open_positions.values()
            ) if False else (gross_proceeds - sell_fee - pos["entry_cost"])
            completed.append({
                "symbol": symbol, "buy_time": pos["buy_time"], "sell_time": stamp,
                "buy_price_raw": pos["raw_buy"], "sell_price_raw": raw_sell,
                "shares": round(pos["shares"], 6),
                "net_pnl_try": round(net_pnl, 2),
                "net_return_percent": round(net_pnl / pos["entry_cost"] * 100, 4),
            })
            equity_points.append((stamp, cash + sum(
                p["shares"] * p["last_price"] for p in open_positions.values()
            )))
        else:
            if symbol in open_positions:
                continue
            if len(open_positions) >= MAX_OPEN_POSITIONS:
                skipped_entries += 1
                continue
            raw_buy = float(trade["buy_price"])
            executed_buy = raw_buy * (1 + SLIPPAGE_RATE)
            equity = cash + sum(p["shares"] * p["last_price"] for p in open_positions.values())
            budget = min(cash, equity * POSITION_FRACTION)
            shares = budget / (executed_buy * (1 + COMMISSION_RATE))
            entry_cost = shares * executed_buy * (1 + COMMISSION_RATE)
            if shares <= 0 or entry_cost > cash:
                skipped_entries += 1
                continue
            cash -= entry_cost
            open_positions[symbol] = {
                "buy_time": stamp, "raw_buy": raw_buy, "shares": shares,
                "entry_cost": entry_cost, "last_price": raw_buy,
                "cash_before_entry": cash,
            }
            # Link each entry to its later exit using this symbol's trade record.
            open_positions[symbol]["expected_sell_time"] = trade["sell_time"]
    # Mark any positions still open from the source data separately; this simulation only
    # includes fully closed historical trades to avoid inventing future exits.
    final_equity = cash + sum(p["shares"] * p["last_price"] for p in open_positions.values())
    peak = STARTING_CAPITAL
    max_drawdown = 0.0
    for _, value in equity_points:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak * 100)
    return {
        "assumptions": {
            "starting_capital_try": STARTING_CAPITAL,
            "max_concurrent_positions": MAX_OPEN_POSITIONS,
            "position_size_fraction_of_equity": POSITION_FRACTION,
            "commission_each_side_percent": COMMISSION_RATE * 100,
            "slippage_each_side_percent": SLIPPAGE_RATE * 100,
        },
        "completed_portfolio_trades": len(completed),
        "skipped_entries_due_to_slot_or_cash": skipped_entries,
        "ending_equity_try": round(final_equity, 2),
        "net_profit_try": round(final_equity - STARTING_CAPITAL, 2),
        "return_percent": round((final_equity / STARTING_CAPITAL - 1) * 100, 2),
        "max_drawdown_percent_observed_at_closes": round(max_drawdown, 2),
        "open_positions_at_end": len(open_positions),
        "note": "Hypothetical close-to-close model. Open positions are marked using their entry price because this closed-trade event stream does not carry the latest mark; use this as a rough model, not a live performance claim.",
    }

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
        "sum_pnl_per_share_non_portfolio_metric": round(sum(t["pnl_per_share"] for t in trades), 6),
        "portfolio_simulation": simulate_portfolio(trades),
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
