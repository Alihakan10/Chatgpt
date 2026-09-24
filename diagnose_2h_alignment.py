import requests
import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = ["BIST:ARTMS", "BIST:KRONT", "BIST:QNBTR", "BIST:SUWEN", "BIST:DEVA"]
URL = "https://scanner.tradingview.com/turkey/scan"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

def label(ts):
    return datetime.fromtimestamp(float(ts), ZoneInfo("UTC")).astimezone(
        ZoneInfo("Europe/Istanbul")
    ).strftime("%d.%m.%Y %H:%M")

def merge_1h_to_native_2h(one_hour, direct_2h):
    by_time = {int(round(c["time"])): c for c in one_hour}
    result = []
    for d in direct_2h:
        t = int(round(d["time"]))
        a = by_time.get(t)
        b = by_time.get(t + 3600)
        if a is None or b is None:
            continue
        result.append({
            "time": d["time"],
            "open": a["open"],
            "high": max(a["high"], b["high"]),
            "low": min(a["low"], b["low"]),
            "close": b["close"],
        })
    return result

def scanner_120(symbols):
    payload = {
        "symbols": {"tickers": symbols, "query": {"types": []}},
        "columns": ["name", "open|120", "high|120", "low|120", "close|120"],
        "range": [0, len(symbols)],
    }
    r = requests.post(URL, json=payload, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("data", [])

scanner_data = scanner_120(SYMBOLS)

for sym in SYMBOLS:
    print("=" * 100)
    print(sym)

    direct = sorted(
        scanner.get_tv_candles_with_retry(sym, "native_2h"),
        key=lambda x: x["time"]
    )
    one = sorted(
        scanner.get_tv_candles_with_retry(sym, "native_1h"),
        key=lambda x: x["time"]
    )
    merged = merge_1h_to_native_2h(one, direct)

    dm = {int(round(x["time"])): x for x in direct}
    mm = {int(round(x["time"])): x for x in merged}
    common = sorted(set(dm) & set(mm))[-5:]

    print("NATIVE_2H:", len(direct))
    print("NATIVE_1H:", len(one))
    print("MERGED_1H_TO_2H:", len(merged))

    for t in common:
        d = dm[t]
        m = mm[t]
        diffs = [
            d["open"] - m["open"],
            d["high"] - m["high"],
            d["low"] - m["low"],
            d["close"] - m["close"],
        ]
        print(
            label(t),
            "DIRECT=",
            d["open"], d["high"], d["low"], d["close"],
            "MERGED=",
            m["open"], m["high"], m["low"], m["close"],
            "DIFF=",
            diffs,
        )

    row = next((x for x in scanner_data if x.get("s") == sym), None)
    print("SCANNER_120:", row.get("d") if row else None)

print("=" * 100)
print("SONUC: Native 2H ile 1H->2H DIFF sifirsa iki WebSocket veri seti OHLC olarak ayni.")
print("Scanner_120 degerleri ayri olarak gosterilir. Bu test Supertrend/Study kodunu degistirmez.")

# Trigger scanner workflow after confirmed-bar fix.
