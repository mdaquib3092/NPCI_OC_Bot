"""Everything the circulars say about a code (MCC, purpose code).

Data/code_mentions.csv is GENERATED on every build from the document text, so
it can never drift from the circulars. It answers three different questions
(PRD FR-3a):
  - the OC sets a specific rule for this code        (rule_type = limit)
  - the OC mentions the code without a limit         (requirement / mention_only)
  - no indexed OC mentions the code at all           (no row)
"""

import csv
import os
import re

from . import paths

CODES_PATH = os.path.join(paths.DATA, "code_mentions.csv")
COLUMNS = ["code_family", "code", "name", "oc_number", "source_doc_id", "rule_type",
           "quote", "effective_date"]

_MCC_ANCHOR = re.compile(r"\bMCCs?\b", re.IGNORECASE)
_FOUR = re.compile(r"(?<![\d.,/-])(\d{4})(?![\d/-])")
_PURPOSE_ANCHOR = re.compile(r"purpose\s*codes?", re.IGNORECASE)
_PURPOSE_CODE = re.compile(r"(?<![\w/])(\d{2}|[A-Z]{2})(?![\w/])")
_NAMED = re.compile(r"MCC\s*[-:]?\s*(\d{4})\s*[:\-–]\s*([A-Z][A-Za-z0-9&/ ,'’()-]{3,70})")
_OBLIGATION = re.compile(r"\b(shall|must|should|required|mandatory|not be allowed|disallowed|allowed only)\b", re.I)
_LIMIT_WORDS = re.compile(r"(limit|lakh|lacs|₹|\bRs\b|\bINR\b)", re.I)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _window(flat: str, start: int, end: int, before: int = 140, after: int = 160) -> str:
    return flat[max(0, start - before): min(len(flat), end + after)].strip()


def _mcc_codes(span: str) -> list:
    return [m for m in _FOUR.findall(span) if not (1900 <= int(m) <= 2100)]


def scan_document(row: dict, text: str) -> list:
    """Mentions found in one document."""
    flat = _flat(text)
    found = {}  # (family, code) -> dict

    def record(family, code, quote, name=""):
        key = (family, code)
        if key not in found:
            # Never "limit" from wording alone: that label is only given to codes
            # that have a reviewed fact (see scan_all).
            rule = "requirement" if _OBLIGATION.search(quote) else "mention_only"
            found[key] = {"code_family": family, "code": code, "name": name,
                          "oc_number": row["oc_number"], "source_doc_id": row["doc_id"],
                          "rule_type": rule, "quote": quote[:360], "effective_date": row["issue_date"]}
        elif name and not found[key]["name"]:
            found[key]["name"] = name

    for m in _MCC_ANCHOR.finditer(flat):
        span = flat[m.end(): m.end() + 110]
        # stop at the end of the sentence
        span = re.split(r"(?<=[a-z\)])\.\s+[A-Z]", span)[0]
        for code in _mcc_codes(span):
            record("mcc", code, _window(flat, m.start(), m.end() + len(span)))
    for m in _NAMED.finditer(flat):
        record("mcc", m.group(1), _window(flat, m.start(), m.end()), name=m.group(2).strip(" ,;:-"))
    for m in _PURPOSE_ANCHOR.finditer(flat):
        span = flat[m.end(): m.end() + 45]
        for code in _PURPOSE_CODE.findall(re.split(r"[.;]", span)[0]):
            record("purpose_code", code, _window(flat, m.start(), m.end() + len(span)))
    return list(found.values())


def scan_all(registry_rows: list, texts: dict, facts: list = None) -> list:
    """Scan every readable document, then merge in the reviewed facts: a code
    with a limit fact gets rule_type 'limit' and its category name."""
    out = []
    for row in registry_rows:
        text = texts.get(row["doc_id"])
        if text:
            out.extend(scan_document(row, text))
    index = {(r["code_family"], r["code"], r["source_doc_id"]): r for r in out}
    docs = {r["doc_id"]: r for r in registry_rows}
    for f in facts or []:
        if not f["mcc"]:
            continue
        key = ("mcc", f["mcc"], f["source_doc_id"])
        if key not in index:
            doc = docs[f["source_doc_id"]]
            index[key] = {"code_family": "mcc", "code": f["mcc"], "name": "", "oc_number": doc["oc_number"],
                          "source_doc_id": doc["doc_id"], "rule_type": "mention_only",
                          "quote": f["quote"][:360], "effective_date": doc["issue_date"]}
            out.append(index[key])
        index[key]["rule_type"] = "limit"
        index[key]["name"] = index[key]["name"] or f["category_name"]
    names = {}
    for r in out:
        if r["name"]:
            names.setdefault((r["code_family"], r["code"]), r["name"])
    for r in out:
        r["name"] = r["name"] or names.get((r["code_family"], r["code"]), "")
    out.sort(key=lambda r: (r["code_family"], r["code"], r["effective_date"], r["source_doc_id"]))
    return out


def save(rows: list, path: str = None) -> None:
    with open(path or CODES_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def load(path: str = None) -> list:
    path = path or CODES_PATH
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def lookup(rows: list, family: str, code: str) -> dict:
    """The three outcomes for a code: {'outcome': ..., 'rows': [...]}."""
    hits = [r for r in rows if r["code_family"] == family and r["code"] == code]
    if not hits:
        return {"outcome": "not_mentioned", "rows": []}
    if any(r["rule_type"] == "limit" for r in hits):
        return {"outcome": "specific_rule", "rows": hits}
    return {"outcome": "mention_only", "rows": hits}
