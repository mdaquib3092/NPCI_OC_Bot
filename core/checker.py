"""The checker: nothing is shown unless it passes (fail closed).

Rules (FSD CH-1 to CH-7):
- every citation quote is found in the source it is attributed to
- every amount in a table cell is visible in that cell's quote
- every number in free text (verdict, details, obligations) appears in a cited quote
- every OC number mentioned exists in the evidence
- every statement in a model-written answer carries a citation
"""

import re
from dataclasses import dataclass, field

from ingest.facts import number_in_quote

_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DATE = re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b(?:,?\s+\d{{4}})?|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|\b{_MONTH}\s+\d{{4}}", re.I)
_ISO_DATE = re.compile(r"\b(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2}\b")
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60, "ninety": 90}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.I)
_OC_REF = re.compile(r"\bOC[\s\-]*(?:No\.?)?\s*0*(\d{1,3})\s?([A-F])?(?![A-Za-z0-9])", re.I)
_NUMBER = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)(?:\s*(lakhs?|lacs?|crores?|k)\b)?", re.I)


@dataclass
class CheckResult:
    ok: bool
    reasons: list = field(default_factory=list)


def _norm(s: str) -> str:
    """Compare text ignoring case, whitespace, quote and dash styles and the rupee glyph."""
    s = (s or "").replace("₹", "rs ").replace("£", "rs ")
    s = re.sub(r"[‘’‚‛`´]", "'", s)
    s = re.sub(r"[“”„]", '"', s)
    s = re.sub(r"[–—‑]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_numbers(text: str) -> set:
    """Every number in `text` as a plain digit string, including 'N lakh', 'N crore' and 'NK' expanded."""
    out = {str(_WORDS[m.group(1).lower()]) for m in _NUMBER_WORD.finditer(text or "")}   # "three months" supports "3"
    for m in _NUMBER.finditer(text or ""):
        digits = m.group(1).replace(",", "")
        out.add(digits.rstrip("0").rstrip(".") if "." in digits else digits)
        unit = (m.group(2) or "").lower()
        mult = {"l": 100000, "c": 10000000, "k": 1000}.get(unit[:1] if unit else "", 0)
        if mult:
            try:
                out.add(str(int(round(float(digits) * mult))))
            except ValueError:
                pass
    return out


def free_text_numbers(text: str) -> list:
    """Numbers a reader would take as a claim: amounts, counts, codes. Dates, years and OC numbers are masked."""
    masked = _OC_REF.sub(" OCREF ", text or "")
    masked = _ISO_DATE.sub(" DATE ", masked)
    masked = _DATE.sub(" DATE ", masked)
    out = []
    for m in _NUMBER.finditer(masked):
        raw = m.group(1).replace(",", "")
        unit = (m.group(2) or "").lower()
        if re.fullmatch(r"(19|20)\d{2}", raw) and not unit:
            continue                                   # a bare year
        if raw.isdigit() and int(raw) < 10 and not unit and not re.match(
                r"\s*(transactions?|times|days|months|hours|per cent|%)", masked[m.end():m.end() + 14], re.I):
            continue                                   # list numbers and tiny counts in prose
        digits = raw.rstrip("0").rstrip(".") if "." in raw else raw
        if unit:
            mult = {"l": 100000, "c": 10000000, "k": 1000}[unit[0]]
            digits = str(int(round(float(raw) * mult)))
        out.append(digits)
    return out


_ELLIPSIS = re.compile(r"\s*(?:\.{3}|…)\s*")


def _quote_in(text: str, quote: str) -> bool:
    """The quote, or every part of it in order when the writer joined parts with '...'."""
    parts = [p for p in _ELLIPSIS.split(_norm(quote)) if p]
    if not parts or any(len(p) < 12 for p in parts):
        return False
    pos = 0
    for part in parts:
        i = text.find(part, pos)
        if i < 0:
            return False
        pos = i + len(part)
    return True


def _in_sources(quote: str, doc_id: str, sources: list) -> bool:
    return any(d == doc_id and _quote_in(_norm(t), quote) for d, t in sources)


def check(answer, sources: list, reviewed_text: list = ()) -> CheckResult:
    """`sources` is a list of (doc_id, text): the evidence passages, or the quotes of the facts used.
    `reviewed_text` is extra reviewed wording (fact conditions and notes): OC numbers in it are
    allowed in the answer, but it can never satisfy a quote check."""
    reasons = []
    if not answer.verdict.strip():
        reasons.append("empty verdict")
    if answer.language == "hinglish" and re.search(r"[\u0900-\u097F]", answer.text()):
        reasons.append("write Hindi words in Roman letters, not Devanagari script")
    cites = {c.id: c for c in answer.citations}
    for c in answer.citations:
        if not _in_sources(c.quote, c.doc_id, sources):
            reasons.append(f"citation {c.id}: quote not found in the source ({c.quote[:60]!r})")

    for row in answer.table:
        for cell in row.cells:
            c = cites.get(cell.citation_id)
            if c is None:
                reasons.append(f"cell '{cell.text}' has no citation")
            elif cell.value is not None and not number_in_quote(str(int(cell.value)), cell.unit, c.quote):
                reasons.append(f"cell '{cell.text}': value {int(cell.value)} not visible in its quote")

    free = answer.answer_type in ("summary", "definition", "general")
    if free:
        for group, name in ((answer.details, "detail"), (answer.earlier, "earlier"), (answer.obligations, "obligation")):
            for i, item in enumerate(group, 1):
                if not item.citation_ids or any(cid not in cites for cid in item.citation_ids):
                    reasons.append(f"{name} {i} has no valid citation")
        quoted = set()
        for c in answer.citations:
            quoted |= quote_numbers(c.quote)
        for n in dict.fromkeys(free_text_numbers(answer.text())):
            if n not in quoted:
                reasons.append(f"number {n} in the answer is not in any cited quote")

    allowed = {c.oc_number.upper() for c in answer.citations if c.oc_number}
    for text in [t for _d, t in sources] + list(reviewed_text):
        for m in _OC_REF.finditer(text):
            allowed.add(f"{int(m.group(1))}{(m.group(2) or '').upper()}")
    for m in _OC_REF.finditer(answer.text()):
        n = f"{int(m.group(1))}{(m.group(2) or '').upper()}"
        if n not in allowed:
            reasons.append(f"OC {n} is mentioned but not in the evidence")
    return CheckResult(not reasons, reasons)
