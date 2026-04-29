"""FastAPI server for PDF OCR + Compression REST API."""

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import get_config
from ..core.batch import BatchJobState, run_batch
from ..core.pipeline import run_pipeline
from .errors import (
    BATCH_JOB_NOT_FOUND,
    FILE_NOT_FOUND,
    INPUT_NOT_PDF,
    INVALID_FOLDER,
    INVALID_MODE,
    INVALID_OUTPUT_DIR,
    INVALID_PRESET,
    PROCESSING_FAILED,
    APIException,
    install_exception_handlers,
)

app = FastAPI(
    title="PDF OCR + Compression API",
    description="REST API for processing scanned PDFs with OCR and compression",
    version="1.0.0",
)
install_exception_handlers(app)


# Temporary storage for processed files
TEMP_DIR = Path(tempfile.gettempdir()) / "pdf_ocr_api"
TEMP_DIR.mkdir(exist_ok=True)

# File storage with cleanup (keep files for 1 hour)
file_storage = {}

# Phase 3 — in-memory batch job state. Phase 4 swaps for SQLite.
batch_jobs: dict = {}


def cleanup_old_jobs():
    """Remove batch jobs older than 1 hour. Mirrors cleanup_old_files()."""
    now = datetime.now()
    expired = []
    for job_id, state in batch_jobs.items():
        try:
            started = datetime.fromisoformat(state.started_at)
        except (ValueError, AttributeError):
            continue
        if now - started > timedelta(hours=1):
            expired.append(job_id)
    for job_id in expired:
        del batch_jobs[job_id]


class ProcessResponse(BaseModel):
    """Response model for /api/process endpoint.

    Phase 2 item 4 added the lower block of fields (ocr_ran,
    ocr_skipped_reason, preset_actually_used, pdfminer_text_extractable,
    pct_change). The original block (original_size / output_size /
    reduction_percent / processing_time) is kept for backward
    compatibility with existing API consumers — they describe the same
    operation, just under the legacy field names.
    """

    status: str
    message: str
    file_id: str
    mode: str
    preset: str  # the requested preset
    original_size: int
    output_size: int
    reduction_percent: float  # positive = output is smaller
    processing_time: float

    # Phase 2 item 4 — structured operation report
    ocr_ran: bool
    ocr_skipped_reason: str | None
    preset_actually_used: str  # may differ from `preset` if oversize fallback fired
    pdfminer_text_extractable: bool
    pct_change: float  # negative = output shrunk; positive = output grew


class BatchRequest(BaseModel):
    """Request body for POST /api/batch.

    Server-side folder path only — no upload. The folder must exist on the
    machine running the API. Empty folders are accepted and produce a
    zero-file report (matches CLI behavior).
    """

    folder: str
    output_dir: str | None = None
    mode: str = "auto"
    preset: str | None = None
    language: str | None = None
    jobs: int | None = None
    pdfa: bool = False
    force_ocr: bool = False


class BatchAcceptedResponse(BaseModel):
    """202 Accepted body returned by POST /api/batch."""

    status: str  # "queued"
    job_id: str
    total_files: int


def cleanup_old_files():
    """Remove files older than 1 hour from storage."""
    now = datetime.now()
    expired = []

    for file_id, info in file_storage.items():
        if now - info["timestamp"] > timedelta(hours=1):
            expired.append(file_id)
            try:
                if info["path"].exists():
                    info["path"].unlink()
                if info.get("workdir") and info["workdir"].exists():
                    shutil.rmtree(info["workdir"], ignore_errors=True)
            except Exception:
                pass

    for file_id in expired:
        del file_storage[file_id]


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "PDF OCR + Compression API",
        "version": "1.0.0",
        "endpoints": {
            "POST /api/process": "Process a PDF file",
            "GET /api/download/{file_id}": "Download processed file",
            "GET /health": "Health check",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "pdf-ocr-compress-api"}


@app.post("/api/process", response_model=ProcessResponse)
async def process_pdf(
    file: UploadFile = File(..., description="PDF file to process"),
    mode: str = Form("auto", description="Processing mode: auto, ocr, compress"),
    preset: str = Form(
        "balanced", description="Quality preset: balanced, archival, smallest"
    ),
    language: str = Form("eng", description="OCR language codes (e.g., eng, eng+spa)"),
    pdfa: bool = Form(False, description="Produce PDF/A-2 compliant output"),
    force_ocr: bool = Form(False, description="Force OCR even if text exists"),
    jobs: int = Form(4, description="Number of parallel jobs for OCR"),
):
    """
    Process a PDF file with OCR and/or compression.

    Returns a file_id that can be used to download the processed file.
    """
    cleanup_old_files()

    # Validate inputs
    if mode not in ["auto", "ocr", "compress"]:
        raise APIException(400, INVALID_MODE, f"Invalid mode: {mode}")

    if preset not in ["balanced", "archival", "smallest"]:
        raise APIException(400, INVALID_PRESET, f"Invalid preset: {preset}")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise APIException(400, INPUT_NOT_PDF, "File must be a PDF")

    # Create work directory
    file_id = str(uuid.uuid4())
    workdir = TEMP_DIR / file_id
    workdir.mkdir(exist_ok=True)

    input_path = workdir / "input.pdf"
    output_base = workdir / "output.pdf"

    try:
        # Save uploaded file
        with open(input_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Run the unified pipeline; it builds the structured ProcessResult
        # report we surface in the response.
        result = run_pipeline(
            input_path,
            output_base,
            mode=mode,
            lang=language,
            preset=preset,
            pdfa=pdfa,
            jobs=jobs,
            force_ocr=force_ocr,
        )

        # Store file info
        file_storage[file_id] = {
            "path": result.output_path,
            "workdir": workdir,
            "timestamp": datetime.now(),
            "original_name": file.filename,
            "mode": mode,
            "preset": preset,
        }

        # reduction_percent uses the inverse-sign convention of pct_change
        # (positive when output shrank); kept for API backward compat.
        reduction_percent = -result.pct_change

        return ProcessResponse(
            status="success",
            message="Processing complete",
            file_id=file_id,
            mode=mode,
            preset=preset,
            original_size=result.input_bytes,
            output_size=result.output_bytes,
            reduction_percent=round(reduction_percent, 2),
            processing_time=round(result.processing_seconds, 2),
            ocr_ran=result.ocr_ran,
            ocr_skipped_reason=result.ocr_skipped_reason,
            preset_actually_used=result.preset_actually_used,
            pdfminer_text_extractable=result.pdfminer_text_extractable,
            pct_change=round(result.pct_change, 2),
        )

    except APIException:
        # Already a wire-shape exception (validation etc.); just clean up.
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
        raise
    except Exception as e:
        # Cleanup on error. PDFProcessingError flows to the domain handler
        # registered in install_exception_handlers; everything else is
        # mapped to a generic PROCESSING_FAILED 500.
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
        from ..utils.errors import PDFProcessingError

        if isinstance(e, PDFProcessingError):
            raise
        raise APIException(
            500, PROCESSING_FAILED, f"Processing failed: {str(e)}"
        ) from e


@app.get("/api/download/{file_id}")
async def download_file(file_id: str):
    """
    Download a processed PDF file.

    Files are kept for 1 hour after processing.
    """
    cleanup_old_files()

    if file_id not in file_storage:
        raise APIException(404, FILE_NOT_FOUND, "File not found or expired")

    file_info = file_storage[file_id]

    if not file_info["path"].exists():
        raise APIException(404, FILE_NOT_FOUND, "File has been deleted")

    # Return original filename as-is
    download_name = file_info["original_name"]

    return FileResponse(
        path=file_info["path"], media_type="application/pdf", filename=download_name
    )


@app.post(
    "/api/batch",
    response_model=BatchAcceptedResponse,
    status_code=202,
)
async def start_batch(req: BatchRequest, background_tasks: BackgroundTasks):
    """Queue a folder-batch job. Returns a job_id immediately; processing
    runs in the background. Poll GET /api/batch/{job_id}/status for state.
    """
    cleanup_old_jobs()

    if req.mode not in ["auto", "ocr", "compress"]:
        raise APIException(400, INVALID_MODE, f"Invalid mode: {req.mode}")

    folder = Path(req.folder)
    if not folder.exists() or not folder.is_dir():
        raise APIException(
            400,
            INVALID_FOLDER,
            f"Folder does not exist or is not a directory: {req.folder}",
        )

    output_dir = (
        Path(req.output_dir) if req.output_dir is not None else folder / "processed"
    )
    # If output_dir doesn't exist, its parent must be writable so we can mkdir.
    target_for_writability_check = (
        output_dir if output_dir.exists() else output_dir.parent
    )
    if not os.access(target_for_writability_check, os.W_OK):
        raise APIException(
            400,
            INVALID_OUTPUT_DIR,
            f"Output dir (or its parent) is not writable: {output_dir}",
        )

    settings = get_config().settings
    preset = req.preset if req.preset is not None else settings.default_preset
    if preset not in ["archival", "balanced", "smallest"]:
        raise APIException(400, INVALID_PRESET, f"Invalid preset: {preset}")

    language = req.language if req.language is not None else settings.default_language
    jobs = req.jobs if req.jobs is not None else settings.default_jobs

    pdfs = sorted(p for p in folder.glob("*.pdf") if p.is_file())
    job_id = str(uuid.uuid4())
    state = BatchJobState(
        job_id=job_id,
        status="queued",
        started_at=datetime.now().isoformat(timespec="milliseconds"),
        finished_at=None,
        progress_current=0,
        progress_total=len(pdfs),
        report=None,
        error_msg=None,
    )
    batch_jobs[job_id] = state

    def _run() -> None:
        state.status = "running"
        try:

            def cb(current: int, total: int, current_path: Path) -> None:
                state.progress_current = current
                state.progress_total = total

            report = run_batch(
                folder,
                output_dir,
                mode=req.mode,  # type: ignore[arg-type]
                preset=preset,
                lang=language,
                jobs=jobs,
                pdfa=req.pdfa,
                force_ocr=req.force_ocr,
                progress_callback=cb,
            )
            state.report = report
            state.status = "done"
        except (
            Exception
        ) as e:  # noqa: BLE001 — surface orchestrator-level errors to the client
            state.status = "error"
            state.error_msg = str(e)
        finally:
            state.finished_at = datetime.now().isoformat(timespec="milliseconds")

    background_tasks.add_task(_run)

    return BatchAcceptedResponse(status="queued", job_id=job_id, total_files=len(pdfs))


@app.get("/api/batch/{job_id}/status")
async def batch_status(job_id: str):
    """Poll a batch job's state. Returns 404 if unknown or expired."""
    cleanup_old_jobs()
    state = batch_jobs.get(job_id)
    if state is None:
        raise APIException(404, BATCH_JOB_NOT_FOUND, "Batch job not found or expired")
    return state.to_dict()


def start_server(host: str = "0.0.0.0", port: int = 8502):
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
