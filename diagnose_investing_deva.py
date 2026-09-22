import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PAIR_ID = 19359  # Investing.com DEVA
URL = f"https://api.investing.com/api/financialdata/historical/{PAIR_ID}"

params = {
    "start-date": "2026-09-22",
    "end-date": "2026-09-23",
    "interval": "P1H",
    "time-frame": "Daily",
}

headers = {
    "User-Agent": "Mozilla/5.0",
    "domain-id": "www",
    "Origin": "https://www.investing.com",
    "Referer": "https://www.investing.com/",
    "Accept": "application/json, text/plain, */*",
}

r = requests.get(URL, params=params, headers=headers, timeout=30)
print("HTTP", r.status_code)
print(r.text[:5000])
r.raise_for_status()
data = r.json()
print("JSON type:", type(data).__name__)

rows = data.get("data", data) if isinstance(data, dict) else data
if isinstance(rows, list):
    print("ROWS", len(rows))
    for row in rows[-20:]:
        print(row)
