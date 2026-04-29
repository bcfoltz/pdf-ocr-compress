"""FastAPI server for PDF OCR + Compression REST API."""

import shutil
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core.pipeline import run_pipeline

app = FastAPI(
    title="PDF OCR + Compression API",
    description="REST API for processing scanned PDFs with OCR and compression",
    version="1.0.0",
)


# Temporary storage for processed files
TEMP_DIR = Path(tempfile.gettempdir()) / "pdf_ocr_api"
TEMP_DIR.mkdir(exist_ok=True)

# File storage with cleanup (keep files for 1 hour)
file_storage = {}


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
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    if preset not in ["balanced", "archival", "smallest"]:
        raise HTTPException(status_code=400, detail=f"Invalid preset: {preset}")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

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

    except Exception as e:
        # Cleanup on error
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

        raise HTTPException(
            status_code=500, detail=f"Processing failed: {str(e)}"
        ) from e


@app.get("/api/download/{file_id}")
async def download_file(file_id: str):
    """
    Download a processed PDF file.

    Files are kept for 1 hour after processing.
    """
    cleanup_old_files()

    if file_id not in file_storage:
        raise HTTPException(status_code=404, detail="File not found or expired")

    file_info = file_storage[file_id]

    if not file_info["path"].exists():
        raise HTTPException(status_code=404, detail="File has been deleted")

    # Return original filename as-is
    download_name = file_info["original_name"]

    return FileResponse(
        path=file_info["path"], media_type="application/pdf", filename=download_name
    )


def start_server(host: str = "0.0.0.0", port: int = 8502):
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
