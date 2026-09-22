import os,json,time,random,string,websocket
from datetime import datetime
from zoneinfo import ZoneInfo
WS="wss://data.tradingview.com/socket.io/websocket"; TZ="Europe/Istanbul"; SYMBOL="BIST:KENT"
def msg(m,p):
 s=json.dumps({"m":m,"p":p},separators=(",",":")); return f"~m~{len(s)}~m~{s}"
def sess(p): return p+"_"+"".join(random.choice(string.ascii_lowercase) for _ in range(12))
def frames(raw):
 out=[]; pos=0
 while True:
  st=raw.find("~m~",pos)
  if st<0: break
  le=raw.find("~m~",st+3)
  if le<0: break
  n=int(raw[st+3:le]); js=le+3; je=js+n
  if je>len(raw): break
  out.append(raw[js:je]); pos=je
 return out,raw[pos:]
sid=os.getenv("TV_SESSIONID","").strip(); sig=os.getenv("TV_SESSIONID_SIGN","").strip()
headers=["Cookie: sessionid="+sid+("; sessionid_sign="+sig if sig else "")] if sid else []
ws=websocket.create_connection(WS,timeout=12,origin="https://www.tradingview.com",header=headers)
try:
 auth=os.getenv("TRADINGVIEW_AUTH_TOKEN","").strip() or "unauthorized_user_token"
 cs=sess("cs"); qs=sess("qs")
 for m,p in [("set_auth_token",[auth]),("chart_create_session",[cs,""]),("switch_timezone",[cs,"exchange"]),("quote_create_session",[qs]),("quote_set_fields",[qs,"lp","volume","ch","chp"]),("quote_add_symbols",[qs,SYMBOL]),("resolve_symbol",[cs,"sds_sym_1","="+json.dumps({"symbol":SYMBOL,"adjustment":"splits","session":"regular"},separators=(",",":"))]),("create_series",[cs,"sds_1","s1","sds_sym_1","60",3000,""])]:
  ws.send(msg(m,p))
 candles={}; raw=""; start=time.time()
 while time.time()-start<12:
  try: packet=ws.recv()
  except Exception: break
  if isinstance(packet,bytes): packet=packet.decode("utf-8","ignore")
  raw+=packet; fs,raw=frames(raw)
  for payload in fs:
   if payload.startswith("~h~"):
    try: ws.send("~m~"+str(len(payload))+"~m~"+payload)
    except: pass
    continue
   try: obj=json.loads(payload)
   except: continue
   if obj.get("m") not in ("timescale_update","du"): continue
   p=obj.get("p",[])
   if len(p)<2 or not isinstance(p[1],dict): continue
   sd=p[1].get("sds_1")
   if not isinstance(sd,dict): continue
   for bar in sd.get("s",[]):
    v=bar.get("v") if isinstance(bar,dict) else None
    if isinstance(v,list) and len(v)>=5:
     try:
      t,o,h,l,c=map(float,v[:5]); candles[t]={"time":t,"open":o,"high":h,"low":l,"close":c}
     except: pass
 bars=sorted(candles.values(),key=lambda x:x["time"])
 one=[]
 for b in bars[-100:]:
  dt=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ))
  if 10<=dt.hour<18 and dt.minute==0: one.append(b)
 grouped={}
 for b in one:
  dt=datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ)); start_h=10+((dt.hour-10)//2)*2; grouped.setdefault((dt.date(),start_h),[]).append(b)
 merged=[]
 for key,bs in sorted(grouped.items()):
  bs=sorted(bs,key=lambda x:x["time"])
  if len(bs)==2: merged.append({"time":bs[0]["time"],"open":bs[0]["open"],"high":max(x["high"] for x in bs),"low":min(x["low"] for x in bs),"close":bs[-1]["close"]})
 out={"auth":bool(os.getenv("TRADINGVIEW_AUTH_TOKEN") or sid),"raw_1h":[{"time":datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M"),"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"]} for b in one[-20:]],"merged_2h":[{"time":datetime.fromtimestamp(b["time"],tz=ZoneInfo("UTC")).astimezone(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M"),"open":b["open"],"high":b["high"],"low":b["low"],"close":b["close"]} for b in merged[-10:]]}
 os.makedirs("diagnostics",exist_ok=True)
 json.dump(out,open("diagnostics/kent_alignment.json","w"),indent=2)
 print(json.dumps(out,indent=2))
finally: ws.close()
