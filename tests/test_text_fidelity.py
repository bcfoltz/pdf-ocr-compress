"""Round-trip text-fidelity tests for run_pipeline.

Phase 2 item 6 of ROADMAP.md. Operationalizes "output is RAG-usable":
take a multi-token text-bearing input, run it through the pipeline, and
verify pdfminer extracts approximately the same content. Catches gross
failures the unit tests can't see -- empty OCR layers, font-stripping
compress passes, garbled extraction.

Two cases:
    compress branch: text_paragraph_pdf (already has /Font) -> mode=auto
                     routes to compress(). Round-trip fidelity should be
                     near-perfect since Ghostscript pdfwrite preserves
                     text layers.
    OCR branch:      image_paragraph_pdf (no /Font) -> mode=auto routes
                     to OCR. Round-trip fidelity is bounded by Tesseract
                     accuracy on the rendered raster.

Tokenization choice: pdfminer extracting from OCRmyPDF's Form-XObject
text layer concatenates the last word of one OCR line with the first
word of the next without inserting whitespace ("dog" + "Pack" -> "dogPack").
The content survives but plain text.split() under-counts. We split on
both whitespace AND lowercase->uppercase transitions, which recovers
the per-word count without masking real Tesseract recognition errors
(missing characters, hallucinated runs of one case).
"""

import re
import shutil

import pytest

# tests/ is not a package, so pytest's rootdir-injection makes conftest
# importable as a top-level module (no leading dot).
from conftest import PARAGRAPH_TEXT
from pdfminer.high_level import extract_text

from pdf_ocr_compress.core.pipeline import run_pipeline

requires_ghostscript = pytest.mark.skipif(
    not (shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")),
    reason="Ghostscript not installed",
)
requires_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract"),
    reason="Tesseract not installed",
)

# Token recovery tolerance: pdfminer + Tesseract round-trip can drop or
# split a small number of tokens at OCR-line boundaries. ROADMAP item 6
# specifies +/-10%; we use that as the upper bound for both branches.
TOLERANCE = 0.10


def _tokens(text: str) -> list[str]:
    """Tokenize a string into word-like runs.

    Splits on whitespace AND lowercase->uppercase boundaries so OCR
    artifacts like "dogPack" -> ["dog", "Pack"] don't artificially
    deflate the count.
    """
    return re.findall(r"[A-Z][a-z]*|[a-z]+", text)


def _assert_rag_usable(extracted: str, expected_token_count: int) -> None:
    """Common shape: non-empty, not all form-feeds, token count within +/-10%."""
    assert extracted, "pdfminer returned empty -- output has no text layer"
    assert extracted.replace(
        "\f", ""
    ).strip(), "pdfminer returned only form-feeds -- output is page-separators only"
    actual = len(_tokens(extracted))
    assert actual > 0, "tokenized output is empty"
    drift = abs(actual - expected_token_count)
    assert drift <= TOLERANCE * expected_token_count, (
        f"token count drift {drift} exceeds {TOLERANCE:.0%} of "
        f"{expected_token_count} (got {actual})"
    )


@requires_ghostscript
def test_compress_branch_preserves_text_fidelity(text_paragraph_pdf, tmp_path):
    """text_paragraph_pdf round-trips through compress() with token fidelity.

    The compress branch must not strip /Font resources or rewrite the
    text layer in a way that defeats pdfminer extraction (Phase 0 bug #3).
    """
    input_text = extract_text(str(text_paragraph_pdf))
    expected = len(_tokens(input_text))
    assert expected > 0, "fixture itself is not extractable"

    out = tmp_path / "out.pdf"
    result = run_pipeline(text_paragraph_pdf, out, mode="auto", preset="smallest")

    assert result.ocr_ran is False
    assert result.pdfminer_text_extractable is True
    extracted = extract_text(str(result.output_path))
    _assert_rag_usable(extracted, expected)


@requires_ghostscript
@requires_tesseract
def test_ocr_branch_preserves_text_fidelity(image_paragraph_pdf, tmp_path):
    """image_paragraph_pdf round-trips through run_ocr() with token fidelity.

    The OCR branch must produce a text layer pdfminer can extract with
    approximately the same content as what was rendered into the image.
    Catches the tesseract-timeout-style bug where OCR "succeeds" but
    Tesseract had no time to recognize anything.
    """
    expected = len(_tokens(PARAGRAPH_TEXT))

    out = tmp_path / "out.pdf"
    result = run_pipeline(image_paragraph_pdf, out, mode="auto", preset="smallest")

    assert result.ocr_ran is True
    assert result.pdfminer_text_extractable is True
    extracted = extract_text(str(result.output_path))
    _assert_rag_usable(extracted, expected)
