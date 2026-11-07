import pytest

from ingest import codes as C
from ingest import facts as F
from ingest import review as RV


def _fact(**kw):
    base = dict.fromkeys(F.COLUMNS, "")
    base.update(fact_id="X-1", domain="UPI", txn_type="P2P", limit_kind="per_txn_amount", direction="send",
                value="100000", unit="INR", source_oc="120", source_doc_id="UPI-120",
                quote="| P2P / P2PM | Pay | 1 Lakh |", status="current", review_status="auto_checked")
    base.update(kw)
    return base


REG = [{"doc_id": "UPI-120"}]
TEXTS = {"UPI-120": "Annexure A\n| P2P / P2PM | Pay | 1 Lakh |\n| P2P / P2PM | Collect | 2K |"}


@pytest.mark.parametrize("value,unit,quote,ok", [
    ("100000", "INR", "| P2P | Pay | 1 Lakh |", True),
    ("200000", "INR", "enhanced to ₹ 2 lakhs for", True),
    ("2000", "INR", "| Collect | 2K |", True),
    ("2000", "INR", "limit of INR 2000/- for all", True),
    ("10000", "INR", "| Per transaction | Rs. 10,000 |", True),
    ("500000", "INR", "| ₹ 5 Lakh | ₹ 10 Lakh |", True),
    ("5000", "INR", "from ₹25,000 to ₹10,000", False),      # 25,000 is not 5,000
    ("1000000", "INR", "₹ 5 Lakh", False),
    ("50", "count", "capped at 50 successful transactions", True),
    ("25", "count", "capped at 250 successful transactions", False),
])
def test_number_must_be_visible_in_the_quote(value, unit, quote, ok):
    assert F.number_in_quote(value, unit, quote) is ok


def test_valid_fact_passes():
    assert F.validate([_fact()], TEXTS, REG) == []


def test_quote_must_exist_in_the_source():
    msgs = [m for _, _, m in F.validate([_fact(quote="| P2P / P2PM | Pay | 5 Lakh |", value="500000")], TEXTS, REG)]
    assert any("not found in the source" in m for m in msgs)


def test_superseded_needs_a_target_and_human_verified_needs_a_reviewer():
    bad = [_fact(status="superseded"), _fact(fact_id="X-2", review_status="human_verified")]
    msgs = [m for _, _, m in F.validate(bad, TEXTS, REG)]
    assert any("superseded_by_fact" in m for m in msgs)
    assert any("without reviewer" in m for m in msgs)
    ok = [_fact(status="superseded", superseded_by_fact="X-2"), _fact(fact_id="X-2")]
    assert F.validate(ok, TEXTS, REG) == []


def test_only_human_verified_facts_are_served():
    rows = [_fact(), _fact(fact_id="X-2", review_status="human_verified", reviewer="A", reviewed_on="2026-10-22")]
    assert [f["fact_id"] for f in F.servable(rows)] == ["X-2"]


def test_review_import_marks_only_verified_rows():
    facts = [_fact(), _fact(fact_id="X-2"), _fact(fact_id="X-3")]
    res = RV.apply_decisions(facts, [
        {"fact_id": "X-1", "Decision": "Verified"},
        {"fact_id": "X-2", "Decision": "Needs change", "Comment / corrected value": "value is 2 lakh"},
        {"fact_id": "X-3", "Decision": ""},
        {"fact_id": "X-9", "Decision": "Verified"},
    ], "Reviewer", "2026-10-22")
    assert res["verified"] == 1 and res["unknown"] == ["X-9"] and res["needs_change"][0][0] == "X-2"
    assert facts[0]["review_status"] == "human_verified" and facts[0]["reviewer"] == "Reviewer"
    assert facts[1]["review_status"] == "auto_checked" and facts[2]["review_status"] == "auto_checked"


def test_code_lookup_has_three_outcomes():
    rows = [
        {"code_family": "mcc", "code": "6211", "rule_type": "limit"},
        {"code_family": "mcc", "code": "7407", "rule_type": "requirement"},
    ]
    assert C.lookup(rows, "mcc", "6211")["outcome"] == "specific_rule"
    assert C.lookup(rows, "mcc", "7407")["outcome"] == "mention_only"
    assert C.lookup(rows, "mcc", "1520")["outcome"] == "not_mentioned"


def test_scan_finds_mcc_lists_and_ignores_years():
    row = {"doc_id": "UPI-1", "oc_number": "1", "issue_date": "2020-01-01"}
    text = "Insurance MCC - 5960, 6300, 6529. The circular dated 2019 says MCC 7407 shall be used."
    got = {r["code"]: r["rule_type"] for r in C.scan_document(row, text)}
    assert {"5960", "6300", "6529", "7407"} <= set(got) and "2019" not in got
    assert got["7407"] == "requirement"  # never "limit" from wording alone


def test_closed_by_quote_must_exist_in_the_closing_document():
    f = [{"fact_id": "A", "txn_type": "P2P", "limit_kind": "collect_per_txn", "status": "withdrawn", "review_status": "drafted",
          "unit": "INR", "value": "2000", "source_doc_id": "D1", "quote": "Collect 2K", "superseded_by_fact": "",
          "reviewer": "", "reviewed_on": "", "closed_by_doc_id": "D2", "closed_by_quote": "collect is not permitted"}]
    reg = [{"doc_id": "D1"}, {"doc_id": "D2"}]
    ok = F.validate(f, {"D1": "Collect 2K", "D2": "Note: collect is not permitted."}, reg)
    bad = F.validate(f, {"D1": "Collect 2K", "D2": "nothing here"}, reg)
    assert not [i for i in ok if i[0] == "error"]
    assert any("closed_by_quote" in i[2] for i in bad)
