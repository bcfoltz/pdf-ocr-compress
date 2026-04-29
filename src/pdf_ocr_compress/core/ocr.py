# ocr.py — ALWAYS writes a brand-new output file
import shutil
import time
from pathlib import Path
from subprocess import CalledProcessError, run

from ..config import get_config
from ..utils.errors import PDFProcessingError, SystemToolError
from ..utils.file_utils import unique_output_path
from ..utils.logging_config import get_logger, get_performance_logger
from .oversize import enforce_oversize_policy

logger = get_logger("ocr")
perf_logger = get_performance_logger("ocr")


def _optimize_args(preset: str) -> list[str]:
    levels = {"archival": "0", "balanced": "2", "smallest": "3"}
    if preset not in levels:
        raise ValueError("preset must be one of: archival, balanced, smallest")
    return ["--optimize", levels[preset]]


def run_ocr(
    input_pdf: Path,
    output_pdf: Path,
    lang: str = None,
    preset: str = None,
    pdfa: bool = None,
    jobs: int = None,
    force_ocr: bool = None,
    *,
    _enforce_oversize: bool = True,
    _result: dict | None = None,
) -> Path:
    """
    Runs OCRmyPDF and returns the NEW output path created.
    Never writes in place; never overwrites existing files.

    `_enforce_oversize` is private: when True (default), the configured
    oversize_policy is applied at the end (Design rule #1, output ≤ input).
    The policy's "fallback retry" recurses with _enforce_oversize=False to
    avoid an infinite loop.

    `_result` is an optional OUT-parameter dict; when supplied the function
    populates _result["preset_used"] with the preset whose output we
    actually shipped — "passthrough" if the input was copied verbatim,
    "smallest" if the fallback retry succeeded, otherwise the requested
    preset.
    """
    # Get configuration defaults
    settings = get_config().settings

    # Apply defaults from configuration
    if lang is None:
        lang = settings.default_language
    if preset is None:
        preset = settings.default_preset
    if pdfa is None:
        pdfa = False
    if jobs is None:
        jobs = settings.default_jobs
    if force_ocr is None:
        force_ocr = False

    # Validate inputs
    if not input_pdf.exists():
        raise PDFProcessingError(
            f"Input file not found: {input_pdf}",
            f"Cannot find input file '{input_pdf.name}'",
            [
                "Check that the file path is correct",
                "Ensure the file exists and is accessible",
                "Try browsing for the file instead of typing the path",
            ],
            "INPUT_FILE_NOT_FOUND",
        )

    # Check if OCRmyPDF is available
    if not shutil.which("ocrmypdf"):
        raise SystemToolError(
            "ocrmypdf",
            "OCRmyPDF not found in PATH",
            [
                "Install OCRmyPDF: pip install ocrmypdf",
                "Ensure OCRmyPDF is in your system PATH",
                "Verify installation with: ocrmypdf --version",
            ],
        )

    # Ensure we write to a fresh file and never to the input
    if output_pdf.exists() or output_pdf.resolve() == input_pdf.resolve():
        output_pdf = unique_output_path(output_pdf, suffix="_ocr")

    # Log processing start
    perf_logger.log_processing_start(
        input_pdf, "OCR", language=lang, preset=preset, jobs=jobs, force_ocr=force_ocr
    )

    start_time = time.time()

    try:
        args = [
            "ocrmypdf",
            "--output-type",
            "pdf",
            "--jobs",
            str(jobs),
            "--language",
            lang,
            "--rotate-pages",
            "--tesseract-timeout",
            str(settings.tesseract_timeout),
        ]

        # OCR strategy
        args.append("--force-ocr" if force_ocr else "--skip-text")

        # Optimization level per preset
        args += _optimize_args(preset)

        # Optional: lossy JBIG2 only for "smallest" preset
        if preset == "smallest":
            args += ["--jbig2-lossy"]

        # Optional PDF/A-2
        if pdfa:
            args += ["--pdfa", "2"]

        # Inputs
        args += [str(input_pdf), str(output_pdf)]

        logger.info(f"Starting OCR processing: {input_pdf.name}")
        logger.debug(f"OCR command: {' '.join(args)}")

        result = run(args, check=False, capture_output=True, text=True)

        # Handle OCRmyPDF exit codes
        # 0 = success
        # 6 = already has text (with --skip-text) - not an error
        # 3 = error but output may still be usable
        if result.returncode == 0:
            logger.info(f"OCR completed successfully: {output_pdf.name}")
        elif result.returncode == 6:
            logger.info(f"PDF already contains text, skipping OCR: {input_pdf.name}")
            # Copy input to output since no OCR was needed
            if not output_pdf.exists():
                shutil.copy2(input_pdf, output_pdf)
        elif result.returncode == 3:
            logger.warning(f"OCR completed with warnings (exit 3): {output_pdf.name}")
            if not output_pdf.exists():
                raise CalledProcessError(
                    result.returncode, args, result.stdout, result.stderr
                )
        else:
            # Other exit codes are genuine errors
            raise CalledProcessError(
                result.returncode, args, result.stdout, result.stderr
            )

        if result.stderr:
            logger.debug(f"OCR output: {result.stderr}")

        duration = time.time() - start_time
        perf_logger.log_processing_complete(
            input_pdf,
            "OCR",
            duration,
            output_pdf,
            language=lang,
            preset=preset,
            jobs=jobs,
        )

        logger.info(f"OCR processing completed in {duration:.1f}s: {output_pdf.name}")

        if not _enforce_oversize:
            if _result is not None:
                _result["preset_used"] = preset
            return output_pdf

        # Oversize-policy guard: per Design rule #1, output ≤ input. On
        # "fallback", retry with --optimize 3 (preset=smallest) if we
        # weren't already using it; if smallest also grows the file, copy
        # input verbatim. The retry is a full re-run of OCRmyPDF, which is
        # expensive — that's the documented cost of opting into "fallback"
        # for the OCR branch.
        def _retry_smallest() -> Path:
            return run_ocr(
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                lang=lang,
                preset="smallest",
                pdfa=pdfa,
                jobs=jobs,
                force_ocr=force_ocr,
                _enforce_oversize=False,
            )

        outcome: dict[str, str] = {}
        final_path = enforce_oversize_policy(
            input_pdf,
            output_pdf,
            settings.oversize_policy,
            can_retry=(preset != "smallest"),
            retry_with_smallest=_retry_smallest,
            outcome=outcome,
        )
        if _result is not None:
            status = outcome.get("status")
            if status == "passthrough":
                _result["preset_used"] = "passthrough"
            elif status == "retry_succeeded":
                _result["preset_used"] = "smallest"
            else:
                _result["preset_used"] = preset
        return final_path

    except CalledProcessError as e:
        duration = time.time() - start_time
        error_msg = f"OCR failed after {duration:.1f}s: {e}"

        if e.stderr:
            error_msg += f" - {e.stderr}"

        perf_logger.log_processing_error(input_pdf, "OCR", error_msg)
        logger.error(error_msg)

        # Clean up failed output
        if output_pdf.exists():
            try:
                output_pdf.unlink()
            except Exception:
                pass

        # Convert to user-friendly error
        if "tesseract" in str(e).lower():
            raise SystemToolError(
                "tesseract",
                str(e),
                [
                    "Install Tesseract OCR using the provided installation scripts",
                    "Ensure Tesseract is in your system PATH",
                    f"Check if the language '{lang}' is installed",
                    "Verify with: tesseract --version",
                ],
            ) from e
        else:
            raise PDFProcessingError(
                f"OCR processing failed: {e}",
                f"Failed to add text recognition to '{input_pdf.name}'",
                [
                    "Check that the PDF is not corrupted",
                    "Try with a smaller number of parallel jobs (--jobs 1)",
                    "Ensure you have enough free disk space",
                    "Check the log files for detailed error information",
                ],
            ) from e

    except Exception as e:
        duration = time.time() - start_time
        perf_logger.log_processing_error(input_pdf, "OCR", str(e))
        logger.error(f"Unexpected OCR error after {duration:.1f}s: {e}")

        # Clean up failed output
        if output_pdf.exists():
            try:
                output_pdf.unlink()
            except Exception:
                pass

        raise PDFProcessingError(
            f"Unexpected OCR error: {e}",
            f"An unexpected error occurred while processing '{input_pdf.name}'",
            [
                "Please try again",
                "If the problem persists, check the log files",
                "Consider reporting this issue on GitHub",
            ],
        ) from e
