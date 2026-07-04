"""
Build regression test candidates from user feedback.

Since we don't have direct API/billing access to the Google Sheet, this
script works off a manually-exported CSV of the feedback Sheet:
  Google Sheet -> File -> Download -> Comma Separated Values (.csv)
  Save it as: Data/feedback_export.csv

It filters for 👎 ("Not helpful") rows and writes a template CSV where you
fill in the correct expected_oc_number for each — then merge confirmed rows
into eval_test_set.csv to grow your regression suite over time.

Run:
    python build_regression_set.py
"""

import csv
import os

FEEDBACK_EXPORT_PATH = os.path.join("Data", "feedback_export.csv")
OUTPUT_PATH = "regression_candidates.csv"


def read_csv_robust(path):
    encodings_to_try = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_error = None
    for enc in encodings_to_try:
        try:
            with open(path, newline="", encoding=enc) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError as e:
            last_error = e
            continue
    raise last_error


def main():
    if not os.path.isfile(FEEDBACK_EXPORT_PATH):
        print(f"{FEEDBACK_EXPORT_PATH} not found.")
        print(
            "Export your feedback Google Sheet as CSV "
            "(File -> Download -> Comma Separated Values) and save it there."
        )
        return

    rows = read_csv_robust(FEEDBACK_EXPORT_PATH)
    print(f"Loaded {len(rows)} feedback entries.")

    # Column names depend on your Google Form's exact field order — adjust
    # these keys if your exported CSV headers differ.
    negative_rows = [
        r for r in rows
        if "👎" in r.get("Feedback", "") or "not helpful" in r.get("Feedback", "").lower()
    ]

    print(f"Found {len(negative_rows)} 👎 (not helpful) entries.")

    if not negative_rows:
        print("No regression candidates to build. Nothing written.")
        return

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "question",
                "expected_oc_number",
                "expected_keywords",
                "notes",
                "_original_answer",
                "_comment",
            ],
        )
        writer.writeheader()
        for r in negative_rows:
            writer.writerow(
                {
                    "question": r.get("Question", ""),
                    "expected_oc_number": "",  # fill in manually
                    "expected_keywords": "",   # fill in manually
                    "notes": "regression candidate from 👎 feedback",
                    "_original_answer": r.get("Answer", "")[:200],
                    "_comment": r.get("Comment", ""),
                }
            )

    print(f"\nWrote {len(negative_rows)} candidate(s) to {OUTPUT_PATH}")
    print(
        "\nNext: open this file, fill in the correct 'expected_oc_number' and "
        "'expected_keywords' for each row (using your domain knowledge), then "
        "delete the '_original_answer' and '_comment' columns and append the "
        "confirmed rows to eval_test_set.csv to grow your regression suite."
    )


if __name__ == "__main__":
    main()