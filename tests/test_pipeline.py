import os

import pytest

from core.config import Settings
from core.evidence.documents import Evidence, EvidencePack
from core.llm import LLMError
from core.pipeline import Pipeline
from core.stores import Stores
from ingest import paths

pytestmark = pytest.mark.skipif(not os.path.isfile(paths.REGISTRY_PATH), reason="data not built")

TEXT = ("the per-transaction limit for On-Device Biometric Authentication (fingerprint, face, etc.) in UPI is hereby "
        "enhanced from ₹5,000 to ₹10,000, effective 07th August 2026.")


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls, self.enabled = list(replies), 0, True

    def complete_json(self, system, user, max_tokens=1500):
        self.calls += 1
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeSearcher:
    def search(self, query, top_k=None):
        return EvidencePack([Evidence("E1", "UPI-226A", "226A", "On-device biometric limit", "2026-07-03", TEXT)], 1)


@pytest.fixture(scope="module")
def unreviewed_data(tmp_path_factory):
    """A copy of the built data in which no fact has been human-verified."""
    import csv
    import shutil

    d = tmp_path_factory.mktemp("unreviewed")
    for name in ("registry.csv", "code_mentions.csv", "chunks.jsonl", "build_info.json"):
        if os.path.isfile(os.path.join(paths.DATA, name)):
            shutil.copy(os.path.join(paths.DATA, name), d / name)
    with open(paths.DATA + "/facts.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["review_status"], r["reviewer"], r["reviewed_on"] = "auto_checked", "", ""
    with open(d / "facts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return str(d)


def _pipe(llm=None, unverified=True, data_dir=None):
    s = Settings(llm_provider="none", allow_unverified_facts=unverified)
    return Pipeline(stores=Stores(s, data_dir=data_dir), llm=llm, searcher=FakeSearcher())


GOOD = {"answer_type": "general", "verdict": "The limit was raised from ₹5,000 to ₹10,000.",
        "details": [{"text": "Effective 7 August 2026.", "evidence": "E1",
                     "quote": "enhanced from ₹5,000 to ₹10,000, effective 07th August 2026."}]}
BAD = {**GOOD, "verdict": "The limit was raised from ₹5,000 to ₹2,10,000."}


def test_p2p_table_has_every_limit_kind_and_says_what_no_oc_sets(unreviewed_data):
    a = _pipe(data_dir=unreviewed_data).answer("What is the P2P limit on UPI?")
    labels = {r.label: r for r in a.table}
    assert a.answer_type == "limit_table" and len(a.table) == 7
    assert labels["Total amount sent in 24 hours"].status == "no_oc_sets_this"
    assert labels["Per transaction (pay)"].cells[0].value == 100000
    assert a.meta["checker"]["ok"] and a.status == "unverified_facts"


def test_unverified_facts_are_not_served_by_default(unreviewed_data):
    a = _pipe(unverified=False, data_dir=unreviewed_data).answer("What is the P2P limit on UPI?")
    assert a.answer_type == "passages"          # no served facts: falls through to search, no LLM, so passages


def test_mcc_outcomes():
    p = _pipe()
    assert p.answer("What is the limit for MCC 5944?").table[0].cells[0].value == 200000
    assert p.answer("MCC 1520 ki limit kya hai?").status == "not_found"
    assert p.answer("What is MCC 7407?").answer_type == "code_result"


def test_not_public_not_found_refusal_clarify():
    p = _pipe()
    assert p.answer("What does OC 233 say?").answer_type == "not_public"
    assert p.answer("What does OC 999 say?").answer_type == "not_found"
    assert p.answer("Who is the CEO of NPCI?").answer_type == "refusal"
    assert p.answer("What is my SBI limit?").meta["reason"] == "bank"
    assert p.answer("limit kya hai").chips


def test_llm_answer_is_shown_only_if_the_checker_passes():
    llm = FakeLLM([GOOD])
    a = _pipe(llm).answer("What is the on-device biometric authentication rule?")
    assert a.answer_type == "general" and a.status == "verified" and llm.calls == 1


def test_a_wrong_number_is_regenerated_once_then_falls_back():
    llm = FakeLLM([BAD, GOOD])
    a = _pipe(llm).answer("Explain the biometric rule")
    assert a.answer_type == "general" and llm.calls == 2
    llm = FakeLLM([BAD, BAD])
    a = _pipe(llm).answer("Explain the biometric rule")
    assert a.answer_type == "passages" and "210000" in str(a.meta["checker"]["reasons"])


def test_llm_failures_end_in_passages_not_a_crash():
    a = _pipe(FakeLLM([LLMError("rate_limit")])).answer("Explain the biometric rule")
    assert a.answer_type == "passages"
    a = _pipe(FakeLLM([LLMError("invalid_json"), LLMError("invalid_json")])).answer("Explain the biometric rule")
    assert a.answer_type == "passages"


def test_a_withdrawn_oc_is_flagged_in_its_answer():
    class OneDoc:
        def search(self, query, top_k=None):
            return EvidencePack()
    llm = FakeLLM([{"answer_type": "summary", "verdict": "OC 61 set a frequency limit.",
                    "details": [{"text": "10 transactions per bank account for P2P.", "evidence": "E1",
                                 "quote": "10 transactions per bank account for P2P segment"}]}])
    p = _pipe(llm)
    a = p.answer("Summarize OC 61")
    assert "withdrawn" in a.notice.lower()


def test_citations_carry_a_precise_reference():
    a = _pipe().answer("What is the limit for MCC 5944?")
    c = a.citations[0]
    assert c.reference.startswith("OC 185B (28 Aug 2025)") and c.reference.endswith("p. 2")
    a = _pipe().answer("What is the P2PM merchant monthly inward limit?")
    assert any(c.reference.startswith("UPI Consolidated Circular (18 Sep 2026)") and c.reference.endswith("p. 12") for c in a.citations)


def test_a_statement_without_a_quote_gets_the_passages_own_sentence():
    llm = FakeLLM([{"answer_type": "general", "verdict": "The limit was raised from ₹5,000 to ₹10,000.",
                    "details": [{"text": "Raised from ₹5,000 to ₹10,000.", "evidence": "E1"}]}])
    a = _pipe(llm).answer("Explain the biometric rule")
    assert a.answer_type == "general" and a.citations
    assert "₹10,000" in a.citations[0].quote and a.citations[0].quote in " ".join(TEXT.split())


def test_a_number_that_the_passage_does_not_contain_is_still_rejected_without_quotes():
    bad = {"answer_type": "general", "verdict": "The limit was raised to ₹2,10,000.",
           "details": [{"text": "Raised to ₹2,10,000.", "evidence": "E1"}]}
    a = _pipe(FakeLLM([bad, bad])).answer("Explain the biometric rule")
    assert a.answer_type == "passages"


def test_a_number_in_a_table_row_is_quoted_with_its_row():
    from core.writer import auto_quote

    text = "Intro sentence about limits.\n\n| Description | Existing | New |\n|---|---|---|\n| Per Transaction Limit | ₹500 | ₹1000 |\n| Total Limit | ₹2000 | ₹5000 |"
    q = auto_quote("The per transaction limit was ₹500 and is now ₹1000.", text)
    assert "₹500" in q and "₹1000" in q and "---" not in q


def test_a_reply_cut_off_at_the_token_limit_is_repaired():
    from core.llm import extract_json

    cut = '{"answer_type": "summary", "verdict": "ok", "details": [{"text": "a", "evidence": "E1"}, {"text": "b", "evid'
    data = extract_json(cut)
    assert data["verdict"] == "ok" and data["details"][0]["text"] == "a"


def test_a_number_held_in_another_passage_of_the_same_circular_is_found():
    from core.writer import locate_quote

    p1 = Evidence("E1", "UPI-185A", "185A", "t", "2024-08-24", "In view of the above, the limit has been enhanced to ₹ 5")
    p2 = Evidence("E2", "UPI-185A", "185A", "t", "2024-08-24", "lakhs for entities under categories aligned to tax payments.")
    q, holder = locate_quote("The limit is ₹5,00,000 for tax payments.", p1, EvidencePack([p1, p2]))
    assert q and q in " ".join(holder.text.split())          # one contiguous piece of one passage


def test_p2p_collect_row_says_it_is_withdrawn_and_cites_the_closing_clause():
    a = _pipe(unverified=True).answer("What is the collect request limit for P2P?")
    row = next(r for r in a.table if r.label.startswith("Collect"))
    assert row.status == "withdrawn" and "No longer in force" in row.note and not row.cells
    assert a.meta["checker"]["ok"]
    why = next(l for l in a.earlier if l.text.startswith("Why it is no longer in force"))
    cite = next(c for c in a.citations if c.id == why.citation_ids[0])
    assert cite.doc_id == "UPI-CC-01" and "clause 2.16" in cite.reference and "not permitted" in cite.quote


def test_withdrawn_oc61_count_cites_annexure_g():
    a = _pipe(unverified=True).answer("How many P2P transactions can I send per day?")
    why = [l for l in a.earlier if l.text.startswith("Why it is no longer in force")]
    refs = [c.reference for c in a.citations if c.id in {i for l in why for i in l.citation_ids}]
    assert any("Annexure G, serial 22" in r and "p. 53" in r for r in refs)
