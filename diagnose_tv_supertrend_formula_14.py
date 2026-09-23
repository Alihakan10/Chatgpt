import json,time,random,string,websocket
from datetime import datetime
from zoneinfo import ZoneInfo
URL="wss://data.tradingview.com/socket.io/websocket"
SYMBOLS=["BIST:CLEBI","BIST:EMNIS","BIST:EUHOL","BIST:KENT","BIST:KERVN","BIST:KLYPV","BIST:KRPLS","BIST:KSTUR","BIST:OYLUM","BIST:SODSN","BIST:TUCLK","BIST:TURSG","BIST:ULUFA","BIST:USHOL"]
TZ=ZoneInfo("Europe/Istanbul")
def sid(p): return p+"_"+''.join(random.choice(string.ascii_lowercase+string.digits) for _ in range(12))
def msg(m,p):
 s=json.dumps({"m":m,"p":p},separators=(",",":")); return f"~m~{len(s)}~m~{s}"
def frames(raw):
 out=[];pos=0
 while True:
  a=raw.find("~m~",pos)
  if a<0: break
  b=raw.find("~m~",a+3)
  if b<0: break
  try:n=int(raw[a+3:b])
  except: pos=b+3;continue
  st=b+3;en=st+n
  if en>len(raw):break
  out.append(raw[st:en]);pos=en
 return out,raw[pos:]
def get(sym):
 cs=sid("cs");ws=websocket.create_connection(URL,timeout=10,origin="https://www.tradingview.com")
 try:
  ws.send(msg("set_auth_token",["unauthorized_user_token"]));ws.send(msg("chart_create_session",[cs,""]))
  cfg=json.dumps({"symbol":sym,"adjustment":"splits","session":"regular"},separators=(",",":"))
  ws.send(msg("resolve_symbol",[cs,"sds_sym_1","="+cfg]));ws.send(msg("create_series",[cs,"sds_1","s1","sds_sym_1","120",3000,""]));ws.send(msg("switch_timezone",[cs,"exchange"]))
  bars={};raw="";deadline=time.time()+12
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
    if o.get("m")!="timescale_update":continue
    ps=o.get("p",[])
    if len(ps)<2:continue
    d=ps[1];s=d.get("sds_1") if isinstance(d,dict) else None
    if not isinstance(s,dict):continue
    for b in s.get("s",[]):
     v=b.get("v",[]) if isinstance(b,dict) else []
     if len(v)>=5:
      try:bars[float(v[0])]=[float(v[i]) for i in range(1,5)]
      except:pass
   if len(bars)>=2900:break
  return [{"time":t,"open":v[0],"high":v[1],"low":v[2],"close":v[3]} for t,v in sorted(bars.items())]
 finally:ws.close()
def rma_atr(c,p=10):
 tr=[]
 for i,x in enumerate(c):
  if i==0:tr.append(x["high"]-x["low"])
  else:
   pc=c[i-1]["close"];tr.append(max(x["high"]-x["low"],abs(x["high"]-pc),abs(x["low"]-pc)))
 a=[None]*len(c)
 if len(c)>=p:a[p-1]=sum(tr[:p])/p
 for i in range(p,len(c)):a[i]=(a[i-1]*(p-1)+tr[i])/p
 return a
def official(c,p=10,m=2):
 a=rma_atr(c,p);up=[None]*len(c);dn=[None]*len(c);st=[None]*len(c);d=[None]*len(c)
 for i,x in enumerate(c):
  if a[i] is None:d[i]=1;continue
  hl=(x["high"]+x["low"])/2;bu=hl+m*a[i];bl=hl-m*a[i]
  pu=0 if i==0 or up[i-1] is None else up[i-1];pl=0 if i==0 or dn[i-1] is None else dn[i-1]
  pc=c[i-1]["close"] if i else None
  up[i]=bu if i==0 or bu<pu or (pc is not None and pc>pu) else pu
  dn[i]=bl if i==0 or bl>pl or (pc is not None and pc<pl) else pl
  if i==p-1:d[i]=1
  else:
   prev=st[i-1];prevup=up[i-1]
   d[i]=-1 if prev is not None and prev==prevup and x["close"]>up[i] else (1 if prev is None or prev==prevup else (1 if x["close"]<dn[i] else -1))
  st[i]=dn[i] if d[i]==-1 else up[i]
 return d
def kivanc(c,p=10,m=2):
 a=rma_atr(c,p);up=[None]*len(c);dn=[None]*len(c);d=[1]*len(c)
 for i,x in enumerate(c):
  if a[i] is None:continue
  hl=(x["high"]+x["low"])/2;u=hl-m*a[i];q=hl+m*a[i]
  up1=u if i==0 or up[i-1] is None else up[i-1]
  dn1=q if i==0 or dn[i-1] is None else dn[i-1]
  pc=c[i-1]["close"] if i else None
  up[i]=max(u,up1) if i>0 and pc>up1 else u
  dn[i]=min(q,dn1) if i>0 and pc<dn1 else q
  prev=d[i-1] if i else 1
  d[i]=1 if (prev==-1 and x["close"]>dn1) else (-1 if (prev==1 and x["close"]<up1) else prev)
 return d
for sym in SYMBOLS:
 c=get(sym);o=official(c);k=kivanc(c)
 buys_o=[i for i in range(1,len(c)) if o[i-1]==-1 and o[i]==1]
 buys_k=[i for i in range(1,len(c)) if k[i-1]==-1 and k[i]==1]
 print("\n",sym,"BARS",len(c))
 print("OFFICIAL_LAST",o[-2:],"KIVANC_LAST",k[-2:])
 print("OFFICIAL_LAST_BUY",buys_o[-5:])
 print("KIVANC_LAST_BUY",buys_k[-5:])
 if buys_o[-1:]!=buys_k[-1:]:
  print("DIFF_LAST_BUY_TIME", [datetime.fromtimestamp(c[i]["time"],ZoneInfo("UTC")).astimezone(TZ).strftime("%Y-%m-%d %H:%M") for i in sorted(set(buys_o[-3:]+buys_k[-3:]))])
