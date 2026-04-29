"""Pipeline tests for core.compress.compress.

Requires Ghostscript on PATH (compress() shells out to it). Skipped
if Ghostscript is unavailable.
"""

import shutil

import pytest

from pdf_ocr_compress.core.compress import compress

requires_ghostscript = pytest.mark.skipif(
    not (shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")),
    reason="Ghostscript not installed",
)


@requires_ghostscript
def test_compress_writes_to_requested_path(tmp_path, sample_pdf):
    """compress() must return the exact output path the caller asked for.

    Regression guard for the _processed_processed double-suffix bug
    fixed in commit 0d85b3b.
    """
    out = tmp_path / "compressed.pdf"
    result = compress(sample_pdf, out, preset="balanced")

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


@requires_ghostscript
def test_compress_does_not_clobber_input(tmp_path, sample_pdf):
    """When output == input, compress() must pick a unique name."""
    in_copy = tmp_path / "doc.pdf"
    in_copy.write_bytes(sample_pdf.read_bytes())
    original_size = in_copy.stat().st_size

    result = compress(in_copy, in_copy, preset="balanced")

    assert result != in_copy
    assert result.exists()
    assert in_copy.exists()
    assert in_copy.stat().st_size == original_size  # original untouched
    assert result.stem.startswith("doc_processed")
