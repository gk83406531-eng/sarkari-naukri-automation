"""
automation/lib_common.py
=========================
Shared helpers used by run_pipeline.py and republish_reviewed.py.
Kept in one place so both the automatic path and the manual-fixup path
apply exactly the same validation and safety rules — there is no
"stricter" or "looser" mode, only one set of rules.
"""
import json
import re
import time
import hashlib
import urllib.robotparser
from datetime import datetime, timezone, date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
AUTOMATION_DIR = ROOT / "automation"
STATE_DIR = AUTOMATION_DIR / "state"
SOURCES_FILE = AUTOMATION_DIR / "sources.json"
SEEN_FILE = STATE_DIR / "seen.json"
SNAPSHOT_FILE = STATE_DIR / "page_snapshots.json"
DATA_FILE = ROOT / "data.json"
NEEDS_REVIEW_FILE = ROOT / "needs_review.json"
AUDIT_LOG_FILE = AUTOMATION_DIR / "audit_log.jsonl"
AUDIT_LOG_MAX_LINES = 4000  # trimmed automatically so the repo doesn't grow forever

USER_AGENT = (
    "SarkariNaukriBot/2.0 (+contact: set-your-real-contact-email-in-sources.json; "
    "automated, low-frequency, robots.txt-respecting checker; queues uncertain "
    "items for human review and never bypasses logins/CAPTCHAs/access controls)"
)
REQUEST_TIMEOUT = 20
DELAY_BETWEEN_REQUESTS = 3

REQUIRED_JOB_FIELDS = [
    "org", "title", "category", "vacancies", "qualification", "ageLimit",
    "postDate", "lastDate", "notificationUrl", "applyUrl",
]

# ---------------------------------------------------------------- I/O ----

def load_json(path, default):
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def append_audit(entry):
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def trim_audit_log():
    if not AUDIT_LOG_FILE.exists():
        return
    lines = AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) > AUDIT_LOG_MAX_LINES:
        lines = lines[-AUDIT_LOG_MAX_LINES:]
        AUDIT_LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------ network ----

def robots_allows(url):
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        # If robots.txt can't be read, we do NOT assume permission.
        return False


def fetch(url):
    """GET a URL. Raises on failure. Never follows a login form, never
    submits credentials, never attempts to solve/bypass a CAPTCHA — this
    is a plain, polite, read-only HTTP GET with a descriptive User-Agent."""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


def looks_like_pdf(url, response=None):
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    if response is not None:
        ct = response.headers.get("Content-Type", "").lower()
        if "pdf" in ct:
            return True
    return False


def extract_links(html, base_url):
    pairs = []
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) < 6:
            continue
        abs_href = urljoin(base_url, href)
        if abs_href.startswith(("mailto:", "javascript:", "tel:")):
            continue
        pairs.append((text, abs_href))
    return pairs


def strip_tags(html):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ------------------------------------------------------------- ids/dedupe

def stable_id(*parts):
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


def normalise(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def is_duplicate_in_data(fields, existing_array):
    key = (normalise(fields.get("title")), normalise(fields.get("org")))
    for existing in existing_array:
        if (normalise(existing.get("title")), normalise(existing.get("org"))) == key:
            return True
    return False


# ----------------------------------------------------------- validation --

def domain_allowed(url, allowed_domains):
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    for d in allowed_domains:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False


DATE_PATTERNS = [
    (r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", "dmy"),          # 31-12-2026 or 31/12/2026
    (r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", "ymd"),          # 2026-12-31
    (r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})", "dmonthy"),
]
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August","September","October","November","December"], start=1)}


def parse_date_loose(text):
    """Try to find and parse a date inside a string. Returns 'YYYY-MM-DD' or None.
    Deliberately conservative: only returns a value for an unambiguous match."""
    if not text:
        return None
    for pattern, kind in DATE_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        try:
            if kind == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                d = int(m.group(1)); mo = MONTHS[m.group(2).lower()]; y = int(m.group(3))
            candidate = date(y, mo, d)
            return candidate.isoformat()
        except (ValueError, KeyError):
            continue
    return None


def parse_vacancies(text):
    if not text:
        return None
    m = re.search(r"(\d[\d,]{0,6})\s*(post|posts|vacanc)", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    m = re.search(r"(?:total\s+vacanc\w*|no\.?\s*of\s*posts?)\D{0,5}(\d[\d,]{0,6})", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def parse_age_limit(text):
    if not text:
        return None
    m = re.search(r"(\d{2})\s*(?:-|to|–)\s*(\d{2})\s*years", text, re.IGNORECASE)
    if m:
        return f"{m.group(1)}-{m.group(2)} years (relaxation as per rules)"
    return None


def has_placeholder(value):
    if value is None:
        return True
    s = str(value).strip()
    return s == "" or "[" in s


def validate_job_fields(fields, allowed_domains):
    """Returns (ok: bool, missing_or_invalid: list[str])."""
    problems = []
    for key in REQUIRED_JOB_FIELDS:
        if has_placeholder(fields.get(key)):
            problems.append(f"{key}: missing")

    if fields.get("vacancies") is not None and not has_placeholder(fields.get("vacancies")):
        try:
            if int(fields["vacancies"]) <= 0:
                problems.append("vacancies: not a positive number")
        except (ValueError, TypeError):
            problems.append("vacancies: not a clean number")

    for key in ("postDate", "lastDate"):
        val = fields.get(key)
        if val and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(val)):
            problems.append(f"{key}: not a valid parsed date")

    if not has_placeholder(fields.get("postDate")) and not has_placeholder(fields.get("lastDate")):
        try:
            p = date.fromisoformat(fields["postDate"])
            l = date.fromisoformat(fields["lastDate"])
            if l < p:
                problems.append("lastDate: earlier than postDate")
            if l < date.today():
                problems.append("lastDate: already in the past (likely stale/mis-parsed)")
        except ValueError:
            problems.append("postDate/lastDate: could not compare")

    for key in ("notificationUrl", "applyUrl"):
        url = fields.get(key)
        if url and not has_placeholder(url):
            if not domain_allowed(url, allowed_domains):
                problems.append(f"{key}: domain not in this source's approved official-domain list")

    return (len(problems) == 0, problems)
