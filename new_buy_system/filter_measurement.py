from __future__ import annotations
import json, math, os, sys, time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scanner
from new_buy_system.buy_engine import Candle, calculate_directions

SYMBOLS = ["BIST:ACSEL","BIST:AKSUE","BIST:ATSYH","BIST:BESLR","BIST:BMSCH",
           "BIST:DMRGD","BIST:EMNIS","BIST:ENPRA","BIST:MOBTL","BIST:PETUN"]
INTERVALS = {"2H":"120","4H":"240","1D":"1D"}
BUY_SETTINGS = (10, 2.0)

def tv_native(symbol, interval, count=300):
    ws = None
    cs = scanner.random_session("cs")
    qs = scanner.random_session("qs")
    candles = {}
    raw_buffer = ""
    try:
        for attempt in range(1,4):
            try:
                headers=[]
                sid=os.getenv("TV_SESSIONID","").strip()
                ss=os.getenv("TV_SESSIONID_SIGN","").strip()
                if sid:
                    cookie="sessionid="+sid
                    if ss: cookie += "; sessionid_sign="+ss
                    headers.append("Cookie: "+cookie)
                ws=scanner.websocket.create_connection(
                    scanner.TV_WS_URL, timeout=scanner.WS_TIMEOUT,
                    origin="https://www.tradingview.com", header=headers)
                break
            except Exception as e:
                if attempt>=3: raise
                time.sleep(2*attempt)
        auth=scanner.get_tradingview_auth_token()
        ws.send(scanner.tv_message("set_auth_token",[auth]))
        ws.send(scanner.tv_message("chart_create_session",[cs,""]))
        ws.send(scanner.tv_message("quote_create_session",[qs]))
        ws.send(scanner.tv_message("quote_set_fields",[qs,"lp","volume","ch","chp"]))
        sym=json.dumps({"symbol":symbol,"adjustment":"splits","session":"regular"},separators=(",",":"))
        ws.send(scanner.tv_message("quote_add_symbols",[qs,symbol]))
        ws.send(scanner.tv_message("resolve_symbol",[cs,"sds_sym_1","="+sym]))
        ws.send(scanner.tv_message("create_series",[cs,"sds_1","s1","sds_sym_1",interval,count,""]))
        ws.send(scanner.tv_message("switch_timezone",[cs,"exchange"]))
        start=time.time()
        complete=False
        while time.time()-start < scanner.WS_TIMEOUT:
            try: packet=ws.recv()
            except scanner.websocket.WebSocketTimeoutException: break
            if packet is None: break
            if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
            raw_buffer += packet
            msgs,raw_buffer=scanner.extract_tv_messages(raw_buffer)
            for full,payload in msgs:
                if payload.startswith("~h~"):
                    try: ws.send(full)
                    except: pass
                    continue
                try: obj=json.loads(payload)
                except: continue
                method=obj.get("m"); params=obj.get("p",[])
                if method not in ("timescale_update","du"): 
                    if method=="series_completed": complete=True
                    elif method in ("symbol_error","series_error","critical_error"):
                        raise RuntimeError(f"{method}: {params}")
                    continue
                if len(params)<2 or not isinstance(params[1],dict): continue
                sd=params[1].get("sds_1")
                if not isinstance(sd,dict):
                    for v in params[1].values():
                        if isinstance(v,dict) and "s" in v: sd=v; break
                if not isinstance(sd,dict): continue
                for bar in sd.get("s",[]):
                    vals=bar.get("v") if isinstance(bar,dict) else None
                    if not isinstance(vals,list) or len(vals)<6: continue
                    try:
                        ts,o,h,l,c=map(float,vals[:5])
                        vol=float(vals[5] or 0.0)
                        if all(math.isfinite(x) for x in (ts,o,h,l,c)):
                            candles[ts]={"time":ts,"open":o,"high":h,"low":l,"close":c,"volume":vol}
                    except: pass
            if complete and len(candles)>=30: break
        out=sorted(candles.values(),key=lambda x:x["time"])
        if len(out)<30: raise RuntimeError(f"yetersiz {interval} mum: {len(out)}")
        return out
    finally:
        if ws:
            try: ws.close()
            except: pass

def dirs(rows):
    c=[Candle(r["time"],r["open"],r["high"],r["low"],r["close"]) for r in rows]
    d=calculate_directions(c,*BUY_SETTINGS)
    return d[-1] if d else None

def rma(vals,p=10):
    if len(vals)<p:return []
    out=[math.nan]*len(vals); out[p-1]=sum(vals[:p])/p
    a=1/p
    for i in range(p,len(vals)): out[i]=a*vals[i]+(1-a)*out[i-1]
    return out

def metrics(rows):
    x=rows[-1]; prev=rows[-2]
    mom1=x["close"]/prev["close"]-1
    mom2=x["close"]/rows[-3]["close"]-1
    vols=[r["volume"] for r in rows[:-1][-20:] if r["volume"]>0]
    rvol=(x["volume"]/ (sum(vols)/len(vols))) if vols and x["volume"]>0 else None
    rng=x["high"]-x["low"]
    body=abs(x["close"]-x["open"])
    tr=[]
    for i,r in enumerate(rows):
        if i==0: tr.append(r["high"]-r["low"])
        else:
            pc=rows[i-1]["close"]
            tr.append(max(r["high"]-r["low"],abs(r["high"]-pc),abs(r["low"]-pc)))
    atr=rma(tr,10)[-1]
    return {"mom1":mom1,"mom2":mom2,"rvol":rvol,
            "body_ratio":(body/rng if rng else 0),"range_atr":(rng/atr if atr and atr>0 else None),
            "close":x["close"],"time":x["time"]}

def fmt(ts):
    return datetime.fromtimestamp(ts,ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")

def main():
    data={}
    for s in SYMBOLS:
        print("FETCH",s,flush=True)
        d2=tv_native(s,"120",300); d4=tv_native(s,"240",300); dd=tv_native(s,"1D",300)
        data[s]={"m":metrics(d2),"t4":dirs(d4),"td":dirs(dd)}
        print(s,data[s],flush=True)
    Path("new_buy_system/filter_measurement_result.txt").write_text(json.dumps(data,indent=2),encoding="utf-8")
    rows=[]
    for s,v in data.items():
        m=v["m"]; rows.append({
            "symbol":s.split(":")[-1],"time":fmt(m["time"]),"close":m["close"],
            "mom1_pct":m["mom1"]*100,"mom2_pct":m["mom2"]*100,"rvol":m["rvol"],
            "body_ratio":m["body_ratio"],"range_atr":m["range_atr"],
            "4H":v["t4"],"1D":v["td"]})
    print("\n=== FILTER MEASUREMENT ===")
    for r in rows: print(json.dumps(r,ensure_ascii=False))
    tests=[
        ("2H momentum > 0%", lambda r:r["mom1_pct"]>0),
        ("2H momentum > 0.5%", lambda r:r["mom1_pct"]>0.5),
        ("2H momentum > 1.0%", lambda r:r["mom1_pct"]>1.0),
        ("RVOL >= 1.0", lambda r:r["rvol"] is not None and r["rvol"]>=1.0),
        ("RVOL >= 1.2", lambda r:r["rvol"] is not None and r["rvol"]>=1.2),
        ("RVOL >= 1.5", lambda r:r["rvol"] is not None and r["rvol"]>=1.5),
        ("Candle body >= 50%", lambda r:r["body_ratio"]>=0.5),
        ("4H trend = AL", lambda r:r["4H"]==1),
        ("1D trend = AL", lambda r:r["1D"]==1),
        ("4H + 1D = AL", lambda r:r["4H"]==1 and r["1D"]==1),
        ("Momentum>0 + RVOL>=1.2", lambda r:r["mom1_pct"]>0 and r["rvol"] is not None and r["rvol"]>=1.2),
        ("Momentum>0 + 4H AL + 1D AL", lambda r:r["mom1_pct"]>0 and r["4H"]==1 and r["1D"]==1),
        ("All 5: mom>0 + RVOL>=1.2 + body>=50% + 4H AL + 1D AL", lambda r:r["mom1_pct"]>0 and r["rvol"] is not None and r["rvol"]>=1.2 and r["body_ratio"]>=0.5 and r["4H"]==1 and r["1D"]==1),
    ]
    print("\n=== COMPARISON ===")
    for name,fn in tests:
        passed=[r["symbol"] for r in rows if fn(r)]
        print(f"{name}: {len(passed)}/10 -> {', '.join(passed) if passed else '-'}")
if __name__=="__main__": main()
