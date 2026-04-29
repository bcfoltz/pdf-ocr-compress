"""End-to-end tests for the three pipeline branches in run_pipeline().

Complements tests/test_pipeline.py (which mocks compress() and run_ocr() to
verify routing logic in isolation). These tests exercise the real
Ghostscript and OCRmyPDF binaries against purpose-built fixtures so the
"three surfaces, one pipeline" guarantee is verified end-to-end.

Phase 2 item 5 of ROADMAP.md.
"""

import shutil

import pytest

from pdf_ocr_compress.core.pipeline import run_pipeline

requires_ghostscript = pytest.mark.skipif(
    not (shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")),
    reason="Ghostscript not installed",
)
requires_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract"),
    reason="Tesseract not installed",
)


@requires_ghostscript
def test_compress_only_branch(text_pdf, tmp_path):
    """A PDF with a text layer takes the compress-only branch in mode='auto'.

    The needs_ocr() probe sees the /Font resource and routes to compress().
    """
    out = tmp_path / "out.pdf"

    result = run_pipeline(text_pdf, out, mode="auto", preset="smallest")

    assert result.ocr_ran is False
    assert result.ocr_skipped_reason == "input_has_text_layer"
    assert result.output_path.exists()
    assert result.output_bytes > 0
    # Ghostscript preserves the text layer when OCR is skipped.
    assert result.pdfminer_text_extractable is True


@requires_ghostscript
@requires_tesseract
def test_ocr_branch(image_only_pdf, tmp_path):
    """An image-only PDF takes the OCR branch with integrated optimization.

    needs_ocr() returns True (no /Font resource), so run_pipeline calls
    run_ocr() which invokes OCRmyPDF with --optimize matching the preset.
    Text fidelity (token-count round-trip) is item 6's job; here we only
    verify the OCR branch fires and produces a text-bearing output.
    """
    out = tmp_path / "out.pdf"

    result = run_pipeline(image_only_pdf, out, mode="auto", preset="smallest")

    assert result.ocr_ran is True
    assert result.ocr_skipped_reason is None
    assert result.output_path.exists()
    assert result.output_bytes > 0
    # OCRmyPDF added a text layer; pdfminer should now extract something.
    assert result.pdfminer_text_extractable is True


@requires_ghostscript
def test_passthrough_branch_when_every_preset_grows(incompressible_pdf, tmp_path):
    """A PDF Ghostscript inflates under every preset triggers passthrough.

    Verifies the oversize-fallback chain: archival grew -> retry smallest
    -> still grew -> copy input verbatim. preset_actually_used reports
    'passthrough' and output_bytes equals input_bytes (Design rule #1).
    """
    out = tmp_path / "out.pdf"

    result = run_pipeline(incompressible_pdf, out, mode="compress", preset="archival")

    assert result.preset_actually_used == "passthrough"
    assert result.output_bytes == result.input_bytes
    assert result.pct_change == 0.0
    assert result.ocr_ran is False
    assert result.ocr_skipped_reason == "compress_only_mode"
