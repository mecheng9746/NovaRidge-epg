#!/usr/bin/env python3
"""Synchronize a merged, reviewed Stage 3 mapping PR into CANADIAN MASTER.

Fail closed on non-Stage3 PRs, stale master selections, or ambiguous changes.
Never edits GitHub mappings, triggers deployments, or changes sheet identity decisions.
"""
import base64
import csv
import io
import json
import os
import sys
import urllib.request
from urllib.parse import quote
from audit_epg import SHEET_ID, sheets_request, sheets_session

REPO = os.environ.get("GITHUB_REPOSITORY", "mecheng9746/NovaRidge-epg")
API = "https://api.github.com"
FILES = {"CA2": "data/reviewed_mappings.csv", "EPG6": "data/provider_mappings.csv"}

def gh(path):
    req = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
        "Accept": "application/vnd.github+json",
        "User-Agent": "NovaRidge-EPG-Sync"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)

def rows_at(path, ref):
    item = gh(f"/repos/{REPO}/contents/{path}?ref={quote(ref, safe='')}")
    return list(csv.DictReader(io.StringIO(base64.b64decode(item["content"]).decode())))

def delta(before, after, provider):
    idcol = "provider_epg_id"
    old = {r[idcol]:r for r in before}
    new = {r[idcol]:r for r in after}
    if set(old)-set(new):
        raise ValueError("Proposal deleted a mapping; synchronization refused")
    added = [r for pid,r in new.items() if old.get(pid)!=r]
    if len(added)!=1:
        raise ValueError("Exactly one changed mapping is required")
    row=added[0]
    if provider=="CA2" and row.get("provider")!="CA2":
        raise ValueError("CA2 provider field mismatch")
    return row

def main():
    event=json.loads(open(os.environ["GITHUB_EVENT_PATH"],encoding="utf-8").read())
    pr=event.get("pull_request",{})
    if event.get("action")!="closed" or not pr.get("merged"):
        print("Not a merged PR; no change")
        return
    # Only the deterministic Stage 3 proposal branch pattern is accepted.
    branch=pr.get("head",{}).get("ref","")
    if not branch.startswith("proposal/epg-") or len(branch)!=27:
        print("Not a Stage 3 mapping proposal")
        return
    if pr.get("base",{}).get("ref")!="main":
        raise ValueError("Unexpected base branch")
    files=gh(f"/repos/{REPO}/pulls/{pr['number']}/files?per_page=100")
    paths=[f["filename"] for f in files]
    if len(paths)!=1 or paths[0] not in FILES.values():
        raise ValueError("Unexpected changed files in Stage 3 PR")
    provider=next(p for p,v in FILES.items() if v==paths[0])
    parent=gh(f"/repos/{REPO}/commits/{pr['merge_commit_sha']}")
    parents=parent.get("parents",[])
    if not parents:raise ValueError("No merge parent for comparison")
    before=rows_at(paths[0],parents[0]["sha"])
    after=rows_at(paths[0],pr["merge_commit_sha"])
    changed=delta(before,after,provider)
    pid=changed["provider_epg_id"]
    source=changed["source_epg_id"]
    if not pid or not source:raise ValueError("Empty mapping identity")
    session=sheets_session()
    master=sheets_request(session,"GET","/values/"+quote("'CANADIAN MASTER'!A1:P822",safe="")).get("values",[])
    head=master[0]
    id_idx=head.index("Original tvg-id"); position_idx=head.index("Playlist position")
    provider_idx=head.index("Selected provider"); source_idx=head.index("Selected source ID")
    identity_idx=head.index("Identity decision")
    matches=[(index,row) for index,row in enumerate(master[1:],2) if len(row)>id_idx and row[id_idx]==pid]
    if len(matches)!=1:raise ValueError("IPTV ID absent or duplicated in master")
    rowno,row=matches[0]
    cell=lambda idx:row[idx].strip() if len(row)>idx else ""
    if cell(identity_idx)!="Identity approved":
        raise ValueError("Master identity is not approved")
    if provider=="CA2" and cell(position_idx)!=changed["playlist_position"]:
        raise ValueError("Playlist position mismatch")
    old_provider=cell(provider_idx);old_source=cell(source_idx)
    if (old_provider,old_source)==(provider,source):
        print("Already synchronized:",pid);return
    # Evidence of accepted proposal must still exist in the sheet.
    candidates=sheets_request(session,"GET","/values/"+quote("'MAPPING CANDIDATES'!A1:N2000",safe="")).get("values",[])
    approved=[r for r in candidates[1:] if len(r)>12 and r[12].strip().lower()=="approved"
              and len(r)>6 and r[1].strip()==cell(position_idx)
              and r[5].strip()==provider and r[6].strip()==source
              and not (len(r)>11 and "STALE" in r[11].upper())]
    if len(approved)!=1:raise ValueError("Exact approved, non-stale candidate not found")
    candidate=approved[0]
    if (candidate[3].strip(),candidate[4].strip())!=(old_provider,old_source):
        raise ValueError("Master selected provider/source changed after proposal; manual reconciliation needed")
    if int(float(candidate[7]))<90 or int(float(candidate[9]))<20:
        raise ValueError("Candidate evidence no longer sufficient")
    # Single update, only selected provider and source cells. Preserve all other content.
    cells=[[provider,source]]
    url="/values/"+quote(f"'CANADIAN MASTER'!I{rowno}:J{rowno}",safe="")
    sheets_request(session,"PUT",url,params={"valueInputOption":"RAW"},json={"values":cells})
    print(f"Synchronized {pid}: {old_provider}/{old_source} -> {provider}/{source} (row {rowno})")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print(f"Stage 3 synchronization refused: {exc}",file=sys.stderr)
        sys.exit(1)
