"""FastAPI server for PDF OCR + Compression REST API."""

import shutil
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..core.compress import compress as run_compress
from ..core.detect import needs_ocr
from ..core.ocr import run_ocr

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
    """Response model for /api/process endpoint."""

    status: str
    message: str
    file_id: str
    mode: str
    preset: str
    original_size: int
    output_size: int
    reduction_percent: float
    processing_time: float


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

    start_time = time.time()

    try:
        # Save uploaded file
        with open(input_path, "wb") as f:
            content = await file.read()
            f.write(content)

        original_size = input_path.stat().st_size

        # Detect if OCR is needed
        need_ocr = False
        if mode == "auto":
            try:
                need_ocr = needs_ocr(input_path)
            except Exception:
                need_ocr = True

        # Process based on mode
        if mode == "ocr":
            output_path = run_ocr(
                input_pdf=input_path,
                output_pdf=output_base,
                lang=language,
                preset=preset,
                pdfa=pdfa,
                jobs=jobs,
                force_ocr=force_ocr,
            )

        elif mode == "compress":
            output_path = run_compress(input_path, output_base, preset=preset)

        else:  # auto
            if force_ocr or need_ocr:
                # OCR first, then compress
                ocr_output = run_ocr(
                    input_pdf=input_path,
                    output_pdf=workdir / "ocr.pdf",
                    lang=language,
                    preset=preset,
                    pdfa=pdfa,
                    jobs=jobs,
                    force_ocr=True,
                )
                output_path = run_compress(ocr_output, output_base, preset=preset)
            else:
                # Just compress
                output_path = run_compress(input_path, output_base, preset=preset)

        output_size = output_path.stat().st_size
        processing_time = time.time() - start_time
        reduction_percent = 100.0 * (1 - output_size / max(original_size, 1))

        # Store file info
        file_storage[file_id] = {
            "path": output_path,
            "workdir": workdir,
            "timestamp": datetime.now(),
            "original_name": file.filename,
            "mode": mode,
            "preset": preset,
        }

        return ProcessResponse(
            status="success",
            message="Processing complete",
            file_id=file_id,
            mode=mode,
            preset=preset,
            original_size=original_size,
            output_size=output_size,
            reduction_percent=round(reduction_percent, 2),
            processing_time=round(processing_time, 2),
        )

    except Exception as e:
        # Cleanup on error
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


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
