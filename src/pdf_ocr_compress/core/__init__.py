"""
Core processing modules for PDF OCR and compression.
"""

from .compress import compress
from .detect import needs_ocr
from .ocr import run_ocr

__all__ = [
    "run_ocr",
    "compress",
    "needs_ocr",
]
