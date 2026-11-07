"""
Retry failed NPCI circular downloads by trying EVERY Wayback snapshot.
Reads download_log.csv, picks failed rows, queries CDX for all capture
timestamps of each URL, and tries each one until a valid PDF is found.

Usage:
    python retry_failed_circulars.py
(run from the same folder where npci_upi_circulars/ exists)
"""

import csv
import os
import re
import time

import requests

OUTPUT_DIR = "npci_upi_circulars"
LOG_FILE = os.path.join(OUTPUT_DIR, "download_log.csv")
RETRY_LOG = os.path.join(OUTPUT_DIR, "retry_log.csv")
DELAY = 3
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (personal research; NPCI archive retry)"}
CDX_API = "https://web.archive.org/cdx/search/cdx"


def all_timestamps(url):
    """Get every capture timestamp for a URL (no collapse)."""
    params = {"url": url, "output": "json", "fl": "timestamp,statuscode,mimetype"}
    try:
        r = requests.get(CDX_API, params=params, headers=HEADERS, timeout=TIMEOUT)
        rows = r.json()
        if len(rows) < 2:
            return []
        # Prefer snapshots whose recorded mimetype is application/pdf,
        # then everything else as fallback.
        caps = rows[1:]
        pdf_first = [c[0] for c in caps if c[2] == "application/pdf"]
        others = [c[0] for c in caps if c[2] != "application/pdf"]
        return pdf_first + others
    except Exception:
        return []


def safe_filename(url):
    m = re.search(r"/circular/(\d{4})/", url)
    year = m.group(1) if m else "unknown_year"
    name = requests.utils.unquote(url.rsplit("/", 1)[-1])
    name = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return year, name


def try_download(url):
    year, fname = safe_filename(url)
    folder = os.path.join(OUTPUT_DIR, year)
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, fname)

    if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
        return "already downloaded", out_path

    for ts in all_timestamps(url):
        wb = f"https://web.archive.org/web/{ts}id_/{url}"
        try:
            r = requests.get(wb, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return f"recovered (snapshot {ts})", out_path
        except requests.RequestException:
            time.sleep(5)
        time.sleep(DELAY)
    return "unrecoverable - no PDF snapshot exists", ""


def main():
    if not os.path.exists(LOG_FILE):
        print(f"{LOG_FILE} not found. Run this from the folder containing it.")
        return

    with open(LOG_FILE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    failed = [r for r in rows if r["status"].startswith("failed")]
    print(f"Retrying {len(failed)} failed URLs (trying ALL snapshots each)...\n")

    recovered, dead = 0, 0
    with open(RETRY_LOG, "w", newline="", encoding="utf-8") as lf:
        w = csv.writer(lf)
        w.writerow(["original_url", "result", "saved_path"])
        for i, row in enumerate(failed, 1):
            url = row["original_url"]
            print(f"[{i}/{len(failed)}] {url.rsplit('/', 1)[-1][:70]}")
            result, path = try_download(url)
            print(f"    -> {result}")
            w.writerow([url, result, path])
            if result.startswith(("recovered", "already")):
                recovered += 1
            else:
                dead += 1

    print("\n============= RETRY SUMMARY =============")
    print(f"Recovered     : {recovered}")
    print(f"Unrecoverable : {dead}  (see {RETRY_LOG})")
    print("Unrecoverable files ka Wayback par PDF exist hi nahi karta -")
    print("inke liye alternate sources (new NPCI site / Scribd / TeamLease) use karo.")


if __name__ == "__main__":
    main()