"""One command rebuilds everything and stops if a data-quality gate fails.

    python -m ingest.build                 # full build
    python -m ingest.build --skip-index    # data only (fast; no embedding model)
    python -m ingest.build --no-fresh-ocr  # never run OCR; use native text and cached OCR only

Steps: extract -> registry (draft new rows, validate) -> chunk -> gates ->
vector index -> build_info.json + coverage_report.md.
Rows already in Data/registry.csv are never overwritten; new PDFs are added as
'drafted' rows that a person must review.
"""

import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
import re
import sys

from . import chunk, codes, extract, facts as facts_mod, paths, registry


def check_chunks(rows: list, chunks: list) -> list:
    """Chunk-level gates. Returns (severity, where, message) tuples."""
    issues = []
    seen = set()
    per_doc = collections.Counter(c["doc_id"] for c in chunks)
    by_id = {r["doc_id"]: r for r in rows}
    for c in chunks:
        if c["chunk_id"] in seen:
            issues.append(("error", c["chunk_id"], "duplicate chunk_id"))
        seen.add(c["chunk_id"])
        for k in ("doc_id", "title", "status"):
            if not c.get(k):
                issues.append(("error", c["chunk_id"], f"{k} is empty"))
        if not c.get("issue_date") and "date_unknown_confirmed" not in by_id[c["doc_id"]]["needs_review"]:
            issues.append(("error", c["chunk_id"], "issue_date is empty"))
    for r in rows:
        if r["status"] not in ("unreadable", "not_public") and per_doc[r["doc_id"]] == 0:
            issues.append(("error", r["doc_id"], "readable document produced no chunks"))
    return issues


_CITE = re.compile(r"\bOC[\s\-_./]*(?:No\.?)?[\s\-_./]*0*(\d{1,3})\s?([A-F])?(?![A-Za-z0-9])", re.IGNORECASE)


def missing_citations(rows: list, doc_texts: dict) -> list:
    """OC numbers that other circulars cite but the registry does not contain,
    most-cited first: [(oc_number, citing_documents)]."""
    have = {r["oc_number"] for r in rows if r["series"] == "UPI" and r["oc_number"]}
    cited = collections.defaultdict(set)
    for doc_id, text in doc_texts.items():
        for m in _CITE.finditer(text):
            n = f"{int(m.group(1))}{(m.group(2) or '').upper()}"
            if n not in have and int(m.group(1)) <= 260:
                cited[n].add(doc_id)
    ranked = sorted(((n, sorted(d)) for n, d in cited.items() if len(d) >= 2), key=lambda x: (-len(x[1]), x[0]))
    return ranked


def coverage_report(rows: list, chunks: list, info: dict, fact_rows: list = (), code_rows: list = (), doc_texts: dict = None) -> str:
    readable = [r for r in rows if r["status"] not in ("unreadable", "not_public")]
    hidden = [r for r in rows if r["status"] == "not_public"]
    by_series = collections.Counter(r["series"] for r in rows)
    by_year = collections.Counter((r["issue_date"] or "unknown")[:4] for r in readable)
    flags = collections.Counter(f.split("(")[0] for r in rows for f in r["needs_review"].split(";") if f)
    gaps = [r for r in rows if r["status"] == "unreadable"]
    lines = [
        "# Corpus coverage report", "",
        f"Build `{info['build_id']}` · corpus as of **{info['corpus_as_of']}** · built {info['built_at']}", "",
        f"- Documents in registry: **{len(rows)}** ({len(readable)} readable, {len(gaps)} unreadable, {len(hidden)} listed by NPCI but not public)",
        f"- Chunks: **{len(chunks)}**",
        f"- Documents still marked `drafted` (not yet human-reviewed): **{sum(r['review_status'] == 'drafted' for r in rows)}**",
        "", "## Documents by series", "", "| Series | Documents |", "|---|---|",
    ]
    lines += [f"| {s} | {n} |" for s, n in sorted(by_series.items())]
    lines += ["", "## Readable documents by year of issue", "", "| Year | Documents |", "|---|---|"]
    lines += [f"| {y} | {n} |" for y, n in sorted(by_year.items())]
    lines += ["", "## Known gaps (unreadable source files)", ""]
    if gaps:
        lines += [f"- `{r['doc_id']}` ({r['source_file']}): {r['notes']}" for r in gaps]
    else:
        lines.append("None.")
    lines += ["", "## Circulars NPCI lists but does not publish (member-only)", ""]
    if hidden:
        lines += ["The chatbot tells users that these exist and that their text is not public.", "",
                  "| OC | FY | Title as listed by NPCI |", "|---|---|---|"]
        lines += [f"| {r['oc_number']} | {r['fy']} | {r['title']} |" for r in hidden]
    else:
        lines.append("None.")
    lines += ["", "## Items awaiting review", "", "| Flag | Documents |", "|---|---|"]
    lines += [f"| {f} | {n} |" for f, n in flags.most_common()]
    by_review = collections.Counter(f["review_status"] for f in fact_rows)
    by_status = collections.Counter(f["status"] for f in fact_rows)
    by_type = collections.Counter(f["txn_type"] for f in fact_rows)
    lines += ["", "## Facts (limits)", "",
              f"- Facts: **{len(fact_rows)}**; by review status: " + ", ".join(f"{k} {v}" for k, v in sorted(by_review.items())),
              "- By limit status: " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())),
              "- By transaction type: " + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items()))]
    mcc = {r["code"] for r in code_rows if r["code_family"] == "mcc"}
    limit_mcc = {r["code"] for r in code_rows if r["code_family"] == "mcc" and r["rule_type"] == "limit"}
    pc = {r["code"] for r in code_rows if r["code_family"] == "purpose_code"}
    lines += ["", "## Codes found in the circulars", "",
              f"- MCCs mentioned: **{len(mcc)}** (with a reviewed limit fact: {len(limit_mcc)})",
              f"- Purpose codes mentioned: **{len(pc)}**",
              "- A code that is not listed in `Data/code_mentions.csv` is not mentioned in any indexed circular."]
    if doc_texts:
        missing = missing_citations(rows, doc_texts)
        lines += ["", "## Circulars cited by other circulars but not in the corpus", "",
                  "These OC numbers appear in the text of at least two indexed circulars but have no document in the registry. "
                  "Some may be OCR misreadings; check the ones cited most often first.", "",
                  "| OC | Cited by (documents) |", "|---|---|"]
        lines += [f"| {n} | {len(d)} |" for n, d in missing[:25]]
    return "\n".join(lines) + "\n"


def write_dedupe_report(skipped: list) -> None:
    with open(paths.DEDUPE_REPORT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "reason", "kept", "detail"])
        w.writeheader()
        w.writerows(skipped)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-index", action="store_true")
    ap.add_argument("--no-fresh-ocr", action="store_true")
    args = ap.parse_args(argv)
    failed = False

    print("1/5 Extracting text from PDFs...")
    records = extract.extract_all(allow_fresh_ocr=not args.no_fresh_ocr)
    text_by_hash = {r["content_hash"]: r["text"] for r in records}

    print("2/5 Updating the registry...")
    existing = registry.load()
    rows, added, orphaned, skipped = registry.draft(records, existing)
    registry.save(rows)
    write_dedupe_report(skipped)
    print(f"    {len(rows)} documents; {len(added)} new draft row(s); "
          f"{len(orphaned)} registry row(s) with no PDF now; {len(skipped)} file(s) skipped")
    for r in orphaned:
        print(f"    WARNING: registry row {r['doc_id']} has no matching PDF (kept out of the build)")
    issues = registry.validate(rows)

    print("3/5 Chunking, facts and code mentions...")
    pages_by_hash = {r["content_hash"]: r.get("pages", []) for r in records}
    chunks = chunk.chunk_registry(rows, text_by_hash, pages_by_hash)
    issues += check_chunks(rows, chunks)
    fact_rows = facts_mod.load()
    doc_texts = facts_mod.source_texts(rows, records)
    issues += facts_mod.validate(fact_rows, doc_texts, rows)
    unverified = [f for f in fact_rows if f["review_status"] != "human_verified"]
    if unverified:
        issues.append(("warn", "facts", f"{len(unverified)} of {len(fact_rows)} facts are not human_verified yet and will not be served"))
    code_rows = codes.scan_all(rows, doc_texts, fact_rows)

    errors = [i for i in issues if i[0] == "error"]
    warns = [i for i in issues if i[0] == "warn"]
    print(f"4/5 Gates: {len(errors)} error(s), {len(warns)} warning(s)")
    for sev, where, msg in errors[:30]:
        print(f"    ERROR {where}: {msg}")
    for sev, where, msg in warns:
        print(f"    warn  {where}: {msg}")
    if errors:
        print("Build stopped: fix the errors above (edit Data/registry.csv) and run again.")
        return 1

    chunk.write_chunks(chunks)
    codes.save(code_rows)
    digest = hashlib.sha1(open(paths.CHUNKS_PATH, "rb").read()).hexdigest()[:7]
    now = datetime.datetime.now(datetime.timezone.utc)
    dates = [r["issue_date"] for r in rows if r["issue_date"]]
    info = {
        "build_id": f"{now:%Y%m%d-%H%M}-{digest}",
        "built_at": f"{now:%Y-%m-%d %H:%M} UTC",
        "corpus_as_of": max(dates) if dates else "",
        "documents": len(rows),
        "unreadable_documents": sum(r["status"] == "unreadable" for r in rows),
        "not_public_documents": sum(r["status"] == "not_public" for r in rows),
        "chunks": len(chunks),
        "facts": len(fact_rows),
        "facts_human_verified": len(fact_rows) - len(unverified),
        "code_mentions": len(code_rows),
        "embed_model": paths.EMBED_MODEL_NAME,
    }

    if args.skip_index:
        print("5/5 Skipping the vector index (--skip-index).")
    else:
        print("5/5 Building the vector index...")
        from . import index

        info["indexed_chunks"] = index.build_index(chunks)
        if info["indexed_chunks"] != len(chunks):
            print("ERROR: indexed chunk count does not match chunks.jsonl")
            failed = True

    with open(paths.BUILD_INFO_PATH, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    with open(paths.COVERAGE_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(coverage_report(rows, chunks, info, fact_rows, code_rows, doc_texts))
    print(f"Done: build {info['build_id']} ({info['documents']} documents, {info['chunks']} chunks).")
    print(f"Coverage report: {paths.COVERAGE_REPORT_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
