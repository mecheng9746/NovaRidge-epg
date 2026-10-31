#!/usr/bin/env python3
"""Fail closed on stale or broken EPG output; publish machine-readable diagnostics."""
import gzip
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from lxml import etree

def xmltv_dt(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except ValueError:
        return None

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_epg_health.py _site/guide.xml.gz")
    path = Path(sys.argv[1])
    if not path.exists() or path.stat().st_size < 100_000:
        raise RuntimeError("Guide missing or unexpectedly small")
    now = datetime.now(timezone.utc)
    channel_ids = set()
    counts = Counter()
    future_counts = Counter()
    latest_end = {}
    with gzip.open(path, "rb") as stream:
        for _, node in etree.iterparse(stream, events=("end",), tag=("channel", "programme"), no_network=True, resolve_entities=False, huge_tree=True):
            cid = node.get("id") if node.tag == "channel" else node.get("channel")
            if node.tag == "channel":
                if cid in channel_ids:
                    raise RuntimeError("Duplicate XMLTV channel ID: " + str(cid))
                channel_ids.add(cid)
            elif cid:
                counts[cid] += 1
                start = xmltv_dt(node.get("start"))
                stop = xmltv_dt(node.get("stop"))
                if start and now <= start < now + timedelta(days=7):
                    future_counts[cid] += 1
                if stop and (cid not in latest_end or stop > latest_end[cid]):
                    latest_end[cid] = stop
            node.clear()
            while node.getprevious() is not None:
                del node.getparent()[0]
    errors = []
    if len(channel_ids) < 300:
        errors.append("Too few channel entries: " + str(len(channel_ids)))
    if sum(counts.values()) < 5000:
        errors.append("Too few programme entries: " + str(sum(counts.values())))
    orphan = sorted(set(counts) - channel_ids)
    if orphan:
        errors.append("Programme IDs absent from channel listing: " + repr(orphan[:10]))
    disney = "DisneyChannel.ca"
    if disney not in channel_ids or future_counts[disney] < 3:
        errors.append("Missing upcoming Disney Channel Canada CA2 listings")
    if latest_end.get(disney, now) < now + timedelta(hours=12):
        errors.append("Disney Channel guide ends within 12 hours")
    if sum(future_counts.values()) < 500:
        errors.append("Too few upcoming listings overall")
    report = {
        "generated_utc": now.isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "compressed_bytes": path.stat().st_size,
        "channel_count": len(channel_ids),
        "programme_count": sum(counts.values()),
        "upcoming_programme_count": sum(future_counts.values()),
        "disney_channel_id": disney,
        "disney_programmes": counts[disney],
        "disney_upcoming_programmes": future_counts[disney],
        "disney_last_programme_end_utc": latest_end.get(disney).isoformat() if disney in latest_end else None,
        "errors": errors,
    }
    dest = path.parent / "health.json"
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise RuntimeError("; ".join(errors))

if __name__ == "__main__":
    main()
