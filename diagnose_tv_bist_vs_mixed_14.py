import json,time,random,string,websocket
from datetime import datetime
from zoneinfo import ZoneInfo
SYMBOLS=["CLEBI","EMNIS","EUHOL","KENT","KERVN","KLYPV","KRPLS","KSTUR","OYLUM","SODSN","TUCLK","TURSG","ULUFA","USHOL"]
def msg(m,p):
 s=json.dumps({"m":m,"p":p},separators=(",",":")); return f"~m~{len(s)}~m~{s}"
def frames(raw):
 out=[]; pos=0
 while 1:
  s=raw.find("~m~",pos)
  if s<0: break
  a=s+3;b=raw.find("~m~",a)
  if b<0: break
  try:n=int(raw[a:b])
  except:pos=b+3;continue
  j=b+3
  if j+n>len(raw):break
  out.append(raw[j:j+n]);pos=j+n
 return out,raw[pos:]
def get(sym,exchange):
 cs="cs_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(10))
 ws=websocket.create_connection("wss://data.tradingview.com/socket.io/websocket",timeout=8,origin="https://www.tradingview.com")
 try:
  ws.send(msg("set_auth_token",["unauthorized_user_token"]));ws.send(msg("chart_create_session",[cs,""]))
  full=exchange+":"+sym
  desc=json.dumps({"symbol":full,"adjustment":"splits","session":"regular"},separators=(",",":"))
  ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+desc]));ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1","120",3000,""]))
  ws.send(msg("switch_timezone",[cs,"exchange"]))
  raw="";bars={}
  end=time.time()+8
  while time.time()<end:
   try:p=ws.recv()
   except:break
   if isinstance(p,bytes):p=p.decode("utf8","ignore")
   raw+=p;fs,raw=frames(raw)
   for x in fs:
    try:d=json.loads(x)
    except:continue
    if d.get("m")!="timescale_update":continue
    node=d.get("p",[None,{}])[1].get("sds_1",{})
    for q in node.get("s",[]):
     v=q.get("v",[])
     if len(v)>=5 and all(z is not None for z in v[:5]):
      bars[float(v[0])]=v[:5]
  return sorted(bars.values(),key=lambda x:x[0])
 finally:
  ws.close()
def fmt(v):
 d=datetime.fromtimestamp(v[0],tz=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Istanbul"))
 return f"{d:%m-%d %H:%M} O={v[1]:.2f} H={v[2]:.2f} L={v[3]:.2f} C={v[4]:.2f}"
print("NEW TEST: BIST vs BIST_MIXED NATIVE 2H DATA")
print("NO STUDY / NO BROKER / NO 1H->2H MERGE")
for sym in SYMBOLS:
 print("\nBIST:"+sym)
 try:
  a=get(sym,"BIST"); b=get(sym,"BIST_MIXED")
  print("BIST bars:",len(a),"BIST_MIXED bars:",len(b))
  if a: print("  BIST:",fmt(a[-1]))
  if b: print("  MIXED:",fmt(b[-1]))
  if a and b:
   aa={x[0]:x for x in a};bb={x[0]:x for x in b};common=sorted(set(aa)&set(bb))
   diffs=[t for t in common[-20:] if aa[t][1:]!=bb[t][1:]]
   print("  common:",len(common),"different_last20:",len(diffs))
   if diffs:
    t=diffs[-1];print("  DIFFERENCE:",fmt(aa[t]),"| MIXED:",fmt(bb[t]))
 except Exception as e: print("  ERROR:",repr(e))
print("\nTEST FINISHED")
