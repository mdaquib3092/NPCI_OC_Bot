# Developer / maintenance scripts

One-off and maintenance utilities used while building and curating the corpus.
They are **not** part of the runtime app (`app.py`) and are not imported by it —
each is standalone and run manually.

| Script | Purpose |
|---|---|
| `ocr_pdf.py` | Pre-compute Tesseract OCR text for scanned PDFs into `Data/ocr_text/`. `python -m ingest.build` also runs OCR on its own when no cache exists |
| `test_feedback_submit.py` | Standalone probe to debug the Google Form feedback submission |

The old extraction, chunking, manifest and patch scripts were replaced by the `ingest/` package (see the main README).
