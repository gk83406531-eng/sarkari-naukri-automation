"""
automation/extract.py
======================
Label-anchored text extraction. Given a blob of plain text (already
stripped of HTML tags) and a list of label phrases, finds the text that
follows the first matching label and hands it to a specific parser
(date / number / age-range / raw-snippet).

This is intentionally conservative: if no label is found, it returns
None rather than guessing from context. A missing field falls through
to needs_review — it is never silently left blank in a published listing
(lib_common.validate_job_fields rejects any blank required field before
anything is published).
"""
import re

from lib_common import parse_date_loose, parse_vacancies, parse_age_limit

LABELS = {
    "lastDate": [
        r"last date (?:to|for) (?:apply|submission|receipt of application)",
        r"closing date(?: for submission)?",
        r"last date of (?:online )?application",
        r"application(?:s)? (?:close|closes|will close)",
    ],
    "postDate": [
        r"start(?:ing)? date(?: of)? (?:online )?application",
        r"application(?:s)? (?:will )?(?:begin|start|commence)",
        r"commencement of (?:online )?application",
    ],
    "examDate": [
        r"date of examination",
        r"tentative date of exam(?:ination)?",
        r"exam(?:ination)? date",
        r"cbt date",
    ],
    "vacancy": [
        r"total (?:no\.?|number) of (?:vacanc(?:y|ies)|posts?)",
        r"total vacanc(?:y|ies)",
        r"no\.? of posts?",
        r"vacanc(?:y|ies) details",
    ],
    "age": [
        r"age limit",
        r"upper age limit",
        r"minimum age",
    ],
    "qualification": [
        r"educational qualification",
        r"eligibility(?: criteria)?",
        r"qualification required",
        r"minimum qualification",
    ],
}

SNIPPET_WINDOW = 160  # characters captured after a matched label


def _find_after_label(text, label_patterns):
    for pattern in label_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            start = m.end()
            snippet = text[start:start + SNIPPET_WINDOW]
            snippet = re.sub(r"^[\s:.\-–—]+", "", snippet)
            return snippet
    return None


def extract_all(text):
    """Returns a dict with whatever could be confidently found.
    Keys not found are simply absent (not None, not "") — callers should
    use .get() and treat missing keys as 'could not extract'."""
    out = {}

    snippet = _find_after_label(text, LABELS["lastDate"])
    if snippet:
        d = parse_date_loose(snippet)
        if d:
            out["lastDate"] = d

    snippet = _find_after_label(text, LABELS["postDate"])
    if snippet:
        d = parse_date_loose(snippet)
        if d:
            out["postDate"] = d

    snippet = _find_after_label(text, LABELS["examDate"])
    if snippet:
        d = parse_date_loose(snippet)
        if d:
            out["examDate"] = d

    snippet = _find_after_label(text, LABELS["vacancy"])
    if snippet:
        n = parse_vacancies(snippet) or parse_vacancies("posts " + snippet)
        if n is None:
            m = re.search(r"\d[\d,]{0,6}", snippet)
            if m:
                try:
                    n = int(m.group(0).replace(",", ""))
                except ValueError:
                    n = None
        if n:
            out["vacancies"] = n

    snippet = _find_after_label(text, LABELS["age"])
    if snippet:
        a = parse_age_limit(snippet) or parse_age_limit("age " + snippet + " years")
        if a:
            out["ageLimit"] = a

    snippet = _find_after_label(text, LABELS["qualification"])
    if snippet:
        cleaned = re.sub(r"\s+", " ", snippet).strip(" .,:;-")
        if len(cleaned) >= 12:
            out["qualification"] = cleaned

    return out
