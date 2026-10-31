#!/usr/bin/env python3
"""Overlay reviewed CA2 listings onto the existing EPG6 guide without changing IPTV IDs."""
import csv
import gzip
import io
import os
import sys
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from lxml import etree

CA2_URL = os.getenv("CA2_EPG_URL") or "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz"
MAPPINGS = Path("data/reviewed_mappings.csv")
SHEET_ID = "1qkI09neYuJHR9iTB9k0LTUA_3RydrASkOc1FerOi8DQ"

def approved_mappings():
    """Prefer private Google Sheets when a shared service-account credential is configured."""
    credentials = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if credentials:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = service_account.Credentials.from_service_account_info(json.loads(credentials), scopes=scope)
        session = AuthorizedSession(creds)
        from urllib.parse import quote
        url = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/" + quote("'CANADIAN MASTER'!A2:L822", safe="")
        response = session.get(url, timeout=45)
        response.raise_for_status()
        rows = response.json().get("values", [])
        selected = {}
        for row in rows:
            row = row + [""] * (12 - len(row))
            if row[7] != "Identity approved" or row[8] not in ("CA2", "EPG6") or not row[3] or not row[9]:
                continue
            key = row[3].strip()
            new = (row[8].strip(), row[9].strip())
            if key in selected and selected[key] != new:
                raise ValueError("Conflicting selected providers for " + key)
            selected[key] = new
        print("Loaded", len(selected), "approved mappings directly from Google Sheets")
        return selected
    with MAPPINGS.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print("Google Sheets credentials unavailable: using checked-in approved-mapping snapshot")
    return {r["provider_epg_id"]: (r["provider"], r["source_epg_id"]) for r in rows}

def iter_elements(path, tag):
    with gzip.open(path, "rb") as stream:
        for _, node in etree.iterparse(stream, events=("end",), tag=tag, no_network=True, resolve_entities=False, huge_tree=True):
            yield node
            node.clear()
            while node.getprevious() is not None:
                del node.getparent()[0]

def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "NovaRidge-EPG/2.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        total = 0
        while True:
            data = r.read(1024 * 1024)
            if not data: break
            total += len(data)
            if total > 100 * 1024 * 1024: raise ValueError("CA2 archive exceeds 100 MB")
            f.write(data)
    if total < 10000: raise ValueError("CA2 download suspiciously small")

def parse_start(s):
    try:
        return datetime.strptime(s.strip(), "%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None

def main():
    if len(sys.argv) != 2: raise SystemExit("Usage: overlay_ca2.py _site/guide.xml.gz")
    output = Path(sys.argv[1])
    reviewed = approved_mappings()
    ca2 = {pid: sid for pid, (provider, sid) in reviewed.items() if provider == "CA2"}
    if not ca2:
        print("No approved CA2 mappings; existing guide unchanged")
        return
    with tempfile.TemporaryDirectory() as temp:
        ca2file = Path(temp) / "ca2.xml.gz"
        staging = Path(temp) / "merged.xml.gz"
        download(CA2_URL, ca2file)
        bysource = {}
        required = set(ca2.values())
        for node in iter_elements(ca2file, "channel"):
            cid = node.get("id")
            if cid in required:
                bysource[cid] = etree.fromstring(etree.tostring(node))
        missing = required - bysource.keys()
        if missing: raise RuntimeError("CA2 channel IDs missing: " + repr(sorted(missing)))
        now = datetime.now(timezone.utc)
        counts = Counter()
        latest = {}
        # Preflight before touching the published guide.
        for node in iter_elements(ca2file, "programme"):
            sid = node.get("channel")
            if sid not in required: continue
            start = parse_start(node.get("start"))
            if start and start >= now - timedelta(hours=6):
                counts[sid] += 1
                latest[sid] = max(latest.get(sid, start), start)
        unhealthy = [sid for sid in required if counts[sid] < 3 or latest.get(sid, now) < now + timedelta(hours=12)]
        if unhealthy: raise RuntimeError("CA2 missing/future coverage insufficient: " + repr(unhealthy))
        with gzip.open(staging, "wb", compresslevel=6) as z:
            with etree.xmlfile(z, encoding="utf-8") as writer:
                writer.write_declaration()
                with writer.element("tv", attrib={"generator-info-name": "NovaRidge Automated EPG"}):
                    replaced = set()
                    for node in iter_elements(output, "channel"):
                        pid = node.get("id")
                        if pid in ca2:
                            clone = etree.fromstring(etree.tostring(bysource[ca2[pid]]))
                            clone.set("id", pid)
                            writer.write(clone)
                            replaced.add(pid)
                        else:
                            writer.write(node)
                    for pid, sid in ca2.items():
                        if pid not in replaced:
                            clone = etree.fromstring(etree.tostring(bysource[sid]))
                            clone.set("id", pid)
                            writer.write(clone)
                    for node in iter_elements(output, "programme"):
                        if node.get("channel") not in ca2:
                            writer.write(node)
                    emitted = Counter()
                    reverse = {}
                    for pid, sid in ca2.items(): reverse.setdefault(sid, []).append(pid)
                    for node in iter_elements(ca2file, "programme"):
                        for pid in reverse.get(node.get("channel"), []):
                            clone = etree.fromstring(etree.tostring(node))
                            clone.set("channel", pid)
                            writer.write(clone)
                            emitted[pid] += 1
        if any(emitted[pid] < 3 for pid in ca2):
            raise RuntimeError("CA2 programme write failed")
        staging.replace(output)
        print("CA2 overlay complete:", dict(emitted))

if __name__ == "__main__":
    main()
