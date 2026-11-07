import os

import pytest

from core.config import Settings
from core.evidence import facts as fev
from core.router import route
from core.stores import Stores
from ingest import paths

pytestmark = pytest.mark.skipif(not os.path.isfile(paths.REGISTRY_PATH), reason="data not built")


@pytest.fixture(scope="module")
def stores():
    return Stores(Settings(llm_provider="none", allow_unverified_facts=True))


def test_lite_chain_goes_back_through_superseded_facts(stores):
    ev = fev.limit_evidence(stores, route("What is the UPI Lite limit?"))
    row = next(r for r in ev.rows if r.label == "UPI Lite: per transaction")
    assert [f["value"] for f in row.facts] == ["1000"]
    assert {f["value"] for f in row.earlier} == {"500", "200"}      # OC 169 and OC 138


def test_insurance_mccs_share_one_row(stores):
    ev = fev.limit_evidence(stores, route("insurance premium limit"))
    per_txn = next(r for r in ev.rows if r.kind == "per_txn_amount")
    assert {f["mcc"] for f in per_txn.facts} == {"5960", "6300", "6529"}
    assert {f["fact_id"] for f in per_txn.earlier} >= {"OC82-P2M-5960"}


def test_only_current_limits_are_headline_facts(stores):
    ev = fev.limit_evidence(stores, route("capital markets limit"))
    assert all(f["status"] == "current" for r in ev.rows for f in r.facts)
    assert any(f["source_oc"] == "185B" for r in ev.rows for f in r.facts)


def test_unserved_facts_leave_no_rows():
    s = Stores(Settings(llm_provider="none", allow_unverified_facts=False))
    if not s.facts:                       # nothing human-verified yet
        assert fev.limit_evidence(s, route("What is the P2P limit?")) is None


def test_code_outcomes(stores):
    assert fev.code_evidence(stores, route("MCC 1520 ki limit")).outcome == "not_mentioned"
    assert fev.code_evidence(stores, route("MCC 5944 limit")).outcome == "specific_rule"
    assert fev.code_evidence(stores, route("What is MCC 7407?")).outcome == "mention_only"
    rev = fev.code_evidence(stores, route("Which MCC is used for jewellery?"))
    assert [m for m, _c, _f in rev.reverse] == ["5944"]


def test_find_oc_prefers_the_upi_series(stores):
    rows = stores.find_oc("99")
    assert rows and rows[0]["series"] in ("UPI", "IMPS_UPI")
    assert stores.find_oc("233")[0]["status"] == "not_public"
    assert stores.find_oc("999") == []


def test_a_withdrawn_limit_is_shown_as_earlier_never_as_current(stores):
    ev = fev.limit_evidence(stores, route("What is the P2P limit?"))
    row = next(r for r in ev.rows if r.label == "Number of transactions sent in 24 hours")
    assert row.status == "no_oc_sets_this" and not row.facts
    assert [f["fact_id"] for f in row.earlier] == ["OC61-P2P-count10"]
    assert row.earlier[0]["status"] == "withdrawn"


def test_consolidated_circular_row_and_withdrawn_ocs(stores):
    assert stores.by_doc["UPI-CC-01"]["series"] == "CC"
    assert stores.find_oc("61")[0]["status"] == "withdrawn"
    assert stores.find_oc("185")[0]["status"] == "withdrawn"


def test_autopay_interoperability_is_expanded_to_the_circulars_words():
    from core.evidence.synonyms import expand

    assert "port mandate" in expand("UPI AutoPay interoperability kya hai?").lower()
    assert expand("What is UPI Circle?") == "What is UPI Circle?"
