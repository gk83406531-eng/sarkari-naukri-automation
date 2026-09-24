#!/usr/bin/env python3
"""
automation/republish_reviewed.py
==================================
Optional, exception-path-only script. Most listings never reach here —
they're auto-published by run_pipeline.py, or they sit harmlessly in
needs_review.json until you look at them (or forever, if you never do).

Runs when needs_review.json is pushed (you edited an item's fields on
your phone and set "status": "approved"). Applies EXACTLY the same
validate_job_fields() rule run_pipeline.py uses — there is no separate,
looser check for manually-completed items.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_common import (  # noqa: E402
    DATA_FILE, NEEDS_REVIEW_FILE, SOURCES_FILE,
    load_json, save_json, append_audit, is_duplicate_in_data, validate_job_fields,
)


def main():
    data = load_json(DATA_FILE, None)
    if data is None:
        print("! data.json not found — aborting")
        return 1
    needs_review = load_json(NEEDS_REVIEW_FILE, [])
    sources = {s["id"]: s for s in load_json(SOURCES_FILE, {"sources": []})["sources"]}

    remaining = []
    published = 0
    for item in needs_review:
        if item.get("status") != "approved":
            remaining.append(item)
            continue

        source = sources.get(item.get("sourceId"), {})
        fields = item.get("fields", {})
        ok, problems = validate_job_fields(fields, source.get("officialDomains", []))
        if not ok:
            item["status"] = "needs_review"
            item["reasons"] = problems
            item["note"] = "Still incomplete/invalid after your edit — see reasons."
            remaining.append(item)
            append_audit({"sourceId": item.get("sourceId"), "itemId": item["id"],
                           "rawTitle": item.get("rawTitle"), "link": item.get("link"),
                           "outcome": "needs_review", "reason": "; ".join(problems) + " (manual review attempt)"})
            print(f"! {item['id']}: still invalid — {problems}")
            continue

        if is_duplicate_in_data(fields, data.get("jobs", [])):
            item["status"] = "duplicate_skipped"
            remaining.append(item)
            append_audit({"sourceId": item.get("sourceId"), "itemId": item["id"],
                           "outcome": "duplicate_skipped", "reason": "matches an existing listing (manual review)"})
            print(f"! {item['id']}: duplicate")
            continue

        data.setdefault("jobs", []).append({
            "id": item["id"], "title": fields["title"], "org": fields["org"],
            "category": fields["category"], "postDate": fields["postDate"], "lastDate": fields["lastDate"],
            "vacancies": fields["vacancies"], "qualification": fields["qualification"],
            "ageLimit": fields["ageLimit"], "fee": fields.get("fee") or "Refer to official notification",
            "selection": ["Refer to official notification"],
            "salary": fields.get("salary") or "Refer to official notification",
            "importantDates": [["Application starts", fields["postDate"]], ["Application ends", fields["lastDate"]]],
            "notificationUrl": fields["notificationUrl"], "applyUrl": fields["applyUrl"],
        })
        published += 1
        append_audit({"sourceId": item.get("sourceId"), "itemId": item["id"],
                       "outcome": "published", "reason": "manually completed and approved"})
        print(f"+ {item['id']}: published")

    if published:
        save_json(DATA_FILE, data)
    save_json(NEEDS_REVIEW_FILE, remaining)
    print(f"\nDone. Published {published} manually-approved item(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
