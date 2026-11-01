# Canadian EPG Audit — Stages 1 and 2

This is a separate read-only GitHub Actions workflow. It **does not modify production mappings** or the published guide.

## Setup before first run

1. Add repository Actions variable `PUBLISHED_EPG_URL`: the current public `guide.xml.gz` URL used by TiviMate.
2. Ensure `GOOGLE_SERVICE_ACCOUNT_JSON` is configured, with Sheets API access and **Editor** permission on the workbook (previous Viewer permission is not sufficient for audit writes).
3. Optionally configure `EPG6_SOURCE_URL` with a direct original EPG6 XMLTV feed. Without it, the source health tab reports NOT CONFIGURED. `CA2_EPG_URL` optionally overrides the CA2 default.
4. The workflow collects one day of TELUS programmes separately for audit purposes; TELUS collection failures do not break the production guide, but appear in job logs. The audit does not treat identity-only matches as verified schedule matches.
5. Run `Canadian EPG Audit (Stages 1 and 2)` manually once, then check `COVERAGE MONITOR`, `MAPPING CANDIDATES` and `SOURCE HEALTH`.

Audit results are also uploaded as CSV job artifacts. Scheduled audit times are 00:32, 06:32, 12:32 and 18:32 UTC.

## Matching limitations and safety

- Only rows in `CANADIAN MASTER` are audited.
- Names and IDs only produce low-confidence identity suggestions. High scores require 10 or more overlapping half-hour comparisons.
- A schedule match between feeds does not prove that the IPTV stream plays that programme.
- This stage **only produces recommendations**. No candidate is auto-approved or written to `reviewed_mappings.csv`, `provider_mappings.csv`, or any overlay.
- The two blank rightmost columns of `MAPPING CANDIDATES` are reserved for user decisions and future PR links. Automated runs update A:L only. Note that candidate row order can change; approval must eventually be keyed by immutable candidate identity, not row number, before a proposal-to-PR workflow is implemented.
- GitHub mapping-fix PR automation (creating PRs from explicitly approved suggestions) is **not yet implemented**; it requires an approval key, validation checks, and write-scoped GitHub authentication.
