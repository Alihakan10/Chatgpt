import sys, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, ".")
from scanner import get_tv_candles

SYMBOLS = ["BIST:BAKAB","BIST:BARMA","BIST:BRKO","BIST:DGGYO","BIST:EUHOL","BIST:GSDHO","BIST:LMKDC","BIST:PAGYO","BIST:RNPOL","BIST:SANKO","BIST:SUNTK","BIST:VKFYO"]
TZ=ZoneInfo("Europe/Istanbul")

for symbol in SYMBOLS:
    try:
        cs=get_tv_candles(symbol,candle_mode="native_2h",candle_session="regular")
        rows=[]
        for c in cs:
            dt=datetime.fromtimestamp(c["time"],timezone.utc).astimezone(TZ)
            if dt.date().isoformat() in ("2026-09-25","2026-09-26"):
                rows.append({
                    "time":dt.isoformat(),
                    "epoch":c["time"],
                    "open":c["open"],"high":c["high"],
                    "low":c["low"],"close":c["close"]
                })
        print("\n=== "+symbol+" ===")
        print(json.dumps(rows,ensure_ascii=False))
    except Exception as e:
        print("\n=== "+symbol+" ERROR ===\n"+repr(e))
