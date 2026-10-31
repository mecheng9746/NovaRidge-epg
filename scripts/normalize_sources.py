#!/usr/bin/env python3
"""Source-independent XMLTV normalization for EPG6, CA2, and TELUS pilot feeds.

Preserves original source channel IDs under a namespace; no matching is inferred.
Writes newline-delimited JSON for downstream programme comparisons.
"""
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from lxml import etree

def normalize_timestamp(value):
    from datetime import datetime
    return datetime.strptime(value.strip(), "%Y%m%d%H%M%S %z").astimezone(timezone.utc).isoformat()

def normalize(archive, source, output, max_records=None):
    source = source.lower()
    if source not in ("telus", "ca2", "epg6"):
        raise ValueError("Unknown source")
    output.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    channels = {}
    # Channels may precede all programmes; emit one record per airing.
    with gzip.open(archive, "rb") as stream, open(output, "w", encoding="utf-8") as result:
        for _, el in etree.iterparse(stream, events=("end",), tag=("channel", "programme"), resolve_entities=False, no_network=True):
            if el.tag == "channel":
                cid = el.get("id")
                display = el.find("display-name")
                if cid:
                    channels[cid] = display.text if display is not None else cid
            else:
                cid = el.get("channel")
                title_el = el.find("title")
                if cid and title_el is not None and title_el.text:
                    try:
                        start, stop = normalize_timestamp(el.get("start")), normalize_timestamp(el.get("stop"))
                    except (ValueError, AttributeError, TypeError):
                        continue
                    subtitle = el.find("sub-title")
                    row = {"source": source, "source_channel_id": cid,
                           "channel_key": f"{source}:{cid}", "source_channel_name": channels.get(cid, cid),
                           "start_utc": start, "end_utc": stop, "title": title_el.text,
                           "episode_title": subtitle.text if subtitle is not None else None}
                    result.write(json.dumps(row, ensure_ascii=False) + "\n")
                    records += 1
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
            if max_records and records >= max_records:
                break
    return {"source": source, "channel_count": len(channels), "normalized_programmes": records}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source", required=True, choices=["telus", "ca2", "epg6"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-records", type=int)
    args = parser.parse_args()
    print(json.dumps(normalize(args.input, args.source, args.output, args.max_records)))

if __name__ == "__main__":
    main()
