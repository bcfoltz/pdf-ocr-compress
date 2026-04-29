"""
Core processing modules for PDF OCR and compression.
"""

from .batch import BatchJobState, BatchReport, BatchResult, run_batch
from .compress import compress
from .detect import needs_ocr
from .ocr import run_ocr
from .pipeline import ProcessResult, run_pipeline

__all__ = [
    "run_ocr",
    "compress",
    "needs_ocr",
    "run_pipeline",
    "ProcessResult",
    "run_batch",
    "BatchResult",
    "BatchReport",
    "BatchJobState",
]
