"""Evidence from one circular: its registry row and its chunks in reading order."""

import re
from dataclasses import dataclass, field


@dataclass
class Evidence:
    """A numbered passage the writer may cite."""
    id: str
    doc_id: str
    oc_number: str
    title: str
    issue_date: str
    text: str
    status: str = ""
    page: str = ""


@dataclass
class EvidencePack:
    items: list = field(default_factory=list)       # list[Evidence]
    coverage_docs: int = 0                          # how many documents mention the topic
    truncated: bool = False

    def by_id(self, evidence_id: str):
        return next((e for e in self.items if e.id == evidence_id), None)


def _chunk_index(chunk_id: str) -> int:
    m = re.search(r"__(\d+)$", chunk_id)
    return int(m.group(1)) if m else 0


def document_evidence(stores, row: dict) -> EvidencePack:
    chunks = sorted(stores.chunks_by_doc.get(row["doc_id"], []), key=lambda c: _chunk_index(c["chunk_id"]))
    s = stores.settings
    pack, used = EvidencePack(coverage_docs=1), 0
    for c in chunks:
        if len(pack.items) >= s.max_evidence_chunks or used + len(c["chunk_text"]) > s.max_evidence_chars:
            pack.truncated = True
            break
        pack.items.append(Evidence(f"E{len(pack.items) + 1}", row["doc_id"], row["oc_number"] or ("CC" if row.get("series") == "CC" else ""), row["title"],
                                   row["issue_date"], c["chunk_text"], c.get("status", ""), c.get("page", "")))
        used += len(c["chunk_text"])
    return pack
