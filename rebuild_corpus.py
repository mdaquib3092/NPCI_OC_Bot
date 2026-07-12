"""
Full-proof, one-command corpus rebuild.

What it does, in order, automatically:
  1. Scans Data/raw_pdfs/upi for all PDFs.
  2. Hashes each PDF's extracted text content to detect TRUE duplicates
     (same circular saved under two different filenames). Keeps the
     cleanest-named copy, moves the rest to Data/_duplicates_removed/.
  3. Extracts a correct OC number from each remaining filename - always
     including any letter suffix (A/B/C...), so "76A" never collapses
     to "76".
  4. Extracts text for each PDF: native pypdf first, then cached OCR
     text from Data/ocr_text/ if native text is too short, then fresh
     OCR as a last resort.
  5. NEVER silently overwrites one JSON with another document's content.
     If two different PDFs would produce the same output ID, it
     disambiguates automatically (appends a short hash) AND writes a
     collision report so you can see it happened - no manual checking
     needed, but nothing is silently lost either.
  6. Writes Data/manifest.csv and Data/extracted/*.json fresh.

Usage:
    python rebuild_corpus.py

Safe to re-run any time - it always rebuilds from the current state of
Data/raw_pdfs/upi/.
"""

import csv
import difflib
import hashlib
import json
import os
import re
import shutil
from collections import defaultdict

import fitz  # pymupdf
from pypdf import PdfReader

try:
    import pytesseract
    from pdf2image import convert_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# ---------------------------------------------------------------- config --
PDF_ROOT = os.path.join("Data", "raw_pdfs", "upi")
OCR_CACHE_DIR = os.path.join("Data", "ocr_text")
DUP_BACKUP_DIR = os.path.join("Data", "_duplicates_removed")
EXTRACTED_DIR = os.path.join("Data", "extracted")
MANIFEST_PATH = os.path.join("Data", "manifest.csv")
COLLISION_REPORT_PATH = os.path.join("Data", "id_collision_report.csv")
DUP_REPORT_PATH = os.path.join("Data", "duplicate_report.csv")

OCR_FALLBACK_THRESHOLD = 100  # chars

FY_PATTERN = re.compile(r"(20\d{2})[\s\-_]?(\d{2})")
CATEGORY_KEYWORDS = {
    "limits": ["limit", "lakh", "p2pm", "standardization", "standardisation"],
    "disputes": ["chargeback", "dispute", "udir", "complaint", "refund",
                 "reversal", "tat", "arbitration", "good-faith", "good faith"],
    "product": ["lite", "123pay", "autopay", "auto-pay", "mandate", "circle",
                "credit", "cbdc", "voucher", "tap-and-pay", "tap and pay",
                "iccw", "global", "international", "remittance", "hello-upi",
                "plug-in", "voice", "numeric"],
    "merchant": ["merchant", "onboarding", "acquir", "mcc", "qr", "sdk",
                 "checkout", "b2b"],
    "compliance": ["compliance", "penalty", "attestation", "adherence",
                   "guidelines", "mandatory", "non-compliance"],
    "technical": ["api", "raw", "settlement", "reconciliation", "switch",
                  "response", "txnid", "tran-id", "rrn", "purpose-code",
                  "deemed", "decline", "timeout", "check-txn", "cl-version"],
}


# ----------------------------------------------------------- OC number ---
ADMIN_REFERENCE_KEYWORDS = [
    "compliance to circular", "compliance to oc", "reminder on",
    "reminder of", "reiteration of compliance", "reiteration of",
    "adherence to", "self-attestation", "self attestation",
    "initiation of self-attestation", "product-compliance",
    "product compliance", "certification fee",
]


def extract_oc_number(filename: str) -> tuple:
    """Extract OC/circular number INCLUDING any letter suffix.
    '76A' stays '76A', never collapses to '76'. A letter suffix is only
    accepted if NOT immediately followed by another lowercase letter
    (this prevents grabbing the 'A' from a following word like 'Aadhaar').

    Filenames that are ADMINISTRATIVE NOTICES ABOUT another circular
    (e.g. "Compliance to Circular 15B and 32", "Reminder on OC 145")
    are not themselves that circular - they reference it. These are
    flagged for review with a blank oc_number rather than misassigned
    to the referenced number.

    NPCI's "Operation Circular" phrasing is a SEPARATE joint IMPS+UPI
    numbering series that overlaps with the plain UPI "OC" series -
    e.g. "Operation-Circular-99" (IMPS+UPI) and "OC-99"/"Circular-99"
    (UPI-only) are two different documents that happen to share the
    number 99. These get an "_IMPS" suffix so they never collide, and
    this rule is permanent (survives re-running the script fresh).

    If the filename mentions more than one distinct OC/circular number,
    it's also ambiguous - return ("", True) instead of guessing.

    Returns: (oc_number, needs_review: bool)
    """
    lname = filename.lower()
    if any(kw in lname for kw in ADMIN_REFERENCE_KEYWORDS):
        return "", True

    is_operation_circular = bool(
        re.search(r"operation[\s\-_.]*circular", lname)
    )

    patterns = [
        r"OC[\s\-_.]*No[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])",
        r"OC[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])(?!\d)",
        r"Circular[\s\-_.]*No[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])",
        r"Circular[\s\-_.]*(\d+)[\s\-_.]*([A-E])?(?![a-z])(?!\d)",
    ]
    found = []  # list of (number_str, start_position)
    for pat in patterns:
        for m in re.finditer(pat, filename, re.IGNORECASE):
            num = m.group(1)
            letter = (m.group(2) or "").upper()
            found.append((f"{num}{letter}", m.start()))

    distinct_numbers = {n for n, _pos in found}
    if not distinct_numbers:
        return "", False

    if len(distinct_numbers) == 1:
        number = distinct_numbers.pop()
    else:
        # Multiple distinct matches - check if they share the SAME base
        # circular (e.g. "125A" and "125" both have base "125"). If so,
        # this is a self-referencing addendum ("OC-125A - Addendum to
        # OC-125"), not genuine ambiguity - pick whichever appears
        # EARLIEST in the filename (the document's own number; a parent
        # reference typically comes later, after "Addendum to").
        def base_digits(n):
            return re.match(r"(\d+)", n).group(1)

        bases = {base_digits(n) for n in distinct_numbers}
        if len(bases) == 1:
            found.sort(key=lambda pair: pair[1])
            number = found[0][0]
        else:
            return "", True  # genuinely different circulars - ambiguous

    if is_operation_circular:
        number = f"{number}_IMPS"
    return number, False


def extract_fy(filename: str) -> str:
    m = FY_PATTERN.search(filename)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def guess_category(filename: str) -> str:
    lname = filename.lower()
    scores = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        s = sum(1 for kw in kws if kw in lname)
        if s:
            scores[cat] = s
    return max(scores, key=scores.get) if scores else "uncategorised"


# ----------------------------------------------------------- dedup step --
def normalize_text_for_hash(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def get_native_text(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        text = "".join(page.get_text() for page in doc)
        doc.close()
        return text
    except Exception:
        return ""


def get_cached_ocr_text(pdf_path: str) -> str:
    fname = os.path.basename(pdf_path)
    cache_path = os.path.join(OCR_CACHE_DIR, fname + ".txt")
    if os.path.isfile(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return f.read()
    return ""


def get_best_available_text(pdf_path: str) -> str:
    """Best text we can get WITHOUT running fresh OCR (for fast hashing)."""
    native = get_native_text(pdf_path)
    if len(native.strip()) >= OCR_FALLBACK_THRESHOLD:
        return native
    cached = get_cached_ocr_text(pdf_path)
    if len(cached.strip()) >= OCR_FALLBACK_THRESHOLD:
        return cached
    return native  # whatever little we have


def score_filename(fn: str) -> int:
    score = 0
    if re.search(r"OC[\s\-]?No[\s\-]?\d+", fn, re.I):
        score += 3
    if re.search(r"FY[\s\-_]?20\d{2}", fn, re.I):
        score += 2
    score -= fn.count("_")
    score -= fn.count("--")
    score += len(fn)
    return score


def dedupe_pdfs(all_pdfs):
    """Group PDFs by content hash, keep the best-named copy of each,
    move the rest to a backup folder. Returns the list of kept PDFs."""
    os.makedirs(DUP_BACKUP_DIR, exist_ok=True)
    by_hash = defaultdict(list)
    no_text = []

    print("Hashing PDFs for duplicate detection...")
    for i, path in enumerate(all_pdfs, 1):
        text = get_best_available_text(path)
        norm = normalize_text_for_hash(text)
        if len(norm) < 50:
            no_text.append(path)
            continue
        h = hashlib.md5(norm.encode()).hexdigest()
        by_hash[h].append(path)
        if i % 50 == 0:
            print(f"  ...{i}/{len(all_pdfs)}")

    dup_groups = {h: paths for h, paths in by_hash.items() if len(paths) > 1}
    kept = []
    moved = 0

    with open(DUP_REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_hash", "action", "file"])
        for h, paths in by_hash.items():
            ranked = sorted(paths, key=score_filename, reverse=True)
            keeper = ranked[0]
            kept.append(keeper)
            w.writerow([h, "KEEP", keeper])
            for p in ranked[1:]:
                w.writerow([h, "MOVED (duplicate)", p])
                dest = os.path.join(DUP_BACKUP_DIR, os.path.basename(p))
                if os.path.isfile(p):
                    shutil.move(p, dest)
                    moved += 1

    # files with no usable text yet still get carried forward (OCR fallback
    # will be tried again during extraction) - can't judge duplicates for them
    kept.extend(no_text)

    print(f"\nDuplicate groups found : {len(dup_groups)}")
    print(f"Files moved to backup  : {moved}  (in {DUP_BACKUP_DIR}/)")
    print(f"Files with no text yet : {len(no_text)} (kept, will try OCR at extraction)")
    print(f"Duplicate report       : {DUP_REPORT_PATH}\n")

    return kept


# --------------------------------------------------------- manifest step -
def build_manifest(kept_pdfs):
    rows = []
    ambiguous = []
    for path in kept_pdfs:
        rel = os.path.relpath(path, PDF_ROOT)
        fn = os.path.basename(path)
        oc_number, needs_review = extract_oc_number(fn)
        if needs_review:
            ambiguous.append(fn)
        rows.append({
            "file": rel,
            "oc_number": oc_number,
            "fy": extract_fy(fn),
            "category": guess_category(fn),
            "size_kb": round(os.path.getsize(path) / 1024, 1),
            "status": "active",
            "superseded_by": "",
            "needs_review": "AMBIGUOUS_OC_NUMBER" if needs_review else "",
            "notes": "",
        })

    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"Manifest written: {MANIFEST_PATH} ({len(rows)} entries)")
    if ambiguous:
        print(f"  {len(ambiguous)} file(s) have ambiguous OC numbers "
              f"(multiple circular numbers mentioned) - flagged in manifest,"
              f" oc_number left blank, filename used as identity instead:")
        for fn in ambiguous:
            print(f"    - {fn}")
    print()
    return rows


# ------------------------------------------------------- extraction step -
def is_valid_pdf(pdf_path: str) -> bool:
    """Quick check that this is actually a PDF, not an HTML error page
    or other junk saved with a .pdf extension."""
    try:
        with open(pdf_path, "rb") as f:
            header = f.read(5)
        return header[:4] == b"%PDF"
    except Exception:
        return False


def extract_text_fresh_ocr(pdf_path: str) -> str:
    if not OCR_AVAILABLE:
        return ""
    if not is_valid_pdf(pdf_path):
        return ""  # not a real PDF - nothing to OCR
    try:
        images = convert_from_path(pdf_path, dpi=300)
        return "\n\n".join(pytesseract.image_to_string(img) for img in images)
    except Exception as e:
        print(f"    OCR error on {os.path.basename(pdf_path)}: {e}")
        return ""


def safe_out_id(oc_number: str, filename: str) -> str:
    base = oc_number if oc_number else os.path.splitext(filename)[0]
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)
    return base


def run_extraction(rows):
    os.makedirs(EXTRACTED_DIR, exist_ok=True)
    # Clear old extracted JSONs so stale files can't linger.
    for old in os.listdir(EXTRACTED_DIR):
        if old.endswith(".json"):
            os.remove(os.path.join(EXTRACTED_DIR, old))

    assigned_ids = {}         # out_id -> filename that claimed it
    assigned_texts = {}       # out_id -> normalized text (for fuzzy comparison)
    seen_content_hashes = {}  # exact-match content_hash -> (out_id, filename)
    collisions = []
    true_duplicates_skipped = []
    success, used_cache, used_fresh, failures = 0, 0, 0, []

    for i, row in enumerate(rows, 1):
        filename = row["file"]
        oc_number = row["oc_number"]
        pdf_path = os.path.join(PDF_ROOT, filename)

        if not os.path.isfile(pdf_path):
            failures.append((filename, "file not found"))
            continue

        try:
            text = get_native_text(pdf_path)
        except Exception as e:
            print(f"  [{i}] native extraction failed for {filename}: {e}")
            text = ""
        source = "native"

        if len(text.strip()) < OCR_FALLBACK_THRESHOLD:
            try:
                cached = get_cached_ocr_text(pdf_path)
            except Exception:
                cached = ""
            if len(cached.strip()) >= OCR_FALLBACK_THRESHOLD:
                text, source = cached, "ocr_cache"
                used_cache += 1
            elif OCR_AVAILABLE:
                fresh = extract_text_fresh_ocr(pdf_path)  # already try/except-safe
                if len(fresh.strip()) > len(text.strip()):
                    text, source = fresh, "ocr_fresh"
                    used_fresh += 1

        if not text.strip() and not is_valid_pdf(pdf_path):
            failures.append((filename, "not a valid PDF (likely HTML error page)"))
            continue

        # --- true-duplicate guard: same final content, different filename ---
        content_hash = hashlib.md5(normalize_text_for_hash(text).encode()).hexdigest()
        if len(text.strip()) >= 200 and content_hash in seen_content_hashes:
            existing_id, existing_file = seen_content_hashes[content_hash]
            true_duplicates_skipped.append((filename, existing_file, existing_id, "exact_hash_match"))
            continue  # don't write a second JSON for the same content

        out_id = safe_out_id(oc_number, filename)

        # --- collision guard: never silently overwrite ---
        if out_id in assigned_ids and assigned_ids[out_id] != filename:
            # Check fuzzy similarity against the text already holding this ID.
            existing_text = assigned_texts.get(out_id, "")
            norm_new = normalize_text_for_hash(text)
            norm_existing = normalize_text_for_hash(existing_text)
            cap = 20000
            sim = difflib.SequenceMatcher(
                None, norm_existing[:cap], norm_new[:cap]
            ).ratio() if norm_existing and norm_new else 0.0

            if sim >= 0.95:
                # Same document in substance (minor OCR/scan variation) -
                # treat as a true duplicate, don't create a second file.
                true_duplicates_skipped.append(
                    (filename, assigned_ids[out_id], out_id, f"sim={sim:.2f}")
                )
                continue
            else:
                collisions.append((out_id, assigned_ids[out_id], filename))
                hash_suffix = content_hash[:6]
                out_id = f"{out_id}__{hash_suffix}"

        assigned_ids[out_id] = filename
        assigned_texts[out_id] = text
        seen_content_hashes[content_hash] = (out_id, filename)

        record = {
            "filename": filename,
            "oc_number": oc_number,
            "fy": row.get("fy", ""),
            "category": row.get("category", ""),
            "status": row.get("status", "active"),
            "superseded_by": row.get("superseded_by", ""),
            "text": text,
            "char_count": len(text),
            "text_source": source,
        }

        out_path = os.path.join(EXTRACTED_DIR, f"{out_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        success += 1

        if i % 25 == 0:
            print(f"  ...{i}/{len(rows)} extracted")

    if collisions:
        with open(COLLISION_REPORT_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["intended_id", "first_file", "second_file"])
            w.writerows(collisions)

    if true_duplicates_skipped:
        dup_path = os.path.join("Data", "true_duplicates_skipped.csv")
        with open(dup_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["skipped_file", "kept_as_file", "kept_as_id", "reason"])
            w.writerows(true_duplicates_skipped)

    print(f"\n================ EXTRACTION SUMMARY ================")
    print(f"Extracted successfully : {success}/{len(rows)}")
    print(f"  used cached OCR      : {used_cache}")
    print(f"  ran fresh OCR        : {used_fresh}")
    print(f"True duplicates skipped: {len(true_duplicates_skipped)}"
          f"{'  -> see Data/true_duplicates_skipped.csv' if true_duplicates_skipped else ''}")
    print(f"Failures               : {len(failures)}")
    print(f"ID collisions detected : {len(collisions)}"
          f"{'  -> see ' + COLLISION_REPORT_PATH if collisions else ''}")
    print(f"Extracted JSONs in     : {EXTRACTED_DIR}/")

    if failures:
        print("\nFailed files (skipped, not crashed):")
        for fname, reason in failures:
            print(f"  - {fname}  [{reason}]")


def main():
    print("=" * 60)
    print("FULL CORPUS REBUILD - dedupe -> manifest -> extract")
    print("=" * 60 + "\n")

    if not os.path.isdir(PDF_ROOT):
        print(f"ERROR: PDF_ROOT not found: {PDF_ROOT}")
        return

    all_pdfs = [os.path.join(dp, f) for dp, _, fs in os.walk(PDF_ROOT)
                for f in fs if f.lower().endswith(".pdf")]
    print(f"Found {len(all_pdfs)} PDFs in {PDF_ROOT}\n")

    kept_pdfs = dedupe_pdfs(all_pdfs)
    rows = build_manifest(kept_pdfs)
    run_extraction(rows)

    print("\nDone. Corpus rebuilt cleanly.")
    print("Next: re-run your chunking/embedding pipeline, then eval_retrieval.py.")


if __name__ == "__main__":
    main()