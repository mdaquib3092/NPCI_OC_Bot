"""
Generate manifest.csv from a local folder of manually-downloaded NPCI OC PDFs.

Assumes:
- All PDFs sit in one folder: data/raw_pdfs/*.pdf
- Filenames contain the OC number somewhere (e.g. "OC_220.pdf",
  "UPI_OC_No_201_B_FY_2025_26.pdf", "220_UPI_Lite_Limit.pdf")

What it does:
- Scans the folder
- Extracts OC number via regex from the filename
- Extracts a guessed date from the filename if present
- Leaves 'title', 'date', 'category' blank/guessed for you to fill in manually
- Writes data/manifest.csv

Run:
    python generate_manifest.py
"""

import csv
import os
import re

RAW_PDF_DIR = os.path.join("Data", "raw_pdfs", "upi")
MANIFEST_PATH = os.path.join("Data", "manifest.csv")


def extract_oc_number(filename: str) -> str:
    """
    Try several patterns to find an OC number (plus addendum letter suffix,
    e.g. 100A, 208B) in the filename. Handles real NPCI naming conventions:
      OC-151, OC169, OC-No_-220, OC-No_-100B, OC-133A, OC170-A, Circular No.220
    """
    patterns = [
        # OC / OC-No_ / OC No. followed by digits, optional separator + letter suffix
        r"OC[\s_\-]*(?:No\.?[\s_\-]*)?0*(\d{2,4})[\s_\-]?([A-Z])?(?![a-z])",
        r"Circular[\s_\-]?No\.?[\s_\-]?0*(\d{2,4})[\s_\-]?([A-Z])?(?![a-z])",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            number = match.group(1)
            suffix = match.group(2) or ""
            return f"{number}{suffix.upper()}"
    return ""


def extract_date_guess(filename: str) -> str:
    """Try to find a date-like pattern in the filename (FY or explicit date)."""
    # FY pattern e.g. FY_2025_26 or FY2025-26
    fy_match = re.search(r"FY[\s_\-]?(\d{2,4})[_\-](\d{2,4})", filename, re.IGNORECASE)
    if fy_match:
        return f"FY {fy_match.group(1)}-{fy_match.group(2)}"
    # explicit date e.g. 2023, 2019 standalone
    year_match = re.search(r"(20\d{2})", filename)
    if year_match:
        return year_match.group(1)
    return ""


def guess_title_from_filename(filename: str) -> str:
    """Turn 'UPI_OC_No_201_B_FY_2025_26_Addendum_to_...pdf' into a readable guess."""
    name = os.path.splitext(filename)[0]
    name = re.sub(r"[_\-]+", " ", name).strip()
    return name


def guess_category(filename: str) -> str:
    """Detect the product category from the filename so non-UPI circulars
    (e.g. RuPay) don't pollute UPI-specific retrieval."""
    lower = filename.lower()
    if "rupay" in lower:
        return "RuPay"
    if "nfs" in lower:
        return "NFS"
    if "imps" in lower:
        return "IMPS"
    if "billpay" in lower or "bbps" in lower:
        return "BBPS"
    if "pcomp" in lower or "product-compliance" in lower or "self-attestation" in lower:
        return "Compliance"
    return "UPI"


def main():
    if not os.path.isdir(RAW_PDF_DIR):
        print(f"Folder not found: {RAW_PDF_DIR}")
        print("Make sure your PDFs are in data/raw_pdfs/")
        return

    pdf_files = sorted(f for f in os.listdir(RAW_PDF_DIR) if f.lower().endswith(".pdf"))
    print(f"Found {len(pdf_files)} PDF files in {RAW_PDF_DIR}")

    rows = []
    missing_oc = []

    for filename in pdf_files:
        oc_number = extract_oc_number(filename)
        date_guess = extract_date_guess(filename)
        title_guess = guess_title_from_filename(filename)

        if not oc_number:
            missing_oc.append(filename)

        rows.append(
            {
                "filename": filename,
                "oc_number": oc_number,
                "title": title_guess,
                "date": date_guess,
                "category": guess_category(filename),
                "supersedes": "",
                "superseded_by": "",
                "local_path": os.path.join(RAW_PDF_DIR, filename),
            }
        )

    os.makedirs("data", exist_ok=True)
    fieldnames = [
        "filename",
        "oc_number",
        "title",
        "date",
        "category",
        "supersedes",
        "superseded_by",
        "local_path",
    ]
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nManifest written to {MANIFEST_PATH}")
    print(f"Total entries: {len(rows)}")

    if missing_oc:
        print(f"\n{len(missing_oc)} file(s) had no OC number auto-detected — fill these in manually:")
        for f in missing_oc:
            print(f"  - {f}")

    print(
        "\nNext: open data/manifest.csv in Excel/Sheets and fill in/correct "
        "'title' and 'date' where needed. 'supersedes'/'superseded_by' can be "
        "filled in later once we read the actual OC text."
    )


if __name__ == "__main__":
    main()