"""
NPCI UPI Circulars Bulk Downloader (via Wayback Machine)
---------------------------------------------------------
Downloads all archived NPCI UPI circular PDFs (2016-2021 era, old
/PDF/npci/upi/circular/ path) from the Internet Archive's Wayback Machine
into a local folder.

Usage:
    pip install requests
    python download_npci_circulars.py

Output:
    ./npci_upi_circulars/<year>/<filename>.pdf
    ./npci_upi_circulars/download_log.csv
"""

import csv
import os
import re
import time

import requests

# ----------------------------- Config ---------------------------------
URL_PREFIX = "npci.org.in/PDF/npci/upi/circular/*"
OUTPUT_DIR = "npci_upi_circulars"
DELAY_SECONDS = 2          # be polite to archive.org (avoid rate limiting)
MAX_RETRIES = 3
TIMEOUT = 60

CDX_API = "https://web.archive.org/cdx/search/cdx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal research; NPCI circular archive downloader)"
}
# -----------------------------------------------------------------------


def get_all_captures():
    """Fetch every unique captured URL under the prefix using the CDX API."""
    params = {
        "url": URL_PREFIX,
        "output": "json",
        "fl": "original,mimetype,timestamp,statuscode",
        "filter": "statuscode:200",
        "collapse": "urlkey",   # one (latest indexed) row per unique URL
        "limit": "2000",
    }
    print("Fetching capture list from Wayback CDX API...")
    resp = requests.get(CDX_API, params=params, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        print("No captures found. Check the URL prefix.")
        return []
    header, data = rows[0], rows[1:]
    captures = [dict(zip(header, row)) for row in data]
    # Keep only PDF-looking URLs, skip the bare directory listing
    captures = [c for c in captures if c["original"].lower().endswith(".pdf")]
    print(f"Found {len(captures)} unique PDF URLs.")
    return captures


def safe_filename(url):
    """Extract and sanitize a filename (and year subfolder) from the URL."""
    # year folder e.g. .../circular/2016/Circular02-....pdf
    m = re.search(r"/circular/(\d{4})/", url)
    year = m.group(1) if m else "unknown_year"
    name = url.rsplit("/", 1)[-1]
    name = requests.utils.unquote(name)
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return year, name


def is_valid_pdf(first_bytes):
    return first_bytes[:4] == b"%PDF"


def download_capture(capture):
    """Download one capture using the id_ (raw content) endpoint."""
    original = capture["original"]
    ts = capture["timestamp"]
    year, fname = safe_filename(original)

    folder = os.path.join(OUTPUT_DIR, year)
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, fname)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
        return "skipped (already downloaded)", out_path

    wayback_url = f"https://web.archive.org/web/{ts}id_/{original}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(wayback_url, headers=HEADERS, timeout=TIMEOUT, stream=True)
            if r.status_code == 200:
                content = r.content
                if is_valid_pdf(content):
                    with open(out_path, "wb") as f:
                        f.write(content)
                    return "ok", out_path
                else:
                    # Not a real PDF (probably an HTML 404 capture) -> try
                    # without the exact timestamp (closest snapshot)
                    alt_url = f"https://web.archive.org/web/2025id_/{original}"
                    r2 = requests.get(alt_url, headers=HEADERS, timeout=TIMEOUT)
                    if r2.status_code == 200 and is_valid_pdf(r2.content):
                        with open(out_path, "wb") as f:
                            f.write(r2.content)
                        return "ok (alt snapshot)", out_path
                    return "failed (capture is not a PDF - likely HTML/404 capture)", ""
            elif r.status_code in (429, 503):
                wait = 15 * attempt
                print(f"    Rate limited (HTTP {r.status_code}); waiting {wait}s...")
                time.sleep(wait)
            else:
                return f"failed (HTTP {r.status_code})", ""
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                return f"failed ({e})", ""
            time.sleep(5 * attempt)
    return "failed (max retries)", ""


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    captures = get_all_captures()
    if not captures:
        return

    log_path = os.path.join(OUTPUT_DIR, "download_log.csv")
    ok, failed, skipped = 0, 0, 0

    with open(log_path, "w", newline="", encoding="utf-8") as logf:
        writer = csv.writer(logf)
        writer.writerow(["original_url", "timestamp", "mimetype", "status", "saved_path"])

        for i, cap in enumerate(captures, 1):
            print(f"[{i}/{len(captures)}] {cap['original'].rsplit('/', 1)[-1][:70]}")
            status, path = download_capture(cap)
            writer.writerow([cap["original"], cap["timestamp"], cap["mimetype"], status, path])
            print(f"    -> {status}")

            if status.startswith("ok"):
                ok += 1
            elif status.startswith("skipped"):
                skipped += 1
            else:
                failed += 1

            time.sleep(DELAY_SECONDS)

    print("\n================ SUMMARY ================")
    print(f"Downloaded : {ok}")
    print(f"Skipped    : {skipped} (already present)")
    print(f"Failed     : {failed} (see {log_path})")
    print(f"Files saved under: ./{OUTPUT_DIR}/<year>/")
    print("Failed items are usually URLs where Wayback only captured an HTML")
    print("error page instead of the real PDF - source those from Scribd /")
    print("TeamLease RegTech, or check other snapshot dates manually.")


if __name__ == "__main__":
    main()