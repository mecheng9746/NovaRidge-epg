#!/usr/bin/env python3
"""Download CA2 XMLTV and emit an isolated validated, compressed source guide."""
import argparse
import gzip
import json
import logging
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from lxml import etree

CA2_URL = "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz"
LOG = logging.getLogger("ca2")

def download(url, target, retries=3, max_bytes=250_000_000):
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "NovaRidge-EPG/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as dest:
                size = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("Compressed CA2 download exceeds safety limit")
                    dest.write(chunk)
            if size < 1000:
                raise ValueError("Compressed CA2 download too small")
            return size
        except (OSError, ValueError) as error:
            if attempt + 1 == retries:
                raise RuntimeError(f"Failed CA2 download: {error}") from error
            time.sleep(2 ** attempt)

def parse_xmltv_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except ValueError:
        return None

def audit_xmltv(archive):
    channels = set()
    active = set()
    programmes = 0
    earliest = latest = None
    with gzip.open(archive, "rb") as source:
        for _, element in etree.iterparse(source, events=("end",), tag=("channel", "programme"), resolve_entities=False, no_network=True, huge_tree=False):
            if element.tag == "channel":
                cid = element.get("id")
                if cid:
                    channels.add(cid)
            else:
                cid = element.get("channel")
                start = parse_xmltv_date(element.get("start"))
                stop = parse_xmltv_date(element.get("stop"))
                if cid and start and stop and stop > start and element.find("title") is not None:
                    active.add(cid)
                    programmes += 1
                    earliest = min(earliest, start) if earliest else start
                    latest = max(latest, stop) if latest else stop
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]
    return {"channel_count": len(channels), "active_channel_count": len(active),
            "programme_count": programmes, "first_airing_utc": earliest.isoformat() if earliest else None,
            "last_airing_end_utc": latest.isoformat() if latest else None,
            "missing_channel_definitions": len(active - channels)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", type=Path, help="Offline testing archive")
    parser.add_argument("--output", type=Path, default=Path("_sources/ca2.xml.gz"))
    parser.add_argument("--summary", type=Path, default=Path("_sources/ca2-summary.json"))
    parser.add_argument("--allow-stale", action="store_true", help="Only for offline tests")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with tempfile.TemporaryDirectory() as temporary:
        archive = args.source_file or Path(temporary) / "ca2.xml.gz"
        download_size = archive.stat().st_size if args.source_file else download(CA2_URL, archive)
        result = audit_xmltv(archive)
        if result["channel_count"] < 50 or result["programme_count"] < 1000:
            raise RuntimeError(f"CA2 coverage too small: {result}")
        if result["missing_channel_definitions"]:
            raise RuntimeError(f"CA2 references {result['missing_channel_definitions']} undefined channels")
        if not args.allow_stale:
            last = datetime.fromisoformat(result["last_airing_end_utc"])
            if last < datetime.now(timezone.utc) + timedelta(hours=12):
                raise RuntimeError(f"CA2 guide stale: {last}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, args.output)
        result.update({"source": "CA2", "archive_bytes": download_size, "output": str(args.output),
                       "note": "Stage 2 pilot, separate from production guide."})
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        LOG.info("SUCCESS %s", json.dumps(result))

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        LOG.error("%s", error)
        sys.exit(1)
