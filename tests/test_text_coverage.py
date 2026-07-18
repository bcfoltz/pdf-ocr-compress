"""Tests for the sampled text-coverage metric (accepted proposal P-002).

`_text_coverage` replaces the old 2-page boolean probe: it samples pages
across the whole document and reports (pages_sampled, pages_with_text,
words), from which `pdfminer_text_extractable` is now derived. A book
whose text layer dies after the first pages is finally visible.
"""

import pikepdf
import pytest

from pdf_ocr_compress.core.pipeline import _text_coverage


@pytest.fixture(scope="session")
def partial_text_pdf(tmp_path_factory):
    """A 3-page PDF with real text on page 1 only; pages 2-3 are blank.

    The old first-2-pages probe calls this fully extractable; coverage
    must report 1 of 3 sampled pages.
    """
    path = tmp_path_factory.mktemp("fixtures") / "partial.pdf"
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
    )
    for _ in range(3):
        pdf.add_blank_page(page_size=(612, 792))
    pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    pdf.pages[0].Contents = pdf.make_stream(
        b"BT /F1 24 Tf 100 700 Td (Only page one has words) Tj ET"
    )
    pdf.save(path)
    return path


def test_full_text_doc_reports_full_coverage(text_paragraph_pdf):
    sampled, with_text, words = _text_coverage(text_paragraph_pdf)
    assert sampled >= 1
    assert with_text == sampled
    assert words > 10


def test_blank_doc_reports_zero_coverage(sample_pdf):
    sampled, with_text, words = _text_coverage(sample_pdf)
    assert sampled >= 1
    assert with_text == 0
    assert words == 0


def test_corrupt_doc_degrades_to_zeros(corrupt_pdf):
    assert _text_coverage(corrupt_pdf) == (0, 0, 0)


def test_partial_coverage_detected(partial_text_pdf):
    """The whole point of P-002: partial text layers are visible."""
    sampled, with_text, words = _text_coverage(partial_text_pdf)
    assert sampled == 3
    assert with_text == 1
    assert words == 5  # "Only page one has words"


def test_sampling_caps_large_documents(tmp_path):
    """A 40-page doc samples max_sample_pages pages, spread across it."""
    path = tmp_path / "big.pdf"
    pdf = pikepdf.new()
    for _ in range(40):
        pdf.add_blank_page(page_size=(200, 200))
    pdf.save(path)

    sampled, with_text, words = _text_coverage(path, max_sample_pages=10)
    assert sampled == 10
    assert with_text == 0
    assert words == 0


def test_run_pipeline_populates_coverage_fields(text_paragraph_pdf, tmp_path):
    """Compress-mode run (real Ghostscript) carries coverage in the report."""
    from pdf_ocr_compress.core.pipeline import run_pipeline

    result = run_pipeline(
        text_paragraph_pdf, tmp_path / "out.pdf", mode="compress", preset="smallest"
    )
    d = result.to_dict()
    assert d["text_pages_sampled"] >= 1
    assert d["text_pages_with_text"] == d["text_pages_sampled"]
    assert d["text_words"] > 10
    assert d["pdfminer_text_extractable"] is True
