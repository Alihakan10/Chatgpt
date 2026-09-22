import os
from datetime import datetime
from zoneinfo import ZoneInfo
import scanner

S="BIST:KENT"; TZ=ZoneInfo("Europe/Istanbul")
print("AUTH MODE:", "YES" if os.getenv("TV_SESSIONID") or os.getenv("TRADINGVIEW_AUTH_TOKEN") else "NO")
bars=sorted(scanner.get_tv_candles_with_retry(S,"native_2h"),key=lambda x:x["time"])
print("NATIVE 2H COUNT",len(bars))
for b in bars[-12:]:
 d=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
 print(f"{d:%Y-%m-%d %H:%M} O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f}")
idx=scanner.get_last_completed_index(bars)
bars=bars[:idx+1]
old=scanner.calculate_supertrend_directions(bars,10,2.0)
tv=scanner.calculate_tradingview_supertrend_directions(bars,10,2.0)
print("\nLAST 12 DIRECTIONS")
for i in range(max(1,len(bars)-12),len(bars)):
 d=datetime.fromtimestamp(bars[i]["time"],tz=ZoneInfo("UTC")).astimezone(TZ)
 ob=old[i]; tb=tv[i]
 print(f"{d:%Y-%m-%d %H:%M} OLD={ob} TV={tb} OLD_BUY={old[i-1]==-1 and ob==1} TV_BUY={tv[i-1]==1 and tb==-1}")
print("\nLAST:",old[-1],tv[-1])
print("OLD BUY:",old[-2]==-1 and old[-1]==1)
print("TV BUY:",tv[-2]==1 and tv[-1]==-1)
