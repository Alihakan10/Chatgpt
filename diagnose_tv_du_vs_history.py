import json,time,random,string,websocket
from datetime import datetime
from zoneinfo import ZoneInfo
URL="wss://data.tradingview.com/socket.io/websocket";TZ=ZoneInfo("Europe/Istanbul")
SYMBOLS=["BIST:AYGAZ","BIST:BLUME","BIST:CMENT"]
def sid(p):return p+"_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12))
def msg(m,p):
 s=json.dumps({"m":m,"p":p},separators=(",",":"));return f"~m~{len(s)}~m~{s}"
def frames(raw):
 out=[];pos=0
 while 1:
  a=raw.find("~m~",pos)
  if a<0:break
  b=raw.find("~m~",a+3)
  if b<0:break
  try:n=int(raw[a+3:b])
  except:pos=b+3;continue
  st=b+3;en=st+n
  if en>len(raw):break
  out.append(raw[st:en]);pos=en
 return out,raw[pos:]
for sym in SYMBOLS:
 cs=sid("cs");ws=websocket.create_connection(URL,timeout=10,origin="https://www.tradingview.com")
 try:
  ws.send(msg("set_auth_token",["unauthorized_user_token"]));ws.send(msg("chart_create_session",[cs,""]))
  cfg=json.dumps({"symbol":sym,"adjustment":"splits","session":"regular"},separators=(",",":"))
  ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+cfg]));ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1","120",30,""]));ws.send(msg("switch_timezone",[cs,"exchange"]))
  raw="";seen=[];deadline=time.time()+8
  while time.time()<deadline:
   try:p=ws.recv()
   except:break
   if isinstance(p,bytes):p=p.decode("utf8","ignore")
   raw+=p;fs,raw=frames(raw)
   for x in fs:
    if x.startswith("~h~"):
     try:ws.send(x)
     except:pass
     continue
    try:o=json.loads(x)
    except:continue
    if o.get("m") not in ("timescale_update","du"):continue
    ps=o.get("p",[]);d=ps[1] if len(ps)>1 else {}
    s=d.get("sds_1") if isinstance(d,dict) else None
    if not isinstance(s,dict):continue
    for b in s.get("s",[]):
     v=b.get("v",[]) if isinstance(b,dict) else []
     if len(v)>=5:
      dt=datetime.fromtimestamp(v[0],ZoneInfo("UTC")).astimezone(TZ)
      if dt.date().isoformat()=="2026-09-23" and dt.hour in (11,13):
       seen.append((o["m"],dt.strftime("%H:%M"),v[1:5]))
  print("\n",sym)
  for row in seen[-12:]: print(row)
 finally:ws.close()
