"""Single place for every path the build pipeline reads or writes."""

import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "Data")

# Inputs (kept local, not in Git)
PDF_ROOT = os.path.join(DATA, "raw_pdfs", "upi")
OCR_CACHE_DIR = os.path.join(DATA, "ocr_text")
MANUAL_PATCH_DIR = os.path.join(DATA, "manual_patches")

# Intermediate (local, not in Git)
EXTRACTED_DIR = os.path.join(DATA, "text_cache")

# Reviewed data and build outputs that are committed
REGISTRY_PATH = os.path.join(DATA, "registry.csv")
CHUNKS_PATH = os.path.join(DATA, "chunks.jsonl")
CHROMA_DIR = os.path.join(DATA, "chroma_db")
BUILD_INFO_PATH = os.path.join(DATA, "build_info.json")
COVERAGE_REPORT_PATH = os.path.join(DATA, "coverage_report.md")
DEDUPE_REPORT_PATH = os.path.join(DATA, "dedupe_report.csv")

COLLECTION_NAME = "npci_oc_chunks"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
