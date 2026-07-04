"""
Phase 1: Extract text from all NPCI OC PDFs listed in manifest.csv

Reads:  Data/manifest.csv
For each row, opens the PDF at 'local_path', extracts all text,
and writes it to Data/extracted/{oc_number_or_filename}\.json along with
the metadata from the manifest row.

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

# If pypdf extracts fewer than this many characters, we assume it's a
# scanned/image PDF and fall back to OCR.
OCR_FALLBACK_THRESHOLD = 20


def safe_id(oc_number: str, filename: str) -> str:
    """Build a safe file identifier — prefer oc_number, fall back to filename."""
    base = oc_number if oc_number else os.path.splitext(filename)[0]
    base = re.sub(r"[^A-Za-z0-9_\-]", "_", base)
    return base


def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages_text = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages_text.append(text)
    return "\n\n".join(pages_text)


def extract_text_with_ocr(pdf_path: str) -> str:
    """Fallback: render each page as an image and OCR it with Tesseract."""
    if not OCR_AVAILABLE:
        return ""
    images = convert_from_path(pdf_path, dpi=200)
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

    success_count = 0
    failures = []

    for i, row in enumerate(rows, start=1):
        filename = row.get("filename", "")
        local_path = row.get("local_path", "")
        oc_number = row.get("oc_number", "")

        if not os.path.isfile(local_path):
            print(f"[{i}/{len(rows)}] MISSING FILE: {local_path}")
            failures.append(filename)
            continue

        try:
            text = extract_text_from_pdf(local_path)
        except Exception as e:
            print(f"[{i}/{len(rows)}] FAILED to extract {filename}: {e}")
            failures.append(filename)
            continue

        used_ocr = False
        if len(text.strip()) < OCR_FALLBACK_THRESHOLD:
            if OCR_AVAILABLE:
                print(f"[{i}/{len(rows)}] Low/no text found — trying OCR: {filename}")
                try:
                    ocr_text = extract_text_with_ocr(local_path)
                    if len(ocr_text.strip()) > len(text.strip()):
                        text = ocr_text
                        used_ocr = True
                except Exception as e:
                    print(f"[{i}/{len(rows)}] OCR FAILED for {filename}: {e}")
            else:
                print(f"[{i}/{len(rows)}] WARNING: no text extracted and OCR not installed: {filename}")

        out_id = safe_id(oc_number, filename)
        out_path = os.path.join(EXTRACTED_DIR, f"{out_id}.json")

        record = {
            "filename": filename,
            "oc_number": oc_number,
            "title": row.get("title", ""),
            "date": row.get("date", ""),
            "category": row.get("category", ""),
            "supersedes": row.get("supersedes", ""),
            "superseded_by": row.get("superseded_by", ""),
            "text": text,
            "char_count": len(text),
            "used_ocr": used_ocr,
        }

        with open(out_path, "w", encoding="utf-8") as out_f:
            json.dump(record, out_f, indent=2, ensure_ascii=False)

        success_count += 1
        ocr_tag = " [OCR]" if used_ocr else ""
        print(f"[{i}/{len(rows)}] OK: {filename} -> {out_id}.json ({len(text)} chars){ocr_tag}")

    print(f"\nDone. {success_count}/{len(rows)} extracted successfully.")
    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f_name in failures:
            print(f"  - {f_name}")

    print(f"\nExtracted JSON files are in: {EXTRACTED_DIR}/")
    print("Next step: chunking (chunk.py) to prepare data for embedding.")


if __name__ == "__main__":
    main()