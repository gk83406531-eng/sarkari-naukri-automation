# Deploying Sarkari Naukri

`index.html` fetches `data.json` from the same folder at runtime — the
design, layout, categories, search, pagination and detail pages are
unchanged from earlier versions. What's new is everything under
`automation/` and `.github/workflows/`, which can now auto-publish a
fully-validated listing with no manual approval step (see
AUTOMATION-GUIDE.md for the full explanation and its honest limits).

## Files in this package

| File / folder | Required? | Purpose |
|---|---|---|
| `index.html` | **Yes** | Site design and code. |
| `data.json` | **Yes** | Live listings. Starts empty — filled automatically over time, or by hand. |
| `needs_review.json` | **Yes** | Items the automation couldn't confidently auto-publish. Starts as `[]`. Safe to ignore indefinitely. |
| `robots.txt` / `sitemap.xml` | **Yes** | SEO. |
| `_redirects` | Netlify / Cloudflare Pages | Clean-URL routing. |
| `vercel.json` | Vercel only | Same job, Vercel's format. |
| `404.html` | GitHub Pages only | SPA fallback for clean URLs. |
| `automation/sources.json` | **Yes** | Every source's config: type, official domains, fixed org/category, enabled flag. |
| `automation/run_pipeline.py` | **Yes** | Detects, extracts, validates, auto-publishes or defers to review. |
| `automation/extract.py` | **Yes** | Label-anchored field extraction used by the pipeline. |
| `automation/lib_common.py` | **Yes** | Shared validation/dedupe/domain-check logic. |
| `automation/notify.py` | **Yes** | Opens a GitHub Issue only when something needs attention. |
| `automation/republish_reviewed.py` | **Yes** | Publishes items you've manually completed and approved. |
| `automation/requirements.txt` | **Yes** | Python dependencies (installed automatically by the workflow). |
| `automation/audit_log.jsonl` | **Yes** | Append-only record of every detection and its outcome. Starts empty. |
| `automation/state/` | **Yes** | Dedupe registry and per-source page snapshots. Starts empty. |
| `.github/workflows/automation.yml` | **Yes** | The scheduled job (every 6 hours + manual trigger). |
| `.github/workflows/review-followup.yml` | **Yes** | Publishes manually-approved review items. |
| `AUTOMATION-GUIDE.md` | Reference | Full setup + how the auto-publish decision works. |

## Where to upload (Netlify)

For automation, Netlify needs to watch your **GitHub repository**
(Site settings → Build & deploy → Link repository) rather than receiving
drag-and-drop uploads — see AUTOMATION-GUIDE.md Part A for the exact
steps. After that one-time link, every automated commit deploys itself.

If you don't want the automation at all, you can still drag-and-drop just
`index.html`, `data.json`, `_redirects`, `robots.txt` and `sitemap.xml`
into Netlify as before, and skip everything under `automation/` and
`.github/`.

## Before you go live with real data

1. Once `data.json` has real listings, set `"isLive": true` in its `meta`
   block (flips the page's `<meta name="robots">` to "index, follow").
2. Replace `"your-domain-here.example"` in `robots.txt`, `sitemap.xml`,
   and `data.json`'s `meta.baseUrl` / `meta.contactEmail` with your real
   domain and inbox.
3. Swap `robots.txt` for the "allow, indexed" version described in the
   comments at the top of that file.

## Adding a listing by hand

Same as always: open `data.json`, copy an existing object in the array
you want (`jobs`, `results`, `admitCards`, `answerKeys`, `syllabus`,
`admissions`), edit the fields, commit. This works whether or not you use
the automation.
