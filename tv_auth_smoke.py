import os
import requests

URL = "https://www.tradingview.com/quote_token/"

sessionid = os.getenv("TV_SESSIONID", "").strip()
sessionid_sign = os.getenv("TV_SESSIONID_SIGN", "").strip()
device_t = os.getenv("TV_DEVICE_T", "").strip()
fallback = os.getenv("TRADINGVIEW_AUTH_TOKEN", "").strip()

print("SESSIONID_PRESENT:", bool(sessionid))
print("SESSIONID_SIGN_PRESENT:", bool(sessionid_sign))
print("DEVICE_T_PRESENT:", bool(device_t))
print("FALLBACK_TOKEN_PRESENT:", bool(fallback))

if not sessionid:
    print("AUTH_RESULT: FAILED - TV_SESSIONID secret missing")
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
    print("HTTP_STATUS:", r.status_code)
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
    print("AUTH_RESULT:", "SUCCESS" if valid else "FAILED")
    print("TOKEN_RECEIVED:", valid)
    if not valid:
        raise SystemExit(1)
except requests.RequestException as e:
    print("HTTP_ERROR_TYPE:", type(e).__name__)
    print("AUTH_RESULT: FAILED")
    raise SystemExit(1)
