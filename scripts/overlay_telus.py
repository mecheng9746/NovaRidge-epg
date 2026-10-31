#!/usr/bin/env python3
"""Validated TELUS XMLTV overlay. Requires explicit TELUS_XMLTV_URL, never invents schedules."""
import csv
import gzip
import io
import json
import os
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from lxml import etree

SHEET_ID = "1qkI09neYuJHR9iTB9k0LTUA_3RydrASkOc1FerOi8DQ"

def approved_telus():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("TELUS overlay requires live Google Sheets credentials")
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    from urllib.parse import quote
    cred = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    url = ("https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID + "/values/"
           + quote("'CANADIAN MASTER'!A2:L822", safe=""))
    response = AuthorizedSession(cred).get(url, timeout=45)
    response.raise_for_status()
    selected = {}
    for row in response.json().get("values", []):
        row = (row + [""] * 12)[:12]
        if row[7] != "Identity approved" or row[8] != "TELUS" or not row[3] or not row[9]:
            continue
        pid, sid = row[3].strip(), row[9].strip()
        if pid in selected and selected[pid] != sid:
            raise RuntimeError("Conflicting TELUS source ID for " + pid)
        selected[pid] = sid
    if not selected:
        raise RuntimeError("No approved TELUS mappings found in CANADIAN MASTER")
    return selected

def iter_nodes(path, tag):
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rb") as stream:
        for _, node in etree.iterparse(stream, events=("end",), tag=tag, no_network=True,
                                       resolve_entities=False, huge_tree=True):
            yield node
            node.clear()
            while node.getprevious() is not None:
                del node.getparent()[0]

def date(s):
    try:
        return datetime.strptime(s.strip(), "%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: overlay_telus.py _site/guide.xml.gz")
    url = os.getenv("TELUS_XMLTV_URL", "").strip()
    if not url.startswith("https://"):
        raise RuntimeError("TELUS_XMLTV_URL must be a validated HTTPS XMLTV source")
    mappings = approved_telus()
    reverse = defaultdict(list)
    for pid, sid in mappings.items():
        reverse[sid].append(pid)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / ("telus.xml.gz" if url.split("?")[0].endswith(".gz") else "telus.xml")
        req = urllib.request.Request(url, headers={"User-Agent": "NovaRidge-EPG-TELUS/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(source, "wb") as out:
            total = 0
            while chunk := r.read(1024 * 1024):
                total += len(chunk)
                if total > 120 * 1024 * 1024:
                    raise RuntimeError("TELUS XMLTV source exceeds 120 MB")
                out.write(chunk)
        channels = {}
        for node in iter_nodes(source, "channel"):
            sid = node.get("id")
            if sid in reverse:
                channels[sid] = etree.fromstring(etree.tostring(node))
        counts, furthest = Counter(), {}
        now = datetime.now(timezone.utc)
        for node in iter_nodes(source, "programme"):
            sid = node.get("channel")
            if sid not in channels:
                continue
            start = date(node.get("start"))
            stop = date(node.get("stop"))
            if start and stop and start < stop and stop > now and start < now + timedelta(days=7):
                counts[sid] += 1
                furthest[sid] = max(furthest.get(sid, stop), stop)
        valid = {sid for sid in channels if counts[sid] >= 3 and furthest.get(sid, now) > now + timedelta(hours=12)}
        minimum = int(os.getenv("TELUS_MIN_VALID_CHANNELS") or "1")
        if len(valid) < minimum:
            raise RuntimeError(f"TELUS valid channels {len(valid)} below required {minimum}; no deployment")
        replace_ids = {pid for sid in valid for pid in reverse[sid]}
        output = Path(sys.argv[1])
        staged = Path(directory) / "guide.xml.gz"
        with gzip.open(staged, "wb", compresslevel=6) as zipout:
            with etree.xmlfile(zipout, encoding="utf-8") as writer:
                writer.write_declaration()
                with writer.element("tv", attrib={"generator-info-name": "NovaRidge Automated EPG"}):
                    written = set()
                    for node in iter_nodes(output, "channel"):
                        pid = node.get("id")
                        if pid in replace_ids:
                            sid = mappings[pid]
                            replacement = etree.fromstring(etree.tostring(channels[sid]))
                            replacement.set("id", pid)
                            writer.write(replacement)
                            written.add(pid)
                        else:
                            writer.write(node)
                    for pid in sorted(replace_ids - written):
                        copy = etree.fromstring(etree.tostring(channels[mappings[pid]]))
                        copy.set("id", pid)
                        writer.write(copy)
                    for node in iter_nodes(output, "programme"):
                        if node.get("channel") not in replace_ids:
                            writer.write(node)
                    emitted = Counter()
                    for node in iter_nodes(source, "programme"):
                        sid = node.get("channel")
                        if sid not in valid:
                            continue
                        for pid in reverse[sid]:
                            copy = etree.fromstring(etree.tostring(node))
                            copy.set("channel", pid)
                            writer.write(copy)
                            emitted[pid] += 1
        if any(emitted[pid] < 3 for pid in replace_ids):
            raise RuntimeError("TELUS overlay programme write incomplete")
        staged.replace(output)
        print(f"TELUS overlay: {len(mappings)} approved, {len(valid)} healthy sources, "
              f"{len(replace_ids)} IPTV IDs replaced; other channels retain existing guide")
        for sid in sorted(set(mappings.values()) - valid):
            print("TELUS skipped invalid/missing source:", sid)

if __name__ == "__main__":
    main()
