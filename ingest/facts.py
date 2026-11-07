"""Reviewed facts: limits and rules that the answer path can serve exactly.

Data/facts.csv holds one row per fact. Rules enforced here:
- the quote must appear in the source document's text (after manual patches)
- a numeric value must appear in the quote (as digits, '2K', 'N Lakh' or 'Rs N')
- only rows with review_status 'human_verified' are served (see FSD F-2)
- superseded rows point at the row that replaces them
- a withdrawn row may name the document that ended it (closed_by_*), with a quote checked the same way
"""

import csv
import os
import re

from . import paths, patches

FACTS_PATH = os.path.join(paths.DATA, "facts.csv")

COLUMNS = [
    "fact_id", "domain", "txn_type", "limit_kind", "direction", "merchant_type", "mcc",
    "category_name", "value", "unit", "conditions", "effective_date", "end_date",
    "source_oc", "source_doc_id", "quote", "page", "status", "superseded_by_fact",
    "review_status", "reviewer", "reviewed_on", "notes",
    "closed_by_doc_id", "closed_by_clause", "closed_by_page", "closed_by_quote",
]
TXN_TYPES = {"P2P", "P2PM", "P2M", "UPI_LITE", "UPI_LITE_X", "ON_DEVICE_BIOMETRIC"}
LIMIT_KINDS = {
    "per_txn_amount", "per_24h_amount", "per_24h_count", "per_month_amount",
    "collect_per_txn", "qr_share_pay_per_txn", "max_balance",
}
STATUSES = {"current", "superseded", "withdrawn", "unclear"}   # withdrawn: the circular was withdrawn, nothing replaces it in the facts
REVIEW_STATUSES = {"drafted", "auto_checked", "human_verified"}
UNITS = {"INR", "count"}


def load(path: str = None) -> list:
    path = path or FACTS_PATH
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows: list, path: str = None) -> None:
    path = path or FACTS_PATH
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _norm(s: str) -> str:
    """Compare quotes ignoring whitespace and case."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


def source_texts(registry_rows: list, cache_records: list) -> dict:
    """doc_id -> the text facts are checked against (extracted text + patches)."""
    by_hash = {r["content_hash"]: r["text"] for r in cache_records}
    out = {}
    for row in registry_rows:
        if row["status"] in ("unreadable", "not_public"):
            continue
        out[row["doc_id"]] = patches.patched_text(row, by_hash.get(row["content_hash"], ""))
    return out


def number_in_quote(value: str, unit: str, quote: str) -> bool:
    """True if the fact's number is visible in the quote in a common form."""
    if unit not in ("INR", "count"):
        return True
    try:
        v = int(float(value))
    except ValueError:
        return False
    q = quote.replace(",", "")
    candidates = {str(v)}
    if unit == "INR":
        if v % 100000 == 0:
            n = v // 100000
            candidates |= {f"{n} lakh", f"{n} lakhs", f"{n} lacs", f"{n}.0 lakh"}
        if v % 1000 == 0:
            candidates.add(f"{v // 1000}k")
    low = q.lower()
    for c in candidates:
        for m in re.finditer(re.escape(c.lower()), low):
            before = low[m.start() - 1] if m.start() else " "
            after = low[m.end()] if m.end() < len(low) else " "
            if not before.isdigit() and not after.isdigit():
                return True
    return False


def validate(facts: list, texts: dict, registry_rows: list) -> list:
    """Return (severity, fact_id, message) tuples."""
    issues = []
    ids = [f["fact_id"] for f in facts]
    for dup in {i for i in ids if ids.count(i) > 1}:
        issues.append(("error", dup, "duplicate fact_id"))
    known_docs = {r["doc_id"] for r in registry_rows}
    for f in facts:
        fid = f["fact_id"]
        if f["txn_type"] not in TXN_TYPES:
            issues.append(("error", fid, f"unknown txn_type {f['txn_type']!r}"))
        if f["limit_kind"] not in LIMIT_KINDS:
            issues.append(("error", fid, f"unknown limit_kind {f['limit_kind']!r}"))
        if f["status"] not in STATUSES:
            issues.append(("error", fid, f"unknown status {f['status']!r}"))
        if f["review_status"] not in REVIEW_STATUSES:
            issues.append(("error", fid, f"unknown review_status {f['review_status']!r}"))
        if f["unit"] not in UNITS:
            issues.append(("error", fid, f"unknown unit {f['unit']!r}"))
        if f["source_doc_id"] not in known_docs:
            issues.append(("error", fid, f"source_doc_id {f['source_doc_id']!r} not in registry"))
            continue
        text = texts.get(f["source_doc_id"], "")
        if not f["quote"].strip():
            issues.append(("error", fid, "quote is empty"))
        elif _norm(f["quote"]) not in _norm(text):
            issues.append(("error", fid, "quote not found in the source text"))
        elif not number_in_quote(f["value"], f["unit"], f["quote"]):
            issues.append(("error", fid, f"value {f['value']} not visible in the quote"))
        if f["status"] == "superseded":
            if f["superseded_by_fact"] not in ids:
                issues.append(("error", fid, "superseded but superseded_by_fact is missing or unknown"))
        elif f["superseded_by_fact"]:
            issues.append(("error", fid, "superseded_by_fact set on a row that is not superseded"))
        closer = f.get("closed_by_doc_id", "")
        if closer:
            if f["status"] != "withdrawn":
                issues.append(("error", fid, "closed_by_doc_id set on a row that is not withdrawn"))
            elif closer not in known_docs:
                issues.append(("error", fid, f"closed_by_doc_id {closer!r} not in registry"))
            elif not f.get("closed_by_quote", "").strip() or _norm(f["closed_by_quote"]) not in _norm(texts.get(closer, "")):
                issues.append(("error", fid, "closed_by_quote not found in the closing document's text"))
        if f["review_status"] == "human_verified" and not (f["reviewer"] and f["reviewed_on"]):
            issues.append(("error", fid, "human_verified without reviewer and date"))
    return issues


def servable(facts: list) -> list:
    """Facts the answer path may use: human-verified only."""
    return [f for f in facts if f["review_status"] == "human_verified"]
