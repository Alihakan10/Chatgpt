import os, json, time
from tradingviewApiPython import Client
SYMBOLS=["CLEBI","EMNIS","EUHOL","KENT","KERVN","KLYPV","KRPLS","KSTUR","OYLUM","SODSN","TUCLK","TURSG","ULUFA","USHOL"]
def fetch(client,sym):
    chart=client.Session.Chart()
    try:
        chart.set_market("BIST:"+sym, {"timeframe":"2H","range":80})
        start=time.time()
        while time.time()-start<15:
            periods=getattr(chart,"periods",[]) or []
            if len(periods)>=20: return {"symbol":sym,"count":len(periods),"last":list(periods)[:8]}
            time.sleep(.2)
        return {"symbol":sym,"count":len(getattr(chart,"periods",[]) or []),"error":"timeout"}
    except Exception as e: return {"symbol":sym,"error":str(e)}
    finally:
        try: chart.delete()
        except: pass
def main():
    sid=os.getenv("TV_SESSIONID","").strip(); sig=os.getenv("TV_SESSIONID_SIGN","").strip()
    print("SESSIONID_PRESENT",bool(sid),"SESSIONID_SIGN_PRESENT",bool(sig))
    client=Client(token=sid or None, signature=sig or None); out=[]
    try:
        for s in SYMBOLS:
            x=fetch(client,s); out.append(x); print("\n===",s,"==="); print(json.dumps(x,ensure_ascii=False,indent=2)[:5000])
    finally:
        try: client.end()
        except: pass
    os.makedirs("diagnostics",exist_ok=True)
    with open("diagnostics/tv_sdk_14.json","w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
if __name__=="__main__": main()