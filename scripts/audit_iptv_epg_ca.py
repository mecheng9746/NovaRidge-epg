#!/usr/bin/env python3
"""Audit iptv-epg.org CA source against existing TELUS, CA2 and EPG6 catalogs."""
import csv,gzip,json,urllib.request,unicodedata,re
from collections import Counter
from pathlib import Path
from lxml import etree
from scripts.stage3_match_candidates import load_xmltv_channels, EPG6_URL
from scripts.collect_ca2 import CA2_URL,download
from scripts.collect_telus_livechannels import request_catalog,extract
URL="https://iptv-epg.org/files/epg-ca.xml"
def canonical(s):
    s=unicodedata.normalize("NFKD",str(s)).casefold()
    s="".join(x for x in s if not unicodedata.combining(x))
    s=re.sub(r"[^a-z0-9]+"," ",s)
    return " ".join(x for x in s.split() if x not in {"hd","sd","uhd","fhd","ca","canada","tv","channel"})
def read_xml(data):
    from io import BytesIO
    ids={}
    root=etree.iterparse(BytesIO(data),events=("end",),tag=("channel","programme"),resolve_entities=False,no_network=True)
    counts=Counter()
    for _,elem in root:
        if elem.tag=="programme":
            cid=elem.get("channel")
            if cid:counts[cid]+=1
        else:
            cid=elem.get("id")
            if cid:
                names=[x.text.strip() for x in elem.findall("display-name") if x.text and x.text.strip()]
                ids[cid]=names or [cid]
        elem.clear()
        while elem.getprevious() is not None:del elem.getparent()[0]
    return ids,counts
def main():
    req=urllib.request.Request(URL,headers={"User-Agent":"NovaRidge-EPG/1.0"})
    with urllib.request.urlopen(req,timeout=120) as r:data=r.read(150_000_001)
    if len(data)>150_000_000:raise ValueError("Guide exceeded 150MB")
    print("DOWNLOAD",len(data),"bytes",flush=True)
    ids,counts=read_xml(data)
    if not ids:raise ValueError("No channels in guide")
    telus={r["channel_id"]:[r["channel_name"]] for r in extract(request_catalog(1),1)}
    existing={"TELUS":telus}
    for source,url in [("CA2",CA2_URL),("EPG6",EPG6_URL)]:
        path=Path("_audit")/(source+".xml.gz")
        path.parent.mkdir(exist_ok=True)
        download(url,path)
        existing[source]=load_xmltv_channels(path)
    known_ids={name:set(ch) for name,ch in existing.items()}
    known_names={name:set(canonical(x) for values in ch.values() for x in values) for name,ch in existing.items()}
    output=[]
    for cid,names in ids.items():
        ident=[s for s in existing if cid in known_ids[s]]
        names_match=[s for s in existing if any(canonical(n) and canonical(n) in known_names[s] for n in names)]
        status="EXACT_ID_EXISTS" if ident else "NAME_EXISTS" if names_match else "POTENTIALLY_NEW"
        output.append({"source_id":cid,"source_names":" / ".join(names),"programme_records":counts.get(cid,0),"status":status,
                       "exact_id_sources":";".join(ident),"name_match_sources":";".join(names_match)})
    out=Path("_audit/iptv-epg-ca-audit.csv")
    with out.open("w",newline="",encoding="utf8") as f:
        writer=csv.DictWriter(f,fieldnames=list(output[0]));writer.writeheader();writer.writerows(output)
    stats={"new_source_channels":len(ids),"new_programme_records":sum(counts.values()),
          "catalog_counts":{k:len(v) for k,v in existing.items()},
          "statuses":dict(Counter(x["status"] for x in output)),
          "caution":"Channel identity differences do not prove programme equivalence or IPTV match."}
    Path("_audit/summary.json").write_text(json.dumps(stats,indent=2))
    print("AUDIT_SUMMARY|"+json.dumps(stats),flush=True)
    for row in output:
        if row["status"]=="POTENTIALLY_NEW":
            print("NEW_CHANNEL|"+json.dumps(row,ensure_ascii=True,separators=(",",":")),flush=True)
if __name__=="__main__":main()
