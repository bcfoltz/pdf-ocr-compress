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


def _fake_pipeline_factory(tmp_path: Path):
    """Build a stand-in for run_pipeline that writes a tiny output and returns
    a synthetic ProcessResult. Captures every call for assertions.
    """
    calls: list[Path] = []

    def fake(input_pdf, output_pdf, **kwargs):
        calls.append(Path(input_pdf))
        out = output_pdf  # simulate compress/ocr writing exactly to base path
        Path(out).write_bytes(b"%PDF-1.4 fake\n")
        return ProcessResult(
            output_path=Path(out),
            input_bytes=Path(input_pdf).stat().st_size,
            output_bytes=Path(out).stat().st_size,
            pct_change=-50.0,
            ocr_ran=False,
            ocr_skipped_reason="input_has_text_layer",
            processing_seconds=0.01,
            preset_actually_used="smallest",
            pdfminer_text_extractable=True,
        )

    return fake, calls


def _make_pdf(path: Path, payload: bytes = b"%PDF-1.4\n") -> Path:
    path.write_bytes(payload)
    return path


def test_run_batch_empty_folder_writes_zero_file_report(tmp_path):
    from pdf_ocr_compress.core.batch import run_batch

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()

    report = run_batch(in_dir, out_dir)

    assert report.total_files == 0
    assert report.succeeded == 0
    assert report.failed == 0
    assert report.results == []
    assert (out_dir / "batch_report.json").exists()


def test_run_batch_creates_output_dir(tmp_path):
    from pdf_ocr_compress.core.batch import run_batch

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out" / "nested"
    in_dir.mkdir()

    run_batch(in_dir, out_dir)

    assert out_dir.exists()
    assert out_dir.is_dir()


def test_run_batch_happy_path_three_files(tmp_path, monkeypatch):
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    a = _make_pdf(in_dir / "a.pdf")
    b = _make_pdf(in_dir / "b.pdf")
    c = _make_pdf(in_dir / "c.pdf")

    fake, calls = _fake_pipeline_factory(tmp_path)
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    report = batch_mod.run_batch(in_dir, out_dir)

    assert report.total_files == 3
    assert report.succeeded == 3
    assert report.failed == 0
    assert {r.input_path for r in report.results} == {a, b, c}
    assert all(r.status == "ok" for r in report.results)
    assert all(r.attempts == 1 for r in report.results)
    assert len(calls) == 3


def test_run_batch_progress_callback_invoked_per_file(tmp_path, monkeypatch):
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    _make_pdf(in_dir / "a.pdf")
    _make_pdf(in_dir / "b.pdf")

    fake, _ = _fake_pipeline_factory(tmp_path)
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    seen: list[tuple[int, int, str]] = []

    def cb(current: int, total: int, current_path: Path) -> None:
        seen.append((current, total, current_path.name))

    batch_mod.run_batch(in_dir, out_dir, progress_callback=cb)

    assert seen == [(1, 2, "a.pdf"), (2, 2, "b.pdf")]


def test_run_batch_results_sorted_by_input_path(tmp_path, monkeypatch):
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    # Create in non-alphabetical order to make sure sort is path-based.
    _make_pdf(in_dir / "c.pdf")
    _make_pdf(in_dir / "a.pdf")
    _make_pdf(in_dir / "b.pdf")

    fake, _ = _fake_pipeline_factory(tmp_path)
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    report = batch_mod.run_batch(in_dir, out_dir)

    assert [r.input_path.name for r in report.results] == ["a.pdf", "b.pdf", "c.pdf"]


def _flaky_pipeline_factory(tmp_path: Path, fails_per_file: dict[str, int]):
    """Build a fake run_pipeline that fails the first N times for each
    named file, then succeeds. fails_per_file maps filename -> N.
    """
    counters: dict[str, int] = {k: 0 for k in fails_per_file}

    def fake(input_pdf, output_pdf, **kwargs):
        name = Path(input_pdf).name
        if name in fails_per_file:
            counters[name] += 1
            if counters[name] <= fails_per_file[name]:
                raise RuntimeError(f"synthetic failure {counters[name]} on {name}")
        out = output_pdf
        Path(out).write_bytes(b"%PDF-1.4 fake\n")
        return ProcessResult(
            output_path=Path(out),
            input_bytes=Path(input_pdf).stat().st_size,
            output_bytes=Path(out).stat().st_size,
            pct_change=-50.0,
            ocr_ran=False,
            ocr_skipped_reason="input_has_text_layer",
            processing_seconds=0.01,
            preset_actually_used="smallest",
            pdfminer_text_extractable=True,
        )

    return fake, counters


def test_run_batch_retries_once_on_first_failure(tmp_path, monkeypatch):
    """A file that fails once but succeeds on immediate retry: attempts=2, ok."""
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    _make_pdf(in_dir / "flaky.pdf")

    fake, counters = _flaky_pipeline_factory(tmp_path, {"flaky.pdf": 1})
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    report = batch_mod.run_batch(in_dir, out_dir)

    assert report.succeeded == 1
    assert report.failed == 0
    assert report.results[0].attempts == 2
    assert report.results[0].status == "ok"
    assert counters["flaky.pdf"] == 2  # initial + immediate retry


def test_run_batch_end_of_batch_retry_succeeds(tmp_path, monkeypatch):
    """A file that fails initial + immediate-retry but succeeds on end-of-batch retry: attempts=3, ok."""
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    _make_pdf(in_dir / "stubborn.pdf")

    fake, counters = _flaky_pipeline_factory(tmp_path, {"stubborn.pdf": 2})
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    report = batch_mod.run_batch(in_dir, out_dir)

    assert report.succeeded == 1
    assert report.failed == 0
    assert report.results[0].attempts == 3
    assert report.results[0].status == "ok"
    assert counters["stubborn.pdf"] == 3


def test_run_batch_final_failure_attempts_three(tmp_path, monkeypatch):
    """A file that fails all three attempts: status=failed, attempts=3, error_msg populated."""
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    _make_pdf(in_dir / "doomed.pdf")

    fake, counters = _flaky_pipeline_factory(tmp_path, {"doomed.pdf": 999})
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    report = batch_mod.run_batch(in_dir, out_dir)

    assert report.succeeded == 0
    assert report.failed == 1
    r = report.results[0]
    assert r.status == "failed"
    assert r.attempts == 3
    assert r.error_msg is not None
    assert "synthetic failure" in r.error_msg
    assert r.output_path is None
    assert r.process_result is None
    assert counters["doomed.pdf"] == 3


def test_run_batch_one_bad_apple_does_not_kill_batch(tmp_path, monkeypatch):
    """Mixed run: 2 ok, 1 doomed. Phase 3 success criterion."""
    from pdf_ocr_compress.core import batch as batch_mod

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    _make_pdf(in_dir / "a.pdf")
    _make_pdf(in_dir / "b.pdf")
    _make_pdf(in_dir / "doomed.pdf")

    fake, _ = _flaky_pipeline_factory(tmp_path, {"doomed.pdf": 999})
    monkeypatch.setattr(batch_mod, "run_pipeline", fake)

    report = batch_mod.run_batch(in_dir, out_dir)

    assert report.total_files == 3
    assert report.succeeded == 2
    assert report.failed == 1
    by_name = {r.input_path.name: r for r in report.results}
    assert by_name["a.pdf"].status == "ok"
    assert by_name["b.pdf"].status == "ok"
    assert by_name["doomed.pdf"].status == "failed"


@requires_ghostscript
def test_run_batch_real_binaries_all_succeed(text_pdf, tmp_path):
    """Three valid PDFs through real Ghostscript: all `ok`, attempts=1."""
    from pdf_ocr_compress.core.batch import run_batch

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    # Copy the same text_pdf three times under different names.
    shutil.copy(text_pdf, in_dir / "alpha.pdf")
    shutil.copy(text_pdf, in_dir / "bravo.pdf")
    shutil.copy(text_pdf, in_dir / "charlie.pdf")

    report = run_batch(in_dir, out_dir, mode="compress", preset="smallest")

    assert report.total_files == 3
    assert report.succeeded == 3
    assert report.failed == 0
    assert all(r.attempts == 1 for r in report.results)
    assert all(r.process_result is not None for r in report.results)
    # Every output exists on disk
    for r in report.results:
        assert r.output_path is not None
        assert r.output_path.exists()
    assert (out_dir / "batch_report.json").exists()


@requires_ghostscript
def test_run_batch_real_binaries_mixed_outcomes(text_pdf, corrupt_pdf, tmp_path):
    """Two valid PDFs + one corrupt: 2 ok, 1 failed with attempts=3."""
    from pdf_ocr_compress.core.batch import run_batch

    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    shutil.copy(text_pdf, in_dir / "alpha.pdf")
    shutil.copy(text_pdf, in_dir / "bravo.pdf")
    shutil.copy(corrupt_pdf, in_dir / "doomed.pdf")

    report = run_batch(in_dir, out_dir, mode="compress", preset="smallest")

    assert report.total_files == 3
    assert report.succeeded == 2
    assert report.failed == 1
    by_name = {r.input_path.name: r for r in report.results}
    assert by_name["alpha.pdf"].status == "ok"
    assert by_name["bravo.pdf"].status == "ok"
    failed = by_name["doomed.pdf"]
    assert failed.status == "failed"
    assert failed.attempts == 3
    assert failed.error_msg is not None
    assert failed.output_path is None
