import os, json, time, random, string, websocket
from datetime import datetime
from zoneinfo import ZoneInfo
import scanner

TZ = "Europe/Istanbul"
WS = "wss://data.tradingview.com/socket.io/websocket"
SYMBOL = "BIST:KENT"

def sess(p):
    return p + "_" + "".join(random.choice(string.ascii_lowercase) for _ in range(12))

def msg(m,p):
    s=json.dumps({"m":m,"p":p},separators=(",",":"))
    return f"~m~{len(s)}~m~{s}"

def extract(raw):
    out=[]; pos=0
    while True:
        st=raw.find("~m~",pos)
        if st<0: break
        ls=st+3; le=raw.find("~m~",ls)
        if le<0: break
        try: n=int(raw[ls:le])
        except: pos=le+3; continue
        js=le+3; je=js+n
        if je>len(raw): break
        out.append(raw[js:je]); pos=je
    return out,raw[pos:]

def fetch(order, interval="120"):
    cs,qs=sess("cs"),sess("qs")
    headers=[]
    sid=os.getenv("TV_SESSIONID","").strip()
    sig=os.getenv("TV_SESSIONID_SIGN","").strip()
    if sid:
        c="sessionid="+sid
        if sig: c += "; sessionid_sign="+sig
        headers=["Cookie: "+c]
    ws=websocket.create_connection(WS,timeout=15,origin="https://www.tradingview.com",header=headers)
    try:
        auth=os.getenv("TRADINGVIEW_AUTH_TOKEN","").strip() or "unauthorized_user_token"
        ws.send(msg("set_auth_token",[auth]))
        ws.send(msg("chart_create_session",[cs,""]))
        if order=="timezone_before":
            ws.send(msg("switch_timezone",[cs,"exchange"]))
        ws.send(msg("quote_create_session",[qs]))
        ws.send(msg("quote_set_fields",[qs,"lp","volume","ch","chp"]))
        cfg=json.dumps({"symbol":SYMBOL,"adjustment":"splits","session":"regular"},separators=(",",":"))
        ws.send(msg("quote_add_symbols",[qs,SYMBOL]))
        ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+cfg]))
        if order=="timezone_after":
            ws.send(msg("switch_timezone",[cs,"exchange"]))
        ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1",interval,3000,""]))
        candles={}; raw=""
        start=time.time()
        while time.time()-start<15:
            try: packet=ws.recv()
            except Exception: break
            if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
            raw+=packet
            frames,raw=extract(raw)
            for payload in frames:
                if payload.startswith("~h~"):
                    try: ws.send("~m~"+str(len(payload))+"~m~"+payload)
                    except: pass
                    continue
                try: obj=json.loads(payload)
                except: continue
                if obj.get("m") not in ("timescale_update","du"): continue
                p=obj.get("p",[])
                if len(p)<2 or not isinstance(p[1],dict): continue
                sd=p[1].get("sds_1")
                if not isinstance(sd,dict): continue
                for bar in sd.get("s",[]):
                    v=bar.get("v") if isinstance(bar,dict) else None
                    if isinstance(v,list) and len(v)>=5:
                        try:
                            t,o,h,l,c=map(float,v[:5])
                            candles[t]={"time":t,"open":o,"high":h,"low":l,"close":c}
                        except: pass
                if obj.get("m")=="series_completed" or len(candles)>=3000:
                    pass
            if len(candles)>=1000 and time.time()-start>2:
                break
        bars=sorted(candles.values(),key=lambda x:x["time"])
        return bars[-12:]
    finally:
        ws.close()

def fmt(b):
    dt=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ))
    return {"time":dt.strftime("%Y-%m-%d %H:%M"),**{k:b[k] for k in ("open","high","low","close")}}

out={"auth":bool(os.getenv("TRADINGVIEW_AUTH_TOKEN") or os.getenv("TV_SESSIONID"))}
out["current_order"]=[fmt(x) for x in scanner.get_tv_candles("BIST:KENT","native_2h")[-12:]]
out["timezone_before"]=[fmt(x) for x in fetch("timezone_before")]
out["timezone_after_custom"]=[fmt(x) for x in fetch("timezone_after")]\n\none=[x for x in fetch("timezone_before","60")]\nmerged=[]\nby={}\nfor b in one:\n    dt=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ))\n    if dt.hour < 10 or dt.hour >= 18 or dt.minute != 0: continue\n    start=10 + ((dt.hour-10)//2)*2\n    by.setdefault((dt.date(),start),[]).append(b)\nfor (day,start),bs in sorted(by.items()):\n    bs=sorted(bs,key=lambda x:x["time"])\n    if len(bs)!=2: continue\n    merged.append({"time":bs[0]["time"],"open":bs[0]["open"],"high":max(x["high"] for x in bs),"low":min(x["low"] for x in bs),"close":bs[-1]["close"]})\nout["session_merged_1h"]=[fmt(x) for x in merged[-8:]]
os.makedirs("diagnostics",exist_ok=True)
with open("diagnostics/kent_alignment.json","w",encoding="utf-8") as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False,indent=2))

# trigger alignment diagnostic
