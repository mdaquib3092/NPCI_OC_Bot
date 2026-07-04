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

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

CHROMA_DIR = os.path.join("Data", "chroma_db")
COLLECTION_NAME = "npci_oc_chunks"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
TEST_SET_PATH = "eval_test_set.csv"
RESULTS_PATH = "eval_retrieval_results.csv"
GROQ_MODEL = "openai/gpt-oss-20b"

TOP_K = 10

SYSTEM_PROMPT_FOR_EVAL = (
    "Answer only from the provided context. Cite OC numbers you draw from "
    "using the format (OC ###). If the answer isn't in the context, say so."
)


def generate_eval_answer(client, question: str, context: str) -> str:
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_FOR_EVAL},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
        max_tokens=500,
        # Reasoning models (gpt-oss) can spend the entire max_tokens budget on
        # hidden chain-of-thought for large contexts and return an empty
        # answer — keep reasoning low so the budget goes to the visible answer.
        extra_body={"reasoning_effort": "low"},
    )
    return response.choices[0].message.content or ""


def extract_cited_ocs(answer: str) -> list:
    """Pull out OC numbers the answer explicitly cites, e.g. '(OC 220)'."""
    matches = re.findall(r"OC\s*(\d+[A-Z]?)", answer, re.IGNORECASE)
    return [m.upper() for m in matches]


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

    groq_client = None
    check_faithfulness = False
    if GROQ_AVAILABLE and os.environ.get("GROQ_API_KEY"):
        groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
        check_faithfulness = True
        print("GROQ_API_KEY found — will also score answer faithfulness.\n")
    else:
        print("No GROQ_API_KEY set — skipping faithfulness scoring (retrieval-only run).\n")

    test_cases = read_csv_robust(TEST_SET_PATH)

    print(f"Running {len(test_cases)} test questions...\n")

    hits = 0
    keyword_hits = 0
    faithful_count = 0
    faithfulness_checked = 0
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

        is_faithful = None
        if check_faithfulness and docs:
            context = "\n\n---\n\n".join(
                f"[OC {m.get('oc_number')}]\n{d}" for d, m in zip(docs, metas)
            )
            try:
                answer = generate_eval_answer(groq_client, question, context)
                cited_ocs = extract_cited_ocs(answer)
                # faithful if every cited OC actually appears among retrieved chunks
                is_faithful = bool(cited_ocs) and all(oc in retrieved_ocs for oc in cited_ocs)
                faithfulness_checked += 1
                if is_faithful:
                    faithful_count += 1
                print(f"    Cited OCs: {cited_ocs} | Faithful: {is_faithful}")
            except Exception as e:
                print(f"    Faithfulness check failed: {e}")

        rows.append(
            {
                "question": question,
                "expected_oc_number": expected_oc_raw,
                "retrieved_oc_numbers": ";".join(sorted(set(retrieved_ocs))),
                "oc_hit": oc_hit,
                "keyword_hit": keyword_hit,
                "faithful": is_faithful,
            }
        )

    total = len(test_cases)
    hit_rate = hits / total * 100 if total else 0
    keyword_rate = keyword_hits / total * 100 if total else 0

    print(f"\n{'='*50}")
    print(f"Retrieval Hit Rate (correct OC in results): {hits}/{total} ({hit_rate:.1f}%)")
    print(f"Keyword Coverage Rate: {keyword_hits}/{total} ({keyword_rate:.1f}%)")
    if faithfulness_checked:
        faithfulness_rate = faithful_count / faithfulness_checked * 100
        print(
            f"Faithfulness Rate (cited OCs actually retrieved): "
            f"{faithful_count}/{faithfulness_checked} ({faithfulness_rate:.1f}%)"
        )
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