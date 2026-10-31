#!/usr/bin/env python3
"""Collect seven days of TELUS TV+ programme listings, separately from production EPG."""
import argparse
import gzip
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = "https://telus.prod.g.telustvplus.com/TELUS/T7.3/R/ENG/CHROME_FIREFOX_HTML5/PIK/TRAY/EPG"
THREE_HOURS_MS = 3 * 60 * 60 * 1000
LOG = logging.getLogger("telus")


def request_window(start_ms, end_ms, region, timeout=45, retries=3):
    query = urllib.parse.urlencode({
        "filter_startTime": start_ms,
        "filter_endTime": end_ms,
        "filter_regionId": region,
    })
    url = BASE + "?" + query
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "NovaRidge-EPG/1.0",
            })
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read(30_000_001)
            if len(raw) > 30_000_000:
                raise ValueError("TELUS response exceeds 30MB limit")
            obj = json.loads(raw)
            if obj.get("resultCode") != "OK" or not isinstance(obj.get("resultObj", {}).get("containers"), list):
                raise ValueError("Unexpected TELUS API result/schema")
            return obj
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"TELUS request failed for {start_ms}-{end_ms}: {exc}") from exc
            time.sleep(min(2 ** attempt * 2, 20))


def parse_response(payload):
    records = []
    for channel in payload["resultObj"]["containers"]:
        if channel.get("layout") != "CHANNEL_ITEM":
            continue
        cid = channel.get("metadata", {}).get("channelId")
        if cid is None:
            continue
        for item in channel.get("containers", []):
            meta = item.get("metadata", {})
            start, end = meta.get("airingStartTime"), meta.get("airingEndTime")
            if not isinstance(start, int) or not isinstance(end, int) or end <= start:
                continue
            title = meta.get("title")
            if not title or meta.get("contentType") != "PROGRAM":
                continue
            records.append({
                "channel_id": str(cid), "title": title,
                "start_ms": start, "end_ms": end,
                "content_id": str(meta.get("contentId") or ""),
                "program_id": str(meta.get("programId") or ""),
                "description": meta.get("longDescription") or "",
                "episode_title": meta.get("episodeTitle") or "",
                "genres": meta.get("genres") or [],
            })
    return records


def unique_records(records):
    by_airing = {}
    for record in records:
        # Program ID is not unique across airings. Deduplicate on channel/time.
        key = (record["channel_id"], record["start_ms"], record["end_ms"])
        prior = by_airing.get(key)
        if prior is not None and (prior["title"] != record["title"]):
            raise ValueError(f"Conflicting programme entries for channel/time {key}")
        by_airing[key] = record
    return sorted(by_airing.values(), key=lambda r: (r["channel_id"], r["start_ms"]))


def xmltv_timestamp(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def write_xmltv(records, path):
    root = ET.Element("tv", {"generator-info-name": "NovaRidge TELUS Stage 1"})
    for cid in sorted({r["channel_id"] for r in records}):
        ch = ET.SubElement(root, "channel", id=f"telus.{cid}")
        ET.SubElement(ch, "display-name").text = f"TELUS channel {cid}"
    for rec in records:
        prog = ET.SubElement(root, "programme", {
            "channel": f"telus.{rec['channel_id']}",
            "start": xmltv_timestamp(rec["start_ms"]),
            "stop": xmltv_timestamp(rec["end_ms"]),
        })
        ET.SubElement(prog, "title", lang="en").text = rec["title"]
        if rec["description"]:
            ET.SubElement(prog, "desc", lang="en").text = rec["description"]
        if rec["episode_title"]:
            ET.SubElement(prog, "sub-title", lang="en").text = rec["episode_title"]
        for genre in rec["genres"]:
            if isinstance(genre, str):
                ET.SubElement(prog, "category").text = genre
        if rec["program_id"]:
            ET.SubElement(prog, "episode-num", system="telus").text = rec["program_id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=6) as stream:
        ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True)


def collect(start_ms, days, region, sleep_seconds, fetcher=request_window):
    end_ms = start_ms + days * 24 * 3600 * 1000
    all_records = []
    windows = 0
    for current in range(start_ms, end_ms, THREE_HOURS_MS):
        upper = min(current + THREE_HOURS_MS, end_ms)
        response = fetcher(current, upper, region)
        chunk = parse_response(response)
        if not chunk:
            raise RuntimeError(f"Empty programme response at {current}")
        all_records.extend(chunk)
        windows += 1
        LOG.info("Window %s: %d listings, %d cumulative", windows, len(chunk), len(all_records))
        if sleep_seconds and upper < end_ms:
            time.sleep(sleep_seconds)
    return unique_records(all_records), windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--region", type=int, default=25)
    parser.add_argument("--output", type=Path, default=Path("_telus/telus.xml.gz"))
    parser.add_argument("--summary", type=Path, default=Path("_telus/summary.json"))
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--start-ms", type=int, default=None, help="UTC start in Unix milliseconds")
    args = parser.parse_args()
    if not 1 <= args.days <= 7 or not 0 <= args.sleep <= 30:
        parser.error("--days must be 1-7 and --sleep must be 0-30")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Align UTC collection to a three-hour boundary.
    now = datetime.now(timezone.utc)
    aligned = now.replace(hour=(now.hour // 3) * 3, minute=0, second=0, microsecond=0)
    start_ms = args.start_ms if args.start_ms is not None else int(aligned.timestamp() * 1000)
    records, windows = collect(start_ms, args.days, args.region, args.sleep)
    count_channels = len({r["channel_id"] for r in records})
    if count_channels < 50 or len(records) < 300:
        raise RuntimeError(f"Suspiciously small TELUS response: {count_channels} channels / {len(records)} programmes")
    write_xmltv(records, args.output)
    summary = {
        "source": "TELUS", "region": args.region,
        "requested_start_utc": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "requested_days": args.days, "windows_fetched": windows,
        "channel_count": count_channels, "programme_count": len(records),
        "first_airing_utc": datetime.fromtimestamp(min(r["start_ms"] for r in records)/1000, timezone.utc).isoformat(),
        "last_airing_end_utc": datetime.fromtimestamp(max(r["end_ms"] for r in records)/1000, timezone.utc).isoformat(),
        "output": str(args.output),
        "note": "Pilot only. Channels have temporary telus.ID labels. No production merge.",
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    LOG.info("SUCCESS %s", json.dumps(summary))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        LOG.error("Collection failed: %s", exc)
        sys.exit(1)
