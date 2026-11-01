#!/usr/bin/env python3
"""Stage 3: propose reviewed mapping fixes as unmerged GitHub pull requests.

This job is manual-only. Approval in the sheet is evidence to PROPOSE a change,
not authority to modify production, Google Sheets master, or merge a PR.
"""
import csv
import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from audit_epg import SHEET_ID, sheets_session, sheets_request

REPO = os.getenv("GITHUB_REPOSITORY", "mecheng9746/NovaRidge-epg")
GH_API = "https://api.github.com"
ALLOWED = {"CA2": "data/reviewed_mappings.csv", "EPG6": "data/provider_mappings.csv"}


def github(method, path, payload=None):
    token = os.environ["GITHUB_TOKEN"]
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        GH_API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "NovaRidge-Stage3"})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub {method} {path.split('?')[0]} HTTP {exc.code}") from None


def spreadsheet(session, tab, max_row, end):
    from urllib.parse import quote
    result = sheets_request(session, "GET", "/values/" +
                            quote(f"'{tab}'!A1:{end}{max_row}", safe=""))
    return result.get("values", [])


def get_cell(row, column):
    return str(row[column]).strip() if len(row) > column else ""


def approved_candidates(session, target_position, target_source):
    rows = spreadsheet(session, "MAPPING CANDIDATES", 2000, "N")
    master = spreadsheet(session, "CANADIAN MASTER", 822, "P")
    if not rows or rows[0][:7] != ["Audit UTC", "Playlist position", "IPTV channel",
                                     "Current provider", "Current source ID",
                                     "Suggested provider", "Suggested source ID"]:
        raise ValueError("Unexpected candidate sheet schema")
    headers = master[0]
    required = ["Playlist position", "Original tvg-id", "Identity decision"]
    if not all(x in headers for x in required):
        raise ValueError("Canadian master schema changed")
    records = {get_cell(r, headers.index("Playlist position")): r for r in master[1:]}
    approved = []
    for index, row in enumerate(rows[1:], start=2):
        if get_cell(row, 12).casefold() != "approved":
            continue
        if get_cell(row, 1) != target_position or get_cell(row, 6) != target_source:
            continue
        if "STALE" in get_cell(row, 11).upper():
            raise ValueError(f"Approved candidate row {index} is stale. Re-review required")
        pos, provider, source = get_cell(row, 1), get_cell(row, 5), get_cell(row, 6)
        if provider not in ALLOWED:
            raise ValueError(f"Approved row {index}: provider {provider} requires a dedicated implementation")
        m = records.get(pos)
        if not m:
            raise ValueError(f"Approved row {index}: playlist position missing from master")
        pid = get_cell(m, headers.index("Original tvg-id"))
        if not pid:
            raise ValueError(f"Approved row {index}: no IPTV tvg-id; mapping cannot be applied")
        if get_cell(m, headers.index("Identity decision")) != "Identity approved":
            raise ValueError(f"Approved row {index}: channel identity is not approved")
        confidence = float(get_cell(row, 7) or 0)
        matched = int(float(get_cell(row, 8) or 0))
        compared = int(float(get_cell(row, 9) or 0))
        if confidence < 90 or compared < 20 or matched / max(compared, 1) < .8:
            raise ValueError(f"Approved row {index}: insufficient schedule evidence")
        approved.append(dict(position=pos, pid=pid, provider=provider, source=source,
                             channel=get_cell(row, 2), score=confidence,
                             matched=matched, compared=compared, sheet_row=index))
    if len({r["pid"] for r in approved}) != len(approved):
        raise ValueError("Multiple approved alternatives for the same IPTV ID")
    return approved


def prepare_change(row, csv_text):
    lines = list(csv.DictReader(io.StringIO(csv_text)))
    if row["provider"] == "CA2":
        fields = ["playlist_position", "provider_epg_id", "provider", "source_epg_id"]
        lines = [r for r in lines if r["provider_epg_id"] != row["pid"]]
        lines.append(dict(zip(fields, [row["position"], row["pid"], "CA2", row["source"]])))
        lines.sort(key=lambda r: r["provider_epg_id"])
    else:
        fields = ["provider_epg_id", "source_epg_id"]
        lines = [r for r in lines if r["provider_epg_id"] != row["pid"]]
        lines.append(dict(zip(fields, [row["pid"], row["source"]])))
        lines.sort(key=lambda r: r["provider_epg_id"])
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(lines)
    return stream.getvalue()


def create_proposal(row):
    import base64
    branch = "proposal/epg-" + hashlib.sha256(
        (row["pid"] + "|" + row["provider"] + "|" + row["source"]).encode()
    ).hexdigest()[:14]
    main = github("GET", f"/repos/{REPO}/git/ref/heads/main")
    try:
        github("POST", f"/repos/{REPO}/git/refs",
               {"ref": "refs/heads/" + branch, "sha": main["object"]["sha"]})
    except RuntimeError as exc:
        # Don't silently rewrite an existing proposal branch.
        print(f"Skipped existing/blocked proposal {branch}: {exc}")
        return
    path = ALLOWED[row["provider"]]
    file = github("GET", f"/repos/{REPO}/contents/{path}?ref={urllib.parse.quote(branch)}")
    original = base64.b64decode(file["content"]).decode("utf-8")
    updated = prepare_change(row, original)
    if updated == original:
        print(f"No CSV change for {row['pid']}")
        return
    github("PUT", f"/repos/{REPO}/contents/{path}", {
        "message": f"Propose {row['provider']} mapping for {row['pid']}",
        "branch": branch, "sha": file["sha"],
        "content": base64.b64encode(updated.encode()).decode()})
    body = (f"Google Sheets Stage 3 review row: {row['sheet_row']}\\n\\n"
            f"Channel: {row['channel']}\\nOriginal tvg-id: \\x60{row['pid']}\\x60\\n"
            f"Candidate: {row['provider']} / \\x60{row['source']}\\x60\\n"
            f"Score: {row['score']}%; matched slots: {row['matched']}/{row['compared']}.\\n\\n"
            "**Manual merge required.** This changes a checked-in mapping CSV only. "
            "When GOOGLE_SERVICE_ACCOUNT_JSON is set, approved selections in "
            "CANADIAN MASTER take precedence for CA2. Synchronize the master "
            "after independent stream verification before expecting live changes. "
            "Do not merge without confirming the actual broadcast.")
    pr = github("POST", f"/repos/{REPO}/pulls", {
        "title": f"EPG mapping proposal: {row['channel']} → {row['provider']}",
        "head": branch, "base": "main", "body": body, "draft": True})
    print("Created DRAFT PR:", pr["html_url"])


def main():
    if os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("Stage 3 PR proposals are manual dispatch only")
    position = os.getenv("TARGET_PLAYLIST_POSITION", "").strip()
    source = os.getenv("TARGET_SOURCE_ID", "").strip()
    if not position or not source:
        raise ValueError("Provide TARGET_PLAYLIST_POSITION and TARGET_SOURCE_ID in workflow inputs")
    rows = approved_candidates(sheets_session(), position, source)
    if not rows:
        raise ValueError("No Approved candidate matches that playlist position and source ID")
    if len(rows) != 1:
        raise ValueError("Multiple identical approvals for targeted channel; resolve duplicates")
    for row in rows:
        create_proposal(row)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Stage 3 rejected:", error, file=sys.stderr)
        sys.exit(1)
