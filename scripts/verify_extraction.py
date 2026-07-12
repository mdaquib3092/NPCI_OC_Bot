"""
Verify extracted JSON content matches the original PDF content, and
specifically check that Annexure sections are not missing or truncated.

For every file in Data/extracted/*.json:
  1. Re-derive the "best available" text straight from the source PDF
     (native extraction, or cached OCR text if native is too thin).
  2. Compare it against what's stored in the JSON using a similarity
     ratio (difflib) on normalized text - flags drift/corruption.
  3. Specifically look for the word "annexure" (or "annex"/"schedule")
     in the PDF-derived text. If found there but missing/much shorter
     in the JSON's text, flag it - this is exactly the OC-120 bug
     pattern (annexure table content lost during OCR/extraction).

Usage:
    python verify_extraction.py

Output:
    Data/verification_report.csv   - one row per document, with flags
    Console summary of documents needing attention
"""

import csv
import difflib
import glob
import json
import os
import re

import fitz  # pymupdf

PDF_ROOT = os.path.join("Data", "raw_pdfs", "upi")
OCR_CACHE_DIR = os.path.join("Data", "ocr_text")
EXTRACTED_DIR = os.path.join("Data", "extracted")
REPORT_PATH = os.path.join("Data", "verification_report.csv")

OCR_FALLBACK_THRESHOLD = 100
SIMILARITY_WARN_THRESHOLD = 0.90     # below this -> flag content mismatch
ANNEXURE_MARKERS = ["annexure", "annex ", "annex-", "schedule "]


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


def best_source_text(pdf_path: str) -> str:
    """The ground-truth text we can currently get from the PDF, without
    running fresh OCR (fast check). Prefers whichever is longer."""
    native = get_native_text(pdf_path)
    cached = get_cached_ocr_text(pdf_path)
    return native if len(native) >= len(cached) else cached


def find_annexure_section(text: str) -> str:
    """Return the text from the first 'annexure'-like marker to the end."""
    low = text.lower()
    best_idx = -1
    for marker in ANNEXURE_MARKERS:
        idx = low.find(marker)
        if idx != -1 and (best_idx == -1 or idx < best_idx):
            best_idx = idx
    return text[best_idx:] if best_idx != -1 else ""


def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # difflib on very long strings is slow - compare on a capped sample
    cap = 20000
    return difflib.SequenceMatcher(None, a[:cap], b[:cap]).ratio()


def main():
    json_files = sorted(glob.glob(os.path.join(EXTRACTED_DIR, "*.json")))
    print(f"Verifying {len(json_files)} extracted documents...\n")

    rows = []
    flagged = []

    for i, jpath in enumerate(json_files, 1):
        d = json.load(open(jpath, encoding="utf-8"))
        filename = d.get("filename", "")
        oc_number = d.get("oc_number", "")
        json_text = d.get("text", "")

        pdf_path = os.path.join(PDF_ROOT, filename)
        if not os.path.isfile(pdf_path):
            rows.append({
                "json_file": os.path.basename(jpath),
                "oc_number": oc_number,
                "filename": filename,
                "similarity": "",
                "annexure_in_pdf": "",
                "annexure_in_json": "",
                "annexure_pdf_chars": "",
                "annexure_json_chars": "",
                "flag": "PDF_NOT_FOUND",
            })
            flagged.append(jpath)
            continue

        source_text = best_source_text(pdf_path)
        sim = similarity(source_text, json_text)

        pdf_annexure = find_annexure_section(source_text)
        json_annexure = find_annexure_section(json_text)

        annexure_in_pdf = len(pdf_annexure.strip()) > 20
        annexure_in_json = len(json_annexure.strip()) > 20

        flag = "OK"
        if sim < SIMILARITY_WARN_THRESHOLD:
            flag = f"CONTENT_MISMATCH (sim={sim:.2f})"
        if annexure_in_pdf and not annexure_in_json:
            flag = "ANNEXURE_MISSING_IN_JSON"
        elif annexure_in_pdf and annexure_in_json:
            # annexure present in both - check it isn't badly truncated
            ratio = len(json_annexure) / max(len(pdf_annexure), 1)
            if ratio < 0.5:
                flag = f"ANNEXURE_TRUNCATED (json has {ratio:.0%} of pdf annexure length)"

        if flag != "OK":
            flagged.append(jpath)

        rows.append({
            "json_file": os.path.basename(jpath),
            "oc_number": oc_number,
            "filename": filename,
            "similarity": f"{sim:.3f}",
            "annexure_in_pdf": annexure_in_pdf,
            "annexure_in_json": annexure_in_json,
            "annexure_pdf_chars": len(pdf_annexure),
            "annexure_json_chars": len(json_annexure),
            "flag": flag,
        })

        if i % 25 == 0:
            print(f"  ...{i}/{len(json_files)}")

    with open(REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\n================ SUMMARY ================")
    print(f"Total documents checked : {len(rows)}")
    print(f"Flagged for review      : {len(flagged)}")
    print(f"Report written to       : {REPORT_PATH}\n")

    if flagged:
        print("Documents needing attention:")
        for jpath in flagged:
            r = next(r for r in rows if r["json_file"] == os.path.basename(jpath))
            print(f"  - {r['json_file']:50s} [{r['flag']}]")


if __name__ == "__main__":
    main()