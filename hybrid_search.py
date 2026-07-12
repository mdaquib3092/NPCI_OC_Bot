"""
Hybrid Search: BM25 (keyword) + ChromaDB (vector) with Reciprocal Rank Fusion.

Why this exists
---------------
Regulatory text is identifier-dense: "OC 181B", "MCC 7407", "P2PM", "UDIR".
Dense embeddings are weakest exactly there (181A vs 181B look nearly identical
to an embedding model), while BM25 keyword matching is strongest there — and
vice versa for paraphrased/conceptual queries. Fusing both rankings covers
each method's blind spot and retires most of the hand-written keyword hacks.

Usage
-----
    from hybrid_search import HybridSearcher

    searcher = HybridSearcher(chunks_path="Data/chunks.jsonl")   # once, at startup
    docs, metas = searcher.search(collection, "OC 181B P2P limit", top_k=10)

Requires:
    pip install rank-bm25
"""

import json
import os
import re

from rank_bm25 import BM25Okapi

RRF_K = 60          # standard RRF constant — dampens the impact of exact rank
BM25_CANDIDATES = 20
VECTOR_CANDIDATES = 20


def tokenize(text: str) -> list:
    """Lowercase word tokenizer that keeps alphanumeric identifiers intact
    ("181b", "7407", "p2pm" survive as single tokens)."""
    return re.findall(r"[a-z0-9]+", text.lower())


class HybridSearcher:
    def __init__(self, chunks_path: str = os.path.join("Data", "chunks.jsonl")):
        self.chunk_ids = []
        self.chunk_texts = []
        self.chunk_metas = []

        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                self.chunk_ids.append(d["chunk_id"])
                self.chunk_texts.append(d["chunk_text"])
                self.chunk_metas.append(
                    {
                        "oc_number": d.get("oc_number", ""),
                        "title": d.get("title", ""),
                        "date": d.get("date", ""),
                        "category": d.get("category", ""),
                        "supersedes": d.get("supersedes", ""),
                        "superseded_by": d.get("superseded_by", ""),
                        "source_filename": d.get("source_filename", ""),
                    }
                )

        self._id_to_index = {cid: i for i, cid in enumerate(self.chunk_ids)}
        self.bm25 = BM25Okapi([tokenize(t) for t in self.chunk_texts])

    # ------------------------------------------------------------------
    def _bm25_ranking(self, query: str, n: int) -> list:
        """Return chunk indices ranked by BM25 score (best first)."""
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        # Drop zero-score tail — no keyword overlap at all
        return [i for i in ranked[:n] if scores[i] > 0]

    def _vector_ranking(self, collection, query: str, n: int) -> list:
        """Return chunk indices ranked by vector similarity (best first),
        mapped back via chunk_id so both rankings share an index space."""
        results = collection.query(query_texts=[query], n_results=n)
        ids = results["ids"][0]
        distances = results.get("distances", [[]])[0]
        
        valid_indices = []
        for cid, dist in zip(ids, distances):
            if dist <= 0.8: # Cosine distance cutoff
                if cid in self._id_to_index:
                    valid_indices.append(self._id_to_index[cid])
        return valid_indices

    # ------------------------------------------------------------------
    def search(self, collection, query: str, top_k: int = 10):
        """Hybrid retrieval: BM25 + vector rankings fused with RRF.

        Returns (docs, metas) in fused-rank order, mirroring the shape the
        existing retrieve_semantic() returns so it can be swapped in without
        touching downstream code (build_context, chain expansion, etc.).
        """
        bm25_rank = self._bm25_ranking(query, BM25_CANDIDATES)
        vector_rank = self._vector_ranking(collection, query, VECTOR_CANDIDATES)

        rrf_scores = {}
        for rank, idx in enumerate(bm25_rank):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, idx in enumerate(vector_rank):
            rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)

        fused = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)
        top = fused[:top_k]

        docs = [self.chunk_texts[i] for i in top]
        metas = [self.chunk_metas[i] for i in top]
        return docs, metas


if __name__ == "__main__":
    # Standalone smoke test (BM25 side only — no ChromaDB needed):
    searcher = HybridSearcher()
    print(f"Indexed {len(searcher.chunk_ids)} chunks for BM25.")

    for q in ["OC 181B P2P limit", "MCC 7407", "UDIR complaint handling"]:
        idxs = searcher._bm25_ranking(q, 5)
        print(f"\nQuery: {q}")
        for i in idxs:
            print(f"  - OC {searcher.chunk_metas[i]['oc_number']}: "
                  f"{searcher.chunk_texts[i][:90]}...")