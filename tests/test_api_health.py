"""Phase 4 item 5 — /health surfaces real environment state.

The endpoint must report version + binary paths + tesseract languages +
queue depth so a monitoring system can distinguish "API up" from "API
up but tools missing". Tests mock the binary detection helpers so they
work regardless of whether the test machine has Tesseract or
Ghostscript installed.
"""

from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from pdf_ocr_compress.api.server import app


@pytest.fixture
def client(isolated_api_storage) -> TestClient:
    return TestClient(app)


def test_health_returns_required_fields(client: TestClient) -> None:
    """Schema check: every documented field is present and the right type."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    required = {
        "status",
        "service",
        "version",
        "ghostscript_binary",
        "tesseract_binary",
        "tesseract_languages",
        "queue_depth",
    }
    assert required.issubset(body.keys())
    assert isinstance(body["tesseract_languages"], list)
    assert isinstance(body["queue_depth"], int)
    assert body["queue_depth"] >= 0


def test_health_reports_binaries_when_present(client: TestClient) -> None:
    fake_gs = "C:/Program Files/gs/gs10.00.0/bin/gswin64c.exe"
    fake_tess = "/usr/bin/tesseract"

    def fake_which(name: str) -> str | None:
        if name in ("gswin64c", "gswin32c", "gs"):
            return fake_gs
        if name == "tesseract":
            return fake_tess
        return None

    fake_run = CompletedProcess(
        args=["tesseract", "--list-langs"],
        returncode=0,
        stdout="List of available languages (3):\neng\nspa\nfra\n",
        stderr="",
    )

    with (
        patch("pdf_ocr_compress.api.server.shutil.which", side_effect=fake_which),
        patch("pdf_ocr_compress.api.server.subprocess.run", return_value=fake_run),
    ):
        body = client.get("/health").json()

    assert body["ghostscript_binary"] == fake_gs
    assert body["tesseract_binary"] == fake_tess
    assert body["tesseract_languages"] == ["eng", "spa", "fra"]


def test_health_reports_null_when_binaries_missing(client: TestClient) -> None:
    """Missing binaries -> null paths, empty language list (no exceptions)."""
    with patch("pdf_ocr_compress.api.server.shutil.which", return_value=None):
        body = client.get("/health").json()

    assert body["ghostscript_binary"] is None
    assert body["tesseract_binary"] is None
    assert body["tesseract_languages"] == []


def test_health_tesseract_listing_handles_stderr_output(
    client: TestClient,
) -> None:
    """Some Tesseract builds emit --list-langs to stderr instead of stdout."""
    fake_run = CompletedProcess(
        args=["tesseract", "--list-langs"],
        returncode=0,
        stdout="",
        stderr="List of available languages (1):\neng\n",
    )
    with (
        patch(
            "pdf_ocr_compress.api.server.shutil.which",
            return_value="/usr/bin/tesseract",
        ),
        patch("pdf_ocr_compress.api.server.subprocess.run", return_value=fake_run),
    ):
        body = client.get("/health").json()

    assert body["tesseract_languages"] == ["eng"]


def test_health_queue_depth_reflects_active_jobs(
    client: TestClient, isolated_api_storage, tmp_path: Path
) -> None:
    """A queued or running batch_jobs row counts; finished jobs do not."""
    from datetime import datetime

    storage = isolated_api_storage
    now = datetime.now().isoformat(timespec="milliseconds")
    storage.insert_batch_job(
        job_id="active", status="queued", started_at=now, progress_total=1
    )
    storage.insert_batch_job(
        job_id="finished", status="queued", started_at=now, progress_total=1
    )
    storage.finish_batch_job(
        "finished", status="done", finished_at=now, report_json="{}"
    )

    body = client.get("/health").json()
    assert body["queue_depth"] == 1
