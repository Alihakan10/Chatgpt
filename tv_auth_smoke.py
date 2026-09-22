import os, json, time
import websocket

sid=os.getenv("TV_SESSIONID","").strip()
sign=os.getenv("TV_SESSIONID_SIGN","").strip()
fallback=os.getenv("TRADINGVIEW_AUTH_TOKEN","").strip()

print("SESSIONID_PRESENT:", bool(sid))
print("SESSIONID_SIGN_PRESENT:", bool(sign))
print("DEVICE_T_PRESENT:", bool(os.getenv("TV_DEVICE_T","").strip()))
print("FALLBACK_TOKEN_PRESENT:", bool(fallback))

if not sid:
    raise SystemExit("No TV_SESSIONID")

cookie=f"sessionid={sid};"
if sign:
    cookie += f" sessionid_sign={sign};"

url="wss://data.tradingview.com/socket.io/websocket"
headers=[
    "Origin: https://www.tradingview.com",
    "User-Agent: Mozilla/5.0",
    "Cookie: "+cookie,
]

def msg(m,p):
    return json.dumps({"m":m,"p":p},separators=(",",":"))

def parse(buf):
    out=[]
    pos=0
    while pos < len(buf):
        if not buf.startswith("~m~",pos): break
        a=buf.find("~m~",pos+3)
        if a<0: break
        n=int(buf[pos+3:a])
        start=a+3; end=start+n
        if end>len(buf): break
        try: out.append(json.loads(buf[start:end]))
        except: pass
        pos=end
    return out

ws=websocket.create_connection(url,header=headers,timeout=12,origin="https://www.tradingview.com")
if fallback:
    ws.send("~m~"+str(len(msg("set_auth_token",[fallback])))+"~m~"+msg("set_auth_token",[fallback]))
else:
    # Test cookie-authenticated socket directly, without /quote_token/ and without Study.
    ws.send("~m~"+str(len(msg("set_auth_token",["unauthorized_user_token"])))+"~m~"+msg("set_auth_token",["unauthorized_user_token"]))

ws.send("~m~"+str(len(msg("chart_create_session",["auth_smoke",""])))+"~m~"+msg("chart_create_session",["auth_smoke",""]))
ws.send("~m~"+str(len(msg("switch_timezone",["auth_smoke","Europe/Istanbul"])))+"~m~"+msg("switch_timezone",["auth_smoke","Europe/Istanbul"]))
ws.send("~m~"+str(len(msg("resolve_symbol",["auth_smoke","s",json.dumps({"symbol":"BIST:KENT","adjustment":"splits","session":"regular"})])))+"~m~"+msg("resolve_symbol",["auth_smoke","s",json.dumps({"symbol":"BIST:KENT","adjustment":"splits","session":"regular"})]))
ws.send("~m~"+str(len(msg("create_series",["auth_smoke","s1","s","s",100])))+"~m~"+msg("create_series",["auth_smoke","s1","s","s",100]))

got=False
buf=""
deadline=time.time()+12
while time.time()<deadline:
    try:
        data=ws.recv()
    except Exception:
        break
    if not data: break
    buf += data
    for x in parse(buf):
        if isinstance(x,list) and len(x)>=2 and x[0]=="timescale_update":
            got=True
            break
    if got: break

print("DIRECT_WS_CANDLE_DATA:", got)
print("AUTH_TEST_RESULT:", "SUCCESS" if got else "FAILED")
ws.close()
if not got: raise SystemExit(1)
