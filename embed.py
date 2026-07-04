"""
Phase 3: Embed chunks and build a searchable ChromaDB index.

Reads:  Data/chunks.jsonl        (from chunk.py)
Writes: Data/chroma_db/          (persistent ChromaDB vector store)

Uses sentence-transformers (all-MiniLM-L6-v2) — small, fast, runs locally,
no API key needed.

Run:
    python embed.py
"""

import json
import os

import chromadb
from chromadb.utils import embedding_functions

CHUNKS_PATH = os.path.join("Data", "chunks.jsonl")
CHROMA_DIR = os.path.join("Data", "chroma_db")
COLLECTION_NAME = "npci_oc_chunks"

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 100  # embed/add in batches to keep memory usage reasonable


def load_chunks():
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def main():
    if not os.path.isfile(CHUNKS_PATH):
        print(f"{CHUNKS_PATH} not found. Run chunk.py first.")
        return

    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH}")

    print(f"Loading embedding model: {EMBED_MODEL_NAME} (first run downloads it, ~90MB)...")
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL_NAME
    )

    os.makedirs(CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # Fresh start each run — drop and recreate the collection
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    total = len(chunks)
    for start in range(0, total, BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]

        ids = [c["chunk_id"] for c in batch]
        documents = [c["chunk_text"] for c in batch]
        metadatas = [
            {
                "oc_number": c.get("oc_number", ""),
                "title": c.get("title", ""),
                "date": c.get("date", ""),
                "category": c.get("category", ""),
                "supersedes": c.get("supersedes", ""),
                "superseded_by": c.get("superseded_by", ""),
                "source_filename": c.get("source_filename", ""),
            }
            for c in batch
        ]

        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        print(f"Embedded {min(start + BATCH_SIZE, total)}/{total} chunks")

    print(f"\nDone. Vector index built at {CHROMA_DIR}/")
    print(f"Collection '{COLLECTION_NAME}' contains {collection.count()} chunks.")
    print("\nQuick test query:")

    # Sanity-check query
    test_query = "UPI Lite wallet limit"
    results = collection.query(query_texts=[test_query], n_results=3)
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        print(f"\n  OC {meta.get('oc_number')} — {meta.get('title', '')[:60]}")
        print(f"  {doc[:150]}...")

    print("\nNext step: build the Streamlit app (app.py) for search + Q&A.")


if __name__ == "__main__":
    main()