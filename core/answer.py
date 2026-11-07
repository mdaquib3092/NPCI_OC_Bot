"""The answer object: what the pipeline returns and the UI renders.

Everything the user sees is in these fields; the UI never shows raw model text.
"""

from dataclasses import asdict, dataclass, field
from typing import Optional

ANSWER_TYPES = {
    "limit_table", "code_result", "summary", "definition", "general", "passages",
    "not_found", "not_public", "refusal", "clarify",
}
STATUSES = {"verified", "partially_verified", "unverified_facts", "not_found"}


@dataclass
class Citation:
    id: str
    oc_number: str
    doc_id: str
    title: str
    quote: str
    issue_date: str = ""
    page: str = ""
    reference: str = ""     # e.g. "UPI Consolidated Circular (18 Sep 2026), clause 14.24.4, p. 22"


@dataclass
class Cell:
    """One value in a table row, with its source."""
    text: str
    value: Optional[float] = None
    unit: str = ""
    effective_date: str = ""
    source_oc: str = ""
    citation_id: str = ""
    fact_id: str = ""
    more_citation_ids: list = field(default_factory=list)   # other quotes that support the same cell


@dataclass
class Row:
    label: str
    status: str                      # "set" | "no_oc_sets_this" | "unconfirmed" | "withdrawn"
    cells: list = field(default_factory=list)   # list[Cell]
    note: str = ""


@dataclass
class Line:
    text: str
    citation_ids: list = field(default_factory=list)


@dataclass
class Obligation:
    who: str
    what: str
    by: str = ""
    citation_ids: list = field(default_factory=list)


@dataclass
class Answer:
    answer_type: str
    language: str = "en"
    verdict: str = ""
    status: str = "not_found"
    table: list = field(default_factory=list)        # list[Row]
    details: list = field(default_factory=list)      # list[Line]
    earlier: list = field(default_factory=list)      # list[Line], labelled superseded
    obligations: list = field(default_factory=list)  # list[Obligation]
    citations: list = field(default_factory=list)    # list[Citation]
    chips: list = field(default_factory=list)        # list[str]
    notice: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def cited(self, citation_id: str) -> Optional[Citation]:
        return next((c for c in self.citations if c.id == citation_id), None)

    def text(self) -> str:
        """All user-visible text except quotes, for number checks and eval."""
        parts = [self.verdict, self.notice]
        for r in self.table:
            parts.append(r.label)
            parts.extend(c.text for c in r.cells)
            parts.append(r.note)
        parts.extend(l.text for l in self.details)
        parts.extend(l.text for l in self.earlier)
        for o in self.obligations:
            parts.extend([o.who, o.what, o.by])
        return "\n".join(p for p in parts if p)

    def cited_doc_oc_numbers(self) -> set:
        return {c.oc_number for c in self.citations if c.oc_number}
