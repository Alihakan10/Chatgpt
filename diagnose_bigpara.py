import json, os, requests
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOLS = ["CLEBI","EMNIS","EUHOL","KENT","KERVN","KLYPV","KRPLS","KSTUR","OYLUM","SODSN","TUCLK","TURSG","ULUFA","USHOL"]
URL = "https://bigpara.hurriyet.com.tr/api/v1/chart/hisse/{id}/1"
LIST_URL = "https://bigpara.hurriyet.com.tr/api/v1/hisse/list"

def main():
    out=[]
    s=requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0","Referer":"https://bigpara.hurriyet.com.tr/"})
    try:
        lr=s.get(LIST_URL,timeout=20)
        print("LIST",lr.status_code,lr.text[:2000])
        ld=lr.json() if lr.ok else None
        items=ld.get("data",ld) if isinstance(ld,dict) else ld
        if isinstance(items,dict): items=items.get("data",items.get("value",[]))
        mapping={}
        if isinstance(items,list):
            for x in items:
                if isinstance(x,dict):
                    code=str(x.get("kod") or x.get("Code") or x.get("code") or x.get("HisseKodu") or x.get("symbol") or "").upper()
                    ident=x.get("id") or x.get("_id") or x.get("HisseId") or x.get("ID")
                    if code and ident: mapping[code]=ident
        print("MAPPING_SAMPLE",list(mapping.items())[:10])
    except Exception as e:
        print("LIST ERROR",e); mapping={}
    for sym in SYMBOLS:
        try:
            ident=mapping.get(sym)
            if not ident: raise RuntimeError("Bigpara listesinde ID bulunamadi")
            r=s.get(URL.format(id=ident),timeout=20)
            text=r.text[:5000]
            item={"symbol":sym,"id":ident,"status":r.status_code,"content_type":r.headers.get("content-type",""),"text_head":text[:1500]}
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
