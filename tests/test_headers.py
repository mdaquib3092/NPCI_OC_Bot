import pytest

from ingest import headers as H


@pytest.mark.parametrize("text,expected", [
    ('NPCI/UPI/2021-22/0C.121 25" October, 2021', "2021-10-25"),
    ("NPCI/2025-26/UPI/221 Sep 12, 2025", "2025-09-12"),
    ('NPCI/2024-25/PD/001 23" April 2024', "2024-04-23"),
    ('NPCI /UPI/OC No.56/2018-19 August 14, 2018', "2018-08-14"),
    ('NPCI/UPI/OC No.201/2024-25 13!" August 2024', "2024-08-13"),
    ('NPCI/UPI(OC210/2024-25 315\' December 2024', "2024-12-31"),
    ("Date: 02/03/2023", "2023-03-02"),
    ("Date: 24,11.2017", "2017-11-24"),
])
def test_parse_date(text, expected):
    assert H.parse_date(text) == expected


def test_two_digit_year_is_only_a_fallback():
    # "20 June 17" inside a reference must not beat a real four-digit date
    assert H.parse_date("NPCI/UPI/OC-70/2019-20 June 17, 2019") == "2019-06-17"
    assert H.parse_date("Dated 7 November 23") == "2023-11-07"


def test_pick_issue_date_prefers_the_financial_year():
    head = "OC dated January 27, 2022 ... NPCI/UPI/OC-133A/2022-23 February 28, 2023"
    assert H.pick_issue_date(head, "2022-23") == ("2023-02-28", "fy_match")
    assert H.pick_issue_date(head, "")[1] == "first_date"
    assert H.pick_issue_date("no date here", "2022-23") == ("", "")


def test_fy_from_head_and_filename():
    assert H.fy_from_head("NPCI/UPI/OC No. 22 / 2017-18 June 14, 2017") == "2017-18"
    assert H.fy_from_head("ref 2019-2020") == "2019-20"
    assert H.fy_from_head("NPCI/UPI/OC No. 229A/2026 — 2027 August 24, 2026") == "2026-27"
    assert H.fy_from_head("ref 2019-2025") == ""  # not consecutive years
    assert H.fy_from_filename("UPI-_-OC-No_-76B-_-FY-24-25---Addendum.pdf") == "2024-25"
    assert H.fy_from_filename("UPI-_-OC-No_-224-_-FY-2025-26-_-X.pdf") == "2025-26"


def test_parse_reference_variants():
    r = H.parse_reference("NATIONAL PAYMENTS\nNPCI/UPI/OC No.78 /2019-2020 January 27, 2020")
    assert (r["number"], r["product"]) == ("78", "UPI")
    r = H.parse_reference("NPCI/2025-26/UPI/221 Sep 12, 2025")
    assert (r["number"], r["fy"], r["product"]) == ("221", "2025-26", "UPI")
    r = H.parse_reference("NPCI/2024-25/PD/001 23 April 2024")
    assert (r["number"], r["product"]) == ("1", "PD")
    assert H.parse_reference("no reference at all")["reference"] == ""


def test_parse_subject_and_title():
    assert H.parse_subject("Dear Sir,\nSubject: Revision in limits\nbody") == "Revision in limits"
    wrapped = "Subject: " + "Introduction of a very long wrapped subject line " + "x" * 10 + "\ncontinues here\n\nbody"
    assert H.parse_subject(wrapped).endswith("continues here")
    assert H.title_from_filename("UPI-OC-104-Revising-the-number-of-Check-TXNs-in-UPI.pdf") == \
        "Revising the number of Check TXNs in UPI"
    assert H.title_from_filename("UPI-_-OC-No_-185-_-FY-23-24-_-Implementation-of-Rs-5-Lakh-limit.pdf") == \
        "Implementation of Rs 5 Lakh limit"


@pytest.mark.parametrize("text,expected", [
    ('NPCI/UPI/OC-120/2021 24" September’ 2021 To, All', "2021-09-24"),
    ("NPCI/UPI/OC-141 B/2022-23(Addendum) 21 st October 2022 To", "2022-10-21"),
    ("NPCI/UPI/OC-141D/2024-25(Addendum) 2™ April 2025 To", "2025-04-02"),
    ("NPCI/UPI/OC No. 169/2023-24 31* August 2023 To All", "2023-08-31"),
])
def test_ocr_noise_around_the_date(text, expected):
    assert H.parse_date(text) == expected
