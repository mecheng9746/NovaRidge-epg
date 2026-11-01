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

## Publishing failure diagnostics and recovery

The audit logs the service-account email, project ID, workbook ID and requested
Sheets scope, never the key JSON or access token. Compare that email with the
workbook's Share dialog: it must be **Editor**, not Viewer. GitHub repository
permissions and the connected Drive user's access do not grant Sheets write access
to the Actions service account. The existing script already requests
`https://www.googleapis.com/auth/spreadsheets`; no Drive scope is needed.

For HTTP 403, known Google reason codes distinguish a disabled Sheets API
(`SERVICE_DISABLED`), insufficient OAuth scope
(`ACCESS_TOKEN_SCOPE_INSUFFICIENT`), and workbook/protected-range access.
Enable `sheets.googleapis.com` in the credential's project if disabled. If reads
succeed but writes fail, check Editor sharing for the exact logged email and
protected ranges on the audit tabs first. Never paste a private key into logs,
issues or PRs.

All three CSV snapshots are saved before any publishing request. Publishing uses
one atomic `spreadsheets.batchUpdate`: it replaces only values below the headers
in COVERAGE MONITOR A:M, MAPPING CANDIDATES A:L and SOURCE HEALTH A:H, including
stale trailing rows. It grows report tabs when needed. A rejected batch leaves
all previous reports intact; a network timeout has an unknown outcome, so inspect
the report timestamps before retrying. No automatic retry is performed.

Candidate M:N cells are never written. If an annotated row's candidate identity
would change or disappear, publishing stops and retains the CSVs for review.
Archive or resolve those annotations before refreshing. Avoid manual edits during
publication: Sheets does not provide a conditional transaction spanning the
preflight read and write.

Run `python -m unittest discover -s tests -v` for offline regression tests.
The PR test workflow uses no secrets and does not write to Google Sheets.
A live service-account write is only confirmed by a successful audit run.
