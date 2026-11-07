from ingest import extract as E


def test_time_suffix_is_ignored_when_matching_ocr_cache():
    a = E.normalize_stem("Operation-Circular-99-enablement-IMPS-UPI 11.46.37 AM.pdf")
    b = E.normalize_stem("Operation-Circular-99-enablement-IMPS-UPI.pdf.txt".replace(".txt", ""))
    assert a == b


def test_html_saved_as_pdf_is_rejected(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_text("<!DOCTYPE html><html></html>")
    assert not E.is_valid_pdf(str(f))
    assert "wrong header" in E.extract_pdf(str(f))["problem"]
