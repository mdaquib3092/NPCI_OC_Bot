from core.answer import Answer, Cell, Citation, Line, Row
from core.checker import check, free_text_numbers, quote_numbers

SRC = [("UPI-120", "Annexure A\n| P2P / P2PM | Pay | 1 Lakh |\n| P2P / P2PM | Collect | 2K |"),
       ("UPI-226A", "the per-transaction limit for On-Device Biometric Authentication (fingerprint, face, etc.) in UPI is hereby enhanced from ₹5,000 to ₹10,000, effective 07th August 2026.")]


def _limit_answer(value=100000, quote="| P2P / P2PM | Pay | 1 Lakh |", text="₹1,00,000 (OC 120)"):
    return Answer("limit_table", verdict="Per transaction: ₹1,00,000 (OC 120).",
                  table=[Row("Per transaction", "set", [Cell(text=text, value=value, unit="INR", citation_id="c1")])],
                  citations=[Citation("c1", "120", "UPI-120", "UPI Limit Standardization", quote)])


def test_a_correct_fact_table_passes():
    assert check(_limit_answer(), SRC).ok


def test_wrong_amount_is_rejected():
    r = check(_limit_answer(value=500000), SRC)
    assert not r.ok and any("not visible in its quote" in x for x in r.reasons)


def test_invented_quote_is_rejected():
    r = check(_limit_answer(quote="| P2P / P2PM | Pay | 5 Lakh |"), SRC)
    assert not r.ok and any("not found in the source" in x for x in r.reasons)


def test_quote_must_come_from_the_cited_document():
    a = _limit_answer()
    a.citations[0].doc_id = "UPI-226A"
    assert not check(a, SRC).ok


def test_ellipsis_joins_parts_in_order():
    q = "per-transaction limit for On-Device Biometric Authentication ... enhanced from ₹5,000 to ₹10,000"
    a = Answer("summary", verdict="Limit raised from ₹5,000 to ₹10,000.", details=[Line("Raised.", ["c1"])],
               citations=[Citation("c1", "226A", "UPI-226A", "t", q)])
    assert check(a, SRC).ok
    a.citations[0].quote = "enhanced from ₹5,000 to ₹10,000 ... per-transaction limit for On-Device Biometric Authentication"
    assert not check(a, SRC).ok                       # wrong order


def test_free_text_number_must_be_in_a_quote():
    q = "enhanced from ₹5,000 to ₹10,000, effective 07th August 2026."
    good = Answer("summary", verdict="Raised to ₹10,000 from ₹5,000 on 7 August 2026.", details=[Line("x", ["c1"])],
                  citations=[Citation("c1", "226A", "UPI-226A", "t", q)])
    assert check(good, SRC).ok
    bad = Answer("summary", verdict="Raised to ₹2,10,000.", details=[Line("x", ["c1"])],
                 citations=[Citation("c1", "226A", "UPI-226A", "t", q)])
    r = check(bad, SRC)
    assert not r.ok and any("210000" in x for x in r.reasons)


def test_statements_need_citations_and_oc_numbers_must_exist():
    a = Answer("summary", verdict="OC 999 says something.", details=[Line("no cite", [])], citations=[])
    r = check(a, SRC)
    assert any("no valid citation" in x for x in r.reasons) and any("OC 999" in x for x in r.reasons)


def test_number_helpers():
    assert {"100000", "2000", "500000", "1000000", "4"} <= quote_numbers("1 Lakh, 2K, ₹ 5 Lakh, 10 lakhs, 4")
    assert free_text_numbers("On 15 September 2024, OC 185A: limit ₹5 lakh and MCC 9311") == ["500000", "9311"]


def test_snap_replaces_a_slightly_wrong_quote_with_the_sources_own_words():
    from core.evidence.documents import Evidence, EvidencePack
    from core.writer import snap_quotes

    src = "Acquirers shall ensure that the classification of their merchants within ‘MCC-9311’ strictly adheres to tax payments only."
    pack = EvidencePack([Evidence("E1", "UPI-185A", "185A", "t", "2024-08-24", src)])
    a = Answer("summary", verdict="MCC 9311 is for tax payments.", details=[Line("x", ["c1"])],
               citations=[Citation("c1", "185A", "UPI-185A", "t", "classification of their merchants within 'MCC- 9311' strictly adheres to tax payments")])
    snap_quotes(a, pack)
    assert a.citations[0].quote in src
    assert check(a, [("UPI-185A", src)]).ok
    far = Answer("summary", verdict="v", citations=[Citation("c1", "185A", "UPI-185A", "t", "something the circular never says at all")])
    snap_quotes(far, pack)
    assert far.citations[0].quote == "something the circular never says at all"


def test_number_words_and_iso_dates_are_not_false_alarms():
    q = "The Port Mandate can be done thrice, and three months after registration."
    assert "3" in quote_numbers("three months")
    a = Answer("summary", verdict="Ported at most 3 months after registration, per the 2025-10-07 circular.",
               details=[Line("x", ["c1"])], citations=[Citation("c1", "223", "UPI-223", "t", "three months after registration.")])
    assert check(a, [("UPI-223", "It can be done three months after registration.")]).ok
    assert free_text_numbers("Issued 2025-10-07 and 07/10/2025") == []


def test_hinglish_answers_must_use_roman_script():
    a = Answer("general", language="hinglish", verdict="सीमा 5 लाख है", details=[Line("x", ["c1"])],
               citations=[Citation("c1", "185A", "UPI-185A", "t", "limit enhanced to 5 lakhs for tax payments")])
    r = check(a, [("UPI-185A", "the limit enhanced to 5 lakhs for tax payments")])
    assert any("Roman" in x for x in r.reasons)
    a.verdict = "Limit badhakar 5 lakh kar di gayi hai"
    assert check(a, [("UPI-185A", "the limit enhanced to 5 lakhs for tax payments")]).ok


def test_quote_parts_keep_the_circulars_order():
    from core.writer import auto_quote

    text = "| Particulars | Maximum credit |\n|---|---|\n| Per transaction | Rs. 10,000 |\n| Per month | Rs. 1,00,000 |"
    q = auto_quote("Per month Rs. 1,00,000 and per transaction Rs. 10,000", text)
    assert q.index("Per transaction") < q.index("Per month")
