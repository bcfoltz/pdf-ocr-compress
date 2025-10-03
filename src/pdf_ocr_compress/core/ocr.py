# ocr.py — ALWAYS writes a brand-new output file
from pathlib import Path
from subprocess import run, CalledProcessError
import time
import shutil

from ..config import get_config
from ..utils.logging_config import get_performance_logger, get_logger
from ..utils.errors import SystemToolError, PDFProcessingError
from ..utils.temp_manager import get_temp_manager

logger = get_logger("ocr")
perf_logger = get_performance_logger("ocr")

def _optimize_args(preset: str) -> list[str]:
    levels = {"archival": "0", "balanced": "2", "smallest": "3"}
    if preset not in levels:
        raise ValueError("preset must be one of: archival, balanced, smallest")
    return ["--optimize", levels[preset]]

def _unique_output(path: Path, suffix: str = "_ocr") -> Path:
    """
    If the suggested output exists or equals the input, add a timestamped suffix.
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = path.with_name(f"{path.stem}{suffix}_{ts}{path.suffix}")
    i = 0
    out = base
    while out.exists():
        i += 1
        out = path.with_name(f"{path.stem}{suffix}_{ts}_{i}{path.suffix}")
    return out

def run_ocr(
    input_pdf: Path,
    output_pdf: Path,
    lang: str = None,
    preset: str = None,
    pdfa: bool = None,
    jobs: int = None,
    force_ocr: bool = None,
) -> Path:
    """
    Runs OCRmyPDF and returns the NEW output path created.
    Never writes in place; never overwrites existing files.
    """
    # Get configuration defaults
    config = get_config()
    
    # Apply defaults from configuration
    if lang is None:
        lang = config.settings.ocr.default_language
    if preset is None:
        preset = config.settings.compression.default_preset
    if pdfa is None:
        pdfa = False
    if jobs is None:
        jobs = config.settings.ocr.default_jobs
    if force_ocr is None:
        force_ocr = config.settings.ocr.force_ocr
    
    # Validate inputs
    if not input_pdf.exists():
        raise PDFProcessingError(
            f"Input file not found: {input_pdf}",
            f"Cannot find input file '{input_pdf.name}'",
            [
                "Check that the file path is correct",
                "Ensure the file exists and is accessible",
                "Try browsing for the file instead of typing the path"
            ],
            "INPUT_FILE_NOT_FOUND"
        )
    
    # Check if OCRmyPDF is available
    if not shutil.which("ocrmypdf"):
        raise SystemToolError(
            "ocrmypdf",
            "OCRmyPDF not found in PATH",
            [
                "Install OCRmyPDF: pip install ocrmypdf",
                "Ensure OCRmyPDF is in your system PATH",
                "Verify installation with: ocrmypdf --version"
            ]
        )
    
    # Ensure we write to a fresh file and never to the input
    if output_pdf.exists() or output_pdf.resolve() == input_pdf.resolve():
        output_pdf = _unique_output(output_pdf, suffix="_ocr")
    
    # Log processing start
    perf_logger.log_processing_start(
        input_pdf, "OCR", 
        language=lang, preset=preset, jobs=jobs, force_ocr=force_ocr
    )
    
    start_time = time.time()
    
    try:
        args = [
            "ocrmypdf",
            "--output-type", "pdf",
            "--jobs", str(jobs),
            "--language", lang,
            "--rotate-pages",
            "--tesseract-timeout", str(config.settings.ocr.tesseract_timeout),
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
                raise CalledProcessError(result.returncode, args, result.stdout, result.stderr)
        else:
            # Other exit codes are genuine errors
            raise CalledProcessError(result.returncode, args, result.stdout, result.stderr)

        if result.stderr:
            logger.debug(f"OCR output: {result.stderr}")

        duration = time.time() - start_time
        perf_logger.log_processing_complete(
            input_pdf, "OCR", duration, output_pdf,
            language=lang, preset=preset, jobs=jobs
        )

        logger.info(f"OCR processing completed in {duration:.1f}s: {output_pdf.name}")
        return output_pdf

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
                    "Verify with: tesseract --version"
                ]
            )
        else:
            raise PDFProcessingError(
                f"OCR processing failed: {e}",
                f"Failed to add text recognition to '{input_pdf.name}'",
                [
                    "Check that the PDF is not corrupted",
                    "Try with a smaller number of parallel jobs (--jobs 1)",
                    "Ensure you have enough free disk space",
                    "Check the log files for detailed error information"
                ]
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
                "Consider reporting this issue on GitHub"
            ]
        ) from e
