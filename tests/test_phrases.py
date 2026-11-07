from core import phrases as P


def test_indian_grouping():
    assert P.fmt_inr(100000) == "₹1,00,000"
    assert P.fmt_inr(1000000) == "₹10,00,000"
    assert P.fmt_inr("2000") == "₹2,000"
    assert P.fmt_inr(500) == "₹500"
    assert P.fmt_inr(25000) == "₹25,000"


def test_counts_and_fallback_language():
    assert P.fmt_value(1, "count") == "1 transaction"
    assert P.fmt_value("50", "count") == "50 transactions"
    assert "OC 233" in P.t("hinglish", "not_public", oc="233", title="")
    assert P.t("xx", "disclaimer") == P.P["en"]["disclaimer"]
