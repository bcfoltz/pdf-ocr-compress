"""Tests for core.detect.needs_ocr.

Phase 2 / Design rule #2: needs_ocr must use a tolerant parser (pikepdf),
not pdfminer. pdfminer false-positives on real scanner output (Sample B in
BENCHMARKS.md), triggering useless multi-hour OCR passes. The distinguishing
test is test_needs_ocr_does_not_depend_on_pdfminer below.
"""

from pdf_ocr_compress.core.detect import needs_ocr


def test_needs_ocr_text_pdf_returns_false(text_pdf):
    """A PDF with /Font resources and a text content stream does not need OCR."""
    assert needs_ocr(text_pdf) is False


def test_needs_ocr_blank_pdf_returns_true(sample_pdf):
    """A blank PDF (no fonts, no text) is treated as image-only and needs OCR."""
    assert needs_ocr(sample_pdf) is True


def test_needs_ocr_corrupt_file_returns_true(tmp_path):
    """A file that is not a valid PDF is fail-safe routed to OCR."""
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf at all, just garbage")
    assert needs_ocr(corrupt) is True


def test_needs_ocr_does_not_depend_on_pdfminer(monkeypatch, text_pdf):
    """Bug fix proof: even if pdfminer would raise, needs_ocr must read the
    text PDF correctly via pikepdf.

    Regression guard for the Sample B bug — pdfminer's strict parser raises
    PDFSyntaxError on PDFs that pikepdf reads fine, and the old pdfminer-
    based needs_ocr swallowed that and incorrectly returned True, kicking
    off a multi-hour OCR pass on a PDF that already had a text layer.
    """

    def _raise(*args, **kwargs):
        raise RuntimeError("pdfminer should not be called by needs_ocr")

    # Patch at the use site (the bound name inside detect.py). raising=False
    # so this is a no-op once the rewrite removes the pdfminer import — at
    # that point pikepdf alone produces the correct answer.
    monkeypatch.setattr(
        "pdf_ocr_compress.core.detect.extract_text", _raise, raising=False
    )

    assert needs_ocr(text_pdf) is False
