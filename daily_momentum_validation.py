#!/usr/bin/env python3
"""Daily BIST cross-sectional momentum research; virtual only, no orders."""
import json, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from borsapy._providers.tradingview import TradingViewProvider
from tradingview_screener import Query

IST = ZoneInfo("Europe/Istanbul")
PERIOD = "5y"
COMMISSION = 0.001
SLIPPAGE = 0.001
ONE_WAY_COST = COMMISSION + SLIPPAGE
MAX_WORKERS = 2
MIN_REQUEST_GAP = 1.1
_lock = threading.Lock()
_last_request = 0.0
_provider = TradingViewProvider()

def symbols():
    _, df = Query().select("name", "close", "volume").set_markets("turkey").limit(1000).get_scanner_data()
    if df is None or df.empty or "ticker" not in df:
        raise RuntimeError("TradingView Screener sembol listesi döndürmedi")
    out = set()
    for s in df.ticker.dropna().astype(str):
        s = s.upper().strip()
        if ":" in s:
            ex, s = s.split(":", 1)
            if ex != "BIST": continue
        if s and s.isascii(): out.add(s)
    return sorted(out)

def history(symbol):
    global _last_request
    try:
        with _lock:
            wait = MIN_REQUEST_GAP - (time.monotonic() - _last_request)
            if wait > 0: time.sleep(wait)
            _last_request = time.monotonic()
        err = None
        for attempt in range(4):
            try:
                raw = _provider.get_history(symbol, period=PERIOD, interval="1d", exchange="BIST")
                break
            except Exception as e:
                err = e
                if ("429" not in str(e) and "Too Many Requests" not in str(e)) or attempt == 3: raise
                time.sleep(5 * (attempt + 1))
        if raw is None or raw.empty: return symbol, None, "empty history"
        df = raw.copy()
        rename = {c: str(c).capitalize() for c in df.columns if str(c).lower() in {"open","high","low","close","volume"}}
        df.rename(columns=rename, inplace=True)
        if not {"Close","Open","Volume"}.issubset(df.columns):
            return symbol, None, "missing Open/Close/Volume"
        idx = pd.to_datetime(df.index)
        df.index = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df = df[["Open","Close","Volume"]].apply(pd.to_numeric, errors="coerce").dropna(subset=["Open","Close"])
        if len(df) < 500: return symbol, None, f"insufficient daily bars: {len(df)}"
        return symbol, df, None
    except Exception as e:
        return symbol, None, str(e)[:220]

def metrics(daily_returns, equity, turnover, name):
    r = daily_returns.dropna()
    total = float(equity.iloc[-1] - 1)
    years = max(len(r)/252, 0.01)
    cagr = float(equity.iloc[-1] ** (1/years) - 1) if equity.iloc[-1] > 0 else -1.0
    peak = equity.cummax()
    dd = equity/peak - 1
    vol = float(r.std(ddof=1)*np.sqrt(252)) if len(r)>1 else 0.0
    sharpe = float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if len(r)>1 and r.std(ddof=1)>0 else None
    return {"name":name,"total_return_percent":round(total*100,2),"cagr_percent":round(cagr*100,2),
            "annualized_volatility_percent":round(vol*100,2),"sharpe_rf0":round(sharpe,3) if sharpe is not None else None,
            "max_drawdown_percent":round(float(dd.min())*100,2),"daily_observations":int(len(r)),
            "rebalances":int(turnover.ne(0).sum()),"total_one_way_turnover":round(float(turnover.sum()),3)}

def main():
    start = datetime.now(IST).isoformat()
    tickers = symbols()
    print(f"START={start}; PERIOD={PERIOD}; symbols={len(tickers)}")
    frames, errors = {}, []
    # Keep benchmark separate from stock universe.
    tasks = tickers + ["XU100"]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(history, s) for s in tasks]
        for f in as_completed(futures):
            s, df, err = f.result()
            if df is None: errors.append({"symbol":s,"error":err})
            else: frames[s] = df
    if "XU100" not in frames:
        raise RuntimeError("XU100 benchmark daily history unavailable; cannot fairly compare")
    # Use close data, and only symbols with usable history. Point-in-time universe isn't available from screener.
    closes = pd.DataFrame({s:d["Close"] for s,d in frames.items() if s!="XU100"}).sort_index()
    volumes = pd.DataFrame({s:d["Volume"] for s,d in frames.items() if s!="XU100"}).reindex(closes.index)
    benchmark = frames["XU100"]["Close"].reindex(closes.index).ffill()
    # Restrict to shared dates where benchmark exists; indicators use only past observations.
    valid_dates = benchmark.dropna().index
    closes, volumes, benchmark = closes.loc[valid_dates], volumes.loc[valid_dates], benchmark.loc[valid_dates]
    sma200_bench = benchmark.rolling(200, min_periods=200).mean()
    stock_sma100 = closes.rolling(100, min_periods=100).mean()
    stock_sma200 = closes.rolling(200, min_periods=200).mean()
    # 12-1 month momentum plus 6-1 month confirmation; avoid most recent 21 sessions.
    mom12 = closes.shift(21) / closes.shift(252) - 1
    mom6 = closes.shift(21) / closes.shift(126) - 1
    # Liquidity filter: 20-day average traded value approximated with close*volume.
    traded_value = closes * volumes
    liquid = traded_value.rolling(20, min_periods=20).mean() >= 10_000_000
    # Rebalance monthly at the last available session of each calendar month. Signals use that close,
    # and holdings' return starts the following session (shift target weights by one row).
    month = pd.Series(closes.index.to_period("M"), index=closes.index)
    rebalance_dates = month[month.ne(month.shift(-1))].index
    # Sparse target weights: every month-end explicitly records either selected holdings or cash.
    target = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
    for dt in rebalance_dates:
        target.loc[dt] = 0.0
        regime_ok = pd.notna(sma200_bench.loc[dt]) and benchmark.loc[dt] > sma200_bench.loc[dt]
        if not regime_ok:
            continue
        scores = (mom12.loc[dt] + mom6.loc[dt]) / 2
        eligible = ((closes.loc[dt] > stock_sma200.loc[dt]) &
                    (closes.loc[dt] > stock_sma100.loc[dt]) &
                    (mom12.loc[dt] > 0) & (mom6.loc[dt] > 0) &
                    liquid.loc[dt].fillna(False))
        ranked = scores[eligible & scores.notna()].sort_values(ascending=False).head(10)
        if len(ranked):
            target.loc[dt, ranked.index] = 1.0 / len(ranked)
    # Hold month-end targets through the next rebalance; apply one session later to avoid lookahead.
    target = target.ffill().fillna(0.0)
    applied = target.shift(1).fillna(0.0)
    asset_returns = closes.pct_change().replace([np.inf,-np.inf],np.nan).fillna(0.0)
    gross = (applied * asset_returns).sum(axis=1)
    # Charge costs on target turnover at the execution session following each rebalance.
    changes = target.diff().abs().sum(axis=1).fillna(target.iloc[0].abs().sum())
    applied_turnover = changes.shift(1).fillna(changes.iloc[0])
    net = gross - applied_turnover * ONE_WAY_COST
    equity = (1+net).cumprod()
    bench_ret = benchmark.pct_change().fillna(0.0)
    bench_equity = (1+bench_ret).cumprod()
    # OOS = last 30% of dates, with independent start equity and no parameter tuning.
    split = closes.index[int(len(closes)*0.70)]
    oos_idx = closes.index[closes.index >= split]
    oos_net = net.loc[oos_idx]
    oos_equity = (1+oos_net).cumprod()
    oos_turn = applied_turnover.loc[oos_idx]
    oos_bret = bench_ret.loc[oos_idx]
    oos_beq = (1+oos_bret).cumprod()
    summary = {
        "run_time_istanbul":datetime.now(IST).isoformat(),
        "mode":"DAILY_CROSS_SECTIONAL_MOMENTUM_VIRTUAL_ONLY",
        "strategy":{
            "market_regime":"XU100 close above 200-day SMA; otherwise cash at monthly rebalance",
            "universe":"TradingView current Turkey/BIST screener; liquidity filter average 20-day traded value >= TRY 10m",
            "ranking":"top 10 eligible stocks by mean of 12-1 month and 6-1 month returns",
            "filters":"close above SMA100 and SMA200; both 6-1 and 12-1 month returns positive",
            "rebalance":"monthly; signals at month-end close, weights applied next session",
            "positioning":"equal-weight top 10, max 10 positions, no leverage",
            "costs_each_side_percent":{"commission":COMMISSION*100,"slippage":SLIPPAGE*100}
        },
        "data":{"period":PERIOD,"symbols_requested":len(tickers),"symbols_with_history":len(closes.columns),
                "symbols_failed":len(errors),"benchmark":"XU100","start":str(closes.index.min()),"end":str(closes.index.max()),
                "sessions":len(closes),"oos_start":str(split)},
        "full_period":{"strategy":metrics(net,equity,applied_turnover,"strategy"),
                       "xu100_buy_hold":metrics(bench_ret,bench_equity,pd.Series(0,index=bench_ret.index),"XU100 buy-and-hold")},
        "out_of_sample":{"strategy":metrics(oos_net,oos_equity,oos_turn,"strategy"),
                         "xu100_buy_hold":metrics(oos_bret,oos_beq,pd.Series(0,index=oos_bret.index),"XU100 buy-and-hold"),
                         "excess_return_percentage_points":round((float(oos_equity.iloc[-1])-float(oos_beq.iloc[-1]))*100,2)},
        "decision":"REJECT" if (float(oos_equity.iloc[-1]) <= 1 or float(oos_equity.iloc[-1]) <= float(oos_beq.iloc[-1]) or metrics(oos_net,oos_equity,oos_turn,"x")["max_drawdown_percent"] <= -40) else "PROMISING_BUT_REQUIRES_FORWARD_PAPER_TEST",
        "limitations":["Current screener universe creates survivorship bias; delisted historical stocks are absent.",
                       "Provider daily data may not be dividend/rights-adjusted; corporate actions can distort long-history returns.",
                       "Liquidity uses close*volume proxy; actual spread/market impact can be higher.",
                       "Monthly close signal applied from next session; costs modelled as 0.1% commission + 0.1% slippage per side.",
                       "No parameter optimization was performed; one chronological 70/30 split only.",
                       "This is research, not financial advice; no broker orders or Telegram messages are sent."],
        "errors_sample":errors[:40],
        "oos_monthly_equity":{"strategy":{str(k.date()):round(float(v),5) for k,v in oos_equity.resample("ME").last().dropna().items()},
                              "xu100":{str(k.date()):round(float(v),5) for k,v in oos_beq.resample("ME").last().dropna().items()}}
    }
    Path("daily_momentum_report.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
