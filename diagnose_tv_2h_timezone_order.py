import json,time,random,string,websocket
from datetime import datetime
from zoneinfo import ZoneInfo

URL="wss://data.tradingview.com/socket.io/websocket"
SYMBOLS=["BIST:CLEBI","BIST:EMNIS","BIST:EUHOL"]
TZ="Europe/Istanbul"

def sid(p):
    return p+"_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12))
def msg(m,p):
    s=json.dumps({"m":m,"p":p},separators=(",",":"))
    return f"~m~{len(s)}~m~{s}"
def frames(raw):
    out=[]; pos=0
    while True:
        a=raw.find("~m~",pos)
        if a<0: break
        b=raw.find("~m~",a+3)
        if b<0: break
        try:n=int(raw[a+3:b])
        except: pos=b+3; continue
        st=b+3; en=st+n
        if en>len(raw): break
        out.append(raw[st:en]); pos=en
    return out,raw[pos:]
def run(symbol,order):
    cs=sid("cs"); qs=sid("qs"); ws=websocket.create_connection(URL,timeout=10,origin="https://www.tradingview.com")
    cfg=json.dumps({"symbol":symbol,"adjustment":"splits","session":"regular"},separators=(",",":"))
    ws.send(msg("set_auth_token",["unauthorized_user_token"]))
    ws.send(msg("chart_create_session",[cs,""]))
    ws.send(msg("quote_create_session",[qs]))
    if order=="timezone_first":
        ws.send(msg("switch_timezone",[cs,"exchange"]))
    ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+cfg]))
    ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1","120",50,""]))
    if order=="series_first":
        ws.send(msg("switch_timezone",[cs,"exchange"]))
    bars={}; raw=""
    deadline=time.time()+12
    meta=None
    while time.time()<deadline and len(bars)<5:
        try:p=ws.recv()
        except: break
        if isinstance(p,bytes): p=p.decode("utf8","ignore")
        raw+=p; fs,raw=frames(raw)
        for x in fs:
            if x.startswith("~h~"):
                try: ws.send(x)
                except: pass
                continue
            try:o=json.loads(x)
            except: continue
            m=o.get("m"); ps=o.get("p",[])
            if m=="symbol_resolved" and len(ps)>=3:
                meta=ps[2]
            if m not in ("timescale_update","du") or len(ps)<2: continue
            d=ps[1]
            s=d.get("sds_1") if isinstance(d,dict) else None
            if not isinstance(s,dict): continue
            for b in s.get("s",[]):
                v=b.get("v",[]) if isinstance(b,dict) else []
                if len(v)>=5:
                    try: bars[float(v[0])]=[float(v[i]) for i in range(1,5)]
                    except: pass
    ws.close()
    last=sorted(bars.items())[-5:]
    return meta,last

for order in ("series_first","timezone_first"):
    print("\nORDER",order)
    for s in SYMBOLS:
        meta,last=run(s,order)
        print(s,"META_KEYS",sorted(meta.keys()) if isinstance(meta,dict) else None)
        if isinstance(meta,dict):
            print("SESSION",meta.get("session"),"TZ",meta.get("timezone"),"SESSION_ID",meta.get("session_id"),"TYPE",meta.get("type"))
        for t,v in last:
            dt=datetime.fromtimestamp(t,tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ))
            print(dt.strftime("%Y-%m-%d %H:%M"),v)
