# Automatic EPG review orchestration

The regular Canadian audit runs at 00:32, 06:32, 12:32 and 18:32 UTC.
At :57 of the same UTC hours the Stage 3 proposal workflow checks MAPPING CANDIDATES.

## Day-to-day operating procedure

Review one unambiguous EPG candidate against actual IPTV programming.
Set column M (Review decision) to **Queue PR** for a candidate you authorize
for a draft proposal. The next scheduled Stage 3 workflow checks these rows,
creates up to three **draft** mapping pull requests, and never merges them.

Historic **Approved** decisions are not automatically queued.
**Rejected** and **Investigate** are never proposed.
The existing manual Stage 3 dispatch still uses **Approved** and explicit
playlist-position/source-ID inputs.

The automatic job enforces the existing evidence and identity gates and skips
channels with more than one eligible queued alternative. It skips stale
candidates and existing proposal branches, preventing duplicate creation.
Review and manually merge each draft PR. The post-merge workflow attempts
a guarded write to CANADIAN MASTER, followed by the next normal production EPG
refresh and the next scheduled coverage audit.

## Limitations and safeguards

- CA2 and EPG6 only. TELUS changes still require an implementation.
- Source agreement does not prove actual stream programming. Never queue a
  candidate without independent stream verification.
- The audit may finish after the proposal schedule on unusually slow days;
  in that case it is picked up on the next six-hour cycle.
- Existing draft proposals are not automatically repaired or re-opened.
- The GitHub repository must permit GitHub Actions to create pull requests.
  Workflow-level permissions alone cannot override the repository setting.
- If a post-merge synchronization detects an external sheet edit or stale
  decision, it stops and reports a conflict rather than overwriting the master.
- Synchronizing the master does not directly deploy the guide; the normal
  six-hour production workflow consumes the updated sheet.
- The audit and publishing workflow remains independent: a failed source
  comparison does not rewrite the existing published guide.

No changes to production mapping CSVs or the live EPG are made by this PR.
