import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

for symbol in ["BIST:DEVA", "BIST_MIXED:DEVA"]:
    print("\\n===", symbol, "===")
    try:
        candles = scanner.get_tv_candles(symbol, candle_mode="native_2h")
        for c in candles[-8:]:
            dt=datetime.fromtimestamp(c["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
            print(dt.strftime("%d.%m.%Y %H:%M"), "O=",c["open"],"H=",c["high"],"L=",c["low"],"C=",c["close"])
        print("COUNT",len(candles))
    except Exception as e:
        print("ERROR",repr(e))
