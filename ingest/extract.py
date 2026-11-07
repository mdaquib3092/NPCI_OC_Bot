"""Step 1: PDF -> text.

Each PDF is extracted once and cached in Data/extracted/<content_hash>.json so
the later steps never depend on filenames. Order of attempts:

1. native text (PyMuPDF, tables converted to Markdown)
2. cached OCR text from Data/ocr_text (matched by a normalised filename)
3. fresh OCR (and the result is written back to the OCR cache)

A PDF that still yields too little text is recorded as unreadable instead of
being passed on silently.
"""

import hashlib
import json
import os
import re

from . import paths

MIN_TEXT_CHARS = 100

_TIME_SUFFIX = re.compile(r"\s+\d{1,2}[.:]\d{2}[.:]\d{2}\s*(AM|PM)?$", re.IGNORECASE)


def file_hash(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:12]


def is_valid_pdf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5)[:4] == b"%PDF"
    except OSError:
        return False


def normalize_stem(name: str) -> str:
    """Filename stem without extension and without a trailing time stamp such as
    ' 11.46.37 AM' (macOS adds it on re-download), so the OCR cache still matches."""
    stem = os.path.splitext(os.path.basename(name))[0]
    return _TIME_SUFFIX.sub("", stem).strip()


def find_ocr_cache(pdf_path: str) -> str:
    """Return the path of cached OCR text for this PDF, or ''."""
    if not os.path.isdir(paths.OCR_CACHE_DIR):
        return ""
    base = os.path.basename(pdf_path)
    exact = os.path.join(paths.OCR_CACHE_DIR, base + ".txt")
    if os.path.isfile(exact):
        return exact
    want = normalize_stem(base)
    for fname in os.listdir(paths.OCR_CACHE_DIR):
        if fname.endswith(".pdf.txt") and normalize_stem(fname[: -len(".txt")]) == want:
            return os.path.join(paths.OCR_CACHE_DIR, fname)
    return ""


def _page_markdown(page, fitz) -> str:
    """One page of text; tables inside the page become Markdown tables."""
    try:
        tabs = page.find_tables()
        if not tabs.tables:
            return page.get_text() or ""
        rects = [fitz.Rect(t.bbox) for t in tabs.tables]
        items, used = [], set()
        for b in page.get_text("blocks"):
            rect, text = fitz.Rect(b[:4]), b[4].strip()
            if not text:
                continue
            inside = False
            for i, (t, r) in enumerate(zip(tabs.tables, rects)):
                if (rect & r).get_area() > 0.4 * rect.get_area():
                    inside = True
                    if i not in used:
                        used.add(i)
                        items.append((r.y0, t.to_markdown()))
                    break
            if not inside:
                items.append((rect.y0, text))
        for i, (t, r) in enumerate(zip(tabs.tables, rects)):
            if i not in used:
                items.append((r.y0, t.to_markdown()))
        items.sort(key=lambda x: x[0])
        return "\n\n".join(x[1] for x in items)
    except Exception:
        return page.get_text() or ""


def native_pages(pdf_path: str) -> list:
    import fitz

    doc = fitz.open(pdf_path)
    try:
        return [_page_markdown(p, fitz) for p in doc]
    finally:
        doc.close()


def fresh_ocr(pdf_path: str) -> str:
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(pdf_path, dpi=300)
    return "\n\n".join(pytesseract.image_to_string(img) for img in images)


def extract_pdf(pdf_path: str, allow_fresh_ocr: bool = True) -> dict:
    """Return {pages, text, text_source, page_count, readable, problem}."""
    result = {"pages": [], "text": "", "text_source": "none", "page_count": 0,
              "readable": False, "problem": ""}
    if not is_valid_pdf(pdf_path):
        result["problem"] = "not a PDF (wrong header)"
        return result

    try:
        pages = native_pages(pdf_path)
    except Exception as e:  # corrupt or encrypted file
        result["problem"] = f"cannot open: {type(e).__name__}"
        pages = []
    result["page_count"] = len(pages)
    text = "\n\n".join(pages)

    if len(text.strip()) >= MIN_TEXT_CHARS:
        result.update(pages=pages, text=text, text_source="native", readable=True)
        return result

    if not pages:
        result["problem"] = result["problem"] or "PDF has 0 pages (truncated or corrupt download)"
        return result

    cache = find_ocr_cache(pdf_path)
    if cache:
        with open(cache, encoding="utf-8") as f:
            cached = f.read()
        if len(cached.strip()) >= MIN_TEXT_CHARS:
            result.update(pages=[cached], text=cached, text_source="ocr_cache", readable=True)
            return result

    if allow_fresh_ocr:
        try:
            ocr = fresh_ocr(pdf_path)
        except Exception as e:
            ocr = ""
            result["problem"] = f"fresh OCR failed: {type(e).__name__}"
        if len(ocr.strip()) >= MIN_TEXT_CHARS:
            os.makedirs(paths.OCR_CACHE_DIR, exist_ok=True)
            with open(os.path.join(paths.OCR_CACHE_DIR, os.path.basename(pdf_path) + ".txt"),
                      "w", encoding="utf-8") as f:
                f.write(ocr)
            result.update(pages=[ocr], text=ocr, text_source="ocr_fresh", readable=True)
            return result

    result["pages"], result["text"] = pages, text
    result["problem"] = result["problem"] or "too little text after native, cached and fresh OCR"
    return result


def extract_all(allow_fresh_ocr: bool = True, force: bool = False) -> list:
    """Extract every PDF under PDF_ROOT into the hash-keyed cache. Returns the
    list of cache records (one per PDF)."""
    os.makedirs(paths.EXTRACTED_DIR, exist_ok=True)
    records = []
    pdfs = sorted(
        os.path.join(dp, f)
        for dp, _, fs in os.walk(paths.PDF_ROOT)
        for f in fs
        if f.lower().endswith(".pdf")
    )
    for i, pdf in enumerate(pdfs, 1):
        h = file_hash(pdf)
        out = os.path.join(paths.EXTRACTED_DIR, f"{h}.json")
        rel = os.path.relpath(pdf, paths.PDF_ROOT)
        if os.path.isfile(out) and not force:
            with open(out, encoding="utf-8") as f:
                rec = json.load(f)
            if rec.get("readable") or not allow_fresh_ocr or rec.get("ocr_tried"):
                rec["source_file"] = rel
                records.append(rec)
                continue
        res = extract_pdf(pdf, allow_fresh_ocr=allow_fresh_ocr)
        rec = {
            "content_hash": h,
            "source_file": rel,
            "text": res["text"],
            "pages": res["pages"],
            "text_source": res["text_source"],
            "page_count": res["page_count"],
            "char_count": len(res["text"]),
            "readable": res["readable"],
            "problem": res["problem"],
            "ocr_tried": allow_fresh_ocr,
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        records.append(rec)
        if i % 25 == 0:
            print(f"  ...{i}/{len(pdfs)} extracted")
    return records
