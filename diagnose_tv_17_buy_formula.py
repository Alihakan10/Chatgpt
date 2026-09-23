from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
TZ=ZoneInfo("Europe/Istanbul")
exec(open("diagnose_tv_supertrend_formula_14.py").read().replace(
'for sym in SYMBOLS:',
'for sym in []:',
1).replace(
'SYMBOLS=["BIST:CLEBI","BIST:EMNIS","BIST:EUHOL","BIST:KENT","BIST:KERVN","BIST:KLYPV","BIST:KRPLS","BIST:KSTUR","BIST:OYLUM","BIST:SODSN","BIST:TUCLK","BIST:TURSG","BIST:ULUFA","BIST:USHOL"]',
'SYMBOLS=["BIST:AYGAZ","BIST:BLUME","BIST:CMENT","BIST:DIRIT","BIST:DITAS","BIST:DOFRB","BIST:DYOBY","BIST:EKSUN","BIST:HATSN","BIST:KMPUR","BIST:KPEKS","BIST:KUVVA","BIST:ORMA","BIST:OYAYO","BIST:PENGD","BIST:PENTA","BIST:TURGG"]'
))
for sym in SYMBOLS:
 c=get(sym); o=official(c); k=kivanc(c); now=datetime.now(TZ); ci=None
 for ii,x in enumerate(c):
  d=datetime.fromtimestamp(x["time"],ZoneInfo("UTC")).astimezone(TZ)
  end=d.replace(hour=18,minute=0,second=0,microsecond=0) if d.hour==17 and d.minute==0 else d+timedelta(hours=2)
  if end<=now: ci=ii
 print(sym,"COMPLETED",datetime.fromtimestamp(c[ci]["time"],ZoneInfo("UTC")).astimezone(TZ).strftime("%Y-%m-%d %H:%M"),
       "OFF",o[ci-1:ci+1],"OFF_BUY",o[ci-1]==-1 and o[ci]==1,
       "KIV",k[ci-1:ci+1],"KIV_BUY",k[ci-1]==-1 and k[ci]==1)