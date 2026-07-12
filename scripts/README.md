# Developer / maintenance scripts

One-off and maintenance utilities used while building and curating the corpus.
They are **not** part of the runtime app (`app.py`) and are not imported by it —
each is standalone and run manually.

| Script | Purpose |
|---|---|
| `ocr_pdf.py` | Pre-compute Tesseract OCR text for scanned PDFs into a cache that `extract.py` then reuses (avoids re-running OCR on every extraction). |
| `verify_extraction.py` | QA check that extracted JSON matches the source PDF, with special attention to Annexure tables not being truncated. |
| `diagnose_chunks.py` | Quick scan of a circulars folder to classify PDFs as empty / scanned / OK. |
| `apply_patches.py` | Re-apply manual corrections (e.g. the reconstructed OC 120 Annexure A table) to `Data/extracted/` after a full rebuild wipes them. |
| `patch_annexure.py` | Holds the hand-corrected OC 120 Annexure A text used by `apply_patches.py`. |
| `test_feedback_submit.py` | Standalone probe to debug the Google Form feedback submission. |

Typical rebuild order: `ocr_pdf.py` → the main pipeline (`generate_manifest.py`
→ `extract.py` → `chunk.py` → `embed.py`, or `rebuild_corpus.py` for all four)
→ `apply_patches.py` → `verify_extraction.py`.
