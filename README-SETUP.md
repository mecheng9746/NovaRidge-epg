# NovaRidge EPG — daily GitHub Pages updater

Upload the package's three folders/files to the **root** of your existing public `mecheng9746/NovaRidge-epg` repository (preserve the folder structure):

- `.github/workflows/update-epg.yml` (GitHub Actions workflow)
- `scripts/update_epg.py` (streaming XMLTV fetch/mapping/validation)
- `data/provider_mappings.csv` (353 unique provider EPG-ID mappings)
- `index.html` (simple landing page)

**Important:** In Repository → Settings → Pages, change **Source** from **Deploy from a branch** to **GitHub Actions**. The workflow directly deploys Pages so no personal-access token is needed. The existing `guide.xml.gz` in the repository can stay as a historical backup; it is *not* the feed that the Actions-built site will publish.

Go to **Actions → Update NovaRidge EPG → Run workflow**. Watch the run logs and verify the deployment is green. The feed URL remains:

https://mecheng9746.github.io/NovaRidge-epg/guide.xml.gz

Then in TiviMate use **Settings → EPG → Update EPG**.

The workflow runs daily at 10:17 UTC, with manually-triggered updates possible. It reads the publicly accessible EPG6 from the Curated M3U Repository, keeps mapped channel entries and adds the matching provider ID aliases, then publishes a validated `.xml.gz` to GitHub Pages.

If the source disappears, changes format, or is stale, the workflow fails without publishing a broken new guide. The last successfully deployed Pages guide remains available. It **does not** invent schedules for unmapped channels or fix possibly incorrect regional mappings that came from the prior v3 mapping report.

GitHub's scheduled workflows may run later than the scheduled minute. If the upstream source stops updating or the Actions workflow is disabled, TiviMate's guide eventually becomes stale.
