# Stage 2 — CA2 intake and cross-source normalization

Adds CA2 acquisition and a shared source-independent XMLTV-to-JSONL
normalizer for `ca2`, `telus` and `epg6`. The normalizer preserves provider
channel IDs and assigns namespaced keys (`source:channel_id`) without assuming
channel equivalence. It extracts UTC programme start and end, titles, episode
titles, and channel names for the next matching stage.

## GitHub pilot
Open Actions > CA2 EPG Stage 2 Pilot > Run workflow. The PR also triggers
a test. A successful run stores `ca2.xml.gz`, `ca2-summary.json`, and a
1000-row normalized JSONL sample as an artifact, **not** GitHub Pages.

The production EPG6 pipeline, provider mappings, and guide URL remain unchanged.

## Limitations
CA2 may have a different set of channels from EPG6 or TELUS; no identities
are merged and no mapping is auto-confirmed. The shared JSONL representation
is for programme comparisons, not production publishing. The collector
requires successful source access and schedule freshness checks.
