from __future__ import annotations
import sys
from pathlib import Path
from html import escape
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scanner import get_tv_candles, send_telegram
from new_buy_system.buy_engine import Candle, latest_result
from new_buy_system.verify_14 import reference, tv_native, trend_from_rows, filter_metrics, fmt

SYMBOLS = ["BIST:ACSEL","BIST:AKSUE","BIST:ATSYH","BIST:BESLR","BIST:BMSCH","BIST:DMRGD","BIST:EMNIS","BIST:ENPRA","BIST:MOBTL","BIST:PETUN"]
rows=[]
errors=0

for s in SYMBOLS:
    try:
        raw=sorted(get_tv_candles(s,candle_mode="native_2h",candle_session="regular"),key=lambda x:float(x["time"]))
        c=[Candle(float(x["time"]),float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"])) for x in raw]
        e=latest_result(c)
        if not e["buy"]:
            print(f"{s}: 2H BUY kayboldu; atlandi")
            continue
        m=filter_metrics(raw)
        t4=trend_from_rows(tv_native(s,"240",300))
        t1=trend_from_rows(tv_native(s,"1D",300))
        confirmed=(m["momentum"]>0 and m["rvol"] is not None and m["rvol"]>=1.20 and m["body_ratio"]>=0.50 and t4==1 and t1==1)
        row={"symbol":s,"close":m["close"],"time":m["time"],"momentum":m["momentum"],"rvol":m["rvol"],"body":m["body_ratio"],"t4":t4,"t1":t1,"confirmed":confirmed}
        rows.append(row)
        print(f"{s}: MOM={m['momentum']*100:.2f}% RVOL={m['rvol']:.2f} BODY={m['body_ratio']*100:.0f}% 4H={t4} 1D={t1} CONFIRMED={confirmed}")
    except Exception as ex:
        errors+=1
        print(f"{s}: ERROR={ex}")

confirmed=[r for r in rows if r["confirmed"]]
tg=[
"🔔 <b>10 BUY ADAYI — 4H/1D TEYİT KONTROLÜ</b>",
"━━━━━━━━━━━━━━━━━━━━",
"2H BUY: SAT → AL",
"Filtreler: Momentum &gt; 0% | RVOL ≥ 1.20 | Gövde ≥ %50 | 4H AL | 1D AL",
"━━━━━━━━━━━━━━━━━━━━",
f"📊 BUY adayı: <b>{len(rows)}/10</b>",
f"⭐ Teyitli: <b>{len(confirmed)}</b>",
""
]
if confirmed:
    tg.append("⭐ <b>TEYİTLİ BUY</b>")
    for i,r in enumerate(confirmed,1):
        t=r["symbol"].split(":",1)[-1]; u=f"https://www.tradingview.com/chart/?symbol=BIST%3A{t}"
        tg += [f'{i}. <a href="{u}"><b>{escape(t)}</b></a> — {r["close"]:.2f} TL',
               f'   Momentum +{r["momentum"]*100:.2f}% | RVOL {r["rvol"]:.2f} | Gövde %{r["body"]*100:.0f}',
               "   2H SAT → AL | 4H AL | 1D AL", f'   Mum: {escape(fmt(r["time"]))}']
else:
    tg.append("⭐ <b>TEYİTLİ BUY YOK</b>")

tg += ["","📋 <b>TÜM 10 BUY ADAYI</b>"]
for i,r in enumerate(rows,1):
    t=r["symbol"].split(":",1)[-1]; u=f"https://www.tradingview.com/chart/?symbol=BIST%3A{t}"
    rv=f"{r['rvol']:.2f}" if r["rvol"] is not None else "N/A"
    tr4="AL" if r["t4"]==1 else "SAT"
    tr1="AL" if r["t1"]==1 else "SAT"
    tg.append(f'{i}. <a href="{u}"><b>{escape(t)}</b></a> | M:{r["momentum"]*100:+.2f}% | RV:{rv} | G:%{r["body"]*100:.0f} | 4H:{tr4} | 1D:{tr1} | {"⭐ TEYİTLİ" if r["confirmed"] else "⚪ Filtre dışı"}')
tg += ["",f"Kontrol: <b>{len(rows)}/10</b> BUY adayı | Hata: <b>{errors}</b>","⚙️ Study kullanılmadı.","ℹ️ Bu filtreler gelecekteki fiyat hareketini garanti etmez."]
send_telegram("\n".join(tg))
print(f"TELEGRAM GONDERILDI | BUY={len(rows)} CONFIRMED={len(confirmed)} ERRORS={errors}")
if errors or len(rows)!=10:
    raise SystemExit(1)
