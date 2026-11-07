"""Decide what a question is asking. Rules first; no model is involved.

Order (first match wins):
  OUT_OF_SCOPE -> ADVICE -> BANK_SPECIFIC -> CODE_LOOKUP -> OC_LOOKUP / LIMIT -> CLARIFY -> DEFINITION -> GENERAL
"""

import re
from dataclasses import dataclass, field

from .normalize import detect_language, find_mcc, find_oc_numbers, find_purpose_codes, normalize, tokens

OUT_OF_SCOPE_PATTERNS = re.compile(
    r"\b(ceo|chairman|managing director|salary|headquarters?|who founded|founder|share price|stock price|"
    r"repo rate|inflation|gdp|weather|cricket|bitcoin|crypto|ethereum|gold price|joke|poem|recipe|movie|"
    r"election|prime minister|president)\b", re.I)

ADVICE = re.compile(
    r"\bshould (i|we)\b|\bwhich is better\b|\bbetter (for|option)\b|\brecommend(ation|ed)?\b|\badvice\b|\badvise (me|us)\b|\bworth it\b", re.I)

DOMAIN_WORDS = {
    "upi", "npci", "oc", "circular", "circulars", "mcc", "mccs", "p2p", "p2m", "p2pm", "lite", "autopay",
    "psp", "psps", "tpap", "tpaps", "vpa", "qr", "mandate", "merchant", "merchants", "bank", "banks",
    "udir", "odr", "chargeback", "refund", "dispute", "settlement", "urcs", "acquirer", "acquirers",
    "issuer", "payee", "payer", "collect", "intent", "purpose", "limit", "limits", "tat", "aadhaar",
    "cbdc", "circle", "mapper", "ndc", "rrn", "deemed", "mdr", "fee", "penalty", "compliance",
    "transaction", "transactions", "payment", "payments", "rupay", "imps", "bhim", "biometric",
    "pin", "handle", "app", "apps", "ecosystem", "member", "members", "verified", "wallet", "balance",
    "credit", "debit", "cap", "volume", "attestation", "pcomp", "arbitration", "reconciliation",
}

LIMIT_WORDS = re.compile(
    r"\b(limit|limits|cap|capped|maximum|max|ceiling|kitna|kitni|kitne|how many|how much)\b|"
    r"per[\s-]*transaction|per[\s-]*txn|per month|monthly|mahine", re.I)

BANK_SPECIFIC = re.compile(
    r"\b(my|mera|meri|mere|apni|apne|our)\s+(\w+\s+){0,2}(bank|account|acct|a/c|app)\b|"
    r"\bmy bank\b|\b(sbi|hdfc|icici|axis|kotak|pnb|canara|idfc|phonepe|gpay|google pay|paytm)\b", re.I)

TXN_PATTERNS = [   # order matters
    ("UPI_LITE_X", re.compile(r"\blite[\s-]*x\b", re.I)),
    ("UPI_LITE", re.compile(r"\bupi[\s-]*lite\b|\blite\b", re.I)),
    ("ON_DEVICE_BIOMETRIC", re.compile(r"biometric|fingerprint|face (?:id|unlock|authentication)", re.I)),
    ("P2PM", re.compile(r"\bp2pm\b", re.I)),
    ("P2P", re.compile(r"\bp2p\b|peer[\s-]*to[\s-]*peer|person[\s-]*to[\s-]*person", re.I)),
    ("P2M", re.compile(r"\bp2m\b|person[\s-]*to[\s-]*merchant|merchant payments?", re.I)),
]

CATEGORY_WORDS = re.compile(
    r"jewel|insurance|capital market|mutual fund|travel|tax|hospital|educat|school|college|credit card|"
    r"\bcollections?\b|\bloans?\b|\bemis?\b|government|\bgem\b|forex|\bfx\b|term deposit|account opening|\bipo\b|g-?sec|"
    r"retail direct|business|pre-?approved", re.I)

REVERSE_MCC = re.compile(r"\bwhich mcc\b|\bmcc (?:for|of|used for)\b|\b(?:ka|ke liye)\s+mcc\b|\bmcc code for\b", re.I)

DEFINITION = re.compile(
    r"^(what is|what are|what's|whats|define|meaning of|explain|what does .* mean)\b|"
    r"\bkya hai\b|\bkya hota hai\b|\bmatlab\b|\bkise kehte\b", re.I)

STOP = {
    "what", "is", "the", "a", "an", "of", "on", "in", "for", "to", "and", "or", "are", "kya", "hai", "hain",
    "kitna", "kitni", "kitne", "upi", "mein", "me", "abhi", "current", "currently", "ka", "ki", "ke", "se",
    "limit", "limits", "cap", "maximum", "max", "tell", "me", "about", "please", "batao", "how", "much", "many",
}


@dataclass
class Plan:
    intent: str
    language: str = "en"
    oc_numbers: list = field(default_factory=list)
    txn_type: str = ""
    limit_kind: str = ""        # per_txn_amount | per_24h_amount | per_24h_count | per_month_amount | collect_per_txn | qr_share_pay_per_txn | max_balance
    direction: str = ""         # "" | send | receive
    mcc: str = ""
    purpose_code: str = ""
    term: str = ""              # category / definition term, the question text for category lookups
    reverse: bool = False
    question: str = ""


def detect_txn_type(text: str) -> str:
    for name, rx in TXN_PATTERNS:
        if rx.search(text):
            return name
    return ""


def detect_limit_kind(text: str) -> str:
    t = text.lower()
    if re.search(r"collect", t):
        return "collect_per_txn"
    if re.search(r"qr share|share intent", t):
        return "qr_share_pay_per_txn"
    if re.search(r"balance|total limit|wallet limit", t):
        return "max_balance"
    if re.search(r"month|mahine|30 days", t):
        return "per_month_amount"
    if re.search(r"how many|kitne|number of|count|successful transactions|kitni\s+(\w+\s+)?(transactions?|txns?|payments?|baar)", t):
        return "per_24h_count"
    if re.search(r"24 ?h|24 hours?|daily|per day|a day|ek din|din mein|cumulative", t):
        return "per_24h_amount"
    if re.search(r"per[\s-]*transaction|per[\s-]*txn|ek transaction|single transaction|each transaction", t):
        return "per_txn_amount"
    return ""


def detect_direction(text: str) -> str:
    return "receive" if re.search(r"\b(receiv\w*|credits?|inward|aane|milne)\b", text, re.I) else ""


def _content_tokens(text: str) -> list:
    return [t for t in tokens(text) if t not in STOP]


def route(question: str) -> Plan:
    q = normalize(question)
    plan = Plan(intent="GENERAL", language=detect_language(q), question=question)
    toks = set(tokens(q))
    plan.oc_numbers = find_oc_numbers(q)
    mccs, pcs = find_mcc(q), find_purpose_codes(q)
    plan.mcc, plan.purpose_code = (mccs[0] if mccs else ""), (pcs[0] if pcs else "")
    plan.txn_type = detect_txn_type(q)
    plan.limit_kind = detect_limit_kind(q)
    plan.direction = detect_direction(q)
    has_limit = bool(LIMIT_WORDS.search(q))

    if OUT_OF_SCOPE_PATTERNS.search(q) or not (DOMAIN_WORDS & toks or plan.oc_numbers or mccs):
        plan.intent = "OUT_OF_SCOPE"
        return plan
    if ADVICE.search(q) and not plan.oc_numbers:
        plan.intent = "ADVICE"
        return plan
    if has_limit and BANK_SPECIFIC.search(q) and not plan.oc_numbers:
        plan.intent = "BANK_SPECIFIC"
        return plan
    if mccs or pcs:
        plan.intent = "CODE_LOOKUP"
        return plan
    if REVERSE_MCC.search(q):
        plan.intent, plan.reverse, plan.term = "CODE_LOOKUP", True, q
        return plan
    if plan.oc_numbers:
        plan.intent = "LIMIT" if (has_limit and plan.txn_type) else "OC_LOOKUP"
        return plan
    if has_limit and plan.txn_type:
        plan.intent = "LIMIT"
        return plan
    if has_limit and CATEGORY_WORDS.search(q):
        plan.intent, plan.txn_type, plan.term = "LIMIT", "P2M", q
        return plan
    if has_limit and not _content_tokens(q):
        plan.intent = "CLARIFY"
        return plan
    if DEFINITION.search(q):
        plan.intent, plan.term = "DEFINITION", q
        return plan
    plan.intent, plan.term = "GENERAL", q
    return plan
