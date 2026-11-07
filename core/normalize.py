"""Turn a raw question into text the router can match, and pull out identifiers."""

import re
import unicodedata

HINGLISH_WORDS = {
    "kya", "kitna", "kitni", "kitne", "hai", "hain", "batao", "bataiye", "bolta", "kehta", "kab",
    "kaunsa", "kaun", "kaise", "mein", "abhi", "mera", "meri", "mere", "apni", "apne", "nahi",
    "samjhao", "hota", "hoga", "hui", "hua", "wala", "wali", "karo", "rupaye", "rupaiye", "pehle",
    "dukaan", "chalega", "lena", "padega", "mahine", "din", "kaha", "ya",
}

_OC_ID = re.compile(r"\b(?:oc|circular|circ)\s*(?:no\.?|number|#)?\s*[-.:/]?\s*0*(\d{1,3})\s*[-]?\s*([a-f])?(?![a-z0-9])", re.I)
_MCC = re.compile(r"\bmccs?\s*(?:code)?\s*[-:#]?\s*(\d{4})\b", re.I)
_PURPOSE = re.compile(r"\bpurpose\s*codes?\s*[-:#]?\s*(\d{2}|[a-z]{2})\b", re.I)


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("₹", " rs ").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip()


def tokens(text: str) -> list:
    return re.findall(r"[a-z0-9]+", normalize(text).lower())


def detect_language(text: str) -> str:
    return "hinglish" if HINGLISH_WORDS & set(tokens(text)) else "en"


def find_oc_numbers(text: str) -> list:
    """OC numbers mentioned, e.g. 'OC 185A', 'oc-76', 'circular no. 141 b' -> ['185A', '76', '141B']."""
    out = []
    for m in _OC_ID.finditer(normalize(text)):
        n = f"{int(m.group(1))}{(m.group(2) or '').upper()}"
        if n not in out:
            out.append(n)
    return out


def find_mcc(text: str) -> list:
    return list(dict.fromkeys(_MCC.findall(normalize(text))))


def find_purpose_codes(text: str) -> list:
    return [c.upper() for c in dict.fromkeys(_PURPOSE.findall(normalize(text)))]
