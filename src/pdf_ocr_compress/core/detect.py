# detect.py — simple heuristic to decide if OCR is needed
from pathlib import Path

from pdfminer.high_level import extract_text


def needs_ocr(pdf_path: Path, sample_pages: int = 5) -> bool:
    """
    If the first few pages have no extractable text,
    treat the PDF as scanned and run OCR.
    """
    try:
        text = extract_text(str(pdf_path), maxpages=sample_pages) or ""
    except Exception:
        # Corrupt/encrypted or pdfminer failed -> safer to try OCR
        return True
    return len(text.strip()) == 0
