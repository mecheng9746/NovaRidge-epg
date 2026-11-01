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


def approved_candidates(session, target_position=None, target_source=None):
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
        decision = get_cell(row, 12).casefold()
        required_decision = "queue pr" if os.getenv("AUTO_STAGE3") == "true" else "approved"
        if decision != required_decision:
            continue
        if target_position and (get_cell(row, 1) != target_position or get_cell(row, 6) != target_source):
            continue
        if "STALE" in get_cell(row, 11).upper():
            if target_position: raise ValueError(f"Approved candidate row {index} is stale")
            continue
        pos, provider, source = get_cell(row, 1), get_cell(row, 5), get_cell(row, 6)
        if provider not in ALLOWED:
            if target_position: raise ValueError(f"Approved row {index}: provider unsupported")
            continue
        m = records.get(pos)
        if not m:
            if target_position: raise ValueError(f"Approved row {index}: playlist position missing from master")
            continue
        pid = get_cell(m, headers.index("Original tvg-id"))
        if not pid:
            if target_position: raise ValueError(f"Approved row {index}: no IPTV tvg-id")
            continue
        if get_cell(m, headers.index("Identity decision")) != "Identity approved":
            if target_position: raise ValueError(f"Approved row {index}: identity unapproved")
            continue
        confidence = float(get_cell(row, 7) or 0)
        matched = int(float(get_cell(row, 8) or 0))
        compared = int(float(get_cell(row, 9) or 0))
        if confidence < 90 or compared < 20 or matched / max(compared, 1) < .8:
            if target_position: raise ValueError(f"Approved row {index}: insufficient schedule evidence")
            continue
        approved.append(dict(position=pos, pid=pid, provider=provider, source=source,
                             channel=get_cell(row, 2), score=confidence,
                             matched=matched, compared=compared, sheet_row=index))
    if target_position and len({r["pid"] for r in approved}) != len(approved):
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
    # An interrupted run may have committed a branch before PR creation.
    # Resume only if its content matches exactly the candidate we intended.
    existing = github("GET", f"/repos/{REPO}/pulls?state=all&head={urllib.parse.quote(REPO.split('/')[0] + ':' + branch)}&per_page=100")
    if existing:
        print(f"Proposal already has PR #{existing[0]['number']}: {branch}")
        return False
    path = ALLOWED[row["provider"]]
    main = github("GET", f"/repos/{REPO}/contents/{path}?ref=main")
    main_csv = base64.b64decode(main["content"]).decode("utf-8")
    expected = prepare_change(row, main_csv)
    if expected == main_csv:
        print(f"Already mapped on main: {row['pid']}")
        return False
    try:
        github("POST", f"/repos/{REPO}/git/refs",
               {"ref": "refs/heads/" + branch,
                "sha": github("GET", f"/repos/{REPO}/git/ref/heads/main")["object"]["sha"]})
        existing_branch = False
    except RuntimeError as exc:
        if "HTTP 422" not in str(exc):
            raise
        existing_branch = True
    file = github("GET", f"/repos/{REPO}/contents/{path}?ref={urllib.parse.quote(branch)}")
    current = base64.b64decode(file["content"]).decode("utf-8")
    if existing_branch:
        if current != expected:
            raise ValueError(f"Existing proposal branch {branch} differs from intended mapping; manual review required")
        print(f"Recovering interrupted proposal {branch}")
    else:
        github("PUT", f"/repos/{REPO}/contents/{path}", {
            "message": f"Propose {row['provider']} mapping for {row['pid']}",
            "branch": branch, "sha": file["sha"],
            "content": base64.b64encode(expected.encode()).decode()})
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
    return True


def main():
    if os.getenv("GITHUB_EVENT_NAME") not in ("workflow_dispatch", "schedule"):
        raise ValueError("Stage 3 PR proposals are manual dispatch only")
    automatic = os.getenv("AUTO_STAGE3") == "true"
    position = os.getenv("TARGET_PLAYLIST_POSITION", "").strip()
    source = os.getenv("TARGET_SOURCE_ID", "").strip()
    if not automatic and (not position or not source):
        raise ValueError("Provide workflow inputs")
    rows = approved_candidates(sheets_session(), None if automatic else position, None if automatic else source)
    if not rows:
        print("No eligible approved candidates")
        return
    if automatic:
        grouped = {}
        for item in rows: grouped.setdefault(item["pid"], []).append(item)
        eligible = [items[0] for items in grouped.values() if len(items)==1]
        print(f"Queued reviews: {len(grouped)} channels, {len(eligible)} unambiguous; maximum 3 draft PRs per run")
        rows = eligible
    elif len(rows) != 1:
        raise ValueError("Multiple approvals for targeted channel")
    created = 0
    for row in rows:
        if automatic and created >= 3: break
        if create_proposal(row): created += 1


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Stage 3 rejected:", error, file=sys.stderr)
        sys.exit(1)
