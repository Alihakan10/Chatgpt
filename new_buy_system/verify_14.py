from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import math, sys, json, os, time
from html import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scanner
from scanner import get_tv_candles, get_bist_symbols, send_telegram
from new_buy_system.buy_engine import Candle, latest_result

SYMBOLS = []  # populated from TradingView scanner at runtime
P=10; M=2.0
MOMENTUM_MIN=0.0
RVOL_MIN=1.20
BODY_RATIO_MIN=0.50


def rma(v,p):
    o=[math.nan]*len(v)
    if len(v)<p:return o
    o[p-1]=sum(v[:p])/p
    a=1/p
    for i in range(p,len(v)): o[i]=a*v[i]+(1-a)*o[i-1]
    return o

def reference(c):
    tr=[]
    for i,x in enumerate(c):
        if i==0: tr.append(x.high-x.low)
        else:
            pc=c[i-1].close
            tr.append(max(x.high-x.low,abs(x.high-pc),abs(x.low-pc)))
    atr=rma(tr,P); upb=[math.nan]*len(c); dnb=[math.nan]*len(c)
    trend=1; dirs=[0]*len(c); first=P-1
    for i,x in enumerate(c):
        if math.isnan(atr[i]): dirs[i]=trend; continue
        h=(x.high+x.low)/2
        up=h-M*atr[i]; dn=h+M*atr[i]
        up1=up if i==first or math.isnan(upb[i-1]) else upb[i-1]
        dn1=dn if i==first or math.isnan(dnb[i-1]) else dnb[i-1]
        pc=c[i-1].close if i else x.close
        if pc>up1: up=max(up,up1)
        if pc<dn1: dn=min(dn,dn1)
        upb[i]=up; dnb[i]=dn
        if i>first:
            if trend==-1 and x.close>dn1: trend=1
            elif trend==1 and x.close<up1: trend=-1
        dirs[i]=trend
    return dirs

def tv_native(symbol, interval, count=300):
    ws=None
    cs=scanner.random_session("cs"); qs=scanner.random_session("qs")
    candles={}; raw_buffer=""
    try:
        for attempt in range(1,4):
            try:
                headers=[]
                sid=os.getenv("TV_SESSIONID","").strip()
                sid_sign=os.getenv("TV_SESSIONID_SIGN","").strip()
                if sid:
                    cookie="sessionid="+sid
                    if sid_sign: cookie += "; sessionid_sign="+sid_sign
                    headers.append("Cookie: "+cookie)
                ws=scanner.websocket.create_connection(scanner.TV_WS_URL,timeout=scanner.WS_TIMEOUT,
                    origin="https://www.tradingview.com",header=headers)
                break
            except Exception:
                if attempt>=3: raise
                time.sleep(2*attempt)
        if ws is None: raise RuntimeError("TradingView WebSocket baglantisi kurulamadi.")
        ws.send(scanner.tv_message("set_auth_token",[scanner.get_tradingview_auth_token()]))
        ws.send(scanner.tv_message("chart_create_session",[cs,""]))
        ws.send(scanner.tv_message("quote_create_session",[qs]))
        ws.send(scanner.tv_message("quote_set_fields",[qs,"lp","volume","ch","chp"]))
        sym=json.dumps({"symbol":symbol,"adjustment":"splits","session":"regular"},separators=(",",":"))
        ws.send(scanner.tv_message("quote_add_symbols",[qs,symbol]))
        ws.send(scanner.tv_message("resolve_symbol",[cs,"sds_sym_1","="+sym]))
        ws.send(scanner.tv_message("create_series",[cs,"sds_1","s1","sds_sym_1",interval,count,""]))
        ws.send(scanner.tv_message("switch_timezone",[cs,"exchange"]))
        start=time.time(); complete=False
        while time.time()-start < scanner.WS_TIMEOUT:
            try: packet=ws.recv()
            except scanner.websocket.WebSocketTimeoutException: break
            if packet is None: break
            if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
            raw_buffer += packet
            messages,raw_buffer=scanner.extract_tv_messages(raw_buffer)
            for full,payload in messages:
                if payload.startswith("~h~"):
                    try: ws.send(full)
                    except Exception: pass
                    continue
                try: obj=json.loads(payload)
                except Exception: continue
                method=obj.get("m"); params=obj.get("p",[])
                if method=="series_completed": complete=True; continue
                if method in ("symbol_error","series_error","critical_error"):
                    raise RuntimeError(f"{method}: {params}")
                if method not in ("timescale_update","du") or len(params)<2: continue
                container=params[1]
                if not isinstance(container,dict): continue
                series=container.get("sds_1")
                if not isinstance(series,dict):
                    for v in container.values():
                        if isinstance(v,dict) and "s" in v: series=v; break
                if not isinstance(series,dict): continue
                for bar in series.get("s",[]):
                    vals=bar.get("v") if isinstance(bar,dict) else None
                    if not isinstance(vals,list) or len(vals)<6: continue
                    try:
                        ts,op,hi,lo,cl=map(float,vals[:5]); vol=float(vals[5] or 0.0)
                        if not all(math.isfinite(x) for x in (ts,op,hi,lo,cl)) or hi<lo: continue
                        candles[ts]={"time":ts,"open":op,"high":hi,"low":lo,"close":cl,"volume":vol}
                    except Exception: pass
            if complete and len(candles)>=30: break
        out=sorted(candles.values(),key=lambda x:x["time"])
        if len(out)<30: raise RuntimeError(f"TradingView {interval} verisi yetersiz: {len(out)} mum")
        return out
    finally:
        if ws:
            try: ws.close()
            except Exception: pass

def trend_from_rows(rows):
    c=[Candle(float(x["time"]),float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"])) for x in rows]
    return reference(c)[-1]

def filter_metrics(rows):
    x=rows[-1]; prev=rows[-2]
    momentum=x["close"]/prev["close"]-1.0
    vols=[r["volume"] for r in rows[:-1][-20:] if r["volume"]>0]
    avg=sum(vols)/len(vols) if vols else 0.0
    rvol=x["volume"]/avg if avg>0 and x["volume"]>0 else None
    rng=x["high"]-x["low"]; body=abs(x["close"]-x["open"])
    return {"momentum":momentum,"rvol":rvol,"body_ratio":body/rng if rng>0 else 0.0,
            "close":x["close"],"time":x["time"]}

def fmt(ts):
    return datetime.fromtimestamp(ts,tz=ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")

def main():
    symbols=get_bist_symbols()[:620]
    lines=[f"=== NEW BUY SYSTEM + CONFIRMATION FILTERS ===",
           "Native 2H | ATR 10 | Multiplier 2.0 | HL2 | Wilder RMA",
           "Filters: 2H momentum > 0% | RVOL >= 1.20 | body >= 50% | 4H AL | 1D AL",
           "No Study | production scanner/state untouched",""]
    ok=errors=buys=matches=0; buy_rows=[]
    for s in symbols:
        try:
            raw=sorted(get_tv_candles(s,candle_mode="native_2h",candle_session="regular"),key=lambda x:float(x["time"]))
            candles=[Candle(float(x["time"]),float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"])) for x in raw]
            e=latest_result(candles); d=reference(candles); rp,rc=d[-2],d[-1]; rb=(rp==-1 and rc==1)
            same=(e["previous_direction"]==rp and e["current_direction"]==rc and e["buy"]==rb)
            ok+=1; buys+=int(e["buy"]); matches+=int(same)
            if e["buy"]:
                m=filter_metrics(raw)
                buy_rows.append({"symbol":s,"close":m["close"],"time":m["time"],"momentum":m["momentum"],
                                 "rvol":m["rvol"],"body_ratio":m["body_ratio"],"trend4":None,"trend1":None,"confirmed":False})
            lines.append(f"{s}: ENGINE={e['previous_direction']}->{e['current_direction']} BUY={e['buy']} | REF={rp}->{rc} BUY={rb} | MATCH={same} | CANDLE={fmt(candles[-1].timestamp)}")
        except Exception as ex:
            errors+=1; lines.append(f"{s}: ERROR={ex}")

    for row in buy_rows:
        try:
            row["trend4"]=trend_from_rows(tv_native(row["symbol"],"240",300))
            row["trend1"]=trend_from_rows(tv_native(row["symbol"],"1D",300))
            row["confirmed"]=(row["momentum"]>MOMENTUM_MIN and row["rvol"] is not None and row["rvol"]>=RVOL_MIN
                              and row["body_ratio"]>=BODY_RATIO_MIN and row["trend4"]==1 and row["trend1"]==1)
        except Exception as ex:
            row["confirm_error"]=str(ex)
    confirmed=[r for r in buy_rows if r["confirmed"]]
    summary=f"SUMMARY OK={ok} ERRORS={errors} BUY={buys} CONFIRMED={len(confirmed)} MATCH={matches}/{ok} TOTAL={len(symbols)}"
    lines += ["",summary,""] + [
        f"{r['symbol']}: MOM={r['momentum']*100:.2f}% RVOL={(r['rvol'] if r['rvol'] is not None else 0):.2f} BODY={r['body_ratio']*100:.0f}% 4H={r['trend4']} 1D={r['trend1']} CONFIRMED={r['confirmed']}"
        for r in buy_rows]
    Path("new_buy_system/verification_14_result.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))

    tg=["🔔 <b>BIST BUY + YÜKSELİŞ TEYİT TARAMASI</b>","━━━━━━━━━━━━━━━━━━━━",
        "⏱ <b>2H BUY</b> | ATR 10 | Çarpan 2.0 | HL2",
        "🔎 <b>FİLTRELER</b> • Momentum &gt; 0% • RVOL ≥ 1.20 • Gövde ≥ %50 • 4H AL • 1D AL",
        "━━━━━━━━━━━━━━━━━━━━",f"📊 Tarama: <b>{ok}/{len(symbols)}</b>",
        f"🟢 Ham BUY (SAT → AL): <b>{buys}</b>",f"⭐ Tüm filtreleri geçen: <b>{len(confirmed)}</b>",""]
    if confirmed:
        tg.append("⭐ <b>TEYİTLİ BUY</b>")
        for i,r in enumerate(confirmed,1):
            t=r["symbol"].split(":",1)[-1]; u=f"https://www.tradingview.com/chart/?symbol=BIST%3A{t}"
            tg += [f'{i}. <a href="{u}"><b>{escape(t)}</b></a> — {r["close"]:.2f} TL',
                   f'   📈 Momentum: <b>+{r["momentum"]*100:.2f}%</b> | 📊 RVOL: <b>{r["rvol"]:.2f}</b> | 🕯 Gövde: <b>%{r["body_ratio"]*100:.0f}</b>',
                   "   2H: <b>SAT → AL</b> | 4H: <b>AL</b> | 1D: <b>AL</b>",f'   🕯 Mum: <b>{escape(fmt(r["time"]))}</b>']
    else: tg.append("⭐ <b>TEYİTLİ BUY YOK</b>")
    if buy_rows:
        tg += ["","📋 <b>HAM BUY ADAYLARI</b>"]
        for i,r in enumerate(buy_rows,1):
            t=r["symbol"].split(":",1)[-1]; u=f"https://www.tradingview.com/chart/?symbol=BIST%3A{t}"
            rv=f"{r['rvol']:.2f}" if r["rvol"] is not None else "N/A"
            tr4="AL" if r["trend4"]==1 else "SAT" if r["trend4"]==-1 else "?"
            tr1="AL" if r["trend1"]==1 else "SAT" if r["trend1"]==-1 else "?"
            tg.append(f'{i}. <a href="{u}"><b>{escape(t)}</b></a> — {r["close"]:.2f} TL | M:{r["momentum"]*100:+.2f}% | RV:{rv} | Gövde:%{r["body_ratio"]*100:.0f} | 4H:{tr4} | 1D:{tr1} | {"⭐ TEYİTLİ" if r["confirmed"] else "⚪ Filtre dışı"}')
    else: tg.append("🟢 Son tamamlanan 2H mumda yeni BUY yok.")
    tg += ["",f"🔍 BUY motoru doğrulaması: <b>{matches}/{ok}</b>","⚙️ Study kullanılmadı.","ℹ️ Filtreler yükselişi garanti etmez."]
    try:
        send_telegram("\n".join(tg)); print("TELEGRAM: Ayrıntılı BUY + teyit sonucu gönderildi.")
    except Exception as exc:
        print("TELEGRAM ERROR:",exc); raise

if __name__=="__main__": main()
