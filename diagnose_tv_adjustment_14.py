import json
import time
import random
import string
import websocket
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = [
    "BIST:CLEBI","BIST:EMNIS","BIST:EUHOL","BIST:KENT",
    "BIST:KERVN","BIST:KLYPV","BIST:KRPLS","BIST:KSTUR",
    "BIST:OYLUM","BIST:SODSN","BIST:TUCLK","BIST:TURSG",
    "BIST:ULUFA","BIST:USHOL",
]
TZ = ZoneInfo("Europe/Istanbul")
WS_URL = "wss://data.tradingview.com/socket.io/websocket"

def msg(method, params):
    p = json.dumps({"m": method, "p": params}, separators=(",", ":"))
    return f"~m~{len(p)}~m~{p}"

def frames(raw):
    out=[]; pos=0
    while True:
        s=raw.find("~m~",pos)
        if s<0: break
        a=s+3; b=raw.find("~m~",a)
        if b<0: break
        try: n=int(raw[a:b])
        except ValueError: pos=b+3; continue
        j=b+3
        if j+n>len(raw): break
        out.append(raw[j:j+n]); pos=j+n
    return out,raw[pos:]

def get_bars(symbol, adjustment):
    cs="cs_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12))
    ws=websocket.create_connection(WS_URL, timeout=10, origin="https://www.tradingview.com")
    try:
        ws.send(msg("set_auth_token",["unauthorized_user_token"]))
        ws.send(msg("chart_create_session",[cs,""]))
        desc=json.dumps({"symbol":symbol,"adjustment":adjustment,"session":"regular"},separators=(",",":"))
        ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+desc]))
        ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1","120",3000,""]))
        ws.send(msg("switch_timezone",[cs,"exchange"]))
        raw=""; bars={}
        deadline=time.time()+10
        while time.time()<deadline:
            try: packet=ws.recv()
            except Exception: break
            if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
            raw+=packet
            fs,raw=frames(raw)
            for payload in fs:
                try: d=json.loads(payload)
                except Exception: continue
                if d.get("m")!="timescale_update": continue
                node=d.get("p",[None,{}])[1].get("sds_1",{})
                for item in node.get("s",[]):
                    v=item.get("v",[])
                    if len(v)>=5 and all(x is not None for x in v[:5]):
                        bars[float(v[0])]={"time":float(v[0]),"open":float(v[1]),"high":float(v[2]),"low":float(v[3]),"close":float(v[4])}
                if node.get("ns",{}).get("d") is False:
                    return sorted(bars.values(),key=lambda x:x["time"])
        return sorted(bars.values(),key=lambda x:x["time"])
    finally:
        try: ws.close()
        except Exception: pass

def fmt(b):
    d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
    return f"{d:%Y-%m-%d %H:%M} O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}"

print("NEW DATA TEST: NATIVE 2H ADJUSTMENT COMPARISON")
print("NO STUDY / NO BROKER / NO 1H->2H MERGE")
print("Compare TradingView WebSocket adjustment=splits vs adjustment=none.")
for symbol in SYMBOLS:
    print("\n"+symbol)
    try:
        a=get_bars(symbol,"splits")
        b=get_bars(symbol,"none")
        aa={x["time"]:x for x in a}
        bb={x["time"]:x for x in b}
        common=sorted(set(aa)&set(bb))
        diffs=[]
        for t in common[-20:]:
            x,y=aa[t],bb[t]
            if any(abs(x[k]-y[k])>1e-9 for k in ("open","high","low","close")):
                diffs.append(t)
        print(f"bars splits={len(a)} none={len(b)} common={len(common)} differing_last20={len(diffs)}")
        for t in common[-5:]:
            x,y=aa[t],bb[t]
            print(f"  {fmt(x)} | NONE C={y['close']:.2f} O={y['open']:.2f} H={y['high']:.2f} L={y['low']:.2f}")
        if diffs:
            print("  FIRST DIFFERENCE IN LAST 20:", fmt(aa[diffs[0]]), " | NONE:", fmt(bb[diffs[0]]))
        else:
            print("  RESULT: IDENTICAL on last 20 common native 2H bars")
    except Exception as e:
        print("  ERROR:",repr(e))
print("\nADJUSTMENT TEST FINISHED")
