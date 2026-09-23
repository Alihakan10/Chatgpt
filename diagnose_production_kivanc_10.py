import scanner
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS=["BIST:ACSEL","BIST:AKSUE","BIST:ATSYH","BIST:BESLR","BIST:BMSCH","BIST:DMRGD","BIST:EMNIS","BIST:ENPRA","BIST:MOBTL","BIST:PETUN"]
TARGET=datetime(2026,9,23,17,0,tzinfo=ZoneInfo("Europe/Istanbul")).timestamp()

for s in SYMBOLS:
    cs=sorted(scanner.get_tv_candles_with_retry(s,"native_2h"),key=lambda x:x["time"])
    i=next(i for i,c in enumerate(cs) if float(c["time"])==TARGET)
    d=scanner.calculate_supertrend_directions(cs,10,2.0)
    print(f"{s} | PROD={d[i-1]}->{d[i]} BUY={d[i-1]==-1 and d[i]==1}")

