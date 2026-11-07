from core.reference import build_reference, clause_for

CHUNK = ("14.23 UPI AutoPay Mandate withdrawal through Merchant platform does not require AFA validation for UPI. "
         "14.24 Mandate interoperability 14.24.1 Payer PSP shall ensure lifecycle management. "
         "14.24.4 'Port Mandate' can be done thrice in a rolling 90-day period. 14.24.5 Payee PSP shall generate a unique MIC.")


def test_clause_is_the_nearest_one_before_the_quote():
    assert clause_for("'Port Mandate' can be done thrice in a rolling 90-day period", CHUNK) == "14.24.4"
    assert clause_for("Payee PSP shall generate a unique MIC", CHUNK) == "14.24.5"
    assert clause_for("something else entirely", CHUNK) in ("", "14.24.5")      # not located: falls back to the last clause


def test_build_reference():
    cc = {"series": "CC", "issue_date": "2026-09-18", "title": "UPI Consolidated Circular (Version 1.0)", "oc_number": ""}
    assert build_reference(cc, "22", "14.24.4") == "UPI Consolidated Circular (18 Sep 2026), clause 14.24.4, p. 22"
    oc = {"series": "UPI", "issue_date": "2025-10-07", "title": "Enhancement of UPI Autopay", "oc_number": "223"}
    assert build_reference(oc, "1") == "OC 223 (7 Oct 2025), p. 1"
    assert build_reference(oc) == "OC 223 (7 Oct 2025)"
