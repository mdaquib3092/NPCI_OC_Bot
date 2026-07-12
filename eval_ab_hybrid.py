"""
A/B Evaluation: pure-vector retrieval vs hybrid (BM25 + vector + RRF).

Runs every question in the golden test set through BOTH retrieval paths and
reports hit-rate side by side, plus which specific questions changed status
(fixed by hybrid / broken by hybrid). Switch to hybrid only if this shows a
clear win — evidence over vibes.

Run:
    python3 eval_ab_hybrid.py
"""

import csv
import os
import re

import chromadb
from chromadb.utils import embedding_functions

from hybrid_search import HybridSearcher

CHROMA_DIR = os.path.join("Data", "chroma_db")
COLLECTION_NAME = "npci_oc_chunks"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
TEST_SET_PATH = "eval_test_set.csv"
RESULTS_PATH = "eval_ab_results.csv"

TOP_K = 10
DISTANCE_THRESHOLD = 0.8


def load_collection():
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL_NAME
    )
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)


def extract_oc_number_from_query(query: str) -> str:
    """Detect an explicit OC or circular number reference in the user's query,
    e.g. 'OC 76', 'OC-220', 'circular 120', 'circular no. 185A'."""
    patterns = [
        r"\bOC[\s\-]?0*(\d+[A-Z]?)\b",
        r"\bCircular[\s\-]?No\.?[\s\-]?0*(\d+[A-Z]?)\b",
        r"\bCircular[\s\-]?0*(\d+[A-Z]?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def dedupe_by_content(docs, metas):
    """Collapse near-identical chunks (normalized-text match) so duplicates
    don't waste top-k slots."""
    seen = set()
    out_docs, out_metas = [], []
    for d, m in zip(docs, metas):
        key = re.sub(r"[^a-z0-9]", "", d.lower())[:300]
        if key in seen:
            continue
        seen.add(key)
        out_docs.append(d)
        out_metas.append(m)
    return out_docs, out_metas


def retrieve_vector(collection, question: str):
    """OLD path: pure vector search (mirrors current eval_retrieval.py
    semantic branch, minus chain-expansion so we measure raw retrieval)."""
    results = collection.query(query_texts=[question], n_results=TOP_K)
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]
    filtered = [
        (d, m) for d, m, dist in zip(docs, metas, distances)
        if dist <= DISTANCE_THRESHOLD
    ]
    if not filtered:
        return [], []
    docs, metas = zip(*filtered)
    return list(docs), list(metas)


def retrieve_hybrid(searcher, collection, question: str):
    """NEW path: BM25 + vector + RRF, with content-dedup."""
    docs, metas = searcher.search(collection, question, top_k=TOP_K)
    return dedupe_by_content(docs, metas)


def read_csv_robust(path):
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            with open(path, newline="", encoding=enc) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("all encodings failed", b"", 0, 1, path)


def check_hit(expected_ocs, metas):
    retrieved = [m.get("oc_number", "").upper() for m in metas]
    return any(oc in retrieved for oc in expected_ocs), sorted(set(retrieved))


def main():
    collection = load_collection()
    searcher = HybridSearcher()
    print(f"BM25 index ready ({len(searcher.chunk_ids)} chunks).\n")

    test_cases = read_csv_robust(TEST_SET_PATH)

    vec_hits, hyb_hits = 0, 0
    scored = 0
    fixed_by_hybrid, broken_by_hybrid = [], []
    rows = []

    for i, case in enumerate(test_cases, 1):
        question = case["question"]
        expected_raw = case["expected_oc_number"].strip().upper()
        expected_ocs = [oc.strip() for oc in expected_raw.split(",") if oc.strip()]

        if not expected_ocs:
            # negative/behaviour tests — not scoreable on retrieval hit
            rows.append({"question": question, "expected": "", "vector_hit": "",
                         "hybrid_hit": "", "vector_ocs": "", "hybrid_ocs": ""})
            continue

        scored += 1

        # Direct OC-number queries bypass semantic search in the real app —
        # they'd hit the exact-fetch path in both flows, so score them
        # identically via metadata get.
        direct_oc = extract_oc_number_from_query(question)
        if direct_oc:
            result = collection.get(where={"oc_number": direct_oc}, limit=1)
            hit = bool(result.get("documents"))
            v_hit = h_hit = hit and direct_oc in expected_ocs
            v_ocs = h_ocs = [direct_oc] if hit else []
        else:
            v_docs, v_metas = retrieve_vector(collection, question)
            v_hit, v_ocs = check_hit(expected_ocs, v_metas)

            h_docs, h_metas = retrieve_hybrid(searcher, collection, question)
            h_hit, h_ocs = check_hit(expected_ocs, h_metas)

        vec_hits += int(v_hit)
        hyb_hits += int(h_hit)

        if h_hit and not v_hit:
            fixed_by_hybrid.append(question)
        if v_hit and not h_hit:
            broken_by_hybrid.append(question)

        marker = "  " if v_hit == h_hit else ("🟢" if h_hit else "🔴")
        print(f"[{i:2d}] V:{'✅' if v_hit else '❌'} H:{'✅' if h_hit else '❌'} {marker} {question[:70]}")

        rows.append({
            "question": question,
            "expected": expected_raw,
            "vector_hit": v_hit,
            "hybrid_hit": h_hit,
            "vector_ocs": ";".join(v_ocs),
            "hybrid_ocs": ";".join(h_ocs),
        })

    print(f"\n{'='*58}")
    print(f"Pure Vector : {vec_hits}/{scored} ({vec_hits/scored*100:.1f}%)")
    print(f"Hybrid RRF  : {hyb_hits}/{scored} ({hyb_hits/scored*100:.1f}%)")
    print(f"{'='*58}")
    print(f"\n🟢 Fixed by hybrid ({len(fixed_by_hybrid)}):")
    for q in fixed_by_hybrid:
        print(f"   + {q[:80]}")
    print(f"\n🔴 Broken by hybrid ({len(broken_by_hybrid)}):")
    for q in broken_by_hybrid:
        print(f"   - {q[:80]}")

    with open(RESULTS_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nDetailed comparison saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()