import csv
import os

import pytest

from core import normalize as N
from core.router import route

GOLD = os.path.join(os.path.dirname(__file__), "..", "eval", "gold_set.csv")


def _gold():
    with open(GOLD, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("row", _gold(), ids=lambda r: r["id"])
def test_every_gold_question_routes_to_its_intent(row):
    assert route(row["question"]).intent == row["intent"], row["question"]


def test_oc_ids_in_many_forms():
    assert N.find_oc_numbers("OC 185A kya bolta hai") == ["185A"]
    assert N.find_oc_numbers("oc-76 and circular no. 141 b") == ["76", "141B"]
    assert N.find_oc_numbers("OC076") == ["76"]
    assert N.find_oc_numbers("no circular here") == []


def test_codes():
    assert N.find_mcc("limit for MCC 5944?") == ["5944"]
    assert N.find_mcc("mcc - 7407 and mcc: 6211") == ["7407", "6211"]
    assert N.find_purpose_codes("purpose code 25") == ["25"]


def test_language():
    assert N.detect_language("P2P limit kya hai?") == "hinglish"
    assert N.detect_language("What is the P2P limit?") == "en"


def test_slots():
    p = route("What is the daily amount limit for P2P?")
    assert (p.txn_type, p.limit_kind) == ("P2P", "per_24h_amount")
    p = route("How many P2P credits can a user receive in 24 hours?")
    assert (p.txn_type, p.limit_kind, p.direction) == ("P2P", "per_24h_count", "receive")
    assert route("P2PM merchant monthly inward credit limit").limit_kind == "per_month_amount"
    assert route("UPI Lite X per transaction limit").txn_type == "UPI_LITE_X"
    assert route("MCC 1520 ki limit kya hai?").mcc == "1520"


def test_bank_specific_and_scope():
    assert route("What is my HDFC UPI limit?").intent == "BANK_SPECIFIC"
    assert route("what is the weather today").intent == "OUT_OF_SCOPE"
    assert route("Who is NPCI's chairman?").intent == "OUT_OF_SCOPE"


def test_kitni_transactions_is_a_count_question():
    assert route("P2P mein ek din mein kitni transactions kar sakte hain?").limit_kind == "per_24h_count"
    assert route("P2P limit kitni hai?").limit_kind != "per_24h_count"
