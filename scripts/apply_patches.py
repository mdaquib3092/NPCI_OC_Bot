"""
Apply manual patches to extracted JSONs AFTER rebuild_corpus.py runs.

Problem this solves: rebuild_corpus.py clears and regenerates Data/extracted/
from scratch every time (by design, to avoid stale files). Any one-off manual
fix (like reconstructing OC 120's garbled OCR annexure table) gets wiped out
the next time you rerun the pipeline.

Fix: store manual patches as small text snippets in Data/manual_patches/
(one file per OC number, named "<oc_number>.txt"), and run this script
AFTER rebuild_corpus.py + verify_extraction.py. It appends each patch's
content to the matching extracted JSON's "text" field and marks it.

Usage:
    python apply_patches.py

Then re-chunk/re-embed as usual.
"""

import glob
import json
import os

EXTRACTED_DIR = os.path.join("Data", "extracted")
PATCHES_DIR = os.path.join("Data", "manual_patches")


def main():
    os.makedirs(PATCHES_DIR, exist_ok=True)
    patch_files = glob.glob(os.path.join(PATCHES_DIR, "*.txt"))

    if not patch_files:
        print(f"No patch files found in {PATCHES_DIR}/")
        print("To add one: create Data/manual_patches/<oc_number>.txt")
        print("e.g. Data/manual_patches/120.txt for OC 120's annexure fix.")
        return

    print(f"Found {len(patch_files)} patch file(s).\n")
    applied, missing = 0, []

    for patch_path in patch_files:
        oc_number = os.path.splitext(os.path.basename(patch_path))[0]
        json_path = os.path.join(EXTRACTED_DIR, f"{oc_number}.json")

        if not os.path.isfile(json_path):
            missing.append((oc_number, json_path))
            continue

        with open(patch_path, encoding="utf-8") as f:
            patch_text = f.read()

        d = json.load(open(json_path, encoding="utf-8"))

        marker = "[MANUAL PATCH APPLIED]"
        if marker in d["text"]:
            # already patched in a previous run of this script - replace
            # the old patch content rather than appending a duplicate
            d["text"] = d["text"].split(marker)[0].rstrip()

        d["text"] = d["text"].rstrip() + f"\n\n{marker}\n" + patch_text
        d["char_count"] = len(d["text"])
        d["manually_patched"] = True

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)

        applied += 1
        print(f"  Applied patch: {oc_number} -> {json_path}")

    print(f"\nApplied {applied} patch(es).")
    if missing:
        print(f"\n{len(missing)} patch(es) skipped - no matching extracted JSON found:")
        for oc, path in missing:
            print(f"  - {oc} (expected {path})")
        print("Check the OC number matches exactly (case, letters) in the manifest.")


if __name__ == "__main__":
    main()