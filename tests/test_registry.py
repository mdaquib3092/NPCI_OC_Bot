from ingest import registry as R


def test_filename_number_keeps_letter_suffix():
    assert R.oc_from_filename("UPI-_-OC-No_-76B-_-FY-24-25---Addendum.pdf")[0] == "76B"
    assert R.oc_from_filename("OC-125A---Addendum-to-OC-125---Non-revocation.pdf")[0] == "125A"


def test_own_number_is_the_first_one_not_a_reference():
    number, series, ambiguous = R.oc_from_filename(
        "UPI-OC-161-–-Extension-to-UPI-Circular-No_-60-Crediting-Debiting.pdf")
    assert (number, series, ambiguous) == ("161", "UPI", False)
    # years inside the name are not circular numbers
    number, _, _ = R.oc_from_filename(
        "UPI-OC-No-76B-FY-24-25-Addendum-to-NPCI-UPI-2023-24-76A-Revision.pdf")
    assert number == "76B"


def test_administrative_notices_have_no_oc_number():
    assert R.oc_from_filename("Compliance to Circular 15B and 32.pdf")[0] == ""
    assert R.oc_from_filename("Product-Compliance-_-002-_-FY-23-24-_-Self-attestation.pdf")[0] == ""
    # but an OC whose title mentions compliance still keeps its own number
    assert R.oc_from_filename("UPI-_-OC-190-_-FY-23-24-_-Reiteration-of-compliance-to-OC-163.pdf")[0] == "190"


def test_series():
    assert R.oc_from_filename("Operation-Circular-99-enablement-of-penalty-in-IMPS-UPI.pdf")[1] == "IMPS_UPI"
    assert R.oc_from_filename("RuPay-OC-019-A_-Operating-circular.pdf")[1] == "RUPAY"


def _row(**kw):
    base = {c: "" for c in R.COLUMNS}
    base.update(doc_id="UPI-1", oc_number="1", series="UPI", title="T", issue_date="2020-01-01",
               status="current", needs_review="")
    base.update(kw)
    return base


def test_validate_accepts_a_good_row():
    assert R.validate([_row()]) == []


def test_validate_catches_the_gate_cases():
    msgs = [m for _, _, m in R.validate([
        _row(issue_date=""),
        _row(doc_id="UPI-2", oc_number="2", superseded_by="9", status="superseded"),
        _row(doc_id="UPI-3", oc_number="3", status="superseded"),
        _row(doc_id="UPI-1", oc_number="4"),
    ])]
    assert any("issue_date is empty" in m for m in msgs)
    assert any("'9' not in registry" in m for m in msgs)
    assert any("superseded_by is empty" in m for m in msgs)
    assert any("appears 2 times" in m for m in msgs)


def test_confirmed_undated_documents_pass():
    assert R.validate([_row(issue_date="", needs_review="date_unknown_confirmed")]) == []


def test_unreadable_is_a_warning_not_an_error():
    issues = R.validate([_row(status="unreadable", title="", issue_date="", notes="truncated")])
    assert [sev for sev, _, _ in issues] == ["warn"]


def test_existing_rows_are_never_overwritten():
    existing = [_row(content_hash="abc", title="Edited by a person")]
    rec = {"content_hash": "abc", "source_file": "x.pdf", "text": "hello " * 50, "readable": True,
           "text_source": "native", "page_count": 1, "char_count": 300, "problem": ""}
    rows, added, orphaned, _ = R.draft([rec], existing)
    assert added == [] and rows[0]["title"] == "Edited by a person"


def test_not_public_rows_need_a_title_and_no_source():
    ok = _row(doc_id="UPI-233", oc_number="233", status="not_public", issue_date="", needs_review="date_unknown_confirmed;not_public")
    assert R.validate([ok]) == []
    bad = _row(doc_id="UPI-234", oc_number="234", status="not_public", title="", source_file="x.pdf")
    msgs = [m for _, _, m in R.validate([bad])]
    assert any("title is empty" in m for m in msgs) and any("must not have a source file" in m for m in msgs)


def test_a_pdf_that_arrives_later_conflicts_with_the_not_public_row():
    hidden = _row(doc_id="UPI-233", oc_number="233", status="not_public", issue_date="")
    real = _row(doc_id="UPI-233-ab12", oc_number="233")
    assert any("remove the not_public row" in m for _, _, m in R.validate([hidden, real]))


def test_not_public_rows_survive_a_redraft():
    hidden = _row(doc_id="UPI-233", oc_number="233", status="not_public", content_hash="")
    rows, added, orphaned, _ = R.draft([], [hidden])
    assert [r["doc_id"] for r in rows] == ["UPI-233"] and orphaned == []


def test_add_not_public_rows():
    from ingest import not_public as NP

    existing = [_row(doc_id="UPI-5", oc_number="5"), NP.make_row("233", "T", "2026-27")]
    rows, added, skipped = NP.add_rows(existing, [
        {"oc_number": "238", "title": "", "fy": "2026-27"},
        {"oc_number": "233", "title": "T", "fy": "2026-27"},   # already there
        {"oc_number": "5", "title": "x", "fy": ""},            # a PDF exists
        {"oc_number": " 141 e ", "title": "Y", "fy": ""},
    ])
    assert [r["doc_id"] for r in added] == ["UPI-238", "UPI-141E"]
    assert added[0]["title"] == NP.NO_TITLE and added[0]["status"] == "not_public"
    assert {d for d, _ in skipped} == {"UPI-233", "UPI-5"}
    assert R.validate(rows) == []


def test_add_not_public_rejects_bad_numbers():
    import pytest

    from ingest import not_public as NP

    with pytest.raises(ValueError):
        NP.make_row("abc", "", "")
