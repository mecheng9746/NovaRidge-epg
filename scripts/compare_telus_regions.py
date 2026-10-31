#!/usr/bin/env python3
"""Compare actual TELUS programmes by channel ID across EPG region IDs."""
import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
try:
    from scripts.collect_telus import THREE_HOURS_MS, request_window, parse_response
    from scripts.collect_telus_livechannels import request_catalog, extract
except ImportError:
    from collect_telus import THREE_HOURS_MS, request_window, parse_response
    from collect_telus_livechannels import request_catalog, extract

def comparable(records):
    result = defaultdict(set)
    for r in records:
        # Ignore descriptions and metadata revisions; compare the on-air programme.
        result[r["channel_id"]].add((r["start_ms"], r["end_ms"], " ".join(r["title"].casefold().split())))
    return result

def compare(baseline, candidate, base_names, other_names, reference_region, other_region):
    left, right = comparable(baseline), comparable(candidate)
    channel_ids = sorted(set(left) & set(right), key=lambda s: (0,int(s)) if s.isdigit() else (1,s))
    output = []
    for cid in channel_ids:
        a,b=left[cid],right[cid]
        same = a & b
        union = a | b
        output.append({
            "region_a": reference_region, "region_b": other_region,
            "channel_id": cid, "name_a": base_names.get(cid,""),
            "name_b": other_names.get(cid,""),
            "region_a_programmes": len(a), "region_b_programmes": len(b),
            "exact_airings": len(same),
            "jaccard_pct": round(100 * len(same)/len(union), 1) if union else 0,
            "identical": "YES" if a==b else "NO",
            "a_only_example": next(iter(sorted(a-b)),None),
            "b_only_example": next(iter(sorted(b-a)),None),
        })
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--regions",default="1,7,19,22,25,28")
    p.add_argument("--hours",type=int,default=24)
    p.add_argument("--delay",type=float,default=2)
    p.add_argument("--output",type=Path,default=Path("_comparisons/telus-schedule-comparison.csv"))
    p.add_argument("--summary",type=Path,default=Path("_comparisons/summary.json"))
    args=p.parse_args()
    regions=[int(x) for x in args.regions.split(",")]
    if len(regions)<2 or regions[0]!=1 or len(regions)>6 or len(set(regions))!=len(regions): p.error("Provide 1 plus up to five other unique regions")
    if not 3<=args.hours<=48 or args.hours%3: p.error("hours must be divisible by 3, between 3 and 48")
    if not 1.5<=args.delay<=30: p.error("delay 1.5-30 seconds")
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    now=now.replace(hour=now.hour//3*3)
    start=int(now.timestamp()*1000)
    guides={}
    names={}
    for region in regions:
        catalog=extract(request_catalog(region),region)
        names[region]={r["channel_id"]:r["channel_name"] for r in catalog}
        records=[]
        for i in range(args.hours//3):
            lower=start+i*THREE_HOURS_MS
            response=request_window(lower,lower+THREE_HOURS_MS,region)
            records.extend(parse_response(response))
            time.sleep(args.delay)
        guides[region]=records
        print(f"REGION {region}: {len(names[region])} catalog channels; {len(records)} raw programme records",flush=True)
    comparisons=[]
    for region in regions[1:]:
        rows=compare(guides[1],guides[region],names[1],names[region],1,region)
        comparisons.extend(rows)
        exact=sum(x["identical"]=="YES" for x in rows)
        nonmatching=[x for x in rows if x["identical"]=="NO"]
        print("COMPARE_SUMMARY|"+json.dumps({"region":region,"shared_channels":len(rows),"identical_channels":exact,"nonidentical_channels":len(nonmatching),
            "sports_differences":[{"id":x["channel_id"],"name":x["name_b"],"jaccard_pct":x["jaccard_pct"]} for x in nonmatching if any(t in (x["name_a"]+" "+x["name_b"]).lower() for t in ("tsn","sportsnet"))],
            "local_differences":[{"id":x["channel_id"],"name":x["name_b"],"jaccard_pct":x["jaccard_pct"]} for x in nonmatching if any(t in (x["name_a"]+" "+x["name_b"]).lower() for t in ("cbc","ctv","citytv","global"))]
        },separators=(",",":")),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("w",newline="",encoding="utf8") as f:
        fields=["region_a","region_b","channel_id","name_a","name_b","region_a_programmes","region_b_programmes","exact_airings","jaccard_pct","identical","a_only_example","b_only_example"]
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for item in comparisons:
            row=dict(item)
            for key in ("a_only_example","b_only_example"):
                row[key]=json.dumps(row[key]) if row[key] else ""
            writer.writerow(row)
    result={"start_utc":now.isoformat(),"hours":args.hours,"regions":regions,
        "comparisons":len(comparisons),"matched_channels":sum(x["identical"]=="YES" for x in comparisons)}
    args.summary.write_text(json.dumps(result,indent=2)+"\n")
    print("COMPLETED "+json.dumps(result),flush=True)
if __name__=="__main__":
    main()
