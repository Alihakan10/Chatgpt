import json,time,random,string,websocket
from datetime import datetime
from zoneinfo import ZoneInfo

URL="wss://data.tradingview.com/socket.io/websocket"
SYMBOLS=["BIST:CLEBI","BIST:EMNIS","BIST:EUHOL"]
TZ=ZoneInfo("Europe/Istanbul")

def sid(p): return p+"_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12))
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

def get(symbol,tf):
    cs=sid("cs")
    ws=websocket.create_connection(URL,timeout=10,origin="https://www.tradingview.com")
    try:
        ws.send(msg("set_auth_token",["unauthorized_user_token"]))
        ws.send(msg("chart_create_session",[cs,""]))
        cfg=json.dumps({"symbol":symbol,"adjustment":"splits","session":"regular"},separators=(",",":"))
        ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+cfg]))
        ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1",tf,80,""]))
        ws.send(msg("switch_timezone",[cs,"exchange"]))
        bars={}; raw=""; deadline=time.time()+12
        while time.time()<deadline:
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
                if o.get("m")!="timescale_update": continue
                ps=o.get("p",[])
                if len(ps)<2: continue
                d=ps[1]
                s=d.get("sds_1") if isinstance(d,dict) else None
                if not isinstance(s,dict): continue
                for b in s.get("s",[]):
                    v=b.get("v",[]) if isinstance(b,dict) else []
                    if len(v)>=5:
                        try: bars[float(v[0])]=[float(v[i]) for i in range(1,5)]
                        except: pass
            if len(bars)>=20: break
        return sorted(bars.items())
    finally: ws.close()

def dt(ts): return datetime.fromtimestamp(ts,ZoneInfo("UTC")).astimezone(TZ)

def aggregate_09(h1):
    # Pair consecutive exchange-session 1H bars by 09:00,11:00,13:00,15:00,17:00 starts.
    by={dt(t).strftime("%Y-%m-%d %H:%M"):v for t,v in h1}
    out={}
    for day in sorted({k[:10] for k in by}):
        for start in (9,11,13,15,17):
            k1=f"{day} {start:02d}:00"
            k2=f"{day} {start+1:02d}:00"
            if k1 in by and k2 in by:
                a,b=by[k1],by[k2]
                out[k1]=[a[0],max(a[1],b[1]),min(a[2],b[2]),b[3]]
    return out

def aggregate_10(h1):
    # Alternative hypothetical alignment beginning at 10:00; compare only complete 2H pairs.
    by={dt(t).strftime("%Y-%m-%d %H:%M"):v for t,v in h1}
    out={}
    for day in sorted({k[:10] for k in by}):
        for start in (10,12,14,16):
            k1=f"{day} {start:02d}:00"; k2=f"{day} {start+1:02d}:00"
            if k1 in by and k2 in by:
                a,b=by[k1],by[k2]
                out[k1]=[a[0],max(a[1],b[1]),min(a[2],b[2]),b[3]]
    return out

for sym in SYMBOLS:
    h1=get(sym,"60"); h2=get(sym,"120")
    a9=aggregate_09(h1); a10=aggregate_10(h1)
    native={dt(t).strftime("%Y-%m-%d %H:%M"):v for t,v in h2}
    print("\nSYMBOL",sym)
    matches9=matches10=0
    for k,nv in list(native.items())[-10:]:
        m9=a9.get(k); m10=a10.get(k)
        if m9 is not None and all(abs(m9[i]-nv[i])<1e-8 for i in range(4)): matches9+=1
        if m10 is not None and all(abs(m10[i]-nv[i])<1e-8 for i in range(4)): matches10+=1
        print(k,"NATIVE",nv,"A9",m9,"A10",m10)
    print("MATCH_COUNT_LAST10 A9=",matches9,"A10=",matches10)
