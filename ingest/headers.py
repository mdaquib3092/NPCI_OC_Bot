"""Parse an NPCI circular's header: reference number, date, subject.

NPCI headers look like (OCR noise included):
    NPCI/UPI/2021-22/0C.121 25" October, 2021
    NPCI/2025-26/UPI/221 Sep 12, 2025
    NPCI /UPI/OC No.56/2018-19 August 14, 2018
    NPCI/2024-25/PD/001 23" April 2024
These functions are pure (no I/O) so they are easy to test.
"""

import re

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # keyed by the first three letters, lower case
_MONTH_RE = (r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
             r"Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
_ORD = r"(?:\s?(?:st|nd|rd|th)|st|nd|rd|th|[a-z\d]{0,2}[\"'”“’‘`%\]°¢!™*]{1,3}|[a-z]{1,2})?"

_DMY = re.compile(rf"\b(\d{{1,2}}){_ORD}\s*,?\s*{_MONTH_RE}\.?\s*[\"'”’]?\s*,?\s*(\d{{4}})\b", re.I)
_NUM = re.compile(r"\b(\d{1,2})[/.,](\d{1,2})[/.,](20\d{2})\b")
_DMY2 = re.compile(rf"(?<![\d\-/:.])\b(\d{{1,2}}){_ORD}\s*,?\s*{_MONTH_RE}\.?\s*,?\s*(\d{{2}})\b(?!\d)", re.I)
_MDY = re.compile(rf"\b{_MONTH_RE}\.?\s*(\d{{1,2}}){_ORD}\s*,?\s*(\d{{4}})\b", re.I)


def _iso(y, m, d):
    if not (1 <= m <= 12 and 1 <= d <= 31 and 2015 <= y <= 2035):
        return ""
    return f"{y:04d}-{m:02d}-{d:02d}"


def date_candidates(text: str) -> list:
    """All plausible dates in `text` as (position, 'YYYY-MM-DD'), in text order.
    Two-digit-year dates ('7 November 23') are a fallback used only when the
    text has no four-digit-year date, because they also match noise such as
    '2019-20 June 17'."""
    found = []

    def scan(rx, order):
        for m in rx.finditer(text):
            if order == "dmy":
                d, mon, y = int(m.group(1)), MONTHS[m.group(2)[:3].lower()], int(m.group(3))
            elif order == "mdy":
                mon, d, y = MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
            elif order == "num":
                d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            else:
                d, mon, y = int(m.group(1)), MONTHS[m.group(2)[:3].lower()], 2000 + int(m.group(3))
            iso = _iso(y, mon, d)
            if iso:
                found.append((m.start(), iso))

    for rx, order in ((_DMY, "dmy"), (_MDY, "mdy"), (_NUM, "num")):
        scan(rx, order)
    if not found:
        scan(_DMY2, "dmy2")
    return sorted(set(found))


def parse_date(text: str) -> str:
    """First plausible date in `text` as YYYY-MM-DD, or ''."""
    c = date_candidates(text)
    return c[0][1] if c else ""


def fy_bounds(fy: str):
    """'2021-22' -> ('2021-03-01', '2022-04-30'): the financial year plus one month
    of slack either side (circulars are sometimes dated just outside it)."""
    m = re.match(r"^(20\d{2})-(\d{2})$", fy or "")
    if not m:
        return None
    y = int(m.group(1))
    return f"{y:04d}-03-01", f"{y + 1:04d}-04-30"


def pick_issue_date(head: str, fy: str = "") -> tuple:
    """Choose the issue date from the header. Returns (iso_date, confidence) where
    confidence is 'fy_match', 'first_date' or ''. A date that falls outside the
    document's financial year is probably a referenced circular's date, so it is
    skipped when a consistent one exists."""
    cands = date_candidates(head[:1800])
    if not cands:
        return "", ""
    bounds = fy_bounds(fy)
    if bounds:
        for _pos, iso in cands:
            if bounds[0] <= iso <= bounds[1]:
                return iso, "fy_match"
    return cands[0][1], "first_date"


_FY = re.compile(r"^(20\d{2})\s*-\s*(\d{2,4})$")
_NUM_OC = re.compile(r"(?:[O0]C)?[\s.\-]*(?:No\.?)?[\s.\-]*0*(\d{1,3})\s*([A-E])?(?![A-Za-z0-9])", re.I)


def parse_reference(head: str) -> dict:
    """Find the 'NPCI/...' reference line. Returns
    {reference, fy, product, number, suffix} (missing parts are '')."""
    out = {"reference": "", "fy": "", "product": "", "number": "", "suffix": ""}
    m = re.search(r"NPC[I1lH]\s*[/:][^\n]{0,120}", head[:2500])
    if not m:
        return out
    line = m.group(0)
    # cut the line where the date starts
    for rx in (_DMY, _MDY):
        dm = rx.search(line)
        if dm:
            line = line[: dm.start()]
            break
    out["reference"] = re.sub(r"\s+", " ", line).strip(" /")
    tokens = [t.strip() for t in re.split(r"/", line) if t.strip()]
    for tok in tokens[1:] if tokens and tokens[0].upper().startswith("NPC") else tokens:
        fy = _FY.match(tok)
        if fy:
            out["fy"] = f"{fy.group(1)}-{fy.group(2)[-2:]}"
            continue
        if re.fullmatch(r"[A-Za-z]{2,8}", tok) and tok.upper() not in ("OC", "NO"):
            out["product"] = out["product"] or tok
            continue
        nm = _NUM_OC.match(tok)
        if nm:
            out["number"] = nm.group(1)
            out["suffix"] = (nm.group(2) or "").upper()
            if re.match(r"(?i)[O0]C", tok) and not out["product"]:
                out["product"] = "UPI"
    return out


_SUBJECT = re.compile(r"(?im)^[ \t]*(?:Subject|Sub|Re)[ \t]*[:\-–—][ \t]*(.+)$")


def parse_subject(text: str) -> str:
    """The 'Subject:' line. A following line is included only when the subject
    visibly wraps (previous line is near full width and does not end a sentence)."""
    head = text[:4000]
    m = _SUBJECT.search(head)
    if not m:
        return ""
    parts = [m.group(1).strip()]
    rest = head[m.end():].split("\n")[1:]
    for line in rest[:2]:
        prev = parts[-1]
        if not line.strip() or len(prev) < 55 or prev.endswith("."):
            break
        parts.append(line.strip())
    s = re.sub(r"\s+", " ", " ".join(parts)).strip(" -–—:.")
    return s[:220]


_FN_PREFIXES = [
    r"^(?:NPCI\s+)?UPI\s+(?:OC|Circular)\s*(?:No)?\s*\d{1,3}\s*[-]?\s*[A-E]?\b",
    r"^(?:NPCI\s+)?(?:UPI\s+)?(?:Operating\s+|Operation\s+)?(?:OC|Circular|Ciruclar)\s*(?:No)?\s*\d{1,3}\s*[-]?\s*[A-E]?\b",
    r"^(?:NPCI\s+)?UPI\b",
]
_FN_FY = re.compile(r"\bFY\s*(?:20)?\d{2}\s+(?:20)?\d{2}\b", re.I)


def fy_from_filename(name: str) -> str:
    m = re.search(r"FY[\s\-_]*(20)?(\d{2})[\s\-_]+(20)?(\d{2})(?!\d)", name, re.I)
    if not m:
        return ""
    return f"20{m.group(2)}-{m.group(4)}"


def title_from_filename(name: str) -> str:
    """Readable title from a descriptive NPCI filename ('' if nothing descriptive)."""
    stem = re.sub(r"\.pdf$", "", name, flags=re.I)
    stem = re.sub(r"\s*\d{1,2}[.:]\d{2}[.:]\d{2}\s*(AM|PM)?$", "", stem, flags=re.I)
    stem = re.sub(r"[-_–—]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    for _ in range(3):
        before = stem
        for rx in _FN_PREFIXES:
            stem = re.sub(rx, "", stem, flags=re.I).strip()
        stem = _FN_FY.sub("", stem).strip()
        if stem == before:
            break
    stem = re.sub(r"^\W+", "", stem)
    return stem[:220]


def fy_from_head(head: str) -> str:
    """Financial year printed near the top ('2021-22', '2022-2023'), or ''."""
    m = re.search(r"(?<!\d)(20\d{2})\s*[-–—]\s*(20)?(\d{2})(?!\d)", head[:400])
    if not m:
        return ""
    y1, y2 = int(m.group(1)), int(m.group(3))
    return f"{y1}-{y2:02d}" if (y1 + 1) % 100 == y2 else ""
