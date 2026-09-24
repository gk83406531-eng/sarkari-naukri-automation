#!/usr/bin/env python3
"""
automation/notify.py
=====================
Called as a workflow step AFTER run_pipeline.py. Reads
automation/state/last_run_summary.json and, only if alertNeeded is true,
opens or updates a single GitHub Issue labelled 'bot-alert' summarising
what needs attention.

A clean run (everything auto-published, or nothing new at all) writes
nothing here — no issue, no email, nothing for you to see.

Requires the 'gh' CLI, which GitHub Actions runners have pre-installed,
and a GH_TOKEN environment variable (set from the workflow's own
GITHUB_TOKEN — see .github/workflows/automation.yml).

To actually receive a phone notification when this issue is created:
install the GitHub mobile app, open this repository, tap the bell icon,
and turn on notifications (or enable email notifications for Issues in
your GitHub account's Settings -> Notifications). This script does not
send email/SMS/push itself — it uses GitHub's own free notification
system so no extra account or secret is needed.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_FILE = ROOT / "automation" / "state" / "last_run_summary.json"
LABEL = "bot-alert"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def main():
    if not SUMMARY_FILE.exists():
        print("No run summary found — nothing to notify.")
        return 0
    summary = json.loads(SUMMARY_FILE.read_text(encoding="utf-8"))
    if not summary.get("alertNeeded"):
        print("Last run was clean — no notification needed.")
        return 0

    body_lines = [
        f"Automated run at {summary['timestamp']}.",
        "",
        f"- Published automatically: {summary['published']}",
        f"- Sent to needs_review.json: {summary['needsReview']}",
        f"- Source-level errors: {len(summary['sourceErrors'])}",
        "",
    ]
    if summary["sourceErrors"]:
        body_lines.append("**Sources with errors this run:**")
        for e in summary["sourceErrors"]:
            body_lines.append(f"- `{e['sourceId']}` ({e['name']}): {e['error']}")
        body_lines.append("")
    if summary["needsReview"]:
        body_lines.append(
            f"{summary['needsReview']} item(s) could not be auto-published and are waiting in "
            "`needs_review.json`. Open that file, check each item's `reasons`, fill in what's "
            "missing from the official page, and set `\"status\": \"approved\"` to publish it "
            "(see AUTOMATION-GUIDE.md). Items you ignore stay harmlessly unpublished — nothing "
            "is exposed on the live site until it's complete."
        )
    body = "\n".join(body_lines)

    # Ensure the label exists (idempotent — ignore failure if it already does)
    run(["gh", "label", "create", LABEL, "--color", "d93f0b",
         "--description", "Sarkari Naukri automation needs attention", "--force"])

    existing = run(["gh", "issue", "list", "--label", LABEL, "--state", "open",
                     "--json", "number", "--jq", ".[0].number"])
    issue_number = existing.stdout.strip()

    if issue_number:
        result = run(["gh", "issue", "comment", issue_number, "--body", body])
    else:
        result = run(["gh", "issue", "create", "--title", "Sarkari Naukri automation needs attention",
                       "--label", LABEL, "--body", body])

    if result.returncode != 0:
        print("! could not create/update the alert issue:", result.stderr)
        return 1
    print("Alert issue created/updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
