# Stage 3: reviewed EPG mapping proposals

Stage 3 is **manual-only**. It never merges, deploys or edits CANADIAN MASTER.

## Reviewer workflow

1. Open the MAPPING CANDIDATES tab in the canonical workbook.
2. Independently validate actual broadcast identity and programme timing. A high score measures cross-guide agreement, not proof of IPTV programming.
3. Set **Review decision** (column M) to Approved, Rejected or Investigate. Only exact Approved decisions are processed.
4. Manually dispatch Actions -> **Propose approved EPG mappings (Stage 3)**. The job reads the sheet and creates up to 5 draft pull requests. It does not automatically merge them.
5. Inspect each PR, reconcile the corresponding CANADIAN MASTER provider/source decision, validate the actual stream and merge only when satisfied.

## Gating

- Source provider must be CA2 or EPG6; TELUS proposals are intentionally blocked until a safe TELUS-specific change workflow is available.
- The master must contain an original IPTV tvg-id and **Identity approved**.
- Candidate must have at least 90 score, 20 overlapping programme slots, and 80% matched slots.
- Candidate marked STALE or ambiguous approval is rejected.
- Existing proposal branches are never silently rewritten.
- At most five approved candidates per manual run.

## Critical production distinction

A PR edits a versioned CSV fallback, not the live CANADIAN MASTER Google Sheet. The current production CA2 overlay prefers approved selections in CANADIAN MASTER whenever Google credentials are configured. Consequently **merging a proposal PR alone is not guaranteed to activate a CA2 mapping**. The canonical master must be separately reviewed and updated before deployment; never assume the CSV is authoritative in that configuration.

GitHub repo Actions setting *Allow GitHub Actions to create and approve pull requests* must be enabled for the workflow's GITHUB_TOKEN to create draft PRs. The workflow has contents:write and pull-requests:write, but organization policy can still block that action.

No scheduled trigger exists for Stage 3; merely setting Approved in a sheet never starts a workflow.
