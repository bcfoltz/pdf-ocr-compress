"""Single entry point for the auto-routing pipeline.

CLI / GUI / API all call run_pipeline() so the operation produces the same
ProcessResult report regardless of surface (ROADMAP item 4 + the
"three surfaces, one pipeline" rule in CLAUDE.md). The report carries
size deltas, timing, OCR routing decisions, the preset that actually
shipped (matters when the oversize fallback fired), and a pdfminer
text-extractability smoke check.
"""

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from ..config import get_config
from ..utils.file_utils import human_readable_size
from .compress import compress as _compress
from .detect import needs_ocr
from .ocr import run_ocr as _run_ocr

Mode = Literal["auto", "ocr", "compress"]
OcrSkipReason = Literal["input_has_text_layer", "compress_only_mode"]


@dataclass
class ProcessResult:
    """Structured report for a single pipeline operation.

    Returned by run_pipeline() and propagated to all three surfaces.
    """

    output_path: Path
    input_bytes: int
    output_bytes: int
    pct_change: float  # negative = output shrunk; positive = output grew
    ocr_ran: bool
    ocr_skipped_reason: str | None
    processing_seconds: float
    preset_actually_used: str
    pdfminer_text_extractable: bool
    # Sampled text coverage of the output (P-002): up to 10 pages spread
    # across the document. Defaulted so pre-existing constructions stay
    # valid; pdfminer_text_extractable is derived (pages_with_text > 0).
    text_pages_sampled: int = 0
    text_pages_with_text: int = 0
    text_words: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["output_path"] = str(d["output_path"])
        return d

    def one_line_summary(self) -> str:
        size_delta = (
            f"{human_readable_size(self.input_bytes)} -> "
            f"{human_readable_size(self.output_bytes)}"
        )
        sign = "-" if self.pct_change < 0 else "+"
        delta_pct = f"{sign}{abs(self.pct_change):.1f}%"
        operation = "OCR" if self.ocr_ran else "compress"
        text_status = "text OK" if self.pdfminer_text_extractable else "text MISSING"
        return (
            f"{self.output_path.name}: {size_delta} ({delta_pct}) | "
            f"{operation} ({self.preset_actually_used}, "
            f"{self.processing_seconds:.1f}s) | {text_status}"
        )


def run_pipeline(
    input_pdf: Path,
    output_pdf: Path,
    *,
    mode: Mode = "auto",
    lang: str | None = None,
    preset: str | None = None,
    pdfa: bool = False,
    jobs: int | None = None,
    force_ocr: bool = False,
) -> ProcessResult:
    """Execute the requested pipeline branch and return a ProcessResult.

    `mode`:
    - "auto":      route on needs_ocr(input). If True (or force_ocr), OCR;
                   else compress only.
    - "ocr":       always OCR. force_ocr controls --force-ocr vs --skip-text.
    - "compress":  always compress; OCR is skipped.

    Honors the configured oversize_policy via the underlying compress() /
    run_ocr() guards — preset_actually_used reflects what actually shipped.
    """
    settings = get_config().settings
    if preset is None:
        preset = settings.default_preset

    start = time.time()
    input_bytes = input_pdf.stat().st_size

    op_result: dict = {}
    ocr_ran: bool
    ocr_skipped_reason: str | None

    if mode == "compress":
        ocr_ran = False
        ocr_skipped_reason = "compress_only_mode"
        produced = _compress(input_pdf, output_pdf, preset=preset, _result=op_result)

    elif mode == "ocr":
        ocr_ran = True
        ocr_skipped_reason = None
        produced = _run_ocr(
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            lang=lang,
            preset=preset,
            pdfa=pdfa,
            jobs=jobs,
            force_ocr=force_ocr,
            _result=op_result,
        )

    else:  # mode == "auto"
        if force_ocr or needs_ocr(input_pdf):
            ocr_ran = True
            ocr_skipped_reason = None
            produced = _run_ocr(
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                lang=lang,
                preset=preset,
                pdfa=pdfa,
                jobs=jobs,
                force_ocr=True,
                _result=op_result,
            )
        else:
            ocr_ran = False
            ocr_skipped_reason = "input_has_text_layer"
            produced = _compress(
                input_pdf, output_pdf, preset=preset, _result=op_result
            )

    elapsed = time.time() - start
    output_bytes = produced.stat().st_size
    pct_change = 100.0 * (output_bytes - input_bytes) / max(input_bytes, 1)

    pages_sampled, pages_with_text, words = _text_coverage(produced)

    return ProcessResult(
        output_path=produced,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        pct_change=pct_change,
        ocr_ran=ocr_ran,
        ocr_skipped_reason=ocr_skipped_reason,
        processing_seconds=elapsed,
        preset_actually_used=op_result.get("preset_used", preset),
        pdfminer_text_extractable=pages_with_text > 0,
        text_pages_sampled=pages_sampled,
        text_pages_with_text=pages_with_text,
        text_words=words,
    )


def _text_coverage(pdf_path: Path, max_sample_pages: int = 10) -> tuple[int, int, int]:
    """Sampled page-level text coverage: (pages_sampled, pages_with_text, words).

    Replaces the old first-2-pages boolean probe (which passed a book
    whose text layer died on page 3). Samples up to `max_sample_pages`
    pages spread evenly across the document — always including the first
    and last — and counts whitespace-delimited words on them. The point
    is to tell a downstream RAG ingestion how much of the document it
    will actually see, not to diagnose extraction problems. Returns
    (0, 0, 0) on any failure (corrupt/encrypted/parser-strict), matching
    the old probe's failure envelope.
    """
    try:
        import pikepdf
        from pdfminer.high_level import extract_text

        with pikepdf.open(str(pdf_path)) as pdf:
            n_pages = len(pdf.pages)
        if n_pages <= 0:
            return (0, 0, 0)
        if n_pages <= max_sample_pages:
            sample = list(range(n_pages))
        else:
            step = (n_pages - 1) / (max_sample_pages - 1)
            sample = sorted({round(i * step) for i in range(max_sample_pages)})

        # extract_text per page (one parse pass each, capped at
        # max_sample_pages) rather than one extract_pages sweep:
        # OCRmyPDF's invisible text layer lives inside Form XObjects,
        # which layout analysis wraps in LTFigure — text-container
        # iteration misses it, while the TextConverter path sees it.
        pages_with_text = 0
        words = 0
        for idx in sample:
            text = extract_text(str(pdf_path), page_numbers={idx}) or ""
            if text.strip():
                pages_with_text += 1
            words += len(text.split())
        return (len(sample), pages_with_text, words)
    except Exception:
        return (0, 0, 0)
