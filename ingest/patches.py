"""Manual corrections to extracted text (Data/manual_patches/<doc_id>.txt).

Scanned circulars are read by OCR, which garbles tables and the rupee sign
(for example "from ₹5,000 to ₹10,000" is read as "from €5,000 to 210,000"). A
person (or an assistant working from the page image) transcribes the
affected part; the patch file then replaces or extends the OCR text.

Patch file format (first line selects the mode):
    [REPLACE]                  the whole document text is the patch
    [REPLACE_AFTER: marker]    keep the OCR text before the first occurrence of
                               `marker`, then use the patch from there on
    (no first-line tag)        legacy behaviour: append the patch to the text

Every patch should say in its own text that it was transcribed from the page
image, so a reader can tell corrected text from OCR.
"""

import os
import re

from . import paths

APPEND_MARKER = "[MANUAL PATCH APPLIED]"
_REPLACE_AFTER = re.compile(r"^\[REPLACE_AFTER:\s*(.+?)\]\s*\n", re.DOTALL)


def find_patch(row: dict) -> str:
    """Raw patch text for this registry row, or ''."""
    names = [row["doc_id"]]
    if row.get("series") == "UPI" and row.get("oc_number"):
        names.append(row["oc_number"])  # legacy files are named by OC number
    for name in names:
        path = os.path.join(paths.MANUAL_PATCH_DIR, f"{name}.txt")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return ""


def apply_patch(text: str, patch: str) -> str:
    """Return the document text with the patch applied."""
    if not patch.strip():
        return text
    if patch.startswith("[REPLACE]"):
        return patch[len("[REPLACE]"):].lstrip("\n").rstrip() + "\n"
    m = _REPLACE_AFTER.match(patch)
    if m:
        marker = m.group(1).strip()
        body = patch[m.end():].rstrip() + "\n"
        i = text.find(marker)
        if i < 0:
            raise ValueError(f"patch marker not found in the document text: {marker!r}")
        return text[:i].rstrip() + "\n\n" + body
    return f"{text.rstrip()}\n\n{APPEND_MARKER}\n{patch}"


def patched_text(row: dict, text: str) -> str:
    return apply_patch(text, find_patch(row))
