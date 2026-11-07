from core import feedback as fb

ANS = {"answer_type": "limit_table", "verdict": "P2P per transaction: ₹1,00,000", "meta": {"build_id": "b1"}}


def test_no_text_is_sent_without_consent():
    p = fb.build_payload("s1", "👎", "Wrong number", "c", ANS, "What is the P2P limit?", share_text=False)
    joined = " ".join(p.values())
    assert "P2P limit" not in joined and "1,00,000" not in joined
    assert p[fb.ENTRY_IDS["feedback"]] == "👎: Wrong number" and "build b1" in p[fb.ENTRY_IDS["answer"]]


def test_text_is_sent_when_the_user_agrees():
    p = fb.build_payload("s1", "👍", "", "", ANS, "What is the P2P limit?", share_text=True)
    assert p[fb.ENTRY_IDS["question"]] == "What is the P2P limit?" and "1,00,000" in p[fb.ENTRY_IDS["answer"]]
