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
