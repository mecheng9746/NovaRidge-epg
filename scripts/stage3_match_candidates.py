#!/usr/bin/env python3
"""Stage 3: human-reviewed source-channel candidates for Canadian IPTV inventory.

Identifies source channels using names and supplied tvg-ids. It NEVER certifies
that a programme is airing on the IPTV stream; human programme verification is
required. Rejects ambiguous candidates and preserves separate source IDs.
"""
import argparse
import csv
import gzip
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from lxml import etree
try:
    from scripts.collect_telus_livechannels import request_catalog, extract
    from scripts.collect_ca2 import download, CA2_URL
except ImportError:
    from collect_telus_livechannels import request_catalog, extract
    from collect_ca2 import download, CA2_URL

EPG6_URL="https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz"
REMOVE={"hd","fhd","uhd","4k","sd","ca","canada","channel","tv"}
SPORTS=("tsn","sportsnet","sn ")
SPECIAL={"east","west","pacific","ontario","alberta","calgary","edmonton","vancouver","toronto","montreal","flames","oilers","1","2","3","4","5","360"}
FIELDS=["playlist_position","playlist_group","playlist_name","playlist_tvg_id",
        "source","source_channel_id","source_channel_name","identity_score",
        "identity_reason","risk_flags","review_status"]

def tokens(s):
    s=unicodedata.normalize("NFKD",str(s)).casefold()
    s="".join(c for c in s if not unicodedata.combining(c))
    s=re.sub(r"(?i)^ca\s*[|:]\s*","",s)
    s=re.sub(r"[^a-z0-9]+"," ",s)
    return [t for t in s.split() if t not in REMOVE]

def key(s):
    return " ".join(tokens(s))

def hints(s):
    t=set(tokens(s))
    return t & SPECIAL

def load_xmltv_channels(path):
    out={}
    with gzip.open(path,"rb") as f:
        for _,e in etree.iterparse(f,events=("end",),tag=("channel","programme"),resolve_entities=False,no_network=True):
            if e.tag=="channel":
                cid=e.get("id")
                if cid:
                    values=[x.text.strip() for x in e.findall("display-name") if x.text and x.text.strip()]
                    out[cid]=values or [cid]
            e.clear()
            while e.getprevious() is not None: del e.getparent()[0]
    return out

def rank_channel(playlist, candidate_names, source_id):
    name=playlist["name"]
    pid=playlist.get("tvg_id","")
    pk=key(name)
    candidates=[key(s) for s in candidate_names if key(s)]
    ckey=key(source_id)
    # Channel IDs are not generally comparable across provider namespaces.
    exact_id=bool(pid and (pid.casefold()==source_id.casefold()))
    exact_name=bool(pk and pk in candidates)
    if exact_id and exact_name: score,reason=98,"exact tvg-id plus name"
    elif exact_id: score,reason=88,"exact tvg-id (name unverified)"
    elif exact_name: score,reason=80,"normalized name match"
    else: return None
    risk=[]
    ph=hints(name+" "+pid)
    ch=set().union(*(hints(x) for x in candidate_names))
    if ph != ch and (ph or ch):
        # Generic IDs like AandE.ca have no regional token; do not equate them.
        risk.append("regional_variant_check")
        score-=20
    if any(x in ("tsn","sportsnet") for x in tokens(name)):
        risk.append("sports_feed_programme_validation")
    if "east" in ph and "west" in ch or "west" in ph and "east" in ch:
        return None
    return max(0,score),reason,";".join(risk)

def candidates_for(playlist, source_catalogs, limit=4):
    results=[]
    for source,catalog in source_catalogs.items():
        matches=[]
        for cid,names in catalog.items():
            found=rank_channel(playlist,names,cid)
            if found is not None:
                score,reason,flags=found
                matches.append((score,cid,names[0],reason,flags))
        matches.sort(key=lambda x:(-x[0],x[1]))
        for score,cid,name,reason,flags in matches[:limit]:
            results.append({"playlist_position":playlist["position"],"playlist_group":playlist["group"],
              "playlist_name":playlist["name"],"playlist_tvg_id":playlist["tvg_id"],
              "source":source.upper(),"source_channel_id":cid,"source_channel_name":name,
              "identity_score":score,"identity_reason":reason,"risk_flags":flags,
              "review_status":"PENDING — verify programme schedule"})
    results.sort(key=lambda x:(-int(x["identity_score"]),{"TELUS":0,"CA2":1,"EPG6":2}[x["source"]],x["source_channel_id"]))
    # Ranking is only an ordering; every row remains unconfirmed.
    return results

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--playlist",type=Path,default=Path("data/stage3-canadian-playlist.json"))
    p.add_argument("--telus-catalog",type=Path,default=Path("_stage3/telus-catalog.json"))
    p.add_argument("--ca2",type=Path,default=Path("_sources/ca2.xml.gz"))
    p.add_argument("--epg6",type=Path,default=Path("_sources/epg6.xml.gz"))
    p.add_argument("--output",type=Path,default=Path("_stage3/match-candidates.csv"))
    p.add_argument("--summary",type=Path,default=Path("_stage3/summary.json"))
    args=p.parse_args()
    playlist=json.loads(args.playlist.read_text())
    if not args.telus_catalog.exists():
        rows=extract(request_catalog(1),1)
        args.telus_catalog.parent.mkdir(parents=True,exist_ok=True)
        args.telus_catalog.write_text(json.dumps(rows,indent=1))
    telus=json.loads(args.telus_catalog.read_text())
    catalogs={"telus":defaultdict(list)}
    for row in telus: catalogs["telus"][row["channel_id"]].append(row["channel_name"])
    for source,path,url in [("ca2",args.ca2,CA2_URL),("epg6",args.epg6,EPG6_URL)]:
        if not path.exists():
            path.parent.mkdir(parents=True,exist_ok=True)
            download(url,path)
        catalogs[source]=load_xmltv_channels(path)
    results=[]
    coverage={}
    for pitem in playlist:
        cand=candidates_for(pitem,catalogs)
        results.extend(cand)
        coverage[pitem["position"]]=len(cand)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",newline="",encoding="utf-8") as out:
        writer=csv.DictWriter(out,fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    stats={"playlist_channels":len(playlist),"source_channels":{k:len(v) for k,v in catalogs.items()},
           "candidate_rows":len(results),"with_candidates":sum(v>0 for v in coverage.values()),
           "without_candidates":sum(v==0 for v in coverage.values()),
           "approved_matches":0,"approval_policy":"No match is approved without programme evidence."}
    args.summary.write_text(json.dumps(stats,indent=2)+"\n")
    print("STAGE3_SUMMARY|"+json.dumps(stats),flush=True)
    # Print capped preview only, never flood action logs with 801 candidates.
    for row in results[:25]: print("CANDIDATE_PREVIEW|"+json.dumps(row,ensure_ascii=True),flush=True)
if __name__=="__main__":
    main()
