from ingest import chunk as C

TABLE = "| A | B |\n|---|---|\n| 1 | x |\n| 2 | y |"


def test_boilerplate_is_removed():
    out = C.clean_text("Dear Sir/Madam,\nReal rule text here.\nwww.npci.org.in\nPage 2 of 5")
    assert "Real rule text" in out and "Dear" not in out and "npci.org.in" not in out and "Page 2" not in out


def test_table_stays_whole_and_without_overlap():
    text = "Intro paragraph " * 10 + "\n\n" + TABLE + "\n\n" + "Closing paragraph " * 10
    chunks = C.build_chunks(text)
    tables = [c for c in chunks if C.is_table(c)]
    assert tables == [TABLE]
    after = chunks[chunks.index(TABLE) + 1]
    assert not after.startswith("| 2 | y |")  # no table tail glued onto text


def test_big_table_splits_with_header_repeated():
    rows = "\n".join(f"| {i} | {'v' * 40} |" for i in range(60))
    parts = C.split_table_paragraph("| A | B |\n|---|---|\n" + rows, 400)
    assert len(parts) > 1
    assert all(p.startswith("| A | B |\n|---|---|") for p in parts)


def test_chunks_carry_registry_metadata():
    row = dict(doc_id="UPI-7", oc_number="7", series="UPI", domain="UPI", title="Title",
               issue_date="2020-01-02", status="current", supersedes="", superseded_by="",
               category="limits", source_file="f.pdf", content_hash="h", needs_review="")
    chunks = C.chunk_registry([row], {"h": "Some long enough paragraph of text. " * 5})
    assert chunks and chunks[0]["chunk_id"] == "UPI-7__0"
    assert chunks[0]["title"] == "Title" and chunks[0]["issue_date"] == "2020-01-02"


def test_unreadable_documents_produce_no_chunks():
    row = dict(doc_id="UPI-8", oc_number="8", series="UPI", domain="UPI", title="T",
               issue_date="", status="unreadable", supersedes="", superseded_by="",
               category="x", source_file="f.pdf", content_hash="h", needs_review="")
    assert C.chunk_registry([row], {"h": "text " * 100}) == []


from ingest import patches


def test_patch_modes():
    text = "Intro line.\n\nGarbled table: = 5 Lakh | 210,000\n"
    assert patches.apply_patch(text, "").endswith("210,000\n")
    assert "₹10,000" in patches.apply_patch(text, "[REPLACE]\nFixed: ₹10,000")
    assert "210,000" not in patches.apply_patch(text, "[REPLACE]\nFixed: ₹10,000")
    after = patches.apply_patch(text, "[REPLACE_AFTER: Garbled table]\nFixed table: ₹10,000")
    assert after.startswith("Intro line.") and "210,000" not in after and "₹10,000" in after
    appended = patches.apply_patch(text, "Extra note")
    assert "[MANUAL PATCH APPLIED]" in appended and "Garbled" in appended


def test_missing_patch_marker_is_an_error():
    import pytest

    with pytest.raises(ValueError):
        patches.apply_patch("some text", "[REPLACE_AFTER: not there]\nx")
