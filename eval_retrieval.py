"""
Evaluate retrieval accuracy of the NPCI OC search system.

Reads:  eval_test_set.csv   (question, expected_oc_number, expected_keywords, notes)
        Data/chroma_db/     (the built index)

For each question, runs the same retrieval logic as app.py (OC-number
detection -> exact fetch, else semantic search) and checks:
  - Hit@k: is the expected_oc_number among the retrieved OC numbers?
  - Keyword coverage: do any of the expected_keywords appear in the
    retrieved chunk text? (rough proxy for "the right content surfaced")

This evaluates RETRIEVAL only — not whether the LLM's final generated
answer is correct. For that, use eval_answers.py (manual grading) after
this.

Run:
    python eval_retrieval.py
"""

import csv
import os
import re

import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = os.path.join("Data", "chroma_db")
COLLECTION_NAME = "npci_oc_chunks"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
TEST_SET_PATH = "eval_test_set.csv"
RESULTS_PATH = "eval_retrieval_results.csv"

TOP_K = 10


def extract_oc_number_from_query(query: str) -> str:
    match = re.search(r"\bOC[\s\-]?0*(\d+[A-Z]?)\b", query, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return ""


# Domain acronyms whose full meaning embeddings don't always capture well —
# map them directly to the OC number(s) that define them.
ACRONYM_TO_OC = {
    "udir": "165",
    "odr": "145",
    "afa": "151",
    "tpap": "159",
}


def extract_acronym_oc(query: str) -> str:
    lower = query.lower()
    for acronym, oc in ACRONYM_TO_OC.items():
        if re.search(rf"\b{acronym}\b", lower):
            return oc
    return ""


def load_collection():
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL_NAME
    )
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_collection(name=COLLECTION_NAME, embedding_function=embed_fn)


def retrieve(collection, question: str, top_k: int = TOP_K):
    oc_number = extract_oc_number_from_query(question)
    if oc_number:
        results = collection.get(where={"oc_number": oc_number}, limit=50)
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        if docs:
            return docs, metas

    acronym_oc = extract_acronym_oc(question)
    if acronym_oc:
        results = collection.get(where={"oc_number": acronym_oc}, limit=50)
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        if docs:
            return docs, metas

    results = collection.query(
        query_texts=[question], n_results=top_k, where={"category": "UPI"}
    )
    return results["documents"][0], results["metadatas"][0]


def read_csv_robust(path):
    """Try multiple encodings — Excel/Numbers often re-save CSVs as
    Windows-1252 or similar instead of UTF-8."""
    encodings_to_try = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_error = None
    for enc in encodings_to_try:
        try:
            with open(path, newline="", encoding=enc) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError as e:
            last_error = e
            continue
    raise last_error


def main():
    if not os.path.isfile(TEST_SET_PATH):
        print(f"{TEST_SET_PATH} not found. Create your golden test set first.")
        return

    collection = load_collection()

    test_cases = read_csv_robust(TEST_SET_PATH)

    print(f"Running {len(test_cases)} test questions...\n")

    hits = 0
    keyword_hits = 0
    rows = []

    for i, case in enumerate(test_cases, start=1):
        question = case["question"]
        expected_oc_raw = case["expected_oc_number"].strip().upper()
        expected_ocs = [oc.strip() for oc in expected_oc_raw.split(",") if oc.strip()]
        expected_keywords = [
            kw.strip().lower() for kw in case.get("expected_keywords", "").split(",") if kw.strip()
        ]

        docs, metas = retrieve(collection, question)
        retrieved_ocs = [m.get("oc_number", "").upper() for m in metas]
        combined_text = " ".join(docs).lower()

        oc_hit = any(exp_oc in retrieved_ocs for exp_oc in expected_ocs)
        keyword_hit = any(kw in combined_text for kw in expected_keywords) if expected_keywords else None

        if oc_hit:
            hits += 1
        if keyword_hit:
            keyword_hits += 1

        status = "✅ HIT" if oc_hit else "❌ MISS"
        print(f"[{i}/{len(test_cases)}] {status} — {question}")
        print(f"    Expected OC: {expected_oc_raw} | Retrieved OCs: {sorted(set(retrieved_ocs))}")

        rows.append(
            {
                "question": question,
                "expected_oc_number": expected_oc_raw,
                "retrieved_oc_numbers": ";".join(sorted(set(retrieved_ocs))),
                "oc_hit": oc_hit,
                "keyword_hit": keyword_hit,
            }
        )

    total = len(test_cases)
    hit_rate = hits / total * 100 if total else 0
    keyword_rate = keyword_hits / total * 100 if total else 0

    print(f"\n{'='*50}")
    print(f"Retrieval Hit Rate (correct OC in results): {hits}/{total} ({hit_rate:.1f}%)")
    print(f"Keyword Coverage Rate: {keyword_hits}/{total} ({keyword_rate:.1f}%)")
    print(f"{'='*50}")

    with open(RESULTS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nDetailed results saved to {RESULTS_PATH}")

    if hit_rate < 70:
        print(
            "\nHit rate below 70% — consider: increasing TOP_K, checking chunk "
            "size (too large/small chunks hurt retrieval), or verifying your "
            "expected_oc_number values are correct in the test set."
        )


if __name__ == "__main__":
    main()