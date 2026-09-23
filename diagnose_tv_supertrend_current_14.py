# Reuses the same native 2H feed and compares the two documented Supertrend state machines.
exec(open("diagnose_tv_supertrend_formula_14.py").read().replace(
'for sym in SYMBOLS:\n c=get(sym);o=official(c);k=kivanc(c)',
'''for sym in SYMBOLS:
 c=get(sym);o=official(c);k=kivanc(c)
 now=datetime.now(TZ)
 ci=None
 for ii,x in enumerate(c):
  d=dt(x["time"])
  end=d.replace(hour=18,minute=0,second=0,microsecond=0) if d.hour==17 and d.minute==0 else d+__import__("datetime").timedelta(hours=2)
  if end<=now: ci=ii
 if ci is not None:
  print("COMPLETED",dt(c[ci]["time"]).strftime("%Y-%m-%d %H:%M"),"OFF_PREV_CUR",o[ci-1:ci+1],"KIV_PREV_CUR",k[ci-1:ci+1],
        "OFF_BUY",o[ci-1]==-1 and o[ci]==1,"KIV_BUY",k[ci-1]==-1 and k[ci]==1)'''))