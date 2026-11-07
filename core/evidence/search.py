"""Hybrid search over the chunks: BM25 and vectors fused with reciprocal rank fusion.

The vector side needs the Chroma index; if it is missing (for example in tests) the
search degrades to BM25 only.
"""

import os
import re

from rank_bm25 import BM25Okapi

from ingest import paths

from .documents import Evidence, EvidencePack
from .synonyms import expand

RRF_K = 60
CANDIDATES = 20
MAX_COSINE_DISTANCE = 0.8


def _tok(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


class Searcher:
    def __init__(self, stores, use_vectors: bool = True):
        self.stores = stores
        self.chunks = stores.chunks
        self._id_to_idx = {c["chunk_id"]: i for i, c in enumerate(self.chunks)}
        self.bm25 = BM25Okapi([_tok(c["title"] + " " + c["chunk_text"]) for c in self.chunks]) if self.chunks else None
        self.collection = self._open_collection() if use_vectors else None

    def _open_collection(self):
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            if not os.path.isdir(paths.CHROMA_DIR):
                return None
            fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=paths.EMBED_MODEL_NAME)
            return chromadb.PersistentClient(path=paths.CHROMA_DIR).get_collection(paths.COLLECTION_NAME, embedding_function=fn)
        except Exception:
            return None

    def _bm25(self, query: str) -> list:
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(_tok(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:CANDIDATES]
        return [i for i in ranked if scores[i] > 0]

    def _vector(self, query: str) -> list:
        if self.collection is None:
            return []
        res = self.collection.query(query_texts=[query], n_results=CANDIDATES)
        out = []
        for cid, dist in zip(res["ids"][0], res.get("distances", [[]])[0]):
            if dist <= MAX_COSINE_DISTANCE and cid in self._id_to_idx:
                out.append(self._id_to_idx[cid])
        return out

    def search(self, query: str, top_k: int = None) -> EvidencePack:
        s = self.stores.settings
        top_k = top_k or s.top_k
        scores = {}
        query = expand(query)
        for ranking in (self._bm25(query), self._vector(query)):
            for rank, idx in enumerate(ranking):
                scores[idx] = scores.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
        order = sorted(scores, key=scores.get, reverse=True)
        docs = {self.chunks[i]["doc_id"] for i in order}
        picked = []
        for idx in order:
            if len(picked) < top_k:
                picked.append(idx)
        # a hit is often a fragment: add the chunk after it (same document) so the model sees the sentence's context
        extra = []
        for idx in picked:
            nxt = idx + 1
            if nxt < len(self.chunks) and self.chunks[nxt]["doc_id"] == self.chunks[idx]["doc_id"] and nxt not in picked + extra:
                extra.append(nxt)
        pack, used = EvidencePack(), 0
        for idx in sorted(picked + extra):          # chunks.jsonl is in document order
            c = self.chunks[idx]
            if len(pack.items) >= s.max_evidence_chunks or used + len(c["chunk_text"]) > s.max_evidence_chars:
                break
            pack.items.append(Evidence(f"E{len(pack.items) + 1}", c["doc_id"], c["oc_number"] or ("CC" if c.get("series") == "CC" else ""), c["title"],
                                       c["issue_date"], c["chunk_text"], c.get("status", ""), c.get("page", "")))
            used += len(c["chunk_text"])
        pack.coverage_docs = len(docs)
        return pack
