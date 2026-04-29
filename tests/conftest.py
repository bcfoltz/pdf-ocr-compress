"""Shared pytest fixtures."""

import pikepdf
import pytest


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory):
    """A tiny 1-page blank PDF, generated once per session."""
    path = tmp_path_factory.mktemp("fixtures") / "sample.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))  # US Letter
    pdf.save(path)
    return path


@pytest.fixture(scope="session")
def text_pdf(tmp_path_factory):
    """A 1-page PDF with a /Font resource and a 'Hello World' text content stream.

    Mimics ScanSnap-style scanner output: already has a text layer so OCR is
    redundant. Used to verify needs_ocr returns False on text-bearing PDFs.
    """
    path = tmp_path_factory.mktemp("fixtures") / "text.pdf"
    pdf = pikepdf.new()
    font = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica,
        )
    )
    pdf.add_blank_page(page_size=(612, 792))
    pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    pdf.pages[0].Contents = pdf.make_stream(
        b"BT /F1 24 Tf 100 700 Td (Hello World) Tj ET"
    )
    pdf.save(path)
    return path
