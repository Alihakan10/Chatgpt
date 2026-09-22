import os
import requests

URL = "https://www.tradingview.com/quote_token/"

sessionid = os.getenv("TV_SESSIONID", "").strip()
sessionid_sign = os.getenv("TV_SESSIONID_SIGN", "").strip()
device_t = os.getenv("TV_DEVICE_T", "").strip()
fallback = os.getenv("TRADINGVIEW_AUTH_TOKEN", "").strip()

lines = []
def out(s):
    print(s)
    lines.append(s)

out("SESSIONID_PRESENT: " + str(bool(sessionid)))
out("SESSIONID_SIGN_PRESENT: " + str(bool(sessionid_sign)))
out("DEVICE_T_PRESENT: " + str(bool(device_t)))
out("FALLBACK_TOKEN_PRESENT: " + str(bool(fallback)))

if not sessionid:
    out("AUTH_RESULT: FAILED - TV_SESSIONID secret missing")
    open("auth_smoke_result.txt","w").write("\n".join(lines)+"\n")
    raise SystemExit(1)

headers = {
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "User-Agent": "Mozilla/5.0",
    "Accept": "*/*",
}
cookies = {"sessionid": sessionid}
if sessionid_sign:
    cookies["sessionid_sign"] = sessionid_sign
if device_t:
    cookies["device_t"] = device_t

try:
    r = requests.post(
        URL,
        headers=headers,
        cookies=cookies,
        data={"grabSession": "true"},
        timeout=20,
    )
    out("HTTP_STATUS: " + str(r.status_code))
    token = None
    try:
        data = r.json()
        if isinstance(data, dict):
            token = data.get("token")
        elif isinstance(data, str):
            token = data.split(":", 1)[0].strip()
    except Exception:
        raw = r.text.strip()
        if raw:
            token = raw.split(":", 1)[0].strip()

    valid = bool(token) and token not in ("null", "None", "undefined")
    out("AUTH_RESULT: " + ("SUCCESS" if valid else "FAILED"))
    out("TOKEN_RECEIVED: " + str(valid))
    open("auth_smoke_result.txt","w").write("\n".join(lines)+"\n")
    if not valid:
        raise SystemExit(1)
except requests.RequestException as e:
    out("HTTP_ERROR_TYPE: " + type(e).__name__)
    out("AUTH_RESULT: FAILED")
    open("auth_smoke_result.txt","w").write("\n".join(lines)+"\n")
    raise SystemExit(1)
