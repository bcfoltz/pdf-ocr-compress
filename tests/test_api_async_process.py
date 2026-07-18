"""Tests for background single-file processing (accepted proposal P-003).

`POST /api/process` with `background=true` returns 202 + a job id that
doubles as the file id: poll `GET /api/batch/{job_id}/status`, download
via `GET /api/download/{job_id}`. Reuses the batch job store; the sync
path must stay byte-for-byte unchanged.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pdf_ocr_compress.api.server import app
from pdf_ocr_compress.core.pipeline import ProcessResult


@pytest.fixture
def client(isolated_api_storage) -> TestClient:
    return TestClient(app)


def _fake_result(out: Path) -> ProcessResult:
    out.write_bytes(b"%PDF-1.4 fake output\n")
    return ProcessResult(
        output_path=out,
        input_bytes=100,
        output_bytes=80,
        pct_change=-20.0,
        ocr_ran=False,
        ocr_skipped_reason="compress_only_mode",
        processing_seconds=0.01,
        preset_actually_used="smallest",
        pdfminer_text_extractable=True,
        text_pages_sampled=1,
        text_pages_with_text=1,
        text_words=5,
    )


def test_background_process_round_trip(client, sample_pdf):
    """202 -> poll status to done -> download by the same id."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=lambda i, o, **kw: _fake_result(Path(o)),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "compress", "background": "true"},
            )
    # TestClient runs BackgroundTasks synchronously after the response,
    # so by the time we poll, the job has already finished.
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    status = client.get(f"/api/batch/{job_id}/status")
    assert status.status_code == 200
    job = status.json()
    assert job["status"] == "done"
    assert job["progress_current"] == 1
    assert job["report"]["process_result"]["preset_actually_used"] == "smallest"

    dl = client.get(f"/api/download/{job_id}")
    assert dl.status_code == 200
    assert dl.content.startswith(b"%PDF-")


def test_background_process_error_lands_in_job_status(client, sample_pdf):
    """Pipeline failure -> job status error with the message; no file row."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=RuntimeError("kaboom"),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "compress", "background": "true"},
            )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    job = client.get(f"/api/batch/{job_id}/status").json()
    assert job["status"] == "error"
    assert job["error_msg"] == "kaboom"

    assert client.get(f"/api/download/{job_id}").status_code == 404


def test_background_validation_errors_stay_synchronous(client, sample_pdf):
    """Invalid input is rejected with a 4xx before anything is queued."""
    with open(sample_pdf, "rb") as f:
        resp = client.post(
            "/api/process",
            files={"file": ("a.pdf", f, "application/pdf")},
            data={"mode": "auto", "preset": "ultra", "background": "true"},
        )
    assert resp.status_code == 400


def test_sync_path_unchanged_when_background_omitted(client, sample_pdf):
    """Regression: the default path still returns 200 ProcessResponse."""
    with patch(
        "pdf_ocr_compress.api.server.run_pipeline",
        side_effect=lambda i, o, **kw: _fake_result(Path(o)),
    ):
        with open(sample_pdf, "rb") as f:
            resp = client.post(
                "/api/process",
                files={"file": ("a.pdf", f, "application/pdf")},
                data={"mode": "compress"},
            )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["preset_actually_used"] == "smallest"
    assert body["text_pages_sampled"] == 1
