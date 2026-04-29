"""Phase 4 item 2 — every 4xx/5xx route returns the APIError wire shape.

These tests use FastAPI's TestClient (httpx-backed) and never start a
real uvicorn process. They exercise validation paths plus a mocked
pipeline failure to confirm `APIException` and the exception handlers
in `api/errors.py` map correctly to JSON.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pdf_ocr_compress.api import errors as err
from pdf_ocr_compress.api.server import app
from pdf_ocr_compress.utils.errors import PDFFormatError, SystemToolError


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _assert_error_shape(body: dict, expected_code: str) -> None:
    """Every 4xx/5xx response must conform to the APIError schema."""
    assert set(body.keys()) >= {"error_code", "message", "suggestions"}
    assert body["error_code"] == expected_code
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["suggestions"], list)


# --- /api/process validation paths ------------------------------------------


def test_process_invalid_mode(client: TestClient, sample_pdf: Path) -> None:
    with open(sample_pdf, "rb") as f:
        resp = client.post(
            "/api/process",
            files={"file": ("a.pdf", f, "application/pdf")},
            data={"mode": "bogus", "preset": "smallest"},
        )
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INVALID_MODE)


def test_process_invalid_preset(client: TestClient, sample_pdf: Path) -> None:
    with open(sample_pdf, "rb") as f:
        resp = client.post(
            "/api/process",
            files={"file": ("a.pdf", f, "application/pdf")},
            data={"mode": "auto", "preset": "ultra"},
        )
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INVALID_PRESET)


def test_process_non_pdf_filename(client: TestClient, sample_pdf: Path) -> None:
    with open(sample_pdf, "rb") as f:
        resp = client.post(
            "/api/process",
            files={"file": ("notes.txt", f, "text/plain")},
            data={"mode": "auto", "preset": "smallest"},
        )
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INPUT_NOT_PDF)


# --- 404s -------------------------------------------------------------------


def test_download_unknown_file_id(client: TestClient) -> None:
    resp = client.get("/api/download/does-not-exist")
    assert resp.status_code == 404
    _assert_error_shape(resp.json(), err.FILE_NOT_FOUND)


def test_batch_status_unknown_job_id(client: TestClient) -> None:
    resp = client.get("/api/batch/does-not-exist/status")
    assert resp.status_code == 404
    _assert_error_shape(resp.json(), err.BATCH_JOB_NOT_FOUND)


# --- /api/batch validation paths --------------------------------------------


def test_batch_invalid_folder(client: TestClient) -> None:
    resp = client.post(
        "/api/batch", json={"folder": "/no/such/folder/anywhere", "mode": "auto"}
    )
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INVALID_FOLDER)


def test_batch_invalid_mode(client: TestClient, tmp_path: Path) -> None:
    resp = client.post("/api/batch", json={"folder": str(tmp_path), "mode": "nope"})
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INVALID_MODE)


def test_batch_invalid_preset(client: TestClient, tmp_path: Path) -> None:
    resp = client.post(
        "/api/batch",
        json={"folder": str(tmp_path), "mode": "auto", "preset": "ultra"},
    )
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INVALID_PRESET)


# --- 422 validation wrap-around ---------------------------------------------


def test_batch_missing_required_field(client: TestClient) -> None:
    """Pydantic validation errors are wrapped into the APIError shape."""
    resp = client.post("/api/batch", json={})  # missing `folder`
    assert resp.status_code == 422
    _assert_error_shape(resp.json(), err.VALIDATION_ERROR)
    # Per-field detail preserved as suggestions so debug info isn't lost.
    assert any("folder" in s for s in resp.json()["suggestions"])


# --- 500 mapping ------------------------------------------------------------


def test_process_generic_failure_returns_processing_failed(
    client: TestClient, sample_pdf: Path
) -> None:
    """Non-domain exceptions from run_pipeline -> 500 PROCESSING_FAILED."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=RuntimeError("boom"),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "auto", "preset": "smallest"},
            )
    assert resp.status_code == 500
    _assert_error_shape(resp.json(), err.PROCESSING_FAILED)


def test_process_pdf_format_error_maps_to_input_not_pdf(
    client: TestClient, sample_pdf: Path
) -> None:
    """PDFFormatError raised from inside the pipeline -> 400 INPUT_NOT_PDF."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=PDFFormatError(Path("a.pdf"), "not a real PDF"),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "auto", "preset": "smallest"},
            )
    assert resp.status_code == 400
    _assert_error_shape(resp.json(), err.INPUT_NOT_PDF)


def test_process_tesseract_missing_maps_to_ocr_tool_missing(
    client: TestClient, sample_pdf: Path
) -> None:
    """SystemToolError(tool='tesseract') -> 503 OCR_TOOL_MISSING."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=SystemToolError("tesseract", "tesseract not found on PATH"),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "auto", "preset": "smallest"},
            )
    assert resp.status_code == 503
    _assert_error_shape(resp.json(), err.OCR_TOOL_MISSING)


def test_process_ghostscript_missing_maps_to_gs_tool_missing(
    client: TestClient, sample_pdf: Path
) -> None:
    """SystemToolError(tool='ghostscript') -> 503 GHOSTSCRIPT_TOOL_MISSING."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=SystemToolError("ghostscript", "gs not found on PATH"),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "auto", "preset": "smallest"},
            )
    assert resp.status_code == 503
    _assert_error_shape(resp.json(), err.GHOSTSCRIPT_TOOL_MISSING)
