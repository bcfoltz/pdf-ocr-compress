# detect.py — decide if a PDF needs OCR, using pikepdf (tolerant parser).
from pathlib import Path

import pikepdf


def needs_ocr(pdf_path: Path, sample_pages: int = 5) -> bool:
    """Return True if the PDF appears to be image-only and needs OCR.

    Uses pikepdf instead of pdfminer because pdfminer's strict parser
    raises on real scanner output that pikepdf reads fine (Sample B in
    BENCHMARKS.md), which previously triggered useless multi-hour OCR
    passes on PDFs that already had a text layer.

    Heuristic: a PDF needs OCR only if pikepdf can't open it, OR if none
    of the first `sample_pages` pages declare any /Font resource. Pages
    with /Font entries have a real text layer (drawn with text-showing
    operators that reference those fonts).
    """
    try:
        pdf = pikepdf.open(str(pdf_path))
    except Exception:
        # Genuinely unreadable — safer to attempt OCR.
        return True

    try:
        for page in pdf.pages[:sample_pages]:
            try:
                fonts = page.Resources.Font
            except AttributeError:
                continue
            if len(fonts) > 0:
                return False
        return True
    finally:
        pdf.close()
