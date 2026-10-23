#!/usr/bin/env python3
"""Refresh NovaRidge XMLTV from the curated public EPG, preserving reviewed provider-ID aliases."""
import argparse
import csv
import gzip
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lxml import etree

SOURCE_URL = 'https://raw.githubusercontent.com/ferteque/Curated-M3U-Repository/main/epg6.xml.gz'
NS = {'xml': 'http://www.w3.org/XML/1998/namespace'}

def fetch(url, dest):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'NovaRidge-EPG-Refresh/1.0'})
            with urllib.request.urlopen(req, timeout=120) as response, open(dest, 'wb') as out:
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk: break
                    total += len(chunk)
                    if total > 180 * 1024 * 1024:
                        raise RuntimeError('Source archive exceeded 180MB safety limit')
                    out.write(chunk)
            if total < 100_000: raise RuntimeError(f'Source archive unusually small: {total}')
            return
        except Exception as exc:
            if attempt == 2: raise RuntimeError(f'Could not download EPG after 3 tries: {exc}') from exc
            time.sleep(2 ** attempt)

def iter_elements(archive, tags):
    with gzip.open(archive, 'rb') as stream:
        for _, element in etree.iterparse(stream, events=('end',), tag=tags, huge_tree=True, resolve_entities=False, no_network=True):
            yield element
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]

def dt(xmltv_date):
    if not xmltv_date: return None
    try:
        return datetime.strptime(xmltv_date.strip(), '%Y%m%d%H%M%S %z').astimezone(timezone.utc)
    except ValueError:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-file', help='Optional local .xml.gz for offline testing')
    parser.add_argument('--output', default='_site/guide.xml.gz')
    parser.add_argument('--mapping', default='data/provider_mappings.csv')
    args = parser.parse_args()

    mapping = defaultdict(set)
    with open(args.mapping, newline='', encoding='utf-8') as file:
        for row in csv.DictReader(file):
            provider = row['provider_epg_id'].strip()
            source = row['source_epg_id'].strip()
            if provider and source: mapping[provider].add(source)
    conflicts = [key for key, ids in mapping.items() if len(ids) != 1]
    if conflicts: raise RuntimeError(f'Ambiguous provider mapping IDs: {conflicts[:10]}')
    mapping = {k: next(iter(v)) for k, v in mapping.items()}

    with tempfile.TemporaryDirectory() as temp:
        archive = args.source_file or str(Path(temp) / 'source.xml.gz')
        if not args.source_file: fetch(SOURCE_URL, archive)

        # First pass reads channel metadata. Streaming avoids loading a multi-GB XML into RAM.
        source_channels = {}
        for el in iter_elements(archive, 'channel'):
            cid = el.get('id')
            if cid: source_channels[cid] = etree.fromstring(etree.tostring(el))

        selected = set(mapping.values()) & source_channels.keys()
        if len(selected) < 150:
            raise RuntimeError(f'Only {len(selected)} mapped source channels found; refusing to replace published guide')
        # Preserve official source IDs and create aliases for provider IDs.
        aliases = defaultdict(set)
        for provider, source in mapping.items():
            if source in selected and provider != source and provider not in source_channels:
                aliases[source].add(provider)

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(temp) / 'guide.xml.gz'
        count = 0
        active_sources = set()
        earliest = latest = None
        with gzip.open(staging, 'wb', compresslevel=6) as zipped:
            with etree.xmlfile(zipped, encoding='utf-8') as writer:
                writer.write_declaration()
                with writer.element('tv', attrib={'generator-info-name':'NovaRidge Automated EPG', 'generator-info-url':'https://github.com/mecheng9746/NovaRidge-epg'}):
                    for source in sorted(selected):
                        writer.write(source_channels[source])
                        for alias in sorted(aliases[source]):
                            clone = etree.fromstring(etree.tostring(source_channels[source]))
                            clone.set('id', alias)
                            writer.write(clone)
                    # Second pass: stream programme elements directly to gzip output.
                    for el in iter_elements(archive, 'programme'):
                        source = el.get('channel')
                        if source not in selected: continue
                        starts = dt(el.get('start'))
                        stops = dt(el.get('stop'))
                        if starts and (earliest is None or starts < earliest): earliest = starts
                        if stops and (latest is None or stops > latest): latest = stops
                        writer.write(el)
                        count += 1
                        active_sources.add(source)
                        for alias in aliases[source]:
                            clone = etree.fromstring(etree.tostring(el))
                            clone.set('channel', alias)
                            writer.write(clone)
                            count += 1
        now = datetime.now(timezone.utc)
        if len(active_sources) < 100 or count < 5_000:
            raise RuntimeError(f'EPG coverage collapsed: {len(active_sources)} source stations, {count} listings')
        if latest is None or latest < now + timedelta(hours=12):
            raise RuntimeError(f'Source guide is stale: last listing ends {latest}; not replacing published guide')
        if earliest is None or earliest > now + timedelta(days=2):
            raise RuntimeError(f'Source guide starts too far in future: {earliest}')
        shutil.copyfile(staging, output)
        print(f'Success: {len(selected)} source channels, {sum(map(len,aliases.values()))} provider aliases, '
              f'{count} programmes, coverage {earliest} to {latest}, file {output.stat().st_size:,} bytes')

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)
