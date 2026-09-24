# Automation guide (v2 — auto-publish redesign)

## What changed from the previous version

The previous version queued *every* detected item for your approval. This
version auto-publishes a listing the moment it clears **all** of these
checks, with no human step:

1. It comes from a source you've enabled.
2. Its notification/apply links are on that source's official-domain
   allow-list (`officialDomains` in `sources.json`).
3. Every required field (org, title, category, vacancies, qualification,
   age limit, application start date, application end date, official
   notification URL, official apply URL) was extracted from the fetched
   page/feed with no placeholder and no ambiguity.
4. The dates parse and make sense (end date after start date, end date
   not already in the past).
5. It isn't a duplicate of something already published.

Anything that fails **any** of those checks — a missing field, an
unparseable date, a PDF notification (see below), a domain mismatch, a
duplicate — is written to `needs_review.json` instead. It is **not**
published, and it does **not** require your attention either, unless you
choose to look. Nothing sits blocking a queue waiting on you.

You'll hear from the system (via one GitHub Issue) only when a run
produces a `needs_review` item or a source-level error. A run that
auto-publishes cleanly, or finds nothing new, notifies no one.

## The honest limitation, stated plainly

**Nearly every official Indian government recruitment source publishes its
actual notification as a PDF, not as structured HTML or a feed.** This
system does not attempt to extract fields from PDFs — parsing government
PDF layouts reliably enough to auto-publish without human review is not
something this project can honestly claim to do safely. When a detected
notification is a PDF, it goes straight to `needs_review` with that exact
reason, every time, by design.

This means: **for most of the pre-listed official sources, in practice,
most real detections will land in `needs_review`, not auto-publish** —
not because the automation is broken, but because the source material
itself (a PDF) doesn't support confident, unattended extraction. Where a
source's notices are plain HTML with clearly labelled fields ("Total
Vacancies: …", "Last Date: …", etc.), auto-publish has a real chance of
working — this was verified against a mocked HTML page during development
(see the testing section below); it has not been run against the live
government sites themselves, since every source ships disabled until you
personally verify it.

## Which sources are actually automated, and how

| Source | Type | Can auto-publish? | Why |
|---|---|---|---|
| Any source you add with a genuine, verified official JSON API | `json_api` | **Yes, realistically** | Structured data, no guessing involved. No such source is pre-configured — none was found during research (see AUTOMATION-GUIDE's earlier note on `data.gov.in`). |
| Any source you add with a genuine, verified RSS/Atom feed whose entries include labelled vacancy/date text | `rss` | **Sometimes** | Depends entirely on whether that feed's text is labelled clearly enough for `automation/extract.py` to read. |
| SSC, RRB, IBPS, UPSC, armed forces sites, CTET, state PSCs, Employment News | `manual_page` | **Rarely, in practice** | No feed exists; notifications are almost always PDFs. The link-diff + HTML-detail-page extraction path exists and will auto-publish on the (uncommon) HTML-only notice, but most real notices will land in `needs_review`. |
| `data.gov.in` | `unsuitable_for_live_monitoring` | **No** | Real API, but only periodic aggregate datasets — not a notice feed. Not checked at all. |
| PIB press releases | `needs_verification` | **Not enabled** | No confirmed stable feed URL found. |

**No source ships enabled.** You decide, per source, after opening its URL
yourself and reading `sources.json`'s notes for it, whether you're
comfortable enabling it.

## Part A — One-time setup

### A1–A3: GitHub account, repository, upload
Same as before: create a free GitHub account, create a repository (e.g.
`sarkari-naukri`), upload every file from this ZIP keeping the folder
structure — `automation/`, `.github/workflows/` (including hidden
dotfiles), and the root files.

### A4. Workflow permissions
Repo → **Settings → Actions → General → Workflow permissions** →
select **"Read and write permissions"** → **Save**.
This lets the bot commit `data.json` updates and open Issues.

### A5. Link Netlify to the repository
Netlify → your site → **Site settings → Build & deploy → Link repository**
→ GitHub → select your repo. Build command: blank. Publish directory: `/`.
Every push now auto-deploys — you never drag-and-drop files again.

### A6. (Optional but recommended) Turn on GitHub notifications
So the "something needs attention" Issue actually reaches your phone:
install the **GitHub mobile app**, open your repository, tap the bell icon
→ **Watching**, or in a browser go to your account's
**Settings → Notifications** and make sure Issues are emailed to you.
This is GitHub's own free notification system — no extra service, no
extra account, no webhook to configure.

### A7. Review and enable sources
Open `automation/sources.json`. For each source you want checked:
1. Open its `url` yourself in a browser. Confirm it's the right page.
2. Read its `notes`.
3. If you're comfortable, set `"enabled": true`.
Duplicate the `state-psc-template` entry for your own state's PSC (or any
other official page), filling in its real name, URL and
`officialDomains`.

**That's the entire one-time setup.** The schedule in
`.github/workflows/automation.yml` now runs every 6 hours automatically.

## Part B — What you actually have to do afterwards

**Normal case: nothing.** A fully-extracted, validated listing publishes
itself and Netlify redeploys itself. You don't open the site, the repo, or
anything else for this to keep happening.

**Exception case (you'll get a GitHub Issue for these):**
- A source errored (site down, page structure changed) — usually resolves
  itself next cycle; only act if it repeats for the same source many times.
- One or more items landed in `needs_review.json` — open the file, read
  each item's `reasons`, and either:
  - **Ignore it.** It stays harmlessly unpublished. No deadline, no
    downside — the live site just doesn't show it.
  - **Fix it.** Open the item's `link` (the official page), fill in the
    blank/wrong fields in `"fields"` from what the official page actually
    says, set `"status": "approved"`, commit. The `review-followup.yml`
    workflow publishes it within a couple of minutes.

### Checking right now instead of waiting for the schedule
Repo → **Actions** → **"Automation (check, extract, auto-publish)"** →
**Run workflow**.

## The audit trail

`automation/audit_log.jsonl` — one line per item per run, every run,
whether published, sent to review, or a source error, with a timestamp
and the reason. This is a plain text file: open it in GitHub to read it,
or download the repo and `grep`/search it. It's automatically trimmed to
the most recent ~4000 lines so it doesn't grow the repo forever.

`automation/state/last_run_summary.json` — a one-shot summary of the most
recent run only (published count, needs-review count, source errors) —
this is what `notify.py` reads to decide whether to alert you.

## Testing performed before this package was built

Because this environment has no live internet access, the pipeline was
verified against a mocked source simulating four real scenarios:
1. A fully-labelled HTML notice → **published automatically**, no
   approval step.
2. A PDF notice → **needs_review**, with the exact "PDF, not attempted"
   reason.
3. A notice missing several labelled fields → **needs_review**, listing
   exactly which fields were missing.
4. A notice whose "Apply" link pointed off the source's official domain →
   **needs_review**, with the domain-mismatch reason (this is requirement
   2 — the domain allow-list — firing correctly).

Re-running the pipeline against the same mocked source produced zero new
candidates (the seen-registry dedupe worked). A manually-completed
`needs_review` item was then approved and published via
`republish_reviewed.py`, using the exact same validation rule as the
automatic path. All of this is inspectable in the scripts themselves —
nothing here is claimed without having been run.

**What was not tested:** the real behaviour of any live government
website, because every source ships disabled and none was fetched over
the network during development. You are the one who will find out, for
each source you enable, whether its real HTML matches what
`automation/extract.py` can read — that's exactly why sources start
disabled and why `needs_review.json` exists as a safety net rather than a
silent failure.

## Troubleshooting

- **A source keeps erroring**: open its URL yourself in a browser first —
  if the site itself is down or blocking automated requests generally
  (not specific to this bot), there's nothing to fix on this end; try
  again later or disable that source.
- **Nothing is ever auto-publishing for a source you enabled**: open
  `needs_review.json` and read the `reasons` for its items — most likely
  its notifications are PDFs (see "the honest limitation" above), which
  is expected, not a bug.
- **Netlify isn't redeploying**: recheck step A5 — the site must be linked
  to the GitHub repo, not still on manual/drag-and-drop deploys.
