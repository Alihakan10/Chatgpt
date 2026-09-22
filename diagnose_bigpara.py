import json, os, requests
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = ["CLEBI","EMNIS","EUHOL","KENT","KERVN","KLYPV","KRPLS","KSTUR","OYLUM","SODSN","TUCLK","TURSG","ULUFA","USHOL"]
URL = "https://bigpara.hurriyet.com.tr/api/v1/chart/tradingviewlight/history"

def main():
    out=[]
    s=requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0","Referer":"https://bigpara.hurriyet.com.tr/"})
    for sym in SYMBOLS:
        try:
            r=s.get(URL,params={"symbol":sym},timeout=20)
            text=r.text[:5000]
            item={"symbol":sym,"status":r.status_code,"content_type":r.headers.get("content-type",""),"text_head":text[:1500]}
            if r.ok:
                try:
                    data=r.json()
                    item["json_type"]=type(data).__name__
                    item["keys"]=list(data.keys()) if isinstance(data,dict) else None
                    item["sample"]=data[-5:] if isinstance(data,list) else data
                except Exception as e:
                    item["json_error"]=str(e)
            out.append(item)
            print("\n=== "+sym+" ===")
            print(json.dumps(item,ensure_ascii=False,indent=2)[:5000])
        except Exception as e:
            out.append({"symbol":sym,"error":str(e)})
            print(sym,"ERROR",e)
    with open("diagnostics/bigpara_14.json","w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False,indent=2)

if __name__=="__main__":
    main()
