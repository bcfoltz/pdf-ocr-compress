"""Tests for the Phase 3 folder-batch orchestrator (core.batch)."""

import json
import shutil
from pathlib import Path

import pytest

from pdf_ocr_compress.core.batch import (
    BatchJobState,
    BatchReport,
    BatchResult,
)
from pdf_ocr_compress.core.pipeline import ProcessResult

requires_ghostscript = pytest.mark.skipif(
    not (shutil.which("gswin64c") or shutil.which("gswin32c") or shutil.which("gs")),
    reason="Ghostscript not installed",
)
requires_tesseract = pytest.mark.skipif(
    not shutil.which("tesseract"),
    reason="Tesseract not installed",
)


def _fake_process_result(tmp_path: Path) -> ProcessResult:
    """A synthetic ProcessResult that doesn't require running the pipeline."""
    out = tmp_path / "fake_out.pdf"
    out.write_bytes(b"%PDF-1.4 fake\n")
    return ProcessResult(
        output_path=out,
        input_bytes=1000,
        output_bytes=500,
        pct_change=-50.0,
        ocr_ran=False,
        ocr_skipped_reason="input_has_text_layer",
        processing_seconds=1.5,
        preset_actually_used="smallest",
        pdfminer_text_extractable=True,
    )


def test_batch_result_to_dict_ok(tmp_path):
    pr = _fake_process_result(tmp_path)
    br = BatchResult(
        input_path=tmp_path / "input.pdf",
        output_path=pr.output_path,
        status="ok",
        attempts=1,
        error_msg=None,
        process_result=pr,
    )

    d = br.to_dict()

    assert d["input_path"] == str(tmp_path / "input.pdf")
    assert d["output_path"] == str(pr.output_path)
    assert d["status"] == "ok"
    assert d["attempts"] == 1
    assert d["error_msg"] is None
    assert d["process_result"]["preset_actually_used"] == "smallest"


def test_batch_result_to_dict_failed(tmp_path):
    br = BatchResult(
        input_path=tmp_path / "bad.pdf",
        output_path=None,
        status="failed",
        attempts=3,
        error_msg="PDFProcessingError: corrupt",
        process_result=None,
    )

    d = br.to_dict()

    assert d["output_path"] is None
    assert d["status"] == "failed"
    assert d["attempts"] == 3
    assert d["error_msg"] == "PDFProcessingError: corrupt"
    assert d["process_result"] is None


def test_batch_report_write_json_round_trip(tmp_path):
    pr = _fake_process_result(tmp_path)
    report = BatchReport(
        input_dir=tmp_path,
        output_dir=tmp_path / "processed",
        total_files=1,
        succeeded=1,
        failed=0,
        started_at="2026-04-29T10:00:00.000",
        finished_at="2026-04-29T10:00:01.500",
        total_seconds=1.5,
        total_input_bytes=1000,
        total_output_bytes=500,
        results=[
            BatchResult(
                input_path=tmp_path / "input.pdf",
                output_path=pr.output_path,
                status="ok",
                attempts=1,
                error_msg=None,
                process_result=pr,
            )
        ],
    )

    out = tmp_path / "batch_report.json"
    report.write_json(out)

    assert out.exists()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["total_files"] == 1
    assert loaded["succeeded"] == 1
    assert loaded["results"][0]["status"] == "ok"
    assert loaded["results"][0]["process_result"]["pdfminer_text_extractable"] is True


def test_batch_report_one_line_summary(tmp_path):
    report = BatchReport(
        input_dir=tmp_path,
        output_dir=tmp_path / "processed",
        total_files=49,
        succeeded=47,
        failed=2,
        started_at="2026-04-29T10:00:00.000",
        finished_at="2026-04-29T11:12:00.000",
        total_seconds=4320.0,
        total_input_bytes=4 * 1024 * 1024 * 1024,  # 4 GB
        total_output_bytes=280 * 1024 * 1024,  # 280 MB
        results=[],
    )

    s = report.one_line_summary()

    assert "47 ok" in s
    assert "2 failed" in s
    assert "GB" in s
    assert "MB" in s
    # pct change -93.x%
    assert "-93" in s
    # duration formatted with hours
    assert "h" in s


def test_batch_job_state_to_dict_done(tmp_path):
    pr = _fake_process_result(tmp_path)
    report = BatchReport(
        input_dir=tmp_path,
        output_dir=tmp_path / "processed",
        total_files=1,
        succeeded=1,
        failed=0,
        started_at="2026-04-29T10:00:00.000",
        finished_at="2026-04-29T10:00:01.500",
        total_seconds=1.5,
        total_input_bytes=1000,
        total_output_bytes=500,
        results=[
            BatchResult(
                input_path=tmp_path / "input.pdf",
                output_path=pr.output_path,
                status="ok",
                attempts=1,
                error_msg=None,
                process_result=pr,
            )
        ],
    )
    state = BatchJobState(
        job_id="abc-123",
        status="done",
        started_at="2026-04-29T10:00:00.000",
        finished_at="2026-04-29T10:00:01.500",
        progress_current=1,
        progress_total=1,
        report=report,
        error_msg=None,
    )

    d = state.to_dict()

    assert d["job_id"] == "abc-123"
    assert d["status"] == "done"
    assert d["progress_total"] == 1
    assert d["report"]["succeeded"] == 1


def test_batch_job_state_to_dict_running(tmp_path):
    state = BatchJobState(
        job_id="abc-123",
        status="running",
        started_at="2026-04-29T10:00:00.000",
        finished_at=None,
        progress_current=14,
        progress_total=49,
        report=None,
        error_msg=None,
    )

    d = state.to_dict()

    assert d["status"] == "running"
    assert d["finished_at"] is None
    assert d["progress_current"] == 14
    assert d["report"] is None
