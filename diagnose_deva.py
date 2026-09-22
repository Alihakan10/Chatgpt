import json, math, random, time
from datetime import datetime
from zoneinfo import ZoneInfo
import websocket
import scanner

SYMBOL="BIST:DEVA"
TZ=ZoneInfo("Europe/Istanbul")

def dt(ts):
    return datetime.fromtimestamp(ts,tz=ZoneInfo("UTC")).astimezone(TZ).strftime("%d.%m.%Y %H:%M")

def tv_message(method, params):
    return "~m~" + str(len(json.dumps({"m":method,"p":params},separators=(",",":")))) + "~m~" + json.dumps({"m":method,"p":params},separators=(",",":"))

def raw_1h(symbol):
    ws=websocket.create_connection(scanner.TV_WS_URL,timeout=scanner.WS_TIMEOUT,origin="https://www.tradingview.com")
    cs="cs"+random.choice("abcdefghijklmnopqrstuvwxyz0123456789")
    try:
        for m,p in [
            ("set_auth_token",["unauthorized_user_token"]),
            ("chart_create_session",[cs,""]),
            ("resolve_symbol",[cs,"sds_sym_1","="+json.dumps({"symbol":symbol,"adjustment":"splits","session":"regular"},separators=(",",":"))]),
            ("create_series",[cs,"s1","s1","sds_sym_1","60",1000,""]),
            ("switch_timezone",[cs,"exchange"]),
        ]: ws.send(tv_message(m,p))
        out={}; buf=""; start=time.time()
        while time.time()-start<scanner.WS_TIMEOUT:
            try: packet=ws.recv()
            except Exception: break
            if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
            buf+=packet
            messages,buf=scanner.extract_tv_messages(buf)
            for _,payload in messages:
                if payload.startswith("~h~"):
                    try: ws.send("~m~"+str(len(payload))+ "~m~"+payload)
                    except: pass
                    continue
                try: obj=json.loads(payload)
                except: continue
                if obj.get("m") not in ("timescale_update","du"): continue
                params=obj.get("p",[])
                if len(params)<2 or not isinstance(params[1],dict): continue
                sd=params[1].get("sds_1")
                if not isinstance(sd,dict): continue
                for bar in sd.get("s",[]):
                    v=bar.get("v") if isinstance(bar,dict) else None
                    if not isinstance(v,list) or len(v)<5: continue
                    try:
                        vals=list(map(float,v[:5]))
                        out[vals[0]]={"time":vals[0],"open":vals[1],"high":vals[2],"low":vals[3],"close":vals[4]}
                    except: pass
                if obj.get("m")=="series_completed" or len(out)>=50: break
            if len(out)>=50: break
        return sorted(out.values(),key=lambda x:x["time"])
    finally:
        ws.close()

native=scanner.get_tv_candles_with_retry(SYMBOL,candle_mode="native_2h")
raw=raw_1h(SYMBOL)
print("=== DEVA 2H / 1H VERI ESLESTIRME ===")
print("Native 2H son mumlar:")
for b in native:
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
    if d.date().isoformat()=="2026-09-22" and 8<=d.hour<=18:
        print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
print("1H son mumlar:")
for b in raw:
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
    if d.date().isoformat()=="2026-09-22" and 8<=d.hour<=18:
        print(dt(b["time"]),f"O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
