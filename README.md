# NovaRidge EPG

GitHub Pages serves `guide.xml.gz` for TiviMate. The existing EPG6 guide remains the base.
The refresh workflow runs every six hours (UTC hours 00, 06, 12, 18, at minute 17).

## Approved CA2 mapping

The new overlay replaces listings for approved CA2 channels while **preserving the original IPTV tvg-id**. For example, playlist position **587** retains `DisneyChannel.ca` but reads programmes from `Disney.Channel.Canada.HD.ca2`.

The workflow builds and validates the legacy EPG6 output first. It then downloads the CA2 feed (default: `https://m3u-edit.com/epg-source.php?file=CA2.xml.gz`), checks the configured CA2 channel IDs and future programme coverage, replaces just those channel listings, and deploys only when the full pipeline succeeds. If CA2 fails, the job fails and does not overwrite GitHub Pages' last successful deployment.

## Keep mapping selections synchronized with the private Google Sheet

The canonical workbook is [IPTV Channel Library & EPG Audit](https://docs.google.com/spreadsheets/d/1qkI09neYuJHR9iTB9k0LTUA_3RydrASkOc1FerOi8DQ/edit). Approved rows in `CANADIAN MASTER` are read with the following conditions:

- `Identity decision` = `Identity approved`
- `Selected provider` = `CA2` or `EPG6`
- `Original tvg-id` and `Selected source ID` are populated

To enable **automatic live Google Sheets reading**, create a Google Cloud service account with Google Sheets API read access; share this workbook with the service account email as **Viewer**; then add the complete service account JSON credential as the GitHub repository Actions secret `GOOGLE_SERVICE_ACCOUNT_JSON`. Do not commit that JSON to GitHub. The workflow uses it to read the private sheet. Without the secret, the checked-in `data/reviewed_mappings.csv` snapshot is used, so later spreadsheet edits **will not automatically sync**.

`CA2_EPG_URL` is an optional GitHub Actions repository variable to override the CA2 XMLTV source.

Important: this initial implementation overlays **CA2** sources only. Entries selected as `EPG6` remain governed by the legacy `data/provider_mappings.csv`; TELUS ingestion has not yet been implemented. An approved mapping is a channel-identity choice, **not** verification that the schedule matches the stream.

## Operation

From the repository's **Actions** tab select **Update NovaRidge EPG** and run it manually, or let the scheduled run execute. Check for success and verify the XMLTV output for `DisneyChannel.ca` in TiviMate. Do not change the existing EPG URL.

If CA2 is down or programme data is too stale, the update fails rather than publish an incomplete guide. Keep the previous working EPG until the issue is corrected.


## TELUS integration (staged; disabled until validated)

The earlier `feature/telus-epg-stage1` pilot established a working TELUS TV+ JSON API collector:
`scripts/collect_telus.py`, using region 25, three-hour windows, and seven-day XMLTV conversion. It writes source IDs like `telus.1`. `scripts/overlay_telus.py` converts approved numeric IDs from `CANADIAN MASTER` to these IDs and preserves each original IPTV `tvg-id`.

The production workflow includes this stage **only when** repository Actions variable `ENABLE_TELUS_EPG` is exactly `true`. Do not enable until an integration test against the current TELUS feed and sufficient approved channels passes. A full seven-day collection makes 56 three-hour-window requests; avoid unnecessarily frequent tests. Set `TELUS_MIN_VALID_CHANNELS` to a conservative positive threshold when validating broad coverage, rather than the default 1. The existing `GOOGLE_SERVICE_ACCOUNT_JSON` secret is required.

Per-channel validation checks upcoming listings and future coverage. Unhealthy TELUS feeds retain the existing EPG6/CA2 listings. A failure to collect the live source or read the mapping sheet stops deployment and preserves the last successful GitHub Pages guide. The opt-in branch is a development build and requires final integration tests, particularly under the full 6-hour production workflow.
