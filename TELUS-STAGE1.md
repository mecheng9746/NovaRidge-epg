# TELUS EPG Stage 1 pilot

This is an isolated GitHub Actions test. It does **not** modify the existing
`Update NovaRidge EPG` workflow, GitHub Pages, or `guide.xml.gz`.

The TELUS TRAY/EPG API supplies JSON programme listings. The collector makes
56 sequential three-hour calls for seven days (region 25), retries transient
errors, validates the schema, deduplicates overlapping records by
(channel, start, end), and exports XMLTV gzip plus a JSON collection summary.

To test locally:
```bash
python -m unittest discover -s tests -v
python scripts/collect_telus.py --days 7 --region 25
```

To test on GitHub: Actions > TELUS EPG Stage 1 Pilot > Run workflow.
Download the `telus-epg-pilot` artifact from the completed run.

**Limitations:** `telus.<channelId>` identifiers and generic display names
are intentionally provisional pending channel catalog join and human mapping
review. Schedule availability, runner network accessibility, response coverage,
and automated usage permissions require verification. This is NOT merged into
the production feed. An empty or failed window aborts the collection.
