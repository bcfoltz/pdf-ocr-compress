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
def client(isolated_api_storage) -> TestClient:
    """TestClient with an isolated SQLite DB (no shared TEMP_DIR pollution)."""
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


# --- FILE_TOO_LARGE enforcement ---------------------------------------------


def test_process_upload_over_cap_returns_file_too_large(
    client: TestClient, sample_pdf: Path
) -> None:
    """A nonzero max_upload_bytes rejects bigger uploads with 413."""
    from pdf_ocr_compress.config import get_config

    settings = get_config().settings
    with patch.object(settings, "max_upload_bytes", 10):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "compress", "preset": "smallest"},
            )
    assert resp.status_code == 413
    _assert_error_shape(resp.json(), err.FILE_TOO_LARGE)


def test_process_upload_under_cap_processes_normally(
    client: TestClient, sample_pdf: Path, tmp_path: Path
) -> None:
    """Uploads under a nonzero cap flow through to the pipeline untouched."""
    from pdf_ocr_compress.config import get_config
    from pdf_ocr_compress.core.pipeline import ProcessResult

    out = tmp_path / "out.pdf"
    out.write_bytes(b"%PDF-1.4\n%out\n")
    fake_result = ProcessResult(
        output_path=out,
        input_bytes=100,
        output_bytes=80,
        pct_change=-20.0,
        ocr_ran=False,
        ocr_skipped_reason="compress_only_mode",
        processing_seconds=0.01,
        preset_actually_used="smallest",
        pdfminer_text_extractable=True,
    )
    settings = get_config().settings
    with patch.object(settings, "max_upload_bytes", 10_000_000):
        with patch(
            "pdf_ocr_compress.api.server.run_pipeline", return_value=fake_result
        ):
            with open(sample_pdf, "rb") as f:
                resp = client.post(
                    "/api/process",
                    files={"file": ("a.pdf", f, "application/pdf")},
                    data={"mode": "compress", "preset": "smallest"},
                )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# --- Batch end-to-end through SQLite (Phase 4 task 3) -----------------------


def test_batch_job_round_trip_persists_to_sqlite(
    client: TestClient, isolated_api_storage, tmp_path: Path
) -> None:
    """POST /api/batch persists the job; GET /status reads it from SQLite.

    Uses a mocked run_batch so we don't need Tesseract/Ghostscript on the
    test machine. The point of this test is the wiring: insert_batch_job
    on POST, finish_batch_job on completion, get_batch_job on GET.
    """
    from pdf_ocr_compress.core.batch import BatchReport

    folder = tmp_path / "in"
    folder.mkdir()
    # POST /api/batch globs *.pdf even though run_batch is mocked, so put
    # one file there to exercise the total_files counter.
    (folder / "a.pdf").write_bytes(b"%PDF-1.4\n%mock\n")

    fake_report = BatchReport(
        input_dir=folder,
        output_dir=folder / "processed",
        total_files=1,
        succeeded=1,
        failed=0,
        started_at="2026-04-29T00:00:00.000",
        finished_at="2026-04-29T00:00:01.000",
        total_seconds=1.0,
        total_input_bytes=10,
        total_output_bytes=10,
        results=[],
    )
    with patch("pdf_ocr_compress.api.server.run_batch", return_value=fake_report):
        resp = client.post(
            "/api/batch",
            json={"folder": str(folder), "mode": "auto", "preset": "smallest"},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        assert resp.json()["total_files"] == 1

    # FastAPI runs BackgroundTasks after the response is sent; with
    # TestClient that happens synchronously before the .post() returns.
    # By here, the job should already be in the 'done' state.
    status_resp = client.get(f"/api/batch/{job_id}/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "done"
    assert body["report"] is not None
    assert body["report"]["succeeded"] == 1


def test_batch_job_error_persists_to_sqlite(
    client: TestClient, isolated_api_storage, tmp_path: Path
) -> None:
    """run_batch raising ends the job in status=error with the message."""
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"%PDF-1.4\n%mock\n")

    with patch(
        "pdf_ocr_compress.api.server.run_batch",
        side_effect=RuntimeError("kapow"),
    ):
        resp = client.post(
            "/api/batch",
            json={"folder": str(folder), "mode": "auto", "preset": "smallest"},
        )
        job_id = resp.json()["job_id"]

    status_resp = client.get(f"/api/batch/{job_id}/status")
    body = status_resp.json()
    assert body["status"] == "error"
    assert body["error_msg"] == "kapow"
    assert body["report"] is None
