import requests
import json

URL = "https://scanner.tradingview.com/turkey/scan"

payload = {
    "symbols": {
        "tickers": ["BIST:DEVA"],
        "query": {"types": []}
    },
    "columns": [
        "name",
        "close",
        "open|120",
        "high|120",
        "low|120",
        "close|120",
        "change|120",
        "volume|120",
        "open",
        "high",
        "low",
        "change"
    ],
    "range": [0, 10]
}

headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/"
}

r = requests.post(URL, json=payload, headers=headers, timeout=20)
print("HTTP", r.status_code)
print(r.text[:10000])
r.raise_for_status()

data = r.json().get("data", [])
print("\nPARSED:")
for row in data:
    print(json.dumps(row, ensure_ascii=False, indent=2))
