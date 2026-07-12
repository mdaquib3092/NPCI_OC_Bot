"""
Phase 2: Chunk extracted OC text into smaller pieces for embedding.

Reads:  Data/extracted/*.json  (from extract.py / rebuild_corpus.py)
Writes: Data/chunks.jsonl      (one JSON object per line, each a single chunk)

Chunking strategy:
- Split on paragraph breaks (double newlines) first.
- If a paragraph is still too long (> max_chunk_chars), split further on
  sentence boundaries, grouping sentences until the size limit is hit.
- Very short paragraphs (e.g. headers, page numbers) get merged with the
  next paragraph so we don't end up with tiny, context-less chunks.

Run:
    python chunk.py
"""

import json
import os
import re

EXTRACTED_DIR = os.path.join("Data", "extracted")
CHUNKS_PATH = os.path.join("Data", "chunks.jsonl")

MAX_CHUNK_CHARS = 1200   # roughly 200-300 words per chunk
MIN_CHUNK_CHARS = 80     # merge tiny fragments into neighbors
OVERLAP_CHARS = 150      # overlap between consecutive chunks to preserve context

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

BOILERPLATE_REGEX = re.compile(
    "|".join(f"(?:{p})" for p in BOILERPLATE_LINE_PATTERNS), re.IGNORECASE
)

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
    lines = text.split("\n")
    cleaned_lines = [
        line
        for line in lines
        if not BOILERPLATE_REGEX.match(line.strip())
        and not FOOTER_REGEX.search(line)
    ]
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\bSub(ject)?\s*:\s*", "", text)
    text = re.sub(r"\bTo\s*,\s*", "", text)
    text = re.sub(r"\bRef(erence)?\s*:\s*", "", text)
    return text


def split_into_paragraphs(text: str):
    paragraphs = re.split(r"\n\s*\n", text)
    return [p.strip() for p in paragraphs if p.strip()]


def split_long_paragraph(paragraph: str, max_chars: int):
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    chunks = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def build_chunks(text: str):
    paragraphs = split_into_paragraphs(text)

    merged = []
    buffer = ""
    for p in paragraphs:
        if len(buffer) + len(p) < MIN_CHUNK_CHARS:
            buffer = f"{buffer} {p}".strip()
        else:
            if buffer:
                merged.append(f"{buffer} {p}".strip())
                buffer = ""
            else:
                merged.append(p)
    if buffer:
        if merged:
            merged[-1] = f"{merged[-1]} {buffer}".strip()
        else:
            merged.append(buffer)

    raw_chunks = []
    for p in merged:
        if len(p) > MAX_CHUNK_CHARS:
            raw_chunks.extend(split_long_paragraph(p, MAX_CHUNK_CHARS))
        else:
            raw_chunks.append(p)

    final_chunks = []
    for i, chunk in enumerate(raw_chunks):
        if i == 0:
            final_chunks.append(chunk)
        else:
            prev_tail = raw_chunks[i - 1][-OVERLAP_CHARS:]
            final_chunks.append(f"{prev_tail} {chunk}".strip())

    return final_chunks


def main():
    if not os.path.isdir(EXTRACTED_DIR):
        print(f"{EXTRACTED_DIR} not found. Run extract.py first.")
        return

    json_files = sorted(f for f in os.listdir(EXTRACTED_DIR) if f.endswith(".json"))
    print(f"Found {len(json_files)} extracted OC files.")

    total_chunks = 0
    skipped = []
    seen_chunk_ids = set()
    duplicate_ids_found = []

    with open(CHUNKS_PATH, "w", encoding="utf-8") as out_f:
        for i, fname in enumerate(json_files, start=1):
            path = os.path.join(EXTRACTED_DIR, fname)
            with open(path, encoding="utf-8") as f:
                record = json.load(f)

            text = record.get("text", "")
            if not text.strip():
                skipped.append(fname)
                continue

            text = clean_text(text)
            chunks = build_chunks(text)

            # Base chunk_id on the actual .json FILENAME (guaranteed unique
            # on disk), not just the oc_number field. Two different
            # extracted files can share the same oc_number metadata (e.g.
            # after collision-disambiguation upstream gives them different
            # disk filenames like "01.json" and "01__a1b2c3.json" but keeps
            # oc_number="01" in both) — using oc_number alone here would
            # silently produce duplicate chunk_ids and crash embed.py.
            file_stem = os.path.splitext(fname)[0]
            id_prefix = record.get("oc_number") or file_stem

            for idx, chunk_text in enumerate(chunks):
                chunk_id = f"{id_prefix}__{file_stem}_{idx}"

                if chunk_id in seen_chunk_ids:
                    duplicate_ids_found.append((chunk_id, fname))
                    continue
                seen_chunk_ids.add(chunk_id)

                chunk_record = {
                    "chunk_id": chunk_id,
                    "oc_number": record.get("oc_number", ""),
                    "title": record.get("title", ""),
                    "date": record.get("date", ""),
                    "category": record.get("category", ""),
                    "supersedes": record.get("supersedes", ""),
                    "superseded_by": record.get("superseded_by", ""),
                    "source_filename": record.get("filename", ""),
                    "chunk_text": chunk_text,
                }
                out_f.write(json.dumps(chunk_record, ensure_ascii=False) + "\n")
                total_chunks += 1

            print(f"[{i}/{len(json_files)}] {fname}: {len(chunks)} chunks")

    print(f"\nDone. {total_chunks} total chunks written to {CHUNKS_PATH}")
    if skipped:
        print(f"\n{len(skipped)} file(s) had no text (skipped):")
        for s in skipped:
            print(f"  - {s}")
    if duplicate_ids_found:
        print(f"\nWARNING: {len(duplicate_ids_found)} duplicate chunk_id(s) were "
              f"generated and skipped (investigate Data/extracted/ for files "
              f"with identical oc_number + filename stems):")
        for cid, fn in duplicate_ids_found:
            print(f"  - {cid}  (from {fn})")

    print("\nNext step: embedding (embed.py) to build the searchable vector index.")


if __name__ == "__main__":
    main()