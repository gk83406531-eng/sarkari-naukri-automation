#!/usr/bin/env python3
"""
automation/run_pipeline.py
===========================
The single scheduled job (see .github/workflows/automation.yml). For every
ENABLED source in sources.json:

  1. DETECT new items (adapter depends on source["type"] — rss / manual_page
     / json_api). Already-seen items (automation/state/seen.json) are
     skipped — this is the duplicate-detection step at the detection level.

  2. EXTRACT fields. org and category are fixed per source (we know whose
     official site we're reading). Everything else (title, vacancies,
     qualification, age limit, dates, apply link) is extracted from the
     fetched text using label-anchored patterns (automation/extract.py).
     If the linked notification is a PDF, extraction is not attempted at
     all (unreliable) and the item is routed to needs_review outright.

  3. VALIDATE. Every required field must be present, well-formed, and any
     URL must belong to that source's officialDomains allow-list. Dates
     must parse and make chronological sense.

  4. DEDUPE against what's already published (title+org match) — the
     second, independent duplicate check (requirement 5's "detect
     duplicates", applied both at detection time and at publish time).

  5. DECIDE:
       - all required fields valid + not a duplicate  -> published straight
         into data.json. No human approval step for this case.
       - anything missing/invalid/ambiguous/a PDF/a duplicate -> written to
         needs_review.json with the specific reason(s); NOT published.

  6. LOG every single detected item — published, needs_review, or
     source-level error — to automation/audit_log.jsonl (requirement 13).

  7. NOTIFY (automation/notify.py) opens/updates one GitHub Issue if, and
     only if, this run produced any needs_review items or errors. A clean
     run with everything auto-published (or nothing new) creates no
     notification at all.

This script never fabricates a field it could not read from the fetched
page/feed, and it never publishes anything with a missing or invalid
required field, regardless of how "close" it looks.
"""
import re
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))
from lib_common import (  # noqa: E402
    ROOT, SOURCES_FILE, SEEN_FILE, SNAPSHOT_FILE, DATA_FILE, NEEDS_REVIEW_FILE,
    load_json, save_json, append_audit, trim_audit_log,
    robots_allows, fetch, looks_like_pdf, extract_links, strip_tags,
    stable_id, is_duplicate_in_data, validate_job_fields,
    DELAY_BETWEEN_REQUESTS,
)
from extract import extract_all  # noqa: E402

CATEGORY_ARRAY_FOR_LISTING_TYPE = {"job": "jobs"}  # this pipeline currently
# only auto-detects new recruitment notices ("jobs"); results/admit
# cards/answer keys have no reliable official feed at all today and are
# intentionally out of scope for auto-detection (see AUTOMATION-GUIDE.md).


def process_candidate(source, raw_title, link, pre_text=""):
    """Try to build a complete, validated 'job' fields dict for one
    candidate. Returns (fields: dict, meta: dict) — meta explains what,
    if anything, prevented full extraction."""
    extracted = {}
    if pre_text:
        extracted.update(extract_all(pre_text))

    pdf_flag = False
    fetch_error = None
    apply_url_found = None

    need_more = not all(k in extracted for k in ("lastDate", "vacancies", "qualification", "ageLimit"))
    if need_more:
        if robots_allows(link):
            try:
                resp = fetch(link)
                if looks_like_pdf(link, resp):
                    pdf_flag = True
                else:
                    page_text = strip_tags(resp.text)
                    deep = extract_all(page_text)
                    for k, v in deep.items():
                        extracted.setdefault(k, v)
                    for text, href in extract_links(resp.text, link):
                        if re.search(r"apply", text, re.IGNORECASE):
                            apply_url_found = href
                            break
            except Exception as e:
                fetch_error = str(e)
        else:
            fetch_error = "robots.txt disallows fetching the linked detail page"

    fields = {
        "org": source.get("org") or "",
        "category": source["category"],
        "title": (raw_title or "").strip(),
        "vacancies": extracted.get("vacancies"),
        "qualification": extracted.get("qualification"),
        "ageLimit": extracted.get("ageLimit"),
        "postDate": extracted.get("postDate"),
        "lastDate": extracted.get("lastDate"),
        "examDate": extracted.get("examDate"),  # optional, not required
        "notificationUrl": link,
        "applyUrl": apply_url_found or (source.get("applyPortalUrl") or None),
        "fee": None,   # not auto-extracted (rarely labelled consistently) — always needs_review if required
        "salary": None,
    }
    meta = {"pdf": pdf_flag, "fetchError": fetch_error}
    return fields, meta


def detect_manual_page(source, seen, snapshots):
    url = source["url"]
    if not robots_allows(url):
        return [], f"robots.txt disallows fetching {url}"
    try:
        resp = fetch(url)
    except Exception as e:
        return [], f"fetch failed: {e}"

    current_pairs = extract_links(resp.text, url)
    current_set = {f"{t}||{h}" for t, h in current_pairs}
    previous_set = set(snapshots.get(source["id"], []))
    new_pairs = [p for p in current_pairs if f"{p[0]}||{p[1]}" not in previous_set]
    snapshots[source["id"]] = sorted(current_set)

    candidates = []
    for text, href in new_pairs:
        item_id = stable_id(source["id"], href, text)
        if item_id in seen:
            continue
        seen[item_id] = {"source": source["id"], "firstSeen": datetime.now(timezone.utc).isoformat()}
        candidates.append({"id": item_id, "rawTitle": text, "link": href, "preText": ""})
    return candidates, None


def detect_rss(source, seen):
    import feedparser
    feed = feedparser.parse(source["url"])
    if feed.bozo and not feed.entries:
        return [], f"could not parse feed: {feed.bozo_exception}"
    candidates = []
    for entry in feed.entries:
        link = entry.get("link", "")
        if not link:
            continue
        item_id = stable_id(source["id"], link)
        if item_id in seen:
            continue
        seen[item_id] = {"source": source["id"], "firstSeen": datetime.now(timezone.utc).isoformat()}
        pre_text = (entry.get("title", "") + " " + entry.get("summary", "")).strip()
        candidates.append({"id": item_id, "rawTitle": entry.get("title", ""), "link": link, "preText": pre_text})
    return candidates, None


def detect_json_api(source, seen):
    import requests
    r = requests.get(source["url"], timeout=20, headers={"User-Agent": "SarkariNaukriBot/2.0"})
    r.raise_for_status()
    payload = r.json()
    fmap = source.get("fieldMap", {})
    items = payload.get(fmap.get("itemsPath", ""), [])
    candidates = []
    for item in items:
        link = item.get(fmap.get("notificationUrl", ""), "")
        if not link:
            continue
        item_id = stable_id(source["id"], link)
        if item_id in seen:
            continue
        seen[item_id] = {"source": source["id"], "firstSeen": datetime.now(timezone.utc).isoformat()}
        # json_api items are already structured — build fields directly, no regex needed.
        structured = {
            "org": source.get("org") or item.get(fmap.get("org", ""), ""),
            "category": source["category"],
            "title": item.get(fmap.get("title", ""), ""),
            "vacancies": item.get(fmap.get("vacancies", "")),
            "qualification": item.get(fmap.get("qualification", "")),
            "ageLimit": item.get(fmap.get("ageLimit", "")),
            "postDate": item.get(fmap.get("postDate", "")),
            "lastDate": item.get(fmap.get("lastDate", "")),
            "examDate": item.get(fmap.get("examDate", "")),
            "notificationUrl": item.get(fmap.get("notificationUrl", ""), ""),
            "applyUrl": item.get(fmap.get("applyUrl", ""), ""),
            "fee": None, "salary": None,
        }
        candidates.append({"id": item_id, "rawTitle": structured["title"], "link": link,
                            "preText": "", "_structured": structured})
    return candidates, None


def main():
    config = load_json(SOURCES_FILE, {"sources": []})
    seen = load_json(SEEN_FILE, {})
    snapshots = load_json(SNAPSHOT_FILE, {})
    data = load_json(DATA_FILE, None)
    if data is None:
        print("! data.json not found — aborting without changes")
        return 1
    needs_review = load_json(NEEDS_REVIEW_FILE, [])

    published_count = 0
    needs_review_count = 0
    source_errors = []

    for source in config.get("sources", []):
        if not source.get("enabled", False):
            continue
        stype = source.get("type")
        print(f"[{stype}] {source['name']}")

        if stype == "manual_page":
            candidates, err = detect_manual_page(source, seen, snapshots)
        elif stype == "rss":
            try:
                candidates, err = detect_rss(source, seen)
            except Exception as e:
                candidates, err = [], f"rss error: {e}"
        elif stype == "json_api":
            try:
                candidates, err = detect_json_api(source, seen)
            except Exception as e:
                candidates, err = [], f"json_api error: {e}"
        else:
            print(f"  [skip] type '{stype}' is not auto-checked (see sources.json notes)")
            continue

        if err:
            print(f"  ! {err}")
            source_errors.append({"sourceId": source["id"], "name": source["name"], "error": err})
            append_audit({"sourceId": source["id"], "outcome": "source_error", "reason": err})
            time.sleep(DELAY_BETWEEN_REQUESTS)
            continue

        print(f"  {len(candidates)} new candidate(s)")
        for cand in candidates:
            if "_structured" in cand:
                fields = cand["_structured"]
                meta = {"pdf": False, "fetchError": None}
            else:
                fields, meta = process_candidate(source, cand["rawTitle"], cand["link"], cand["preText"])

            problems = []
            if meta["pdf"]:
                problems.append("official notification is a PDF — automatic field extraction is not attempted (unreliable)")
            if meta["fetchError"]:
                problems.append(f"could not fetch/verify detail page: {meta['fetchError']}")

            ok, field_problems = validate_job_fields(fields, source.get("officialDomains", []))
            problems.extend(field_problems)
            ok = ok and not problems

            outcome = None
            reason = None
            if ok:
                if is_duplicate_in_data(fields, data.get("jobs", [])):
                    outcome, reason = "duplicate_skipped", "matches an existing published listing (title+org)"
                else:
                    data.setdefault("jobs", []).append({
                        "id": cand["id"], "title": fields["title"], "org": fields["org"],
                        "category": fields["category"], "postDate": fields["postDate"],
                        "lastDate": fields["lastDate"], "vacancies": fields["vacancies"],
                        "qualification": fields["qualification"], "ageLimit": fields["ageLimit"],
                        "fee": fields.get("fee") or "Refer to official notification",
                        "selection": ["Refer to official notification"],
                        "salary": fields.get("salary") or "Refer to official notification",
                        "importantDates": [["Application starts", fields["postDate"]],
                                            ["Application ends", fields["lastDate"]]] +
                                           ([["Exam date", fields["examDate"]]] if fields.get("examDate") else []),
                        "notificationUrl": fields["notificationUrl"], "applyUrl": fields["applyUrl"],
                    })
                    outcome, reason = "published", "all required fields extracted and validated automatically"
                    published_count += 1
            else:
                needs_review.append({
                    "id": cand["id"], "status": "needs_review", "sourceId": source["id"],
                    "sourceType": stype, "category": source["category"],
                    "detectedAt": datetime.now(timezone.utc).isoformat(),
                    "rawTitle": cand["rawTitle"], "link": cand["link"],
                    "fields": fields, "reasons": problems,
                    "note": "Automatically extracted where possible. Fix/fill the fields below and set "
                            "status to 'approved' to publish via review-followup, or leave as-is to skip.",
                })
                outcome, reason = "needs_review", "; ".join(problems) if problems else "incomplete extraction"
                needs_review_count += 1

            append_audit({
                "sourceId": source["id"], "itemId": cand["id"], "rawTitle": cand["rawTitle"],
                "link": cand["link"], "outcome": outcome, "reason": reason,
            })

        time.sleep(DELAY_BETWEEN_REQUESTS)

    save_json(SEEN_FILE, seen)
    save_json(SNAPSHOT_FILE, snapshots)
    if published_count:
        save_json(DATA_FILE, data)
    if needs_review_count:
        save_json(NEEDS_REVIEW_FILE, needs_review)
    trim_audit_log()

    print(f"\nDone. Published {published_count}. Needs review {needs_review_count}. "
          f"Source errors {len(source_errors)}.")

    # Signal to the workflow (via files) whether a notification is warranted.
    alert_needed = bool(needs_review_count or source_errors)
    save_json(ROOT / "automation" / "state" / "last_run_summary.json", {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "published": published_count,
        "needsReview": needs_review_count,
        "sourceErrors": source_errors,
        "alertNeeded": alert_needed,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
