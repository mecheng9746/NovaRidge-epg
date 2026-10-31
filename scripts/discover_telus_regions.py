#!/usr/bin/env python3
"""Discover TELUS EPG region IDs using a small, sequential diagnostic window.

Only reports whether a region returns programme data. It cannot infer the
geographical region name; that requires profile/config evidence.
"""
import argparse
import csv
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from collect_telus import THREE_HOURS_MS, request_window, parse_response

LOG = logging.getLogger("telus-region-scan")


def scan(start_id, end_id, start_ms, delay, fetcher=request_window):
    results = []
    for rid in range(start_id, end_id + 1):
        row = {"region_id": rid, "status": "", "channels": 0,
               "programme_records": 0, "unique_programmes": 0,
               "sample_channel_ids": "", "error": ""}
        try:
            payload = fetcher(start_ms, start_ms + THREE_HOURS_MS, rid)
            items = parse_response(payload)
            channel_ids = sorted({r["channel_id"] for r in items}, key=lambda x: int(x) if x.isdigit() else x)
            row.update(status="has_programming" if items else "empty",
                       channels=len(channel_ids),
                       programme_records=len(items),
                       unique_programmes=len({(r["channel_id"], r["start_ms"], r["end_ms"]) for r in items}),
                       sample_channel_ids=";".join(channel_ids[:12]))
        except Exception as exc:
            row.update(status="error", error=str(exc)[:240])
        LOG.info("Region %d: %s, %d channels, %d programmes", rid, row["status"], row["channels"], row["programme_records"])
        results.append(row)
        if rid < end_id and delay:
            time.sleep(delay)
    return results


def main():
    parser = argparse.ArgumentParser(description="Probe a bounded range of TELUS region IDs")
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--end-id", type=int, default=30)
    parser.add_argument("--delay", type=float, default=3.0, help="Pause between probes in seconds")
    parser.add_argument("--output", type=Path, default=Path("_regions/telus-regions.csv"))
    parser.add_argument("--summary", type=Path, default=Path("_regions/summary.json"))
    parser.add_argument("--start-ms", type=int, help="Explicit UTC epoch milliseconds")
    args = parser.parse_args()
    if not 1 <= args.start_id <= args.end_id <= 200:
        parser.error("IDs must be between 1 and 200")
    if args.end_id - args.start_id + 1 > 30:
        parser.error("Maximum 30 region IDs per run")
    if not 1.5 <= args.delay <= 30:
        parser.error("Delay must be between 1.5 and 30 seconds")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    aligned = now.replace(hour=now.hour // 3 * 3, minute=0, second=0, microsecond=0)
    start_ms = args.start_ms if args.start_ms is not None else int(aligned.timestamp() * 1000)
    results = scan(args.start_id, args.end_id, start_ms, args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    summary = {"utc_window_start": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(),
               "duration_hours": 3, "start_id": args.start_id, "end_id": args.end_id,
               "status_counts": dict(Counter(r["status"] for r in results)),
               "valid_region_ids": [r["region_id"] for r in results if r["status"] == "has_programming"],
               "known_region_names": {"25": "Calgary (confirmed from supplied TELUS profile)"},
               "note": "Valid programming does not establish geographic region name; inspect profiles or regional config."}
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    LOG.info("Found %s", summary["valid_region_ids"])


if __name__ == "__main__":
    main()
