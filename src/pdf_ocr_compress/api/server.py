"""FastAPI server for PDF OCR + Compression REST API."""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from ..config import get_config
from ..core.batch import run_batch
from ..core.pipeline import run_pipeline
from ..utils.logging_config import setup_logging
from .errors import (
    BATCH_JOB_NOT_FOUND,
    FILE_NOT_FOUND,
    FILE_TOO_LARGE,
    INPUT_NOT_PDF,
    INVALID_FOLDER,
    INVALID_MODE,
    INVALID_OUTPUT_DIR,
    INVALID_PRESET,
    PROCESSING_FAILED,
    APIError,
    APIException,
    install_exception_handlers,
)
from .storage import Storage, default_storage

# Attach a console handler at import time so pipeline INFO messages
# (notably the oversize-fallback audit trail) reach uvicorn's console.
# setup_logging clears existing handlers first, so re-imports are safe.
setup_logging(structured_logging=False)

app = FastAPI(
    title="PDF OCR + Compression API",
    description="REST API for processing scanned PDFs with OCR and compression",
    version="1.0.0",
)
install_exception_handlers(app)


# Reusable OpenAPI `responses=` declarations so /docs renders the
# APIError shape under each route's error status codes. Keys are HTTP
# status codes; FastAPI fills the schema from the `model` field.
_PROCESS_ERROR_RESPONSES: dict = {
    400: {"model": APIError, "description": "Invalid input (mode/preset/file)"},
    422: {"model": APIError, "description": "Request validation failed"},
    500: {"model": APIError, "description": "Pipeline failure"},
    503: {
        "model": APIError,
        "description": "Tesseract or Ghostscript missing on PATH",
    },
}
_BATCH_START_ERROR_RESPONSES: dict = {
    400: {
        "model": APIError,
        "description": "Invalid mode/preset/folder/output_dir",
    },
    422: {"model": APIError, "description": "Request validation failed"},
}
_NOT_FOUND_RESPONSES: dict = {
    404: {"model": APIError, "description": "Resource not found or expired"},
}


# Temporary storage for processed files
TEMP_DIR = Path(tempfile.gettempdir()) / "pdf_ocr_api"
TEMP_DIR.mkdir(exist_ok=True)

# Phase 4 item 1 — SQLite-backed persistence. The module-level reference
# is a Storage instance (rebindable for tests via `set_storage`); routes
# read it through `_storage()` so monkeypatching is transparent.
STORAGE: Storage = default_storage()


def _storage() -> Storage:
    return STORAGE


def set_storage(storage: Storage) -> None:
    """Test hook — swap the module-level Storage for an isolated one.

    Production code never calls this; tests use it to point the app at a
    `tmp_path` SQLite DB so they don't touch the user's TEMP_DIR.
    """
    global STORAGE
    STORAGE = storage


def cleanup_old_jobs():
    """Remove batch_jobs rows older than the default TTL.

    SQLite-backed. Mirrors `cleanup_old_files` for the `batch_jobs`
    table (same 1-hour expiry window).
    """
    _storage().cleanup_expired_batch_jobs()


class ProcessResponse(BaseModel):
    """Response model for /api/process endpoint.

    Phase 2 item 4 added the lower block of fields (ocr_ran,
    ocr_skipped_reason, preset_actually_used, pdfminer_text_extractable,
    pct_change). The original block (original_size / output_size /
    reduction_percent / processing_time) is kept for backward
    compatibility with existing API consumers — they describe the same
    operation, just under the legacy field names.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "message": "Processing complete",
                "file_id": "0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f",
                "mode": "auto",
                "preset": "smallest",
                "original_size": 39_678_222,
                "output_size": 32_823_104,
                "reduction_percent": 17.28,
                "processing_time": 12.34,
                "ocr_ran": False,
                "ocr_skipped_reason": "input_has_text_layer",
                "preset_actually_used": "smallest",
                "pdfminer_text_extractable": True,
                "pct_change": -17.28,
                "text_pages_sampled": 10,
                "text_pages_with_text": 10,
                "text_words": 3140,
            }
        }
    )

    status: str
    message: str
    file_id: str
    mode: str
    preset: str  # the requested preset
    original_size: int
    output_size: int
    reduction_percent: float  # positive = output is smaller
    processing_time: float

    # Structured operation report (fields below added for detailed per-run data)
    ocr_ran: bool
    ocr_skipped_reason: str | None
    preset_actually_used: str  # may differ from `preset` if oversize fallback fired
    pdfminer_text_extractable: bool
    pct_change: float  # negative = output shrunk; positive = output grew

    # Sampled text coverage (P-002): up to 10 pages spread across the
    # output. pdfminer_text_extractable is derived (pages_with_text > 0).
    text_pages_sampled: int
    text_pages_with_text: int
    text_words: int


class BatchRequest(BaseModel):
    """Request body for POST /api/batch.

    Server-side folder path only — no upload. The folder must exist on the
    machine running the API. Empty folders are accepted and produce a
    zero-file report (matches CLI behavior).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "folder": "/data/scans/incoming",
                "output_dir": "/data/scans/processed",
                "mode": "auto",
                "preset": "smallest",
                "language": "eng",
                "jobs": 4,
                "pdfa": False,
                "force_ocr": False,
                "force": False,
            }
        }
    )

    folder: str
    output_dir: str | None = None
    mode: str = "auto"
    preset: str | None = None
    language: str | None = None
    jobs: int | None = None
    pdfa: bool = False
    force_ocr: bool = False
    # Reprocess inputs whose same-name output already exists (default:
    # skip them — incremental batch).
    force: bool = False


class BatchAcceptedResponse(BaseModel):
    """202 Accepted body returned by POST /api/batch."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "queued",
                "job_id": "0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f",
                "total_files": 47,
            }
        }
    )

    status: str  # "queued"
    job_id: str
    total_files: int


def cleanup_old_files():
    """Remove rows past expires_at and their on-disk artifacts.

    SQLite-backed. The 1-hour TTL is enforced via the `expires_at`
    column written by `Storage.insert_file`.
    """
    _storage().cleanup_expired_files()


@app.get("/", summary="API service info and endpoint index")
async def root():
    """Root endpoint listing the available API surface."""
    return {
        "service": "PDF OCR + Compression API",
        "version": _api_version(),
        "endpoints": {
            "POST /api/process": "Process one PDF",
            "GET /api/download/{file_id}": "Download a processed PDF",
            "POST /api/batch": "Queue a folder-batch job",
            "GET /api/batch/{job_id}/status": "Poll a batch job",
            "GET /health": "Service + tool detection",
            "GET /docs": "Interactive OpenAPI docs",
        },
    }


def _detect_ghostscript() -> str | None:
    """Find a Ghostscript binary on PATH. Returns the absolute path or None."""
    # Mirrors core.compress._gs_exe's preference order, but tolerates
    # absence (this endpoint reports state; it never raises).
    for candidate in ("gswin64c", "gswin32c", "gs"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _detect_tesseract() -> str | None:
    """Find the Tesseract binary on PATH. Returns absolute path or None."""
    return shutil.which("tesseract")


def _tesseract_languages(tesseract_path: str | None) -> list[str]:
    """Return the list of installed Tesseract language packs.

    Calls `tesseract --list-langs`; the first line is a header
    ("List of available languages (N):"), remaining lines are codes.
    Empty list on any failure (binary missing, parse error, timeout).
    """
    if tesseract_path is None:
        return []
    try:
        result = subprocess.run(
            [tesseract_path, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    # Tesseract emits the list on stderr in some builds, stdout in others.
    output = result.stdout or result.stderr or ""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    # First line is the header; everything else is a language code.
    return [line for line in lines[1:] if not line.startswith("List of")]


def _api_version() -> str:
    """Resolve the package version via importlib.metadata.

    Falls back to the FastAPI `app.version` string if the package is
    running from source without an installed dist (`pip install -e`
    installs metadata, so this should rarely fire in practice).
    """
    try:
        return importlib_metadata.version("pdf-ocr-compress")
    except importlib_metadata.PackageNotFoundError:
        return app.version


@app.get("/health")
async def health():
    """Health check endpoint.

    Reports environment state so a monitoring system can distinguish
    "API up" from "API up but Tesseract missing". Fields: `version`
    (pdf-ocr-compress version), `ghostscript_binary` and
    `tesseract_binary` (absolute paths or null), `tesseract_languages`
    (installed language codes), `queue_depth` (count of queued/running
    batch jobs).
    """
    tess = _detect_tesseract()
    return {
        "status": "healthy",
        "service": "pdf-ocr-compress-api",
        "version": _api_version(),
        "ghostscript_binary": _detect_ghostscript(),
        "tesseract_binary": tess,
        "tesseract_languages": _tesseract_languages(tess),
        "queue_depth": _storage().queue_depth(),
    }


@app.post(
    "/api/process",
    response_model=ProcessResponse,
    responses=_PROCESS_ERROR_RESPONSES,
    summary="Process one PDF (OCR + compression)",
)
def process_pdf(
    file: UploadFile = File(..., description="PDF file to process"),
    mode: str = Form(
        "auto",
        description=(
            "Processing mode. `auto` runs OCR only when needed (text-layer "
            "detection via pikepdf); `ocr` always runs OCR; `compress` skips "
            "OCR. One of: auto | ocr | compress."
        ),
    ),
    preset: str | None = Form(
        None,
        description=(
            "Compression preset. `smallest` is recommended for ScanSnap "
            "scans of any size and is enforced as the oversize-fallback "
            "target. One of: archival | balanced | smallest. Default from "
            "settings (factory default: smallest)."
        ),
    ),
    language: str | None = Form(
        None,
        description=(
            "Tesseract language codes joined by `+` (e.g. `eng`, `eng+spa`). "
            "Default from settings (factory default: eng)."
        ),
    ),
    pdfa: bool = Form(False, description="Produce PDF/A-2 compliant output"),
    force_ocr: bool = Form(
        False,
        description="Force OCR even if a text layer is already present.",
    ),
    jobs: int | None = Form(
        None,
        description=(
            "Number of parallel OCR workers (passed to OCRmyPDF). "
            "Default from settings (factory default: 4)."
        ),
    ),
):
    """Process one PDF with OCR + compression and return a file_id.

    The pipeline enforces the size-invariant guard: if the requested
    preset would grow the file, the response's `preset_actually_used`
    will reflect the fallback that was applied (or the original preset
    if a passthrough was needed). Use the returned `file_id` with
    `GET /api/download/{file_id}` to retrieve the processed file
    within 1 hour.

    Deliberately a sync `def`: FastAPI runs it in the threadpool, so a
    long pipeline run (hours for multi-GB scans) doesn't block the event
    loop — /health and batch polling stay responsive.
    """
    cleanup_old_files()

    # Resolve settings-driven defaults (mirrors start_batch) so the
    # documented default preset (`smallest`) actually applies here too.
    settings = get_config().settings
    if preset is None:
        preset = settings.default_preset
    if language is None:
        language = settings.default_language
    if jobs is None:
        jobs = settings.default_jobs

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
        # Save the upload in 16 MB chunks (same size as the GUI's
        # _chunk_copy) so a multi-GB scan never lands in RAM at once.
        # `file.file` is the underlying synchronous SpooledTemporaryFile.
        # A nonzero max_upload_bytes setting rejects oversized uploads
        # with the documented FILE_TOO_LARGE code; 0 means unlimited.
        max_bytes = settings.max_upload_bytes
        chunk_size = 16 * 1024 * 1024
        bytes_written = 0
        with open(input_path, "wb") as f:
            while chunk := file.file.read(chunk_size):
                bytes_written += len(chunk)
                if max_bytes and bytes_written > max_bytes:
                    raise APIException(
                        413,
                        FILE_TOO_LARGE,
                        f"Upload exceeds max_upload_bytes ({max_bytes} B)",
                        [
                            "Raise max_upload_bytes in settings (or set it "
                            "to 0 for unlimited)",
                            "Or process the file locally via the CLI, which "
                            "reads from disk without an upload",
                        ],
                    )
                f.write(chunk)

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

        # Persist to SQLite — survives uvicorn restart.
        _storage().insert_file(
            file_id=file_id,
            original_name=file.filename,
            output_path=result.output_path,
            workdir=workdir,
            mode=mode,
            preset=preset,
        )

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
            text_pages_sampled=result.text_pages_sampled,
            text_pages_with_text=result.text_pages_with_text,
            text_words=result.text_words,
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


@app.get(
    "/api/download/{file_id}",
    responses={
        200: {
            "description": "The processed PDF file",
            "content": {"application/pdf": {}},
        },
        **_NOT_FOUND_RESPONSES,
    },
    summary="Download a processed PDF by file_id",
)
async def download_file(file_id: str):
    """Download the processed PDF for a given file_id.

    Returns 404 once the file has been cleaned up (1-hour TTL after
    processing).
    """
    cleanup_old_files()

    row = _storage().get_file(file_id)
    if row is None:
        raise APIException(404, FILE_NOT_FOUND, "File not found or expired")

    output_path = Path(row["output_path"])
    if not output_path.exists():
        raise APIException(404, FILE_NOT_FOUND, "File has been deleted")

    return FileResponse(
        path=output_path,
        media_type="application/pdf",
        filename=row["original_name"],
    )


@app.post(
    "/api/batch",
    response_model=BatchAcceptedResponse,
    status_code=202,
    responses=_BATCH_START_ERROR_RESPONSES,
    summary="Queue a folder of PDFs for batch processing",
)
async def start_batch(req: BatchRequest, background_tasks: BackgroundTasks):
    """Queue a folder-batch job and return its job_id immediately.

    Folder must exist on the server's filesystem (no upload). The
    request returns 202 with a `job_id`; processing runs in the
    background. Poll `GET /api/batch/{job_id}/status` for state. The
    failure ladder per file is: initial → immediate retry →
    end-of-batch retry; one failing PDF will not abort the batch.
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
    started_at = datetime.now().isoformat(timespec="milliseconds")
    storage = _storage()
    storage.insert_batch_job(
        job_id=job_id,
        status="queued",
        started_at=started_at,
        progress_total=len(pdfs),
    )

    # Capture the storage reference so the background closure doesn't
    # re-resolve the module-level STORAGE (it could be swapped by tests
    # before the task runs, but this request already committed to one DB).
    job_storage = storage

    def _run() -> None:
        try:

            def cb(current: int, total: int, current_path: Path) -> None:
                # Per-file progress write. SQLite WAL means this doesn't
                # block /status reads; the writes are a couple hundred
                # bytes each and run at file-level granularity, not
                # per-page, so volume stays small.
                job_storage.update_batch_progress(
                    job_id,
                    progress_current=current,
                    progress_total=total,
                )

            report = run_batch(
                folder,
                output_dir,
                mode=req.mode,  # type: ignore[arg-type]
                preset=preset,
                lang=language,
                jobs=jobs,
                pdfa=req.pdfa,
                force_ocr=req.force_ocr,
                force=req.force,
                progress_callback=cb,
            )
            job_storage.finish_batch_job(
                job_id,
                status="done",
                finished_at=datetime.now().isoformat(timespec="milliseconds"),
                report_json=json.dumps(report.to_dict()),
            )
        except (
            Exception
        ) as e:  # noqa: BLE001 — surface orchestrator-level errors to the client
            job_storage.finish_batch_job(
                job_id,
                status="error",
                finished_at=datetime.now().isoformat(timespec="milliseconds"),
                error_msg=str(e),
            )

    background_tasks.add_task(_run)

    return BatchAcceptedResponse(status="queued", job_id=job_id, total_files=len(pdfs))


@app.get(
    "/api/batch/{job_id}/status",
    responses=_NOT_FOUND_RESPONSES,
    summary="Poll a batch job's state",
)
async def batch_status(job_id: str):
    """Return the current state of a batch job.

    Fields: `status` (queued | running | done | error), `started_at`,
    `finished_at`, `progress_current`, `progress_total`, `error_msg`,
    and `report` (the full BatchReport once status == done).
    Returns 404 if the job is unknown or has been cleaned up (1-hour TTL).
    """
    cleanup_old_jobs()
    row = _storage().get_batch_job(job_id)
    if row is None:
        raise APIException(404, BATCH_JOB_NOT_FOUND, "Batch job not found or expired")
    return row


def start_server(host: str = "127.0.0.1", port: int = 8502):
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
