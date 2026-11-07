"""The OC registry: one reviewed row per circular (Data/registry.csv).

`draft` proposes rows from the extracted text and filenames. It never overwrites
a row that already exists in the registry, so a person's corrections survive a
rebuild. `validate` is the gate the build runs.
"""

import csv
import hashlib
import json
import os
import re
from collections import defaultdict

from . import headers as H
from . import paths

COLUMNS = [
    "doc_id", "oc_number", "series", "domain", "reference", "title", "issue_date",
    "effective_date", "fy", "category", "status", "supersedes", "superseded_by",
    "source_file", "content_hash", "text_source", "page_count", "char_count",
    "review_status", "needs_review", "notes",
]
STATUSES = {"current", "superseded", "partially_superseded", "informational", "unreadable", "not_public", "withdrawn"}
# not_public: NPCI lists the circular but publishes no PDF (member-only). The row has no
# source file; the chatbot says the circular exists and that its text is not public.
# withdrawn: NPCI has withdrawn the circular (for example listed in Annexure G of the UPI Consolidated
# Circular). It stays searchable but is never presented as in force.
NO_TEXT_STATUSES = {"unreadable", "not_public"}

CATEGORY_KEYWORDS = {
    "limits": ["limit", "lakh", "p2pm", "standardization", "standardisation"],
    "disputes": ["chargeback", "dispute", "udir", "complaint", "refund", "reversal",
                 "tat", "arbitration", "good faith"],
    "product": ["lite", "123pay", "autopay", "auto pay", "mandate", "circle", "credit",
                "cbdc", "voucher", "tap and pay", "iccw", "global", "international",
                "remittance", "hello upi", "plug in", "voice", "numeric"],
    "merchant": ["merchant", "onboarding", "acquir", "mcc", "qr", "sdk", "checkout", "b2b"],
    "compliance": ["compliance", "penalty", "attestation", "adherence", "guidelines",
                   "mandatory", "non compliance"],
    "technical": ["api", "raw", "settlement", "reconciliation", "switch", "response",
                  "txnid", "rrn", "purpose code", "deemed", "decline", "timeout", "check txn"],
}

ADMIN_KEYWORDS = [
    "compliance to circular", "compliance to oc", "reminder on", "reminder of",
    "reiteration of", "adherence to", "self-attestation", "self attestation",
    "product-compliance", "product compliance", "certification fee",
]


# --------------------------------------------------------------- OC numbers --
def oc_from_filename(filename: str) -> tuple:
    """(oc_number, series, ambiguous). Keeps letter suffixes ('76A' stays '76A').

    The circular's own number is the one that comes first in the name; numbers
    that follow are references ('Extension to Circular No 60', 'Addendum to OC
    125') and 4-digit numbers are years. Administrative notices (self-attestation,
    'Compliance to Circular 15B and 32', fee notes) are not OCs and return ''."""
    lname = re.sub(r"[-_]+", " ", filename.lower())
    is_imps = bool(re.search(r"operation[\s\-_.]*circular", lname))
    own_series = "IMPS_UPI" if is_imps else ("RUPAY" if lname.startswith("rupay") else "UPI")
    patterns = [
        r"OC[\s\-_.]*No[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])",
        r"OC[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])(?!\d)",
        r"Circular[\s\-_.]*No[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])",
        r"Circular[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])(?!\d)",
        r"Ciruclar[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])(?!\d)",
        r"NPCI[\s\-_.]*UPI[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])(?!\d)",
    ]
    found = []
    for pat in patterns:
        for m in re.finditer(pat, filename, re.IGNORECASE):
            if int(m.group(1)) >= 1000:  # a year, not a circular number
                continue
            found.append((f"{int(m.group(1))}{(m.group(2) or '').upper()}", m.start()))
    found.sort(key=lambda x: x[1])
    kw_pos = [lname.find(k.replace("-", " ")) for k in ADMIN_KEYWORDS if k.replace("-", " ") in lname]
    admin = bool(kw_pos)
    if not found or (admin and min(kw_pos) < found[0][1]):
        return "", "", admin
    return found[0][0], own_series, False


def oc_from_text(head: str) -> tuple:
    """(oc_number, product, fy, reference) from the NPCI reference line."""
    ref = H.parse_reference(head)
    number = f"{ref['number']}{ref['suffix']}" if ref["number"] else ""
    product = ref["product"]
    if not number and ref["reference"]:
        m = re.search(r"[O0][CcEe][\s.\-—–:]*(?:No\.?)?[\s.\-—–:]*0*(\d{1,3})\s?([A-E])?(?![A-Za-z0-9])",
                      ref["reference"])
        if m:
            number, product = f"{m.group(1)}{(m.group(2) or '').upper()}", product or "UPI"
    if re.search(r"UP.?[IVHU]?\s*/?\s*[O0]C", ref["reference"] or "") and not product:
        product = "UPI"
    return number, product, ref["fy"], ref["reference"]


def _base(oc: str) -> str:
    m = re.match(r"\d+", oc or "")
    return m.group(0) if m else ""


def _sort_key(row):
    m = re.match(r"(\d+)([A-Z]*)", row.get("oc_number") or "")
    return (row.get("series", ""), int(m.group(1)) if m else 10**6, m.group(2) if m else "", row.get("doc_id", ""))


def guess_category(text: str) -> str:
    low = re.sub(r"[-_]+", " ", text.lower())
    scores = {c: sum(1 for k in kws if k in low) for c, kws in CATEGORY_KEYWORDS.items()}
    scores = {c: s for c, s in scores.items() if s}
    return max(scores, key=scores.get) if scores else "uncategorised"


# -------------------------------------------------------------- dedupe -------
def _norm_text_hash(text: str) -> str:
    t = re.sub(r"[^a-z0-9]", "", text.lower())
    return hashlib.md5(t.encode()).hexdigest()


def _name_score(name: str) -> int:
    score = 0
    if re.search(r"OC[\s\-_]*No[\s\-_]*\d+", name, re.I):
        score += 3
    if re.search(r"FY[\s\-_]*\d", name, re.I):
        score += 2
    return score - name.count("_") + len(name) // 20


def load_text_cache() -> list:
    out = []
    for f in sorted(os.listdir(paths.EXTRACTED_DIR)):
        if f.endswith(".json"):
            with open(os.path.join(paths.EXTRACTED_DIR, f), encoding="utf-8") as fh:
                out.append(json.load(fh))
    return out


def split_records(records: list) -> tuple:
    """Return (usable, skipped) where skipped is a list of dicts for the dedupe
    report: files that are not PDFs at all, and text-identical duplicates."""
    skipped, usable = [], []
    for r in records:
        if "wrong header" in (r.get("problem") or ""):
            skipped.append({"file": r["source_file"], "reason": "invalid_source", "kept": "",
                            "detail": r["problem"]})
        else:
            usable.append(r)
    groups = defaultdict(list)
    for r in usable:
        if r.get("readable"):
            groups[_norm_text_hash(r["text"])].append(r)
    drop = set()
    for recs in groups.values():
        if len(recs) > 1:
            recs.sort(key=lambda r: (-_name_score(r["source_file"]), r["source_file"]))
            for d in recs[1:]:
                drop.add(d["content_hash"])
                skipped.append({"file": d["source_file"], "reason": "duplicate_text",
                                "kept": recs[0]["source_file"], "detail": ""})
    return [r for r in usable if r["content_hash"] not in drop], skipped


# -------------------------------------------------------------- drafting -----
def _doc_id(series, oc, fy, number_text, content_hash):
    if series and oc:
        return f"{series}-{oc}"
    if series and number_text:
        return f"{series}-{fy or 'NA'}-{number_text}".replace(" ", "")
    return f"DOC-{content_hash[:8]}"


def draft_row(rec: dict) -> dict:
    name = os.path.basename(rec["source_file"])
    flags, notes = [], []
    head = (rec.get("text") or "")[:2500]
    t_oc, t_prod, t_fy, t_ref = oc_from_text(head)
    f_oc, f_series, ambiguous = oc_from_filename(name)

    series, oc = "", ""
    if f_oc:
        series, oc = f_series, f_oc  # the filename wins: header numbers are often OCR noise or a referenced circular
    elif t_oc and t_prod.upper() == "UPI":
        series, oc = "UPI", t_oc
        flags.append("oc_from_text")
    else:
        series = (t_prod or "").upper() if t_prod else ""
        if ambiguous:
            flags.append("administrative_or_ambiguous_filename")
        if not series:
            flags.append("no_reference_found")

    fy = t_fy or H.fy_from_head(head) or H.fy_from_filename(name)
    number_text = (re.sub(r"\D", "", t_oc) or "").zfill(3) if (t_oc and not oc) else ""
    issue_date, conf = H.pick_issue_date(head, fy) if rec.get("readable") else ("", "")
    if not issue_date and rec.get("readable"):
        flags.append("date_missing")
    elif fy and conf != "fy_match" and issue_date:
        flags.append("date_check")

    fn_title = H.title_from_filename(name)
    subject = H.parse_subject(rec.get("text") or "") if rec.get("readable") else ""
    if len(fn_title.split()) >= 4:
        title = fn_title
    elif subject:
        title, _ = subject, flags.append("title_from_text")
    else:
        title = fn_title or "(untitled)"
        flags.append("title_check")

    domain = "UPI" if series in ("UPI", "IMPS_UPI") else ("RUPAY" if series == "RUPAY" else "GENERAL")
    status = "current" if rec.get("readable") else "unreadable"
    if not rec.get("readable"):
        notes.append(rec.get("problem") or "no readable text")
        flags.append("unreadable_source")

    return {
        "doc_id": _doc_id(series, oc, fy, number_text, rec["content_hash"]),
        "oc_number": oc, "series": series or "UNKNOWN", "domain": domain, "reference": t_ref,
        "title": title, "issue_date": issue_date, "effective_date": "", "fy": fy,
        "category": guess_category(f"{name} {title}"), "status": status,
        "supersedes": "", "superseded_by": "", "source_file": rec["source_file"],
        "content_hash": rec["content_hash"], "text_source": rec.get("text_source", ""),
        "page_count": rec.get("page_count", 0), "char_count": rec.get("char_count", 0),
        "review_status": "drafted", "needs_review": ";".join(flags), "notes": "; ".join(notes),
    }


def unique_doc_ids(rows: list) -> None:
    seen = defaultdict(int)
    for r in rows:
        seen[r["doc_id"]] += 1
        if seen[r["doc_id"]] > 1:
            r["doc_id"] = f"{r['doc_id']}-{r['content_hash'][:4]}"
            r["needs_review"] = (r["needs_review"] + ";duplicate_number").strip(";")


def drop_similar_duplicates(rows: list, text_by_hash: dict, skipped: list) -> list:
    """Documents that share a doc_id AND read almost the same (OCR/scan variants of
    one circular) are one document: keep the best-named file, report the rest."""
    from difflib import SequenceMatcher

    groups = defaultdict(list)
    for r in rows:
        groups[r["doc_id"]].append(r)
    drop = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: (-_name_score(r["source_file"]), r["source_file"]))
        keeper = group[0]
        kt = _norm_text_hash_text(text_by_hash.get(keeper["content_hash"], ""))
        for other in group[1:]:
            ot = _norm_text_hash_text(text_by_hash.get(other["content_hash"], ""))
            if kt and ot and SequenceMatcher(None, kt[:20000], ot[:20000]).ratio() >= 0.95:
                drop.add(other["content_hash"])
                skipped.append({"file": other["source_file"], "reason": "duplicate_similar",
                                "kept": keeper["source_file"], "detail": ""})
    return [r for r in rows if r["content_hash"] not in drop]


def _norm_text_hash_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def draft(records: list, existing: list) -> tuple:
    """Merge: keep existing rows (by content_hash); draft new ones. Returns
    (rows, added, orphaned) where orphaned are existing hashes with no PDF now."""
    usable, skipped = split_records(records)
    not_public = [r for r in existing if r["status"] == "not_public"]
    have = {r["content_hash"]: r for r in existing if r["status"] != "not_public"}
    rows, added = [], []
    for rec in usable:
        if rec["content_hash"] in have:
            rows.append(have.pop(rec["content_hash"]))
        else:
            row = draft_row(rec)
            rows.append(row)
            added.append(row)
    orphaned = list(have.values())
    rows.extend(not_public)
    text_by_hash = {r["content_hash"]: r.get("text", "") for r in usable}
    rows = drop_similar_duplicates(rows, text_by_hash, skipped)
    added = [r for r in added if r in rows]
    unique_doc_ids(rows)
    rows.sort(key=_sort_key)
    return rows, added, orphaned, skipped


# ------------------------------------------------------------------ I/O -----
def load(path: str = None) -> list:
    path = path or paths.REGISTRY_PATH
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows: list, path: str = None) -> None:
    path = path or paths.REGISTRY_PATH
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------- validation ----
def validate(rows: list) -> list:
    """Return a list of (severity, doc_id, message); severity is 'error' or 'warn'."""
    issues = []
    ids = defaultdict(int)
    by_key = {(r["series"], r["oc_number"]): r for r in rows if r["oc_number"]}
    for r in rows:
        did = r["doc_id"]
        ids[did] += 1
        if r["status"] not in STATUSES:
            issues.append(("error", did, f"unknown status '{r['status']}'"))
        if r["status"] == "not_public":
            if not (r.get("title") or "").strip():
                issues.append(("error", did, "title is empty"))
            if r.get("source_file") or r.get("content_hash"):
                issues.append(("error", did, "not_public row must not have a source file"))
            continue
        if r["status"] == "unreadable":
            issues.append(("warn", did, f"unreadable source: {r['notes']}"))
            continue
        for col in ("title", "issue_date"):
            if col == "issue_date" and "date_unknown_confirmed" in (r.get("needs_review") or ""):
                continue  # a person checked: the document carries no usable date
            if not (r.get(col) or "").strip():
                issues.append(("error", did, f"{col} is empty"))
        for col in ("supersedes", "superseded_by"):
            for ref in filter(None, (r.get(col) or "").split(";")):
                if (r["series"], ref) not in by_key:
                    issues.append(("error", did, f"{col} '{ref}' not in registry"))
        if r["status"] == "superseded" and not r["superseded_by"]:
            issues.append(("error", did, "status superseded but superseded_by is empty"))
    pdf_keys = {(r["series"], r["oc_number"]) for r in rows if r["oc_number"] and r["status"] != "not_public"}
    for r in rows:
        if r["status"] == "not_public" and (r["series"], r["oc_number"]) in pdf_keys:
            issues.append(("error", r["doc_id"], "a PDF now exists for this OC: remove the not_public row"))
    for did, n in ids.items():
        if n > 1:
            issues.append(("error", did, f"doc_id appears {n} times"))
    return issues
