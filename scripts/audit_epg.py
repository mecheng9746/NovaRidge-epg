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
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
WRITE_WIDTHS = {"COVERAGE MONITOR": 13, "MAPPING CANDIDATES": 12, "SOURCE HEALTH": 8}

class SheetsError(RuntimeError):
    """Actionable error without credentials, response bodies or request headers."""

def sheets_session():
    secret = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not secret:
        raise SheetsError("GOOGLE_SERVICE_ACCOUNT_JSON is missing.")
    try:
        info = json.loads(secret)
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        creds = service_account.Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
    except (ValueError, TypeError, KeyError):
        raise SheetsError("GOOGLE_SERVICE_ACCOUNT_JSON is not a valid service-account key.") from None
    # Identity is safe to log; never log the JSON key or access token.
    print("Sheets identity: " + json.dumps({
        "client_email": info.get("client_email"), "project_id": info.get("project_id"),
        "spreadsheet_id": SHEET_ID, "scope": SHEETS_SCOPE}))
    return AuthorizedSession(creds)

def sheets_request(session, method, path, **kwargs):
    try:
        response = session.request(method, f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}" + path,
                                   timeout=60, **kwargs)
    except Exception:
        raise SheetsError("Sheets transport/authentication failure; check key validity and network. "
                          "A timed-out publish may have committed; inspect the report timestamp before retrying.") from None
    if response.ok:
        return response.json()
    try:
        error = response.json().get("error", {})
        reasons = [item.get("reason", "") for item in error.get("details", [])]
        reasons += [item.get("reason", "") for item in error.get("errors", [])]
    except (ValueError, AttributeError, TypeError):
        reasons = []
    # Only emit known reason codes; raw server messages can contain sensitive data.
    known = {"SERVICE_DISABLED", "accessNotConfigured", "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
             "insufficientPermissions", "PERMISSION_DENIED", "forbidden"}
    reasons = sorted(set(r for r in reasons if isinstance(r, str) and r in known))
    hint = "Check the workbook ID, tab names and grid bounds."
    if "SERVICE_DISABLED" in reasons or "accessNotConfigured" in reasons:
        hint = "Enable sheets.googleapis.com in the logged service-account project."
    elif "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in reasons or "insufficientPermissions" in reasons:
        hint = "Issue credentials with the spreadsheets write scope; readonly is insufficient."
    elif response.status_code == 403:
        hint = ("Share this exact workbook with the logged client_email as Editor (Viewer can read but cannot publish). "
                "Check protected ranges on the three audit tabs and Workspace policy. "
                "The connected Drive user's access does not prove the Actions service account's access.")
    elif response.status_code == 401:
        hint = "Check that the Actions service-account key is current and enabled."
    raise SheetsError(f"Sheets {method} failed: HTTP {response.status_code}; "
                      f"reasons={','.join(reasons) or 'unspecified'}. {hint}")

def sheets_rows(session):
    from urllib.parse import quote
    result = sheets_request(session, "GET", "/values/" + quote("'CANADIAN MASTER'!A1:P822", safe=""))
    rows = result.get("values", [])
    required = {"Original tvg-id", "Original IPTV name", "Playlist position",
                "Selected provider", "Selected source ID"}
    if not rows or not required.issubset(rows[0]):
        raise SheetsError("Canadian master is empty or required headers are missing; refusing to publish.")
    keys = rows[0]
    records = [dict(zip(keys, row + [""] * (len(keys)-len(row)))) for row in rows[1:] if row]
    if not records:
        raise SheetsError("Canadian master has no data; refusing to publish.")
    return records

def publish(session, reports):
    """Replace all automated areas atomically, leaving headers and manual cells intact."""
    from urllib.parse import quote
    if set(reports) != set(WRITE_WIDTHS):
        raise SheetsError("Publishing requires exactly the three allowlisted audit reports.")
    for tab, rows in reports.items():
        if any(len(row) != WRITE_WIDTHS[tab] for row in rows):
            raise SheetsError(f"Invalid row width in {tab}; nothing published.")
    if not reports["COVERAGE MONITOR"] or not reports["SOURCE HEALTH"]:
        raise SheetsError("Refusing to publish empty coverage or source health.")
    metadata = sheets_request(session, "GET", "", params={
        "fields": "sheets(properties(sheetId,title,gridProperties))"})
    sheets = {s["properties"]["title"]: s["properties"] for s in metadata["sheets"]}
    if not set(WRITE_WIDTHS).issubset(sheets):
        raise SheetsError("An audit tab is missing; nothing published.")
    candidate_rows = sheets["MAPPING CANDIDATES"]["gridProperties"]["rowCount"]
    old = sheets_request(session, "GET", "/values/" + quote(
        f"'MAPPING CANDIDATES'!A2:N{candidate_rows}", safe=""),
        params={"valueRenderOption": "FORMULA"}).get("values", [])
    # Carry human decisions by immutable channel/candidate identity, never row number.
    # Keep reviewed candidates absent from this scan as explicit stale rows.
    def candidate_key(row):
        return (str(row[1]).strip(), str(row[2]).strip(),
                str(row[5]).strip(), str(row[6]).strip())
    fresh = reports["MAPPING CANDIDATES"]
    fresh_keys = [candidate_key(row) for row in fresh]
    if len(set(fresh_keys)) != len(fresh_keys):
        raise SheetsError("Duplicate candidate identities; refusing to publish.")
    previous = {}
    for old_row in old:
        if len(old_row) < 13 or not any(old_row[12:14]):
            continue
        key = candidate_key(old_row)
        if key in previous:
            raise SheetsError("Duplicate reviewed candidate identity in existing sheet.")
        previous[key] = old_row
    merged = []
    for row in fresh:
        old_row = previous.pop(candidate_key(row), None)
        merged.append(row + ([old_row[12] if len(old_row)>12 else "",
                              old_row[13] if len(old_row)>13 else ""] if old_row else ["",""]))
    for old_row in previous.values():
        # Removed source or changed candidate: retain the review, but mark stale.
        kept = (old_row[:12] + [""]*12)[:12]
        kept[11] = "STALE: not suggested in latest audit; revalidate before action. " + str(kept[11])
        merged.append(kept + [old_row[12] if len(old_row)>12 else "",
                              old_row[13] if len(old_row)>13 else ""])
    reports["MAPPING CANDIDATES"] = merged
    requests = []
    for tab, rows in reports.items():
        prop = sheets[tab]
        grid = prop["gridProperties"]
        width = len(HEADERS[tab]) if tab == "MAPPING CANDIDATES" else WRITE_WIDTHS[tab]
        if grid["columnCount"] < len(HEADERS[tab]):
            raise SheetsError(f"{tab} has too few columns; nothing published.")
        end = max(grid["rowCount"], len(rows) + 1)
        if end > grid["rowCount"]:
            requests.append({"appendDimension": {"sheetId": prop["sheetId"],
                             "dimension": "ROWS", "length": end-grid["rowCount"]}})
        cells = []
        for row in rows:
            cells.append({"values": [{"userEnteredValue": {
                "numberValue" if isinstance(value, (int, float)) else "stringValue": value
            }} for value in row]})
        requests.append({"updateCells": {
            "range": {"sheetId": prop["sheetId"], "startRowIndex": 1, "endRowIndex": end,
                      "startColumnIndex": 0, "endColumnIndex": width},
            "rows": cells, "fields": "userEnteredValue"}})
    # updateCells clears uncovered values within each bounded range in the same transaction.
    sheets_request(session, "POST", ":batchUpdate", json={"requests": requests})
    print("Published all three audit reports atomically.")

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
    session=sheets_session()
    rows=sheets_rows(session)
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
        if not pid: status="NO IPTV ID";vals=[]
        else:vals=feeds["PUBLISHED"].get(pid,[]);status="HEALTHY"
        current=best_titles(vals,now)
        c24=coverage(vals,now,now+86400);c72=coverage(vals,now,now+3*86400)
        if pid and not vals:status="MAPPING NEEDED" if not source else "MISSING"
        elif pid and not current:status="CURRENT GAP"
        elif pid and c24<90:status="PARTIAL"
        last=max((v[1] for v in vals),default=0)
        note = ("Playlist tvg-id missing; source selection cannot fix the published ID." if not pid else ("No selected source ID in master." if not source else ""))
        coverage_rows.append([timestamp,pos,label,pid,provider,source,status,current,c24,c72,sum(v[0]>now for v in vals),datetime.fromtimestamp(last,timezone.utc).isoformat() if last else "",note])
        # Rank candidates by schedule similarity; name similarity is only a preliminary filter.
        channel_norm=norm(label.replace("CA|",""))
        options=[]
        for other in ("CA2","EPG6","TELUS"):
            if other not in feeds:continue
            for sid,v in feeds[other].items():
                n=norm(names[other].get(sid,sid))
                similarity=max(SequenceMatcher(None,channel_norm,n).ratio(),SequenceMatcher(None,norm(pid),norm(sid)).ratio()) if channel_norm else 0
                if similarity<.73:continue
                if other==provider and sid==source:continue
                if len(vals)>=10:score,matched,compared,shift=match_score(vals,v,now)
                else:score,matched,compared,shift=(0,0,0,0)
                # Identity-only candidates are intentionally never presented as high-confidence matches.
                confidence=score if compared>=10 else min(49,round(similarity*45))
                options.append((confidence,matched,compared,shift,other,sid,similarity))
        for score,matched,compared,shift,other,sid,sim in sorted(options,reverse=True)[:3]:
            candidates.append([timestamp,pos,label,provider,source,other,sid,score,matched,compared,shift,f"Name similarity {sim:.2f}; schedule comparisons {compared}"])
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    reports={"COVERAGE MONITOR":coverage_rows,"MAPPING CANDIDATES":candidates,"SOURCE HEALTH":health}
    for tab,data in reports.items():
        with (output/(tab.lower().replace(" ","_")+".csv")).open("w",newline="",encoding="utf-8") as f:
            writer=csv.writer(f);writer.writerow(HEADERS[tab]);writer.writerows(data)
    if args.publish:publish(session,reports)
    print(json.dumps({"channels":len(coverage_rows),"candidates":len(candidates),"source_health":health},indent=2))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--published",required=True);p.add_argument("--ca2",default=CA2);p.add_argument("--epg6");p.add_argument("--telus");p.add_argument("--output",default="audit-results");p.add_argument("--publish",action="store_true")
    try:
        run(p.parse_args())
    except SheetsError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
