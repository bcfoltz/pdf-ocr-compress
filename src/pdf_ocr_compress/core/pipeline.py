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

    return ProcessResult(
        output_path=produced,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        pct_change=pct_change,
        ocr_ran=ocr_ran,
        ocr_skipped_reason=ocr_skipped_reason,
        processing_seconds=elapsed,
        preset_actually_used=op_result.get("preset_used", preset),
        pdfminer_text_extractable=_pdfminer_text_extractable(produced),
    )


def _pdfminer_text_extractable(pdf_path: Path) -> bool:
    """Smoke check: does pdfminer extract any text from the first 2 pages?

    Used as a post-hoc fidelity signal in ProcessResult. False on any
    pdfminer exception (corrupt/encrypted/parser-strict failure) — the
    point is to confirm a downstream RAG ingestion would see text, not
    to diagnose extraction problems.
    """
    try:
        from pdfminer.high_level import extract_text

        text = extract_text(str(pdf_path), maxpages=2) or ""
    except Exception:
        return False
    return bool(text.strip())
