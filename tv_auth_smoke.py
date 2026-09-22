import os, json, time
import requests
import websocket

sessionid = os.getenv("TV_SESSIONID", "").strip()
sessionid_sign = os.getenv("TV_SESSIONID_SIGN", "").strip()
device_t = os.getenv("TV_DEVICE_T", "").strip()
fallback = os.getenv("TRADINGVIEW_AUTH_TOKEN", "").strip()

lines=[]
def out(s):
    print(s); lines.append(s)

out("SESSIONID_PRESENT: "+str(bool(sessionid)))
out("SESSIONID_SIGN_PRESENT: "+str(bool(sessionid_sign)))
out("DEVICE_T_PRESENT: "+str(bool(device_t)))
out("FALLBACK_TOKEN_PRESENT: "+str(bool(fallback)))

if not sessionid:
    out("AUTH_RESULT: FAILED - TV_SESSIONID missing")
    open("auth_smoke_result.txt","w").write("\n".join(lines)+"\n")
    raise SystemExit(1)

cookies = ["sessionid="+sessionid]
if sessionid_sign: cookies.append("sessionid_sign="+sessionid_sign)
if device_t: cookies.append("device_t="+device_t)
cookie_header="; ".join(cookies)

# Test A: documented quote-token exchange, form body.
try:
    r=requests.post("https://www.tradingview.com/quote_token/",
        headers={"Origin":"https://www.tradingview.com","Referer":"https://www.tradingview.com/","User-Agent":"Mozilla/5.0","Accept":"*/*"},
        cookies={"sessionid":sessionid, **({"sessionid_sign":sessionid_sign} if sessionid_sign else {}), **({"device_t":device_t} if device_t else {})},
        data={"grabSession":"true"}, timeout=20)
    out("QUOTE_FORM_STATUS: "+str(r.status_code))
except Exception as e:
    out("QUOTE_FORM_ERROR: "+type(e).__name__)

# Test B: same endpoint, JSON body.
try:
    r=requests.post("https://www.tradingview.com/quote_token/",
        headers={"Origin":"https://www.tradingview.com","Referer":"https://www.tradingview.com/","User-Agent":"Mozilla/5.0","Accept":"application/json","Content-Type":"application/json"},
        cookies={"sessionid":sessionid, **({"sessionid_sign":sessionid_sign} if sessionid_sign else {}), **({"device_t":device_t} if device_t else {})},
        json={"grabSession":True}, timeout=20)
    out("QUOTE_JSON_STATUS: "+str(r.status_code))
except Exception as e:
    out("QUOTE_JSON_ERROR: "+type(e).__name__)

# Test C: direct authenticated websocket handshake with the actual cookies.
direct_ok=False
try:
    ws=websocket.create_connection(
        "wss://data.tradingview.com/socket.io/websocket",
        cookie=cookie_header,
        origin="https://www.tradingview.com",
        host="data.tradingview.com",
        timeout=15,
        suppress_origin=True,
    )
    ws.send('~m~'+str(len(json.dumps({"m":"set_auth_token","p":[fallback or "unauthorized_user_token"]})))+'~m~'+json.dumps({"m":"set_auth_token","p":[fallback or "unauthorized_user_token"]}))
    deadline=time.time()+8
    while time.time()<deadline:
        msg=ws.recv()
        if msg:
            direct_ok=True
            break
    ws.close()
except Exception as e:
    out("DIRECT_WS_ERROR: "+type(e).__name__+":"+str(e)[:80])

out("DIRECT_WS_HANDSHAKE: "+str(direct_ok))
out("AUTH_RESULT: "+("SUCCESS" if direct_ok else "FAILED"))
open("auth_smoke_result.txt","w").write("\n".join(lines)+"\n")
if not direct_ok:
    raise SystemExit(1)
