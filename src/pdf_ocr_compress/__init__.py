"""
PDF OCR + Compression Tool

A cross-platform tool for adding OCR and compressing PDFs using Tesseract and Ghostscript.
"""

__version__ = "1.0.0"
__author__ = "PDF OCR Compress Contributors"

from .core.compress import compress
from .core.detect import needs_ocr
from .core.ocr import run_ocr

__all__ = ["run_ocr", "compress", "needs_ocr"]
