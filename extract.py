"""
Phase 1: Extract text from all NPCI OC PDFs listed in manifest.csv

Reads:  Data/manifest.csv  (as produced by generate_manifest.py)
For each row, resolves the PDF path, extracts text (using cached OCR
output from Data/ocr_text/ if available, or running OCR fresh as a
last resort), and writes it to Data/extracted/{oc_number_or_filename}.json
along with the metadata from the manifest row.

Run:
    python extract.py
"""

import csv
import json
import os
import re

from pypdf import PdfReader

try:
    import pytesseract
    from pdf2image import convert_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

MANIFEST_PATH = os.path.join("Data", "manifest.csv")
EXTRACTED_DIR = os.path.join("Data", "extracted")

# Root folder the manifest's "file" paths are relative to. This must match
# whatever folder you passed to generate_manifest.py, e.g.:
#   python generate_manifest.py "Data/raw_pdfs/upi"
PDF_ROOT = os.path.join("Data", "raw_pdfs", "upi")

# Folder with pre-computed OCR text from scripts/ocr_pdf.py (avoids re-running OCR).
OCR_CACHE_DIR = os.path.join("Data", "ocr_text")

# If native pypdf extraction yields fewer than this many characters, we
# assume it's a scanned/image PDF and fall back to OCR (cache first).
OCR_FALLBACK_THRESHOLD = 100


def safe_id(oc_number: str, filename: str) -> str:
    """Build a safe file identifier — prefer oc_number, fall back to filename."""
    base = oc_number if oc_number else os.path.splitext(filename)[0]
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)
    return base


def get_field(row, *candidates, default=""):
    """Return the first present, non-empty column among several possible names.

    Different versions of generate_manifest.py have used different column
    names (e.g. 'file' vs 'filename', 'issue_date' vs 'date'). This makes
    extract.py tolerant of either schema.
    """
    for c in candidates:
        val = row.get(c)
        if val:
            return val
    return default


def resolve_pdf_path(row):
    """Figure out the actual PDF path on disk for this manifest row."""
    # Some manifest versions may already store a full/relative local_path.
    explicit = get_field(row, "local_path", "path")
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        candidate = os.path.join(PDF_ROOT, explicit)
        if os.path.isfile(candidate):
            return candidate

    # Standard case: manifest's "file" column is relative to PDF_ROOT.
    rel = get_field(row, "file", "filename")
    if rel:
        candidate = os.path.join(PDF_ROOT, rel)
        if os.path.isfile(candidate):
            return candidate

    return ""  # not found


def extract_text_native(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return "\n\n".join(pages_text)


def get_cached_ocr_text(pdf_path: str) -> str:
    """Look for pre-computed OCR output (from scripts/ocr_pdf.py) for this PDF."""
    fname = os.path.basename(pdf_path)
    cache_path = os.path.join(OCR_CACHE_DIR, fname + ".txt")
    if os.path.isfile(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return f.read()
    return ""


def extract_text_with_fresh_ocr(pdf_path: str) -> str:
    """Last-resort fallback: render each page as an image and OCR it."""
    if not OCR_AVAILABLE:
        return ""
    images = convert_from_path(pdf_path, dpi=300)
    pages_text = []
    for img in images:
        text = pytesseract.image_to_string(img)
        pages_text.append(text)
    return "\n\n".join(pages_text)


def main():
    if not os.path.isfile(MANIFEST_PATH):
        print(f"Manifest not found at {MANIFEST_PATH}. Run generate_manifest.py first.")
        return

    os.makedirs(EXTRACTED_DIR, exist_ok=True)

    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Found {len(rows)} entries in manifest.")
    print(f"PDF root       : {PDF_ROOT}")
    print(f"OCR cache dir  : {OCR_CACHE_DIR} "
          f"({'found' if os.path.isdir(OCR_CACHE_DIR) else 'NOT FOUND'})\n")

    success_count = 0
    used_ocr_cache_count = 0
    used_fresh_ocr_count = 0
    failures = []

    for i, row in enumerate(rows, start=1):
        filename = get_field(row, "file", "filename")
        oc_number = get_field(row, "oc_number")
        local_path = resolve_pdf_path(row)

        if not local_path:
            print(f"[{i}/{len(rows)}] MISSING FILE: {filename}")
            failures.append(filename)
            continue

        # 1) Try native extraction first (fast, works for ~70 files already).
        try:
            text = extract_text_native(local_path)
        except Exception as e:
            print(f"[{i}/{len(rows)}] Native extraction error for {filename}: {e}")
            text = ""

        source = "native"

        # 2) If native extraction is too thin, use cached OCR text if we have it.
        if len(text.strip()) < OCR_FALLBACK_THRESHOLD:
            cached = get_cached_ocr_text(local_path)
            if len(cached.strip()) >= OCR_FALLBACK_THRESHOLD:
                text = cached
                source = "ocr_cache"
                used_ocr_cache_count += 1
            else:
                # 3) Last resort: run OCR fresh (slow - should rarely trigger
                #    if you already ran scripts/ocr_pdf.py over the same folder).
                if OCR_AVAILABLE:
                    print(f"[{i}/{len(rows)}] No cached OCR - running fresh OCR: {filename}")
                    try:
                        fresh = extract_text_with_fresh_ocr(local_path)
                        if len(fresh.strip()) > len(text.strip()):
                            text = fresh
                            source = "ocr_fresh"
                            used_fresh_ocr_count += 1
                    except Exception as e:
                        print(f"[{i}/{len(rows)}] Fresh OCR FAILED for {filename}: {e}")
                else:
                    print(f"[{i}/{len(rows)}] WARNING: no text and OCR unavailable: {filename}")

        out_id = safe_id(oc_number, filename)
        out_path = os.path.join(EXTRACTED_DIR, f"{out_id}.json")

        record = {
            "filename": filename,
            "oc_number": oc_number,
            "title": get_field(row, "title"),
            "date": get_field(row, "issue_date", "date"),
            "fy": get_field(row, "fy"),
            "category": get_field(row, "category"),
            "status": get_field(row, "status", default="active"),
            "supersedes": get_field(row, "supersedes"),
            "superseded_by": get_field(row, "superseded_by"),
            "text": text,
            "char_count": len(text),
            "text_source": source,   # native | ocr_cache | ocr_fresh
        }

        with open(out_path, "w", encoding="utf-8") as out_f:
            json.dump(record, out_f, indent=2, ensure_ascii=False)

        success_count += 1
        tag = {"native": "", "ocr_cache": " [OCR-cache]", "ocr_fresh": " [OCR-fresh]"}[source]
        print(f"[{i}/{len(rows)}] OK: {filename} -> {out_id}.json ({len(text)} chars){tag}")

    print(f"\nDone. {success_count}/{len(rows)} extracted successfully.")
    print(f"  Used cached OCR text : {used_ocr_cache_count}")
    print(f"  Ran fresh OCR        : {used_fresh_ocr_count}")

    if failures:
        print(f"\n{len(failures)} failure(s) (file not found on disk):")
        for f_name in failures:
            print(f"  - {f_name}")

    print(f"\nExtracted JSON files are in: {EXTRACTED_DIR}/")
    print("Next step: chunking (chunk.py) to prepare data for embedding.")


if __name__ == "__main__":
    main()