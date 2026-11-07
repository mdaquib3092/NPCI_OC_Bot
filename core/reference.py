"""Turn a source into a precise reference a reader can look up: document, clause, page."""

import re

from . import phrases as ph

# a numbered clause such as "14.24.4" at the start of a sentence (Consolidated Circular style)
_CLAUSE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2}){1,2})(?=\s+[A-Z'‘“\"])")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def clause_for(quote: str, chunk_text: str) -> str:
    """The nearest clause number at or before the quote inside the chunk, or ''."""
    flat_chunk = re.sub(r"\s+", " ", chunk_text or "")
    flat_quote = re.sub(r"\s+", " ", quote or "").strip()
    pos = flat_chunk.lower().find(flat_quote.lower()[:60]) if flat_quote else -1
    end = len(flat_chunk) if pos < 0 else pos + min(len(flat_quote), 60)
    found = [m.group(1) for m in _CLAUSE.finditer(flat_chunk[:end])]
    return found[-1] if found else ""


def short_date(iso: str) -> str:
    return ph.fmt_date(iso) if iso else ""


def build_reference(doc: dict, page: str = "", clause: str = "") -> str:
    """'UPI Consolidated Circular (18 Sep 2026), clause 14.24.4, p. 22' or 'OC 223 (7 Oct 2025), p. 1'."""
    if doc.get("series") == "CC":
        name = "UPI Consolidated Circular"
    elif doc.get("oc_number"):
        name = f"OC {doc['oc_number']}"
    else:
        name = doc.get("title", "")
    parts = [f"{name} ({short_date(doc.get('issue_date', ''))})" if doc.get("issue_date") else name]
    if clause:
        parts.append(f"clause {clause}" if clause[0].isdigit() else clause)   # "14.24.4" or a label such as "Annexure G, serial 22"
    if page:
        parts.append(f"p. {page}")
    return ", ".join(parts)
