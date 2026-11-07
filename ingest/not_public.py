"""Add circulars that NPCI lists but does not publish (member-only) to the registry.

    python -m ingest.not_public <file.csv>

CSV columns: oc_number, title, fy   (title and fy may be empty)
Example:
    oc_number,title,fy
    233,Introduction of Limit Management Member Portal through URCS,2026-27
    141E,,2026-27

Rows that already exist in the registry are skipped (and reported). If a PDF for
the same OC is in the registry, the row is refused. Every added row is written
to Data/review_log.csv.
"""

import csv
import datetime
import re
import sys

from . import paths, registry

NOTE = ("Listed on NPCI's UPI circulars page with the note 'Please get in touch with your bank'; "
        "NPCI publishes no PDF, so the text is not public. Title as listed by NPCI.")
NO_TITLE = "(title not shown on NPCI's list)"


def make_row(oc_number: str, title: str, fy: str, series: str = "UPI") -> dict:
    oc = re.sub(r"\s+", "", oc_number).upper().lstrip("0")
    if not re.fullmatch(r"\d{1,3}[A-F]?", oc):
        raise ValueError(f"not a valid OC number: {oc_number!r}")
    row = dict.fromkeys(registry.COLUMNS, "")
    row.update(
        doc_id=f"{series}-{oc}", oc_number=oc, series=series, domain="UPI",
        title=(title or "").strip() or NO_TITLE, fy=(fy or "").strip(), category="uncategorised",
        status="not_public", page_count="0", char_count="0", review_status="drafted",
        needs_review="date_unknown_confirmed;not_public", notes=NOTE,
    )
    return row


def add_rows(rows: list, items: list) -> tuple:
    """Return (rows, added, skipped). `items` are dicts with oc_number, title, fy."""
    by_id = {r["doc_id"]: r for r in rows}
    pdf_keys = {(r["series"], r["oc_number"]) for r in rows if r["status"] != "not_public"}
    added, skipped = [], []
    for it in items:
        row = make_row(it.get("oc_number", ""), it.get("title", ""), it.get("fy", ""))
        if row["doc_id"] in by_id:
            skipped.append((row["doc_id"], "already in the registry"))
        elif (row["series"], row["oc_number"]) in pdf_keys:
            skipped.append((row["doc_id"], "a PDF for this OC exists; not adding a not_public row"))
        else:
            rows.append(row)
            by_id[row["doc_id"]] = row
            added.append(row)
    rows.sort(key=registry._sort_key)
    return rows, added, skipped


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    with open(argv[0], newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    rows, added, skipped = add_rows(registry.load(), items)
    registry.save(rows)
    today = datetime.date.today().isoformat()
    with open(paths.DATA + "/review_log.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in added:
            w.writerow([today, r["doc_id"], "(new row)", "", f"not_public: {r['title']}",
                        "Member-only circular from NPCI's public list", "added with ingest.not_public"])
    print(f"added {len(added)}; skipped {len(skipped)}")
    for did, why in skipped:
        print(f"  skipped {did}: {why}")
    print("Now run: python -m ingest.build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
