"""Step 4: chunks.jsonl -> ChromaDB vector index.

The index is rebuilt from scratch into an empty directory every time, so old
segment folders can never pile up. BM25 is built in memory from the same
chunks.jsonl at app start, so the two indexes cannot disagree.
"""

import os
import shutil

from . import paths

BATCH_SIZE = 100
META_FIELDS = ["doc_id", "oc_number", "series", "title", "issue_date", "status",
               "supersedes", "superseded_by", "category", "page"]


def build_index(chunks: list) -> int:
    import chromadb
    from chromadb.utils import embedding_functions

    chroma_dir = os.path.abspath(paths.CHROMA_DIR)
    if os.path.basename(chroma_dir) != "chroma_db" or not chroma_dir.startswith(paths.DATA):
        raise RuntimeError(f"refusing to rebuild an unexpected directory: {chroma_dir}")
    if os.path.isdir(chroma_dir):
        shutil.rmtree(chroma_dir)
    os.makedirs(chroma_dir)

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=paths.EMBED_MODEL_NAME
    )
    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.create_collection(
        name=paths.COLLECTION_NAME, embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )
    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        collection.add(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["chunk_text"] for c in batch],
            metadatas=[{k: c.get(k, "") or "" for k in META_FIELDS} for c in batch],
        )
        print(f"  embedded {min(start + BATCH_SIZE, len(chunks))}/{len(chunks)}")
    return collection.count()
