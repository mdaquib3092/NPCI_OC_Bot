"""Evidence from the reviewed facts: limit tables and code lookups.

Pure data selection: no model, no formatting of user text. The writer turns this into an answer.
"""

import re
from dataclasses import dataclass, field

# (limit_kind, direction, merchant_type or None, label)
ROW_SPECS = {
    "P2P": [
        ("per_txn_amount", "send", None, "Per transaction (pay)"),
        ("collect_per_txn", "send", None, "Collect request, per transaction"),
        ("qr_share_pay_per_txn", "send", None, "QR share & pay, per transaction"),
        ("per_24h_amount", "send", None, "Total amount sent in 24 hours"),
        ("per_24h_count", "send", None, "Number of transactions sent in 24 hours"),
        ("per_24h_count", "receive", None, "P2P credits received in 24 hours (count)"),
        ("per_24h_amount", "receive", None, "P2P credits received in 24 hours (amount)"),
    ],
    "P2PM": [
        ("per_txn_amount", "send", None, "Per transaction (pay)"),
        ("collect_per_txn", "send", None, "Collect request, per transaction"),
        ("per_txn_amount", "receive", None, "Inward credit to a P2PM merchant, per transaction"),
        ("per_24h_amount", "receive", None, "Inward credit to a P2PM merchant, per 24 hours"),
        ("per_month_amount", "receive", None, "Inward credit to a P2PM merchant, per month"),
    ],
    "P2M": [
        ("per_txn_amount", "send", "all", "Per transaction (all P2M)"),
        ("per_txn_amount", "send", "non_verified_offline", "Per transaction, non-verified offline merchants"),
        ("qr_share_pay_per_txn", "send", "non_verified_offline", "QR share & pay, non-verified offline merchants"),
        ("per_txn_amount", "send", "specific_categories", "Per transaction, verified merchants in specific categories"),
    ],
    "UPI_LITE": [
        ("per_txn_amount", "send", None, "UPI Lite: per transaction"),
        ("max_balance", "send", None, "UPI Lite: total balance at any point in time"),
    ],
    "UPI_LITE_X": [
        ("per_txn_amount", "send", None, "UPI Lite X (offline): per transaction"),
        ("max_balance", "send", None, "UPI Lite X (offline): total balance at any point in time"),
    ],
    "ON_DEVICE_BIOMETRIC": [
        ("per_txn_amount", "send", None, "Per transaction with on-device biometric authentication"),
    ],
}

# keyword in the question -> substring of a fact's category_name (lower case)
CATEGORY_KEYWORDS = [
    (r"jewel", "jewellery"), (r"insurance", "insurance"), (r"capital market|mutual fund", "capital market"),
    (r"travel", "travel"), (r"\btax", "tax payments"), (r"hospital|medical", "hospitals"),
    (r"educat|school|college|universit", "educational"), (r"credit card", "credit card"),
    (r"\bcollections?\b|\bloans?\b|\bemis?\b", "collections"), (r"\bgem\b|government e|emd", "government e-market"),
    (r"forex|\bfx\b", "fx retail"), (r"term deposit", "term deposits"), (r"account opening", "digital account opening"),
    (r"\bipo\b|g-?sec|retail direct|\brds\b|asba", "ipo|capital market"), (r"pre-?approved|business", "business/merchant"),
]


@dataclass
class RowEvidence:
    label: str
    kind: str
    direction: str
    status: str                       # set | no_oc_sets_this | unconfirmed
    facts: list = field(default_factory=list)      # served facts that state the limit
    earlier: list = field(default_factory=list)    # superseded facts in the chain
    note: str = ""


@dataclass
class LimitEvidence:
    txn_type: str
    rows: list
    category: str = ""
    hint: str = ""
    unverified: bool = False


def _earlier(all_served: list, current: dict) -> list:
    """Superseded facts that lead, directly or through other superseded facts, to `current`."""
    out, frontier = [], [current["fact_id"]]
    while frontier:
        target = frontier.pop()
        for f in all_served:
            if f["status"] == "superseded" and f["superseded_by_fact"] == target and f not in out:
                out.append(f)
                frontier.append(f["fact_id"])
    return sorted(out, key=lambda f: f["effective_date"] or "", reverse=True)


def _row(stores, txn, kind, direction, merchant, label) -> RowEvidence:
    pool = [f for f in stores.facts if f["txn_type"] == txn and f["limit_kind"] == kind
            and (f["direction"] or "send") == direction and (merchant is None or f["merchant_type"] == merchant)
            and not f["mcc"]]
    current = [f for f in pool if f["status"] == "current"]
    unclear = [f for f in pool if f["status"] == "unclear"]
    withdrawn = [f for f in pool if f["status"] == "withdrawn"]
    row = RowEvidence(label=label, kind=kind, direction=direction, status="no_oc_sets_this", earlier=list(withdrawn))
    if current:
        row.status, row.facts = "set", sorted(current, key=lambda f: f["fact_id"])
        for f in row.facts:
            row.earlier.extend(x for x in _earlier(stores.facts, f) if x not in row.earlier)
    elif unclear:
        row.status, row.facts = "unconfirmed", unclear
    return row


def _prefer_asked_first(rows: list, plan) -> list:
    def rank(r):
        want_kind = plan.limit_kind and r.kind == plan.limit_kind
        want_dir = (not plan.direction) or r.direction == plan.direction
        return 0 if (want_kind and want_dir) else (1 if want_kind else 2)
    return sorted(rows, key=rank)  # sorted() is stable: other rows keep their order


def category_keywords(text: str) -> list:
    low = (text or "").lower()
    return [sub for rx, sub in CATEGORY_KEYWORDS if re.search(rx, low)]


def _category_rows(stores, mcc: str, subs: list) -> list:
    wanted = [part for s in subs for part in s.split("|")]      # a keyword may stand for several categories
    pool = [f for f in stores.facts if f["txn_type"] == "P2M" and f["status"] in ("current",)
            and ((mcc and f["mcc"] == mcc) or (wanted and any(w in f["category_name"].lower() for w in wanted)))]
    groups = {}
    for f in pool:
        groups.setdefault((f["category_name"].lower(), f["limit_kind"]), []).append(f)
    rows = []
    for (cat, kind), fs in sorted(groups.items()):
        label_cat = fs[0]["category_name"]
        label = f"{label_cat}: " + ("per transaction" if kind == "per_txn_amount" else "cumulative in 24 hours")
        row = RowEvidence(label=label, kind=kind, direction="send", status="set", facts=sorted(fs, key=lambda f: (f["mcc"], f["fact_id"])))
        for f in fs:
            row.earlier.extend(x for x in _earlier(stores.facts, f) if x not in row.earlier)
        rows.append(row)
    rows.sort(key=lambda r: (0 if r.kind == "per_txn_amount" else 1, r.label))
    return rows


def limit_evidence(stores, plan):
    """Limit table for the planned transaction type / MCC / category. None if there is nothing to show."""
    subs = category_keywords(plan.term)
    if plan.mcc or (plan.txn_type == "P2M" and subs):
        rows = _category_rows(stores, plan.mcc, subs)
        if not rows:
            return None
        return LimitEvidence("P2M", rows, category=rows[0].facts[0]["category_name"],
                             unverified=stores.unverified_facts_in_use)
    txn = plan.txn_type
    if txn not in ROW_SPECS:
        return None
    specs = list(ROW_SPECS[txn])
    if txn == "UPI_LITE":
        specs += ROW_SPECS["UPI_LITE_X"]
    rows = []
    for spec in specs:
        t = "UPI_LITE_X" if spec[3].startswith("UPI Lite X") else txn
        rows.append(_row(stores, t, *spec))
    if not any(r.status != "no_oc_sets_this" for r in rows):
        return None
    ev = LimitEvidence(txn, _prefer_asked_first(rows, plan), unverified=stores.unverified_facts_in_use)
    if txn == "P2M":
        ev.hint = "p2m_hint"
    return ev


# ------------------------------------------------------------------ codes
@dataclass
class CodeEvidence:
    outcome: str                      # specific_rule | mention_only | not_mentioned | reverse
    family: str
    code: str
    mentions: list = field(default_factory=list)      # code_mentions rows
    limit: object = None                              # LimitEvidence when outcome == specific_rule
    reverse: list = field(default_factory=list)       # [(mcc, category_name, fact)]


def code_evidence(stores, plan):
    if plan.reverse:
        subs = category_keywords(plan.term)
        found = {}
        for f in stores.facts:
            if f["mcc"] and f["status"] == "current" and any(s in f["category_name"].lower() for s in subs):
                found.setdefault(f["mcc"], f)
        return CodeEvidence("reverse", "mcc", "", reverse=[(m, f["category_name"], f) for m, f in sorted(found.items())])
    family, code = ("mcc", plan.mcc) if plan.mcc else ("purpose_code", plan.purpose_code)
    mentions = [m for m in stores.codes if m["code_family"] == family and m["code"] == code]
    limit = None
    if family == "mcc":
        limit = limit_evidence(stores, plan)
    if limit:
        return CodeEvidence("specific_rule", family, code, mentions, limit)
    if mentions:
        return CodeEvidence("mention_only", family, code, mentions)
    return CodeEvidence("not_mentioned", family, code)
