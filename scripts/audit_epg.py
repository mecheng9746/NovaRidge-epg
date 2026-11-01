#!/usr/bin/env python3
"""Read-only Canadian EPG coverage and candidate audit. Never changes production mappings."""
import argparse,csv,gzip,io,json,os,re,sys,unicodedata,urllib.request
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

SHEET_ID="1qkI09neYuJHR9iTB9k0LTUA_3RydrASkOc1FerOi8DQ"
CA2="https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz"
HEADERS={
"COVERAGE MONITOR":["Audit UTC","Playlist position","IPTV channel","IPTV tvg-id","Selected provider","Source ID","Status","Current programme","Coverage 24h %","Coverage 72h %","Future programmes","Last programme UTC","Notes"],
"MAPPING CANDIDATES":["Audit UTC","Playlist position","IPTV channel","Current provider","Current source ID","Suggested provider","Suggested source ID","Confidence","Matched slots","Compared slots","Time offset min","Evidence","Review decision","PR URL"],
"SOURCE HEALTH":["Audit UTC","Provider","Result","Channels","Programme count","Earliest UTC","Latest UTC","Notes"]}
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"NovaRidge-EPG-Audit/1.0"})
    with urllib.request.urlopen(req,timeout=150) as f:
        content=f.read(150_000_001)
    if len(content)>150_000_000: raise ValueError("download too large")
    return content
def programs(url):
    data=get(url)
    if data[:2]==b"\x1f\x8b": data=gzip.decompress(data)
    root=ET.fromstring(data)
    result=defaultdict(list); names={}
    for c in root.findall("channel"):
        cid=c.get("id")
        names[cid]=" ".join(x.text or "" for x in c.findall("display-name")[:1]) or cid
    for p in root.findall("programme"):
        cid=p.get("channel"); a=parse_time(p.get("start")); b=parse_time(p.get("stop"))
        if not cid or a is None or b is None or b<=a: continue
        title=p.findtext("title") or ""
        result[cid].append((a,b,title))
    for vals in result.values(): vals.sort()
    return result,names
def parse_time(s):
    if not s:return None
    try:
        return datetime.strptime(s[:14],"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()-offset(s)
    except ValueError:return None
def offset(s):
    m=re.search(r"([+-])(\d{2})(\d{2})$",s.strip())
    if not m:return 0
    seconds=(int(m[2])*60+int(m[3]))*60
    return seconds*(1 if m[1]=="+" else -1)
def norm(s):
    s=unicodedata.normalize("NFKD",s).casefold()
    s=re.sub(r"[^a-z0-9]+"," ",s)
    return " ".join(s.split())
def coverage(vals,start,end):
    spans=sorted((max(a,start),min(b,end)) for a,b,_ in vals if b>start and a<end)
    total=0;cursor=start
    for a,b in spans:
        if b>cursor:total+=b-max(cursor,a);cursor=max(cursor,b)
    return round(100*total/(end-start),1)
def sheets_rows():
    secret=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not secret: raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON required to read Canadian master")
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    from urllib.parse import quote
    creds=service_account.Credentials.from_service_account_info(json.loads(secret),scopes=["https://www.googleapis.com/auth/spreadsheets"])
    session=AuthorizedSession(creds)
    url=f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/"+quote("'CANADIAN MASTER'!A1:P822",safe="")
    r=session.get(url,timeout=60);r.raise_for_status()
    rows=r.json().get("values",[])
    keys=rows[0];return [dict(zip(keys,row+[""]*(len(keys)-len(row)))) for row in rows[1:] if row]
def publish(tab,rows):
    secret=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not secret:return
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    from urllib.parse import quote
    creds=service_account.Credentials.from_service_account_info(json.loads(secret),scopes=["https://www.googleapis.com/auth/spreadsheets"])
    session=AuthorizedSession(creds)
    base=f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/"
    # Only the automated data area is cleared; review decisions are preserved separately.
    end="M" if tab=="COVERAGE MONITOR" else "L" if tab=="MAPPING CANDIDATES" else "H"
    region=quote(f"'{tab}'!A2:{end}2000",safe="")
    # Preserve manual review decision and PR URL columns in the candidates tab.
    r=session.post(base+region+":clear",json={},timeout=60);r.raise_for_status()
    if rows:
        region=quote(f"'{tab}'!A2",safe="")
        r=session.put(base+region,params={"valueInputOption":"RAW"},json={"values":rows},timeout=60);r.raise_for_status()
def best_titles(vals,t):
    return next((name for a,b,name in vals if a<=t<b),"")
def match_score(a,b,now):
    slots=[now+h*1800 for h in range(48)]
    results=[]
    for off in (0,-3600,3600,-7200,7200,-10800,10800):
        pairs=[]
        for ts in slots:
            x=norm(best_titles(a,ts));y=norm(best_titles(b,ts+off))
            if x and y:
                pairs.append(SequenceMatcher(None,x,y).ratio())
        if len(pairs)<10:continue
        high=sum(v>=.84 for v in pairs)
        confidence=round(100*sum(pairs)/len(pairs)*min(1,len(pairs)/24))
        results.append((confidence,high,len(pairs),off//60))
    return max(results,default=(0,0,0,0))
def run(args):
    now=datetime.now(timezone.utc).timestamp();timestamp=datetime.fromtimestamp(now,timezone.utc).isoformat()
    rows=sheets_rows()
    feeds={};names={};health=[]
    for provider,url in [("PUBLISHED",args.published),("CA2",args.ca2),("EPG6",args.epg6),("TELUS",args.telus)]:
        if not url:
            health.append([timestamp,provider,"NOT CONFIGURED",0,0,"","","No source URL"])
            continue
        try:
            data,n=programs(url);feeds[provider]=data;names[provider]=n
            starts=[x[0] for v in data.values() for x in v];ends=[x[1] for v in data.values() for x in v]
            health.append([timestamp,provider,"OK",len(data),len(starts),datetime.fromtimestamp(min(starts),timezone.utc).isoformat() if starts else "",datetime.fromtimestamp(max(ends),timezone.utc).isoformat() if ends else "",""])
        except Exception as e:
            health.append([timestamp,provider,"ERROR",0,0,"","",str(e)[:250]])
    if "PUBLISHED" not in feeds:raise RuntimeError("Published guide unavailable: audit not published")
    coverage_rows=[];candidates=[]
    for row in rows:
        pid=row.get("Original tvg-id","").strip();label=row.get("Original IPTV name","")
        pos=row.get("Playlist position","");provider=row.get("Selected provider","");source=row.get("Selected source ID","")
        if not pid: status="UNMAPPED";vals=[]
        else:vals=feeds["PUBLISHED"].get(pid,[]);status="HEALTHY"
        current=best_titles(vals,now)
        c24=coverage(vals,now,now+86400);c72=coverage(vals,now,now+3*86400)
        if pid and not vals:status="MISSING"
        elif pid and not current:status="CURRENT GAP"
        elif pid and c24<90:status="PARTIAL"
        last=max((v[1] for v in vals),default=0)
        coverage_rows.append([timestamp,pos,label,pid,provider,source,status,current,c24,c72,sum(v[0]>now for v in vals),datetime.fromtimestamp(last,timezone.utc).isoformat() if last else "",""])
        # Rank candidates by schedule similarity; name similarity is only a preliminary filter.
        channel_norm=norm(label.replace("CA|",""))
        options=[]
        for other in ("CA2","EPG6","TELUS"):
            if other not in feeds:continue
            for sid,v in feeds[other].items():
                n=norm(names[other].get(sid,sid))
                similarity=max(SequenceMatcher(None,channel_norm,n).ratio(),SequenceMatcher(None,norm(pid),norm(sid)).ratio()) if channel_norm else 0
                if similarity<.73:continue
                if len(vals)>=10:score,matched,compared,shift=match_score(vals,v,now)
                else:score,matched,compared,shift=(0,0,0,0)
                # Identity-only candidates are intentionally never presented as high-confidence matches.
                confidence=score if compared>=10 else min(49,round(similarity*45))
                options.append((confidence,matched,compared,shift,other,sid,similarity))
        for score,matched,compared,shift,other,sid,sim in sorted(options,reverse=True)[:3]:
            candidates.append([timestamp,pos,label,provider,source,other,sid,score,matched,compared,shift,f"Name similarity {sim:.2f}; schedule comparisons {compared}"])
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    for tab,data in [("COVERAGE MONITOR",coverage_rows),("MAPPING CANDIDATES",candidates),("SOURCE HEALTH",health)]:
        with (output/(tab.lower().replace(" ","_")+".csv")).open("w",newline="",encoding="utf-8") as f:
            writer=csv.writer(f);writer.writerow(HEADERS[tab]);writer.writerows(data)
        if args.publish:publish(tab,data)
    print(json.dumps({"channels":len(coverage_rows),"candidates":len(candidates),"source_health":health},indent=2))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--published",required=True);p.add_argument("--ca2",default=CA2);p.add_argument("--epg6");p.add_argument("--telus");p.add_argument("--output",default="audit-results");p.add_argument("--publish",action="store_true")
    run(p.parse_args())
