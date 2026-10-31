#!/usr/bin/env python3
"""Retrieve TELUS LIVECHANNELS catalogs for known regions (pilot only).

The endpoint is tested as a hypothesis; unsuccessful regions are reported, not
silently replaced with a different region's channel metadata.
"""
import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://telus.prod.g.telustvplus.com/TELUS/T7.3/R/ENG/CHROME_FIREFOX_HTML5/PIK/TRAY/LIVECHANNELS"
FIELDS = ["region_id", "channel_id", "channel_name", "call_letters", "external_id"]

def request_catalog(region, timeout=35):
    url = BASE + "?" + urllib.parse.urlencode({"filter_regionId": region})
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "NovaRidge-EPG/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError("Response size exceeds 20MB")
    doc = json.loads(raw)
    if doc.get("resultCode") != "OK":
        raise ValueError("TELUS response not OK")
    return doc

def extract(doc, region):
    obj = doc.get("resultObj") or {}
    containers = obj.get("containers") or []
    if not isinstance(containers, list):
        raise ValueError("Missing channel containers")
    out = []
    seen = set()
    for item in containers:
        meta = item.get("metadata") or {}
        cid = meta.get("channelId")
        if cid is None:
            continue
        cid = str(cid)
        if cid in seen:
            continue
        seen.add(cid)
        out.append({"region_id": region, "channel_id": cid,
                    "channel_name": str(meta.get("channelName") or ""),
                    "call_letters": str(meta.get("callLetter") or ""),
                    "external_id": str(meta.get("externalId") or "")})
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", default="1,7,19,22,25,28")
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--output", type=Path, default=Path("_catalogs/telus-livechannels.csv"))
    parser.add_argument("--summary", type=Path, default=Path("_catalogs/telus-livechannels-summary.json"))
    args = parser.parse_args()
    regions = [int(x) for x in args.regions.split(",")]
    if not regions or len(set(regions)) != len(regions) or len(regions) > 12 or any(x < 1 or x > 200 for x in regions):
        parser.error("Use up to 12 distinct IDs between 1 and 200")
    if args.delay < 1.5:
        parser.error("Minimum 1.5 second spacing")
    rows, report = [], []
    for index, region in enumerate(regions):
        try:
            response = request_catalog(region)
            chunk = extract(response, region)
            if not chunk:
                raise ValueError("No channel entries returned")
            rows.extend(chunk)
            report.append({"region_id": region, "status": "ok", "channels": len(chunk),
                           "named": sum(bool(x["channel_name"]) for x in chunk)})
            print(f"REGION {region}: {len(chunk)} channels, {report[-1]['named']} named")
        except Exception as exc:
            report.append({"region_id": region, "status": "failed", "error": str(exc)[:200]})
            print(f"REGION {region}: failed: {exc}")
        if index != len(regions) - 1:
            time.sleep(args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    args.summary.write_text(json.dumps({"endpoint": BASE, "regions": report,
                     "note": "Region names are NOT inferred from catalog channel identities."}, indent=2) + "\n")
    if not rows:
        raise SystemExit("No catalogs collected: review endpoint URL and API response")

if __name__ == "__main__":
    main()
