import json, time, random
from datetime import datetime
from zoneinfo import ZoneInfo
import websocket
import scanner

SYMBOL="BIST:DEVA"
TZ=ZoneInfo("Europe/Istanbul")

def dt(ts):
    return datetime.fromtimestamp(ts,tz=ZoneInfo("UTC")).astimezone(TZ).strftime("%d.%m.%Y %H:%M")

def tvmsg(m,p):
    o={"m":m,"p":p}; s=json.dumps(o,separators=(",",":"))
    return "~m~"+str(len(s))+"~m~"+s

def fetch_tf(tf, count=300):
    ws=websocket.create_connection(scanner.TV_WS_URL,timeout=12,origin="https://www.tradingview.com")
    cs="cs"+random.choice("abcdefghijklmnopqrstuvwxyz0123456789")
    try:
        ws.send(tvmsg("set_auth_token",["unauthorized_user_token"]))
        ws.send(tvmsg("chart_create_session",[cs,""]))
        cfg=json.dumps({"symbol":SYMBOL,"adjustment":"splits","session":"regular"},separators=(",",":"))
        ws.send(tvmsg("resolve_symbol",[cs,"sds_sym_1","="+cfg]))
        ws.send(tvmsg("create_series",[cs,"s1","s1","sds_sym_1",tf,count,""]))
        ws.send(tvmsg("switch_timezone",[cs,"exchange"]))
        out={}; buf=""; start=time.time(); completed=False
        while time.time()-start<12:
            try: packet=ws.recv()
            except Exception: break
            if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
            buf+=packet
            messages,buf=scanner.extract_tv_messages(buf)
            for full,payload in messages:
                if payload.startswith("~h~"):
                    try: ws.send(full)
                    except: pass
                    continue
                try: obj=json.loads(payload)
                except: continue
                m=obj.get("m"); p=obj.get("p",[])
                if m=="series_completed": completed=True
                if m not in ("timescale_update","du"): continue
                if len(p)<2 or not isinstance(p[1],dict): continue
                sd=p[1].get("sds_1")
                if not isinstance(sd,dict): continue
                for bar in sd.get("s",[]):
                    v=bar.get("v") if isinstance(bar,dict) else None
                    if not isinstance(v,list) or len(v)<5: continue
                    try:
                        x=list(map(float,v[:5]))
                        out[x[0]]={"time":x[0],"open":x[1],"high":x[2],"low":x[3],"close":x[4]}
                    except: pass
            if completed and out: break
        return sorted(out.values(),key=lambda x:x["time"])
    finally:
        ws.close()

native=scanner.get_tv_candles_with_retry(SYMBOL,candle_mode="native_2h")
one=fetch_tf("60",300)
print("=== DEVA 2H vs 1H ===")
print("1H 22.09:")
for b in one:
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
    if d.date().isoformat()=="2026-09-22" and 8<=d.hour<=18:
        print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
print("2H native 22.09:")
for b in native:
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
    if d.date().isoformat()=="2026-09-22" and 8<=d.hour<=18:
        print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")

print("=== POSSIBLE 2H COMBINATIONS ===")
for i,b in enumerate(one):
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
    if d.date().isoformat()=="2026-09-22" and d.hour in (10,11,12,13,14,15,16,17):
        for j in (i,i+1):
            if j < len(one):
                d2=datetime.fromtimestamp(one[j]["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
                if d2.date()==d.date() and (d2.hour-d.hour)==1:
                    print(f"{d.hour:02d}:00+{d2.hour:02d}:00 -> O={b['open']:.2f} H={max(b['high'],one[j]['high']):.2f} L={min(b['low'],one[j]['low']):.2f} C={one[j]['close']:.2f}")
