import csv,gzip,urllib.request
from lxml import etree
from pathlib import Path
sources={
"ca2":"https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
"epg6":"https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz"
}
out=Path("_catalogs");out.mkdir(exist_ok=True)
for source,url in sources.items():
 req=urllib.request.Request(url,headers={"User-Agent":"NovaRidge-EPG/1.0"})
 with urllib.request.urlopen(req,timeout=120) as f: payload=f.read(200_000_001)
 if len(payload)>200_000_000:raise ValueError("Source too large")
 path=out/(source+".xml.gz");path.write_bytes(payload)
 entries=[]
 with gzip.open(path,"rb") as stream:
  for _,el in etree.iterparse(stream,events=("end",),tag=("channel","programme"),resolve_entities=False,no_network=True):
   if el.tag=="programme":break
   cid=el.get("id")
   if cid:
    names=[v.text.strip() for v in el.findall("display-name") if v.text and v.text.strip()]
    entries.append((cid,names[0] if names else cid," / ".join(names[1:]),source.upper()))
   el.clear()
   while el.getprevious() is not None:del el.getparent()[0]
 with (out/(source+".csv")).open("w",encoding="utf8",newline="") as f:
  w=csv.writer(f);w.writerow(["Source channel ID","Display name","Other display names","Provider"]);w.writerows(entries)
 print("CATALOG_COUNT",source,len(entries),flush=True)
