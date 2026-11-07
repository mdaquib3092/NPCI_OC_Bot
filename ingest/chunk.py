"""Step 3: text -> chunks, with metadata copied from the registry.

Rules (unchanged from the first pipeline unless noted):
- administrative boilerplate and letterhead footers are stripped
- paragraphs are the unit; short ones are merged, long ones split on sentences
- Markdown tables are kept whole, or split by rows with the header repeated
- overlap never crosses a table boundary
- NEW: chunk metadata comes only from the registry, never from filenames
- NEW: manual patches (Data/manual_patches/<doc_id or OC number>.txt) replace or
  extend the OCR text before chunking (see ingest/patches.py)
"""

import json
import os
import re

from . import patches, paths

MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 80
OVERLAP_CHARS = 150

BOILERPLATE_LINE_PATTERNS = [
    r"^\s*Dear\s+(Sir|Madam|Members?|Sir/Madam|Madam/Sir)",
    r"^\s*(To\s+)?All\s+Members?(\s+Banks?)?",
    r"^\s*All\s+Member\s+Banks?\s*/?\s*PSPs?",
    r"^\s*Subject\s*:",
    r"^\s*Ref(erence)?\s*(No\.?)?\s*:",
    r"^\s*Yours\s+(faithfully|sincerely|truly)",
    r"^\s*(Best\s+)?Regards\s*,?\s*$",
    r"^\s*Authorized?\s+Signatory",
    r"^\s*For\s+National\s+Payments\s+Corporation\s+of\s+India",
    r"^\s*Chief\s*[-–—]\s*",
    r"^\s*Sr\.?\s*(Vice\s*President|Manager|Officer)",
    r"^\s*This\s+circular\s+is\s+issued\s+for\s+information\s+and\s+necessary\s+action",
    r"^\s*Page\s+\d+\s*(of\s+\d+)?\s*$",
    r"^\s*National\s+Payments\s+Corporation\s+of\s+India\s*$",
]
BOILERPLATE_REGEX = re.compile("|".join(f"(?:{p})" for p in BOILERPLATE_LINE_PATTERNS), re.IGNORECASE)

FOOTER_CONTAINS_PATTERNS = [
    r"CIN\s*:\s*U\d",
    r"www\.npci\.org\.in",
    r"contact@npci\.org\.in",
    r"[\w.\-]+@npci\.org\.in",
    r"\bT\s*:\s*\+?\d{2,3}[\s\-]?\d{2,}",
    r"\bF\s*:\s*\+?\d{2,3}[\s\-]?\d{2,}",
]
FOOTER_REGEX = re.compile("|".join(f"(?:{p})" for p in FOOTER_CONTAINS_PATTERNS), re.IGNORECASE)


def clean_text(text: str) -> str:
    lines = [
        line for line in text.split("\n")
        if not BOILERPLATE_REGEX.match(line.strip()) and not FOOTER_REGEX.search(line)
    ]
    text = "\n".join(lines)
    text = re.sub(r"\bSub(ject)?\s*:\s*", "", text)
    text = re.sub(r"\bTo\s*,\s*", "", text)
    text = re.sub(r"\bRef(erence)?\s*:\s*", "", text)
    return text


def split_into_paragraphs(text: str) -> list:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def split_long_paragraph(paragraph: str, max_chars: int) -> list:
    chunks, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def is_table(text: str) -> bool:
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    return len(lines) >= 2 and lines[0].startswith("|") and lines[1].startswith("|")


def split_table_paragraph(table_text: str, max_chars: int) -> list:
    """Split a large table by rows, repeating the header on every piece."""
    lines = [l.strip() for l in table_text.strip().split("\n") if l.strip()]
    if len(lines) <= 2:
        return [table_text]
    header = lines[0] + "\n" + lines[1]
    chunks, rows, size = [], [], len(header)
    for row in lines[2:]:
        if size + len(row) + 1 <= max_chars or not rows:
            rows.append(row)
            size += len(row) + 1
        else:
            chunks.append(header + "\n" + "\n".join(rows))
            rows, size = [row], len(header) + len(row) + 1
    if rows:
        chunks.append(header + "\n" + "\n".join(rows))
    return chunks


def build_chunks(text: str) -> list:
    merged, buffer = [], ""
    for p in split_into_paragraphs(text):
        if is_table(p):
            if buffer:
                merged.append(buffer)
                buffer = ""
            merged.append(p)
            continue
        if len(buffer) + len(p) < MIN_CHUNK_CHARS:
            buffer = f"{buffer} {p}".strip()
        elif buffer:
            merged.append(f"{buffer} {p}".strip())
            buffer = ""
        else:
            merged.append(p)
    if buffer:
        if merged and not is_table(merged[-1]):
            merged[-1] = f"{merged[-1]} {buffer}".strip()
        else:
            merged.append(buffer)

    raw = []
    for p in merged:
        if len(p) > MAX_CHUNK_CHARS:
            raw.extend(split_table_paragraph(p, MAX_CHUNK_CHARS) if is_table(p)
                       else split_long_paragraph(p, MAX_CHUNK_CHARS))
        else:
            raw.append(p)

    final = []
    for i, chunk in enumerate(raw):
        if i == 0 or is_table(chunk) or is_table(raw[i - 1]):
            final.append(chunk)
        else:
            final.append(f"{raw[i - 1][-OVERLAP_CHARS:]} {chunk}".strip())
    return final


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def find_page(chunk_text: str, pages: list) -> str:
    """Page (1-based) on which the end of the chunk appears, or '' if it cannot be told.
    Only meaningful when `pages` really are PDF pages (scanned documents have a single OCR block)."""
    if len(pages) < 2:
        return ""
    tail = _flat(chunk_text)[-70:]
    if len(tail) < 20:
        return ""
    for i, page in enumerate(pages, 1):
        if tail in _flat(page):
            return str(i)
    return ""


def chunk_registry(rows: list, text_by_hash: dict, pages_by_hash: dict = None) -> list:
    """Return chunk records for every readable document in the registry."""
    out = []
    pages_by_hash = pages_by_hash or {}
    for row in rows:
        if row["status"] in ("unreadable", "not_public"):
            continue
        text = text_by_hash.get(row["content_hash"], "")
        patched = patches.find_patch(row) != ""
        pages = [] if patched else pages_by_hash.get(row["content_hash"], [])
        text = patches.patched_text(row, text)
        if not text.strip():
            continue
        for idx, chunk_text in enumerate(build_chunks(clean_text(text))):
            out.append({
                "chunk_id": f"{row['doc_id']}__{idx}",
                "doc_id": row["doc_id"],
                "oc_number": row["oc_number"],
                "series": row["series"],
                "domain": row["domain"],
                "title": row["title"],
                "issue_date": row["issue_date"],
                "status": row["status"],
                "supersedes": row["supersedes"],
                "superseded_by": row["superseded_by"],
                "category": row["category"],
                "source_filename": row["source_file"],
                "chunk_type": "table" if is_table(chunk_text) else "text",
                "page": find_page(chunk_text, pages) or ("1" if str(row.get("page_count")) == "1" else ""),
                "chunk_text": chunk_text,
            })
    return out


def write_chunks(chunks: list, path: str = None) -> None:
    path = path or paths.CHUNKS_PATH
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
