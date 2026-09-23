import json,time,random,string,websocket
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

URL="wss://data.tradingview.com/socket.io/websocket"
TZ=ZoneInfo("Europe/Istanbul")
SYMBOLS=["BIST:AYGAZ","BIST:BLUME","BIST:CMENT","BIST:DIRIT","BIST:DITAS","BIST:DOFRB","BIST:DYOBY","BIST:EKSUN","BIST:HATSN","BIST:KMPUR","BIST:KPEKS","BIST:KUVVA","BIST:ORMA","BIST:OYAYO","BIST:PENGD","BIST:PENTA","BIST:TURGG"]

def sid():
    return "cs_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12))

def msg(m,p):
    s=json.dumps({"m":m,"p":p},separators=(",",":"))
    return f"~m~{len(s)}~m~{s}"

def frames(raw):
    out=[];pos=0
    while True:
        a=raw.find("~m~",pos)
        if a<0: break
        b=raw.find("~m~",a+3)
        if b<0: break
        try:n=int(raw[a+3:b])
        except:pos=b+3;continue
        st=b+3;en=st+n
        if en>len(raw):break
        out.append(raw[st:en]);pos=en
    return out,raw[pos:]

def fetch(symbol):
    cs=sid()
    ws=websocket.create_connection(URL,timeout=10,origin="https://www.tradingview.com")
    try:
        ws.send(msg("set_auth_token",["unauthorized_user_token"]))
        ws.send(msg("chart_create_session",[cs,""]))
        cfg=json.dumps({"symbol":symbol,"adjustment":"splits","session":"regular"},separators=(",",":"))
        ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+cfg]))
        ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1","120",80,""]))
        ws.send(msg("switch_timezone",[cs,"exchange"]))
        raw="";bars={};deadline=time.time()+10
        while time.time()<deadline:
            try:p=ws.recv()
            except:break
            if isinstance(p,bytes):p=p.decode("utf8","ignore")
            raw+=p;fs,raw=frames(raw)
            for x in fs:
                if x.startswith("~h~"):
                    try:ws.send(x)
                    except:pass
                    continue
                try:o=json.loads(x)
                except:continue
                if o.get("m")!="timescale_update":continue
                ps=o.get("p",[])
                if len(ps)<2:continue
                d=ps[1];s=d.get("sds_1") if isinstance(d,dict) else None
                if not isinstance(s,dict):continue
                for b in s.get("s",[]):
                    v=b.get("v",[]) if isinstance(b,dict) else []
                    if len(v)>=5:
                        try:bars[float(v[0])]=[float(v[i]) for i in range(1,5)]
                        except:pass
            if len(bars)>=20:break
        return sorted(bars.items())
    finally:ws.close()

def dt(ts):
    return datetime.fromtimestamp(ts,ZoneInfo("UTC")).astimezone(TZ)

def calc_buy(candles):
    p=10;m=2.0;n=len(candles)
    tr=[]
    for i,x in enumerate(candles):
        if i==0:tr.append(x[1]-x[2])
        else:
            pc=candles[i-1][4]
            tr.append(max(x[1]-x[2],abs(x[1]-pc),abs(x[2]-pc)))
    atr=[None]*n;atr[p-1]=sum(tr[:p])/p
    for i in range(p,n):atr[i]=(atr[i-1]*(p-1)+tr[i])/p
    up=[None]*n;dn=[None]*n;st=[None]*n;d=[1]*n
    for i,x in enumerate(candles):
        if atr[i] is None:continue
        hl=(x[1]+x[2])/2;bu=hl+m*atr[i];bl=hl-m*atr[i]
        pu=0 if i==0 or up[i-1] is None else up[i-1]
        pl=0 if i==0 or dn[i-1] is None else dn[i-1]
        pc=candles[i-1][4] if i else None
        up[i]=bu if i==0 or bu<pu or (pc is not None and pc>pu) else pu
        dn[i]=bl if i==0 or bl>pl or (pc is not None and pc<pl) else pl
        if i==p-1:d[i]=1
        elif st[i-1] is None:d[i]=1
        elif st[i-1]==up[i-1]:d[i]=-1 if x[4]>up[i] else 1
        else:d[i]=1 if x[4]<dn[i] else -1
        st[i]=dn[i] if d[i]==-1 else up[i]
    return d

def snapshot(symbols):
    out={}
    for sym in symbols:
        bars=fetch(sym)
        if len(bars)<12:
            out[sym]=None;continue
        # At test time, identify the latest bar that is already closed.
        now=datetime.now(TZ)
        idx=None
        for i,(ts,vals) in enumerate(bars):
            o,h,l,c=vals
            t=dt(ts)
            end=t.replace(hour=18,minute=0,second=0,microsecond=0) if (t.hour==17 and t.minute==0) else t+timedelta(hours=2)
            if end<=now: idx=i
        if idx is None or idx<1:
            out[sym]=None;continue
        d=calc_buy([(ts,*vals) for ts,vals in bars[:idx+1]])
        ts,(o,h,l,c)=bars[idx]
        out[sym]={"ts":ts,"ohlc":[o,h,l,c],"prev":d[idx-1],"cur":d[idx],"buy":d[idx-1]==-1 and d[idx]==1}
    return out

print("SNAPSHOT_1_START",datetime.now(TZ).isoformat())
first=snapshot(SYMBOLS)
target={s:v["ts"] for s,v in first.items() if v}
print("TARGET_BARS",json.dumps({s:dt(ts).strftime("%Y-%m-%d %H:%M") for s,ts in target.items()},ensure_ascii=False))
print("WAITING_30_SECONDS")
time.sleep(30)
print("SNAPSHOT_30S_START",datetime.now(TZ).isoformat())
second=snapshot(SYMBOLS)
stable=0;changed=0
for s in SYMBOLS:
    a=first.get(s);b=second.get(s)
    if not a or not b or a["ts"]!=b["ts"]:
        print("RESULT",s,"TARGET_NOT_COMPARABLE",a,b);continue
    same=a["ohlc"]==b["ohlc"] and a["prev"]==b["prev"] and a["cur"]==b["cur"] and a["buy"]==b["buy"]
    print("RESULT",s,"STABLE" if same else "CHANGED","OHLC1",a["ohlc"],"OHLC2",b["ohlc"],"DIR1",a["prev"],a["cur"],"DIR2",b["prev"],b["cur"],"BUY1",a["buy"],"BUY2",b["buy"])
    if same:stable+=1
    else:changed+=1
print("SUMMARY_30S STABLE=",stable,"CHANGED=",changed)
print("WAITING_30_MORE_SECONDS")
time.sleep(30)
print("SNAPSHOT_60S_START",datetime.now(TZ).isoformat())
third=snapshot(SYMBOLS)
for s in SYMBOLS:
    a=first.get(s);b=third.get(s)
    if a and b and a["ts"]==b["ts"]:
        print("RESULT_60S",s,"STABLE" if a["ohlc"]==b["ohlc"] else "CHANGED","OHLC1",a["ohlc"],"OHLC3",b["ohlc"],"BUY1",a["buy"],"BUY3",b["buy"])
print("SUMMARY_60S_DONE")
