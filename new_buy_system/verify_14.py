from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import math, sys
from html import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner import get_tv_candles, get_bist_symbols, send_telegram
from new_buy_system.buy_engine import Candle, latest_result

SYMBOLS = []  # populated from TradingView scanner at runtime
P=10; M=2.0

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

def fmt(ts):
    return datetime.fromtimestamp(ts,tz=ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")

def main():
    symbols = get_bist_symbols()[:620]
    lines=[f"=== {len(symbols)} STOCK INDEPENDENT BUY VERIFICATION ===",
           "Native 2H | ATR 10 | Multiplier 2.0 | HL2 | Wilder RMA",
           "No Study | production scanner/state/Telegram untouched",""]
    ok=errors=buys=matches=0
    buy_rows=[]
    for s in symbols:
        try:
            raw=sorted(get_tv_candles(s,candle_mode="native_2h",candle_session="regular"),
                       key=lambda x:float(x["time"]))
            c=[Candle(float(x["time"]),float(x["open"]),float(x["high"]),
                      float(x["low"]),float(x["close"])) for x in raw]
            e=latest_result(c); d=reference(c)
            rp,rc=d[-2],d[-1]; rb=(rp==-1 and rc==1)
            same=(e["previous_direction"]==rp and e["current_direction"]==rc and e["buy"]==rb)
            ok+=1; buys+=int(e["buy"]); matches+=int(same)
            if e["buy"]:
                buy_rows.append((s, c[-1].close, fmt(c[-1].timestamp)))
            lines.append(f"{s}: ENGINE={e['previous_direction']}->{e['current_direction']} BUY={e['buy']} | REF={rp}->{rc} BUY={rb} | MATCH={same} | CANDLE={fmt(c[-1].timestamp)}")
        except Exception as ex:
            errors+=1; lines.append(f"{s}: ERROR={ex}")
    summary = f"SUMMARY OK={ok} ERRORS={errors} BUY={buys} MATCH={matches}/{ok} TOTAL={len(symbols)}"
    lines += ["", summary]
    Path("new_buy_system/verification_14_result.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))

    telegram_lines = [
        "🔔 <b>BIST YENİ BUY TARAMASI</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        "⏱ <b>2H</b> | ATR 10 | Çarpan 2.0 | HL2",
        f"📊 Tarama: <b>{ok}/{len(symbols)}</b> hisse",
        f"✅ BUY: <b>{buys}</b>",
        ""
    ]

    if buy_rows:
        for idx, (symbol, close, candle_time) in enumerate(buy_rows, 1):
            ticker = symbol.split(":", 1)[-1]
            tv_url = f"https://www.tradingview.com/chart/?symbol=BIST%3A{ticker}"
            telegram_lines.append(
                f'{idx}. <a href="{tv_url}"><b>{escape(ticker)}</b></a> — {close:.2f} TL'
            )
        telegram_lines += [
            "",
            "📌 Sinyal: <b>SAT → AL</b>",
            f"🕯 Son tamamlanan 2H mum: <b>{escape(buy_rows[0][2])}</b>"
        ]
    else:
        telegram_lines.append("🟢 Son tamamlanan 2H mumda yeni BUY yok.")

    telegram_lines += [
        "",
        f"🔍 Doğrulama: <b>{matches}/{ok}</b> birebir eşleşme",
        "⚙️ Study kullanılmadı."
    ]

    try:
        send_telegram("\n".join(telegram_lines))
        print("TELEGRAM: BUY tarama sonucu gönderildi.")
    except Exception as exc:
        print("TELEGRAM ERROR:", exc)
        raise

if __name__=="__main__": main()
