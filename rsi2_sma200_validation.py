#!/usr/bin/env python3
"""Independent long-only RSI(2) pullback research for BIST 2H. No live orders."""
import json, threading, time
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
COMMISSION = 0.001
SLIPPAGE = 0.001
SIDE_COST = 1 + COMMISSION + SLIPPAGE
MAX_WORKERS = 2
REQUEST_GAP = 1.25
START_CASH = 100_000.0
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
    out = []
    for raw in frame["ticker"].dropna().astype(str):
        raw = raw.upper().strip()
        if ":" in raw:
            exchange, symbol = raw.split(":", 1)
            if exchange != "BIST": continue
        else: symbol = raw
        if symbol: out.append(symbol)
    return sorted(set(out))

def normalize(df):
    x = df.copy()
    x.rename(columns={c: str(c).capitalize() for c in x.columns if str(c).lower() in {"open","high","low","close","volume"}}, inplace=True)
    if not {"High","Low","Close"}.issubset(x.columns): raise ValueError("OHLC columns missing")
    idx = pd.to_datetime(x.index)
    x.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    return x[~x.index.duplicated(keep="last")].sort_index()

def trades_for_symbol(symbol, raw):
    x = normalize(raw)
    if len(x) < 240: return [], "Insufficient bars for SMA200 plus warmup"
    c = x["Close"].astype(float)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi2 = 100 - 100/(1+rs)
    sma5 = c.rolling(5, min_periods=5).mean()
    sma200 = c.rolling(100, min_periods=100).mean()
    prev_c = c.shift(1)
    tr = pd.concat([(x["High"]-x["Low"]).abs(), (x["High"]-prev_c).abs(), (x["Low"]-prev_c).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    split = x.index[int(len(x)*0.70)]
    result, holding = [], None
    for i, ts in enumerate(x.index):
        price = float(c.iloc[i])
        if not np.isfinite(price): continue
        if holding is None:
            if pd.notna(sma200.iloc[i]) and pd.notna(rsi2.iloc[i]) and price > float(sma200.iloc[i]) and float(rsi2.iloc[i]) < 10:
                holding = {"time":ts, "price":price, "atr":float(atr14.iloc[i]) if pd.notna(atr14.iloc[i]) else 0.0, "bar":i}
        else:
            stop = holding["price"] - 2.0*holding["atr"]
            time_exit = i - holding["bar"] >= 20
            trend_exit = pd.notna(sma200.iloc[i]) and price < float(sma200.iloc[i])
            mean_exit = pd.notna(sma5.iloc[i]) and price > float(sma5.iloc[i])
            if price <= stop or time_exit or trend_exit or mean_exit:
                entry_t, entry_p = holding["time"], holding["price"]
                net = (price/entry_p)/(SIDE_COST**2)-1
                tag = "oos" if entry_t >= split and ts >= split else ("train" if entry_t < split and ts < split else "crosses_split")
                result.append({"symbol":symbol,"entry_time":entry_t.isoformat(),"exit_time":ts.isoformat(),
                    "entry_price":entry_p,"exit_price":price,"net_return":net,"split":tag,"status":"CLOSED",
                    "exit_reason":"stop_2ATR" if price <= stop else ("time_20_bars" if time_exit else ("below_SMA200" if trend_exit else "above_SMA5"))})
                holding = None
    if holding is not None:
        entry_t, entry_p = holding["time"], holding["price"]
        final_p = float(c.iloc[-1])
        result.append({"symbol":symbol,"entry_time":entry_t.isoformat(),"exit_time":x.index[-1].isoformat(),
            "entry_price":entry_p,"exit_price":final_p,"net_return":(final_p/entry_p)/(SIDE_COST**2)-1,
            "split":"oos" if entry_t >= split else "train","status":"OPEN_MARKED_TO_MARKET","exit_reason":"period_end"})
    return result, None

def fetch(symbol):
    global LAST_REQUEST
    try:
        with LOCK:
            wait = REQUEST_GAP-(time.monotonic()-LAST_REQUEST)
            if wait > 0: time.sleep(wait)
            LAST_REQUEST=time.monotonic()
        error=None
        for attempt in range(5):
            try:
                raw=PROVIDER.get_history(symbol, period=PERIOD, interval="2h", exchange="BIST")
                return trades_for_symbol(symbol, raw)
            except Exception as exc:
                error=str(exc)
                if ("429" not in error and "Too Many Requests" not in error) or attempt==4: break
                time.sleep(min(60,5*(2**attempt)))
        return [], error
    except Exception as exc: return [], str(exc)

def simulate(trades):
    ts=[dict(t) for t in trades if t["split"]=="oos"]
    events=[]
    for t in ts:
        events.append((t["exit_time"],0,t))
        events.append((t["entry_time"],1,t))
    events.sort(key=lambda e:(e[0],e[1],e[2]["symbol"]))
    cash=START_CASH; active=[]; seen=set(); accepted=skipped=0; returns=[]; peak=START_CASH; dd=0.0
    for stamp, kind, t in events:
        key=(t["symbol"],t["entry_time"],t["exit_time"])
        if kind==0:
            p=next((p for p in active if p["key"]==key),None)
            if p is None: continue
            cash += p["stake"]*(1+float(t["net_return"]))
            active.remove(p)
            if t["status"]=="CLOSED": returns.append(float(t["net_return"]))
        else:
            if key in seen: continue
            seen.add(key)
            if len(active)>=MAX_POSITIONS or cash<=0: skipped+=1; continue
            stake=min(cash,max(0,(cash+sum(p["stake"] for p in active))*POSITION_FRACTION))
            if stake<=0: skipped+=1; continue
            cash-=stake; active.append({"key":key,"stake":stake}); accepted+=1
        equity=cash+sum(p["stake"] for p in active)
        peak=max(peak,equity)
        if peak>0: dd=max(dd,(peak-equity)/peak)
    return {"starting_capital_try":round(START_CASH,2),"ending_equity_try":round(cash,2),
        "net_profit_try":round(cash-START_CASH,2),"net_return_percent":round((cash/START_CASH-1)*100,3),
        "max_drawdown_percent_realized_equity_only":round(dd*100,3),"accepted_entries":accepted,
        "entries_skipped_capacity":skipped,"closed_trades":len(returns),
        "closed_win_rate_percent":round(sum(r>0 for r in returns)/len(returns)*100,2) if returns else None,
        "avg_closed_trade_percent":round(float(np.mean(returns))*100,3) if returns else None,
        "profit_factor":round(sum(r for r in returns if r>0)/abs(sum(r for r in returns if r<0)),3) if any(r<0 for r in returns) else None,
        "open_positions_at_end":len(active),
        "note":"Realized-equity-only drawdown excludes intratrade swings; not true max drawdown."}

def main():
    started=datetime.now(IST)
    symbols=get_symbols(); all_trades=[]; errors=[]
    print(f"START={started.isoformat()} SYMBOLS={len(symbols)} PERIOD={PERIOD} TIMEFRAME=2h")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures={pool.submit(fetch,s):s for s in symbols}
        for f in as_completed(futures):
            s=futures[f]; items,err=f.result(); all_trades.extend(items)
            if err: errors.append({"symbol":s,"error":err})
    oos_closed=[t for t in all_trades if t["split"]=="oos" and t["status"]=="CLOSED"]
    returns=[float(t["net_return"]) for t in oos_closed]
    port=simulate(all_trades)
    report={"run_time_istanbul":datetime.now(IST).isoformat(),"mode":"VIRTUAL_RESEARCH_ONLY_NO_BROKER_ORDERS_NO_TELEGRAM",
      "strategy":"RSI2_pullback_in_SMA200_uptrend","rules":{"entry":"2H close above SMA200 and RSI(2)<10",
      "exit":"close above SMA5, close below SMA200, close at least 2 ATR(14) below entry, or 20 bars held",
      "execution":"signal filled at signal close; optimistic assumption"},
      "period":PERIOD,"timeframe":"2h","symbols_requested":len(symbols),"symbols_with_errors":len(errors),
      "oos_method":"last 30% chronological per symbol; crossing-split trades excluded",
      "costs_each_side":{"commission_percent":COMMISSION*100,"slippage_percent":SLIPPAGE*100},
      "oos_trade_diagnostics":{"closed_trades":len(oos_closed),"win_rate_percent":round(sum(r>0 for r in returns)/len(returns)*100,2) if returns else None,
      "avg_net_trade_percent":round(float(np.mean(returns))*100,3) if returns else None,
      "profit_factor":round(sum(r for r in returns if r>0)/abs(sum(r for r in returns if r<0)),3) if any(r<0 for r in returns) else None},
      "portfolio_simulation":port,"deployment_decision":"NO_LIVE_DEPLOYMENT; paper validation required",
      "limitations":["No future profit is guaranteed.","Same-close fills are optimistic.","Corporate actions, liquidity, taxes, spreads, and survivorship bias may affect results.",
      "Drawdown is realized-equity-only and excludes intratrade price swings.","No live orders or Telegram notifications."],
      "errors_sample":errors[:30]}
    Path("rsi2_sma200_validation_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
