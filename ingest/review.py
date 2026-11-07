"""Human review of facts: export a sheet, import the decisions.

    python -m ingest.review export                 # writes Data/review/facts_review.xlsx
    python -m ingest.review import <file.xlsx|.csv> --reviewer "Name"

Only a person can set review_status to human_verified, and only through the
import. Rows marked "Needs change" or "Reject" are left as they are and listed,
so the fact (or its source patch) can be corrected and exported again.
"""

import argparse
import csv
import datetime
import os
import sys

from . import facts as F
from . import paths, patches, registry

REVIEW_DIR = os.path.join(paths.DATA, "review")
EXPORT_PATH = os.path.join(REVIEW_DIR, "facts_review.xlsx")
DECISIONS = ["Verified", "Needs change", "Reject"]
SHEET_COLUMNS = [
    "fact_id", "txn_type", "limit_kind", "direction", "merchant_type", "mcc", "category_name",
    "value", "unit", "conditions", "effective_date", "status", "source_oc", "source_text",
    "quote", "page", "notes", "review_status", "Decision", "Comment / corrected value",
]


def _source_kind(row_by_doc: dict, doc_id: str) -> str:
    row = row_by_doc.get(doc_id)
    return "page-image transcription (manual patch)" if row and patches.find_patch(row) else "OCR / PDF text"


def export(path: str = EXPORT_PATH) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    rows = F.load()
    reg = {r["doc_id"]: r for r in registry.load()}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Facts to review"
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for j, col in enumerate(SHEET_COLUMNS, 1):
        c = ws.cell(1, j, col)
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = border
    widths = {"fact_id": 30, "page": 7, "quote": 60, "conditions": 42, "notes": 42, "category_name": 26,
              "source_text": 22, "Comment / corrected value": 34}
    for j, col in enumerate(SHEET_COLUMNS, 1):
        ws.column_dimensions[ws.cell(1, j).column_letter].width = widths.get(col, 13)
    yellow = PatternFill("solid", fgColor="FFF2CC")
    order = sorted(rows, key=lambda r: (r["txn_type"], r["limit_kind"], r["mcc"], r["status"], r["fact_id"]))
    for i, r in enumerate(order, 2):
        data = dict(r, source_text=_source_kind(reg, r["source_doc_id"]), Decision="", **{"Comment / corrected value": ""})
        if r["review_status"] == "human_verified":
            data["Decision"] = "Verified"
        for j, col in enumerate(SHEET_COLUMNS, 1):
            c = ws.cell(i, j, data.get(col, ""))
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = border
            if col in ("Decision", "Comment / corrected value"):
                c.fill = yellow
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{ws.cell(1, len(SHEET_COLUMNS)).column_letter}{len(order) + 1}"
    dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{ws.cell(1, SHEET_COLUMNS.index('Decision') + 1).column_letter}2:{ws.cell(1, SHEET_COLUMNS.index('Decision') + 1).column_letter}{len(order) + 1}")

    guide = wb.create_sheet("How to review", 0)
    lines = [
        ("Facts review", True),
        ("", False),
        ("For every row: compare 'value' and 'unit' with the 'quote', and check the quote against the circular itself (the PDF).", False),
        ("Pick a Decision (yellow column): Verified, Needs change, or Reject. Add a comment if you pick anything but Verified.", False),
        ("'status' tells whether a limit is the current one, was superseded by a later circular, or is unclear.", False),
        ("'source_text' says whether the quote comes from the OCR/PDF text or from a transcription made from the page image.", False),
        ("Amounts: 1 Lakh = 1,00,000. 'direction' is send, receive (credit received) or any.", False),
        ("Rows with status 'unclear' are not served to users even when verified; they need a domain decision.", False),
        ("", False),
        ("When you are done: save, then run  python -m ingest.review import <this file> --reviewer \"Your name\"", False),
    ]
    for i, (t, b) in enumerate(lines, 1):
        guide.cell(i, 1, t).font = Font(name="Arial", bold=b, size=13 if i == 1 else 11)
    guide.column_dimensions["A"].width = 130
    wb.save(path)
    return path


def _read_decisions(path: str) -> list:
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    from openpyxl import load_workbook

    ws = load_workbook(path, data_only=True)["Facts to review"]
    header = [c.value for c in ws[1]]
    return [dict(zip(header, [c.value for c in row])) for row in ws.iter_rows(min_row=2)]


def apply_decisions(facts: list, decisions: list, reviewer: str, today: str) -> dict:
    """Update `facts` in place from sheet rows. Returns counts and lists."""
    by_id = {f["fact_id"]: f for f in facts}
    result = {"verified": 0, "needs_change": [], "rejected": [], "unknown": [], "unchanged": 0}
    for d in decisions:
        fid = (d.get("fact_id") or "").strip()
        decision = (d.get("Decision") or "").strip()
        if not fid or not decision:
            result["unchanged"] += 1
            continue
        f = by_id.get(fid)
        if f is None:
            result["unknown"].append(fid)
        elif decision == "Verified":
            if f["review_status"] != "human_verified":
                f["review_status"], f["reviewer"], f["reviewed_on"] = "human_verified", reviewer, today
            result["verified"] += 1
        elif decision == "Needs change":
            result["needs_change"].append((fid, d.get("Comment / corrected value") or ""))
        elif decision == "Reject":
            result["rejected"].append((fid, d.get("Comment / corrected value") or ""))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    imp = sub.add_parser("import")
    imp.add_argument("file")
    imp.add_argument("--reviewer", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "export":
        print("Wrote", export())
        return 0
    facts = F.load()
    result = apply_decisions(facts, _read_decisions(args.file), args.reviewer, datetime.date.today().isoformat())
    F.save(facts)
    print(f"human_verified: {result['verified']} | unchanged/blank: {result['unchanged']}")
    for fid, c in result["needs_change"]:
        print(f"  NEEDS CHANGE {fid}: {c}")
    for fid, c in result["rejected"]:
        print(f"  REJECT       {fid}: {c}")
    for fid in result["unknown"]:
        print(f"  UNKNOWN fact_id {fid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
