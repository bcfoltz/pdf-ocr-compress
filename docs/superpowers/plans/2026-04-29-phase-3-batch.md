# Phase 3 Batch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add folder-batch mode to CLI / GUI / API backed by a single `core/batch.py` module, with retry-once failure handling and a `batch_report.json` per run. The pipeline itself is unchanged.

**Architecture:** New `core/batch.py` defines `BatchResult`, `BatchReport`, `BatchJobState`, and a sequential `run_batch()` that loops `core.pipeline.run_pipeline()` over `*.pdf` files in a folder. Surfaces (CLI, GUI, API) translate inputs/outputs but own no logic. API endpoint is async via `BackgroundTasks` with an in-memory `batch_jobs` dict (Phase 4 swaps for SQLite).

**Tech Stack:** Python 3.10+, pikepdf, OCRmyPDF, Ghostscript, FastAPI, Streamlit, Typer, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-04-29-phase-3-batch-design.md`. The spec is the source of truth; this plan is the executable form.

---

## File map

- **Create:** `src/pdf_ocr_compress/core/batch.py` — dataclasses + `run_batch()` orchestrator.
- **Create:** `tests/test_batch.py` — unit and integration tests for batch.
- **Modify:** `src/pdf_ocr_compress/core/__init__.py` — export `run_batch`, `BatchResult`, `BatchReport`.
- **Modify:** `src/pdf_ocr_compress/cli.py` — add `batch` command.
- **Modify:** `src/pdf_ocr_compress/api/server.py` — add `POST /api/batch` and `GET /api/batch/{job_id}/status` plus job state dict.
- **Modify:** `src/pdf_ocr_compress/gui/basic.py` — add multi-file batch section.
- **Modify:** `tests/conftest.py` — add `corrupt_pdf` fixture.
- **Modify:** `CLAUDE.md` — flip "Where I left off" to Phase 3 closed; update "Known issues."
- **Modify:** `ROADMAP.md` — check Phase 3 in the Status section.

---

## Task 1: Dataclasses + JSON serialization (TDD)

Build the data shapes first. Pure-logic, no IO, perfect TDD target.

**Files:**

- Create: `src/pdf_ocr_compress/core/batch.py`
- Create: `tests/test_batch.py`

- [ ] **Step 1: Write the failing tests for dataclass serialization**

Create `tests/test_batch.py` with the following content:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail with import errors**

Run: `uv run pytest tests/test_batch.py -v`
Expected: `ImportError` / collection failure on `from pdf_ocr_compress.core.batch import ...`.

- [ ] **Step 3: Create `src/pdf_ocr_compress/core/batch.py` with the dataclasses**

```python
"""Folder-batch orchestrator. Phase 3 — see docs/superpowers/specs/.

Loops core.pipeline.run_pipeline() over *.pdf files in a folder, applies a
retry-once / second-pass-at-end-of-batch failure ladder, and emits a
BatchReport (also written to <output_dir>/batch_report.json). The pipeline
itself is unchanged: every Phase 0/1/2 invariant (size guard, oversize
fallback, OCR routing, structured ProcessResult) keeps applying per-file.
"""

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from ..utils.file_utils import human_readable_size
from .pipeline import ProcessResult, Mode, run_pipeline

BatchStatus = Literal["queued", "running", "done", "error"]
FileStatus = Literal["ok", "failed"]

ProgressCallback = Callable[[int, int, Path], None]


@dataclass
class BatchResult:
    """Outcome for a single file in a batch."""

    input_path: Path
    output_path: Path | None
    status: FileStatus
    attempts: int  # total run_pipeline calls for this file (1, 2, or 3)
    error_msg: str | None
    process_result: ProcessResult | None

    def to_dict(self) -> dict:
        return {
            "input_path": str(self.input_path),
            "output_path": str(self.output_path) if self.output_path else None,
            "status": self.status,
            "attempts": self.attempts,
            "error_msg": self.error_msg,
            "process_result": (
                self.process_result.to_dict() if self.process_result else None
            ),
        }


@dataclass
class BatchReport:
    """Whole-batch summary + per-file results."""

    input_dir: Path
    output_dir: Path
    total_files: int
    succeeded: int
    failed: int
    started_at: str  # ISO-8601, millisecond precision
    finished_at: str
    total_seconds: float
    total_input_bytes: int
    total_output_bytes: int  # successful files only
    results: list[BatchResult]

    def to_dict(self) -> dict:
        return {
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "total_files": self.total_files,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_seconds": self.total_seconds,
            "total_input_bytes": self.total_input_bytes,
            "total_output_bytes": self.total_output_bytes,
            "results": [r.to_dict() for r in self.results],
        }

    def write_json(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def one_line_summary(self) -> str:
        in_size = human_readable_size(self.total_input_bytes)
        out_size = human_readable_size(self.total_output_bytes)
        if self.total_input_bytes > 0:
            pct = (
                100.0
                * (self.total_output_bytes - self.total_input_bytes)
                / self.total_input_bytes
            )
            sign = "-" if pct < 0 else "+"
            delta = f"{sign}{abs(pct):.1f}%"
        else:
            delta = "0.0%"

        secs = int(self.total_seconds)
        h, secs = divmod(secs, 3600)
        m, s = divmod(secs, 60)
        if h:
            duration = f"{h}h {m}m"
        elif m:
            duration = f"{m}m {s}s"
        else:
            duration = f"{s}s"

        return (
            f"{self.succeeded} ok, {self.failed} failed | "
            f"{in_size} -> {out_size} ({delta}) | {duration}"
        )


@dataclass
class BatchJobState:
    """API job record. Phase 3 lives in an in-memory dict; Phase 4 = SQLite."""

    job_id: str
    status: BatchStatus
    started_at: str
    finished_at: str | None
    progress_current: int
    progress_total: int
    report: BatchReport | None
    error_msg: str | None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "report": self.report.to_dict() if self.report else None,
            "error_msg": self.error_msg,
        }


def _now_iso() -> str:
    """ISO-8601 timestamp, millisecond precision, JSON-friendly."""
    return datetime.now().isoformat(timespec="milliseconds")


def _list_pdfs(folder: Path) -> list[Path]:
    """Return *.pdf files in folder, sorted by path. Non-recursive."""
    return sorted(p for p in folder.glob("*.pdf") if p.is_file())


def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    mode: Mode = "auto",
    preset: str | None = None,
    lang: str | None = None,
    jobs: int | None = None,
    pdfa: bool = False,
    force_ocr: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> BatchReport:
    """Process every *.pdf in input_dir and return a BatchReport.

    Implementation in subsequent tasks. This stub satisfies imports.
    """
    raise NotImplementedError
```

- [ ] **Step 4: Run tests to verify they pass for the dataclass cases**

Run: `uv run pytest tests/test_batch.py -v`
Expected: `test_batch_result_to_dict_ok`, `test_batch_result_to_dict_failed`, `test_batch_report_write_json_round_trip`, `test_batch_report_one_line_summary`, `test_batch_job_state_to_dict_done`, `test_batch_job_state_to_dict_running` all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pdf_ocr_compress/core/batch.py tests/test_batch.py
git commit -m "Phase 3 task 1: BatchResult/BatchReport/BatchJobState dataclasses"
```

---

## Task 2: `run_batch` happy path with progress callback (TDD)

Implement the sequential loop with no retry yet. Use a monkeypatched `run_pipeline` so this task is fast and deterministic — real-binary tests come in Task 5.

**Files:**

- Modify: `src/pdf_ocr_compress/core/batch.py`
- Modify: `tests/test_batch.py`

- [ ] **Step 1: Add the failing happy-path tests**

Append to `tests/test_batch.py`:

```python
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
```

- [ ] **Step 2: Run new tests, expect failure**

Run: `uv run pytest tests/test_batch.py -v -k "run_batch"`
Expected: All `run_batch` tests FAIL — `NotImplementedError`.

- [ ] **Step 3: Implement happy-path `run_batch`**

Replace the `run_batch` body in `src/pdf_ocr_compress/core/batch.py`:

```python
def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    mode: Mode = "auto",
    preset: str | None = None,
    lang: str | None = None,
    jobs: int | None = None,
    pdfa: bool = False,
    force_ocr: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> BatchReport:
    """Process every *.pdf in input_dir and return a BatchReport.

    Sequential loop calling run_pipeline() per file. Per-file successes
    and failures (including retries — see Task 3) are recorded as
    BatchResult entries; whole-batch summary fields are aggregated at
    the end. Always writes <output_dir>/batch_report.json before
    returning, even on a 0-file folder.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = _list_pdfs(input_dir)
    started_at = _now_iso()
    start_t = time.time()
    total_input_bytes = sum(p.stat().st_size for p in pdfs)

    results: list[BatchResult] = []

    for i, pdf in enumerate(pdfs, start=1):
        if progress_callback:
            progress_callback(i, len(pdfs), pdf)

        result, error = _attempt_once(
            pdf,
            output_dir,
            mode=mode,
            preset=preset,
            lang=lang,
            jobs=jobs,
            pdfa=pdfa,
            force_ocr=force_ocr,
        )
        # Retry ladder is added in Task 3. For now: success = ok, failure = failed.
        if result is not None:
            results.append(
                BatchResult(
                    input_path=pdf,
                    output_path=result.output_path,
                    status="ok",
                    attempts=1,
                    error_msg=None,
                    process_result=result,
                )
            )
        else:
            results.append(
                BatchResult(
                    input_path=pdf,
                    output_path=None,
                    status="failed",
                    attempts=1,
                    error_msg=str(error),
                    process_result=None,
                )
            )

    finished_at = _now_iso()
    elapsed = time.time() - start_t

    succeeded = sum(1 for r in results if r.status == "ok")
    failed = len(results) - succeeded
    total_output_bytes = sum(
        r.process_result.output_bytes for r in results if r.process_result
    )

    report = BatchReport(
        input_dir=input_dir,
        output_dir=output_dir,
        total_files=len(pdfs),
        succeeded=succeeded,
        failed=failed,
        started_at=started_at,
        finished_at=finished_at,
        total_seconds=elapsed,
        total_input_bytes=total_input_bytes,
        total_output_bytes=total_output_bytes,
        results=results,
    )
    report.write_json(output_dir / "batch_report.json")
    return report


def _attempt_once(
    pdf: Path,
    output_dir: Path,
    *,
    mode: Mode,
    preset: str | None,
    lang: str | None,
    jobs: int | None,
    pdfa: bool,
    force_ocr: bool,
) -> tuple[ProcessResult | None, Exception | None]:
    """One run_pipeline call. Returns (result, None) on success, (None, exc) on failure."""
    output_base = output_dir / pdf.name
    try:
        result = run_pipeline(
            pdf,
            output_base,
            mode=mode,
            preset=preset,
            lang=lang,
            jobs=jobs,
            pdfa=pdfa,
            force_ocr=force_ocr,
        )
        return result, None
    except Exception as e:  # noqa: BLE001 — intentional: retry policy treats any exception alike
        return None, e
```

- [ ] **Step 4: Run tests, expect happy-path passes**

Run: `uv run pytest tests/test_batch.py -v`
Expected: All tests in this file PASS (the dataclass tests from Task 1 plus the five happy-path tests added here).

- [ ] **Step 5: Lint + format**

Run: `uv run black src/pdf_ocr_compress/core/batch.py tests/test_batch.py && uv run ruff check src/pdf_ocr_compress/core/batch.py tests/test_batch.py`
Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add src/pdf_ocr_compress/core/batch.py tests/test_batch.py
git commit -m "Phase 3 task 2: run_batch happy path + progress callback"
```

---

## Task 3: Retry-once + end-of-batch second pass (TDD)

Implement the failure ladder. Test with monkeypatched `run_pipeline` that fails N times then succeeds.

**Files:**

- Modify: `src/pdf_ocr_compress/core/batch.py`
- Modify: `tests/test_batch.py`

- [ ] **Step 1: Add failing retry tests**

Append to `tests/test_batch.py`:

```python
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
```

- [ ] **Step 2: Run tests, expect failures**

Run: `uv run pytest tests/test_batch.py -v -k "retries or end_of_batch or final_failure or one_bad_apple"`
Expected: All four new tests FAIL — `attempts == 1` instead of expected values, or `status == "failed"` after first attempt instead of retrying.

- [ ] **Step 3: Implement the retry ladder**

Replace the `run_batch` body in `src/pdf_ocr_compress/core/batch.py` with the following (the helper `_attempt_once` from Task 2 is reused unchanged):

```python
def run_batch(
    input_dir: Path,
    output_dir: Path,
    *,
    mode: Mode = "auto",
    preset: str | None = None,
    lang: str | None = None,
    jobs: int | None = None,
    pdfa: bool = False,
    force_ocr: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> BatchReport:
    """Process every *.pdf in input_dir and return a BatchReport.

    Failure ladder per file:
      1. initial attempt
      2. immediate retry on failure
      3. (deferred) second-pass retry at end of batch for any file still failing
    A file that fails all three is recorded with status='failed', attempts=3.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = _list_pdfs(input_dir)
    started_at = _now_iso()
    start_t = time.time()
    total_input_bytes = sum(p.stat().st_size for p in pdfs)

    # Per-file outcomes after initial + immediate retry; the second-pass
    # retry runs after the main loop. `pending_retry` is keyed by input
    # path and carries the prior-attempt count + the most recent error.
    successes: dict[Path, BatchResult] = {}
    pending_retry: dict[Path, tuple[int, Exception]] = {}

    for i, pdf in enumerate(pdfs, start=1):
        if progress_callback:
            progress_callback(i, len(pdfs), pdf)

        # Initial attempt
        result, error = _attempt_once(
            pdf, output_dir, mode=mode, preset=preset, lang=lang,
            jobs=jobs, pdfa=pdfa, force_ocr=force_ocr,
        )
        if result is not None:
            successes[pdf] = BatchResult(
                input_path=pdf,
                output_path=result.output_path,
                status="ok",
                attempts=1,
                error_msg=None,
                process_result=result,
            )
            continue

        # Immediate retry
        result, error = _attempt_once(
            pdf, output_dir, mode=mode, preset=preset, lang=lang,
            jobs=jobs, pdfa=pdfa, force_ocr=force_ocr,
        )
        if result is not None:
            successes[pdf] = BatchResult(
                input_path=pdf,
                output_path=result.output_path,
                status="ok",
                attempts=2,
                error_msg=None,
                process_result=result,
            )
            continue

        # Both attempts failed; defer to end-of-batch second pass.
        pending_retry[pdf] = (2, error)  # type: ignore[assignment]

    # End-of-batch second pass
    final_failures: dict[Path, BatchResult] = {}
    for pdf, (prior_attempts, prior_error) in pending_retry.items():
        result, error = _attempt_once(
            pdf, output_dir, mode=mode, preset=preset, lang=lang,
            jobs=jobs, pdfa=pdfa, force_ocr=force_ocr,
        )
        total_attempts = prior_attempts + 1
        if result is not None:
            successes[pdf] = BatchResult(
                input_path=pdf,
                output_path=result.output_path,
                status="ok",
                attempts=total_attempts,
                error_msg=None,
                process_result=result,
            )
        else:
            final_failures[pdf] = BatchResult(
                input_path=pdf,
                output_path=None,
                status="failed",
                attempts=total_attempts,
                error_msg=str(error),
                process_result=None,
            )

    # Combine in original input order so results follow folder order.
    results: list[BatchResult] = []
    for pdf in pdfs:
        if pdf in successes:
            results.append(successes[pdf])
        else:
            results.append(final_failures[pdf])

    finished_at = _now_iso()
    elapsed = time.time() - start_t

    succeeded = sum(1 for r in results if r.status == "ok")
    failed = len(results) - succeeded
    total_output_bytes = sum(
        r.process_result.output_bytes for r in results if r.process_result
    )

    report = BatchReport(
        input_dir=input_dir,
        output_dir=output_dir,
        total_files=len(pdfs),
        succeeded=succeeded,
        failed=failed,
        started_at=started_at,
        finished_at=finished_at,
        total_seconds=elapsed,
        total_input_bytes=total_input_bytes,
        total_output_bytes=total_output_bytes,
        results=results,
    )
    report.write_json(output_dir / "batch_report.json")
    return report
```

- [ ] **Step 4: Run all tests, expect every test in test_batch.py to pass**

Run: `uv run pytest tests/test_batch.py -v`
Expected: All tests PASS — dataclass tests, happy path, and retry tests.

- [ ] **Step 5: Run the full test suite to catch regressions**

Run: `uv run pytest -v`
Expected: All previously-passing tests still pass; new test_batch tests added.

- [ ] **Step 6: Lint + format**

Run: `uv run black src/pdf_ocr_compress/core/batch.py tests/test_batch.py && uv run ruff check src/pdf_ocr_compress/core/batch.py tests/test_batch.py`
Expected: Clean.

- [ ] **Step 7: Commit**

```bash
git add src/pdf_ocr_compress/core/batch.py tests/test_batch.py
git commit -m "Phase 3 task 3: retry-once + end-of-batch second-pass retry ladder"
```

---

## Task 4: Export `run_batch` from `core/__init__.py`

Trivial but real — surfaces import from `pdf_ocr_compress.core.batch` directly per existing convention (cf. `pdf_ocr_compress.core.pipeline`), but the public re-export keeps `from pdf_ocr_compress.core import ...` ergonomic.

**Files:**

- Modify: `src/pdf_ocr_compress/core/__init__.py`

- [ ] **Step 1: Update `core/__init__.py`**

Replace the file content with:

```python
"""
Core processing modules for PDF OCR and compression.
"""

from .batch import BatchJobState, BatchReport, BatchResult, run_batch
from .compress import compress
from .detect import needs_ocr
from .ocr import run_ocr
from .pipeline import ProcessResult, run_pipeline

__all__ = [
    "run_ocr",
    "compress",
    "needs_ocr",
    "run_pipeline",
    "ProcessResult",
    "run_batch",
    "BatchResult",
    "BatchReport",
    "BatchJobState",
]
```

- [ ] **Step 2: Verify the new exports import cleanly**

Run: `uv run python -c "from pdf_ocr_compress.core import run_batch, BatchResult, BatchReport, BatchJobState; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Run the test suite**

Run: `uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/pdf_ocr_compress/core/__init__.py
git commit -m "Phase 3 task 4: export run_batch + dataclasses from core package"
```

---

## Task 5: Real-binary integration tests + `corrupt_pdf` fixture (TDD)

End-to-end runs against actual Ghostscript and Tesseract, gated on the same skipifs Phase 2 used. Adds the `corrupt_pdf` fixture (the one new fixture for Phase 3).

**Files:**

- Modify: `tests/conftest.py`
- Modify: `tests/test_batch.py`

- [ ] **Step 1: Add the `corrupt_pdf` fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def corrupt_pdf(tmp_path_factory):
    """A file with .pdf extension but non-PDF content.

    Both run_pipeline attempts will raise (pikepdf can't open it; OCRmyPDF
    can't open it). Used by the batch failure-handling tests to verify
    `attempts=3` and `status='failed'` after exhausting the retry ladder.
    """
    path = tmp_path_factory.mktemp("fixtures") / "corrupt.pdf"
    path.write_bytes(b"this is not a PDF, it is just bytes\n")
    return path
```

- [ ] **Step 2: Add the failing integration tests**

Append to `tests/test_batch.py`:

```python
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
```

- [ ] **Step 3: Run the new tests, expect them to pass against the implementation from Tasks 2-3**

Run: `uv run pytest tests/test_batch.py -v -k "real_binaries"`
Expected: Both tests PASS (or are SKIPPED with reason "Ghostscript not installed" on a machine without Ghostscript — both outcomes are acceptable in CI; on the dev machine they should pass).

- [ ] **Step 4: Run the full suite to confirm no regressions**

Run: `uv run pytest -v`
Expected: All tests pass or are appropriately skipped.

- [ ] **Step 5: Lint + format**

Run: `uv run black tests/test_batch.py tests/conftest.py && uv run ruff check tests/test_batch.py tests/conftest.py`
Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_batch.py
git commit -m "Phase 3 task 5: corrupt_pdf fixture + real-binary batch integration tests"
```

---

## Task 6: CLI `pdf-ocr batch` command

Add the Typer subcommand. Smoke test with `typer.testing.CliRunner` against a monkeypatched `run_batch` so the test is fast and deterministic.

**Files:**

- Modify: `src/pdf_ocr_compress/cli.py`
- Create: `tests/test_cli_batch.py`

- [ ] **Step 1: Write the failing CLI test**

Create `tests/test_cli_batch.py`:

```python
"""Smoke test for `pdf-ocr batch`. Mocks run_batch to keep it fast."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pdf_ocr_compress.cli import app
from pdf_ocr_compress.core.batch import BatchReport


def _empty_report(in_dir: Path, out_dir: Path) -> BatchReport:
    return BatchReport(
        input_dir=in_dir,
        output_dir=out_dir,
        total_files=0,
        succeeded=0,
        failed=0,
        started_at="2026-04-29T10:00:00.000",
        finished_at="2026-04-29T10:00:00.000",
        total_seconds=0.0,
        total_input_bytes=0,
        total_output_bytes=0,
        results=[],
    )


def test_cli_batch_invokes_run_batch_with_defaults(tmp_path):
    in_dir = tmp_path / "in"
    in_dir.mkdir()

    runner = CliRunner()
    with patch("pdf_ocr_compress.cli.run_batch") as mock_run_batch:
        mock_run_batch.return_value = _empty_report(in_dir, in_dir / "processed")
        result = runner.invoke(app, ["batch", str(in_dir)])

    assert result.exit_code == 0, result.output
    mock_run_batch.assert_called_once()
    kwargs = mock_run_batch.call_args.kwargs
    args = mock_run_batch.call_args.args
    # First positional is input_dir, second is output_dir (default <in>/processed)
    assert Path(args[0]) == in_dir
    assert Path(args[1]) == in_dir / "processed"
    assert kwargs["mode"] == "auto"


def test_cli_batch_passes_explicit_options(tmp_path):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()

    runner = CliRunner()
    with patch("pdf_ocr_compress.cli.run_batch") as mock_run_batch:
        mock_run_batch.return_value = _empty_report(in_dir, out_dir)
        result = runner.invoke(
            app,
            [
                "batch",
                str(in_dir),
                "--output-dir",
                str(out_dir),
                "--mode",
                "compress",
                "--preset",
                "archival",
                "--lang",
                "eng+spa",
                "--jobs",
                "8",
                "--pdfa",
                "--force-ocr",
            ],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_run_batch.call_args.kwargs
    args = mock_run_batch.call_args.args
    assert Path(args[0]) == in_dir
    assert Path(args[1]) == out_dir
    assert kwargs["mode"] == "compress"
    assert kwargs["preset"] == "archival"
    assert kwargs["lang"] == "eng+spa"
    assert kwargs["jobs"] == 8
    assert kwargs["pdfa"] is True
    assert kwargs["force_ocr"] is True


def test_cli_batch_prints_summary_and_report_path(tmp_path):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()

    runner = CliRunner()
    with patch("pdf_ocr_compress.cli.run_batch") as mock_run_batch:
        mock_run_batch.return_value = _empty_report(in_dir, out_dir)
        result = runner.invoke(app, ["batch", str(in_dir), "--output-dir", str(out_dir)])

    assert result.exit_code == 0
    assert "0 ok, 0 failed" in result.output
    assert "batch_report.json" in result.output
```

- [ ] **Step 2: Run the test, expect failure**

Run: `uv run pytest tests/test_cli_batch.py -v`
Expected: All three tests FAIL with `Usage: ... No such command 'batch'`.

- [ ] **Step 3: Implement the CLI command**

Append the following to `src/pdf_ocr_compress/cli.py` (and add the `from .core.batch import run_batch` import at the top alongside the existing pipeline import):

```python
from .config import get_config
from .core.batch import run_batch
```

(Place these next to the existing `from .core.pipeline import run_pipeline` line.)

Then append the new command after the existing `process` command:

```python
@app.command()
def batch(
    input_dir: Path,
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Where to write processed PDFs. Default: <input_dir>/processed.",
    ),
    mode: str = typer.Option(
        "auto", help="Per-file pipeline mode: auto | ocr | compress"
    ),
    preset: str = typer.Option(
        None, help="archival | balanced | smallest. Default from settings."
    ),
    lang: str = typer.Option(
        None, "--lang", help="OCR language(s). Default from settings."
    ),
    jobs: int = typer.Option(
        None, help="Per-file OCR parallelism. Default from settings."
    ),
    pdfa: bool = typer.Option(False, help="Produce PDF/A-2 output for OCR'd files."),
    force_ocr: bool = typer.Option(
        False, "--force-ocr", help="Force OCR on every file regardless of needs_ocr()."
    ),
):
    """Process every *.pdf in INPUT_DIR; write results + batch_report.json to --output-dir.

    Failures are retried once immediately and once at end of batch (max 3 attempts
    per file). One bad PDF doesn't kill the rest of the batch.
    """
    settings = get_config().settings
    effective_preset = preset if preset is not None else settings.default_preset
    effective_lang = lang if lang is not None else settings.default_language
    effective_jobs = jobs if jobs is not None else settings.default_jobs
    effective_output_dir = (
        output_dir if output_dir is not None else input_dir / "processed"
    )

    typer.echo(f"Batch: {input_dir} -> {effective_output_dir}")
    report = run_batch(
        input_dir,
        effective_output_dir,
        mode=mode,  # type: ignore[arg-type]
        preset=effective_preset,
        lang=effective_lang,
        jobs=effective_jobs,
        pdfa=pdfa,
        force_ocr=force_ocr,
    )

    # Per-file lines
    for r in report.results:
        if r.status == "ok" and r.process_result is not None:
            typer.echo(r.process_result.one_line_summary())
        else:
            typer.echo(
                f"{r.input_path.name}: FAILED after {r.attempts} attempts: {r.error_msg}"
            )

    # Batch summary
    typer.echo("")
    typer.echo(f"Batch summary: {report.one_line_summary()}")
    typer.echo(f"Report: {effective_output_dir / 'batch_report.json'}")
```

- [ ] **Step 4: Run CLI tests, expect them to pass**

Run: `uv run pytest tests/test_cli_batch.py -v`
Expected: All three tests PASS.

- [ ] **Step 5: Verify the new command is visible in `--help`**

Run: `uv run pdf-ocr --help`
Expected: Output contains a `batch` subcommand alongside `ocr`, `compress`, and `process`.

Run: `uv run pdf-ocr batch --help`
Expected: Output describes the options (`--output-dir`, `--mode`, `--preset`, `--lang`, `--jobs`, `--pdfa`, `--force-ocr`).

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass / appropriately skipped.

- [ ] **Step 7: Lint + format**

Run: `uv run black src/pdf_ocr_compress/cli.py tests/test_cli_batch.py && uv run ruff check src/pdf_ocr_compress/cli.py tests/test_cli_batch.py`
Expected: Clean.

- [ ] **Step 8: Commit**

```bash
git add src/pdf_ocr_compress/cli.py tests/test_cli_batch.py
git commit -m "Phase 3 task 6: CLI batch command"
```

---

## Task 7: API endpoints — `POST /api/batch` + `GET /api/batch/{job_id}/status`

Add the two endpoints, the in-memory `batch_jobs` dict, and a `cleanup_old_jobs()` helper that mirrors the existing `cleanup_old_files()` pattern. Per spec, no httpx-based test in Phase 3 — Phase 4 covers via curl smoke. Smoke verification is via the existing `python -c "from pdf_ocr_compress.api.server import app; print('API ok')"` pattern plus a manual `/docs` check.

**Files:**

- Modify: `src/pdf_ocr_compress/api/server.py`

- [ ] **Step 1: Add the request/response models and job-state dict**

In `src/pdf_ocr_compress/api/server.py`, add these Pydantic models after the existing `ProcessResponse` class:

```python
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
```

Modify the existing `from fastapi import ...` line at the top of the file to also include `BackgroundTasks`. The current line:

```python
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
```

Becomes:

```python
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
```

Below the existing `file_storage = {}` line, add:

```python
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
```

- [ ] **Step 2: Add the `/api/batch` POST endpoint**

Add the imports at the top alongside the existing pipeline import:

```python
from ..config import get_config
from ..core.batch import BatchJobState, run_batch
```

Append to `src/pdf_ocr_compress/api/server.py`:

```python
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
        raise HTTPException(status_code=400, detail=f"Invalid mode: {req.mode}")

    folder = Path(req.folder)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Folder does not exist or is not a directory: {req.folder}"
        )

    output_dir = (
        Path(req.output_dir) if req.output_dir is not None else folder / "processed"
    )
    # If output_dir doesn't exist, its parent must be writable so we can mkdir.
    target_for_writability_check = output_dir if output_dir.exists() else output_dir.parent
    if not os.access(target_for_writability_check, os.W_OK):
        raise HTTPException(
            status_code=400,
            detail=f"Output dir (or its parent) is not writable: {output_dir}",
        )

    settings = get_config().settings
    preset = req.preset if req.preset is not None else settings.default_preset
    if preset not in ["archival", "balanced", "smallest"]:
        raise HTTPException(status_code=400, detail=f"Invalid preset: {preset}")

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
        except Exception as e:  # noqa: BLE001 — surface orchestrator-level errors to the client
            state.status = "error"
            state.error_msg = str(e)
        finally:
            state.finished_at = datetime.now().isoformat(timespec="milliseconds")

    background_tasks.add_task(_run)

    return BatchAcceptedResponse(
        status="queued", job_id=job_id, total_files=len(pdfs)
    )


@app.get("/api/batch/{job_id}/status")
async def batch_status(job_id: str):
    """Poll a batch job's state. Returns 404 if unknown or expired."""
    cleanup_old_jobs()
    state = batch_jobs.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Batch job not found or expired")
    return state.to_dict()
```

Also add `import os` to the top of the file if not already present.

- [ ] **Step 3: Verify the API still imports cleanly**

Run: `uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"`
Expected: `API ok`.

- [ ] **Step 4: Sanity-check the new endpoints appear in the OpenAPI schema**

Run: `uv run python -c "from pdf_ocr_compress.api.server import app; import json; spec = app.openapi(); print(sorted(spec['paths'].keys()))"`
Expected output contains `/api/batch` and `/api/batch/{job_id}/status` along with the pre-existing `/api/process`, `/api/download/{file_id}`, `/health`, and `/`.

- [ ] **Step 5: Manual end-to-end smoke (write to the commit message that this was done; no automated test in Phase 3)**

Run in one terminal: `uv run python -m uvicorn pdf_ocr_compress.api.server:app --port 8502`

In another terminal, with a small folder of test PDFs at `pdfs/_batch_smoke/`:

```bash
curl -X POST http://localhost:8502/api/batch \
  -H "Content-Type: application/json" \
  -d '{"folder":"pdfs/_batch_smoke","mode":"compress","preset":"smallest"}'
```

Expected: `{"status":"queued","job_id":"...","total_files":N}`. Then:

```bash
curl http://localhost:8502/api/batch/<job_id>/status
```

Expected: `status` progresses `queued` → `running` → `done`, with a `report` populated when done. `batch_report.json` exists in `pdfs/_batch_smoke/processed/`.

If you don't have a small folder handy, skip this step and rely on Task 5's `test_batch.py` integration tests + the import-cleanly check in Step 3 above. Phase 4 will add `tests/api_smoke.sh` (per ROADMAP).

- [ ] **Step 6: Lint + format**

Run: `uv run black src/pdf_ocr_compress/api/server.py && uv run ruff check src/pdf_ocr_compress/api/server.py`
Expected: Clean.

- [ ] **Step 7: Commit**

```bash
git add src/pdf_ocr_compress/api/server.py
git commit -m "Phase 3 task 7: POST /api/batch + GET /api/batch/{job_id}/status"
```

---

## Task 8: GUI multi-file uploader on `gui/basic.py`

Add a new "Batch upload" section below the existing single-file controls. Per spec, no automated GUI test in Phase 3 — Phase 5 covers click-through testing.

**Files:**

- Modify: `src/pdf_ocr_compress/gui/basic.py`

- [ ] **Step 1: Add the imports needed for batch**

At the top of `src/pdf_ocr_compress/gui/basic.py`, alongside the existing core imports, add `run_batch`:

```python
try:
    from .core.batch import run_batch
    from .core.detect import needs_ocr
    from .core.pipeline import run_pipeline
except ImportError:
    from pdf_ocr_compress.core.batch import run_batch
    from pdf_ocr_compress.core.detect import needs_ocr
    from pdf_ocr_compress.core.pipeline import run_pipeline
```

(Replace the existing two-line import block with this three-line block.)

- [ ] **Step 2: Append the batch section to `main()`**

At the end of `main()`, after the existing `if run_btn:` block (just before the `if __name__ == "__main__":` guard at module level), add a new section:

```python
    # --- Batch upload section ---
    st.divider()
    st.subheader("📦 Batch: process multiple PDFs at once")
    st.caption(
        "Drop several PDFs; each is processed with the same settings. A "
        "batch_report.json summarizing every file is downloadable when done."
    )

    batch_uploads = st.file_uploader(
        "Drop multiple PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key="batch_uploader",
    )

    batch_btn = st.button(
        "Process batch",
        type="primary",
        disabled=not batch_uploads,
        key="batch_run",
    )

    if batch_btn and batch_uploads:
        batch_workdir = Path(tempfile.mkdtemp(prefix="pdfgui_batch_"))
        batch_in = batch_workdir / "input"
        batch_out = batch_workdir / "output"
        batch_in.mkdir()

        # Persist uploads to disk (chunked).
        for uf in batch_uploads:
            _chunk_copy(uf, batch_in / uf.name)

        pipeline_mode = {
            "OCR only": "ocr",
            "Compress only": "compress",
        }.get(mode, "auto")

        progress_bar = st.progress(0.0, text="Starting batch…")
        live_table = st.empty()
        rows: list[dict] = []

        def _cb(current: int, total: int, current_path: Path) -> None:
            progress_bar.progress(
                min(current / max(total, 1), 1.0),
                text=f"{current}/{total} — {current_path.name}",
            )
            rows.append(
                {"file": current_path.name, "status": "processing", "delta": "—"}
            )
            live_table.dataframe(rows, hide_index=True)

        try:
            with st.status("Running batch…", expanded=True) as status:
                report = run_batch(
                    batch_in,
                    batch_out,
                    mode=pipeline_mode,
                    preset=preset,
                    lang=lang,
                    jobs=jobs,
                    pdfa=pdfa,
                    force_ocr=force_ocr,
                    progress_callback=_cb,
                )
                progress_bar.progress(1.0, text="Done")
                status.update(label="Batch complete ✅", state="complete")
        except Exception as e:
            st.error(f"Batch failed at the orchestrator level: {e}")
            st.stop()

        # Final results table
        final_rows = []
        for r in report.results:
            if r.status == "ok" and r.process_result is not None:
                pct = r.process_result.pct_change
                sign = "-" if pct < 0 else "+"
                final_rows.append(
                    {
                        "file": r.input_path.name,
                        "status": "ok",
                        "delta": f"{sign}{abs(pct):.1f}%",
                        "attempts": r.attempts,
                        "error": "",
                    }
                )
            else:
                final_rows.append(
                    {
                        "file": r.input_path.name,
                        "status": "FAILED",
                        "delta": "—",
                        "attempts": r.attempts,
                        "error": r.error_msg or "",
                    }
                )
        live_table.dataframe(final_rows, hide_index=True)

        st.success(report.one_line_summary())

        # Per-file download buttons (successful files only)
        for r in report.results:
            if r.status == "ok" and r.output_path is not None and r.output_path.exists():
                with open(r.output_path, "rb") as f:
                    st.download_button(
                        f"⬇️ Download {r.input_path.name}",
                        data=f.read(),
                        file_name=r.output_path.name,
                        mime="application/pdf",
                        key=f"dl_{r.input_path.name}",
                    )

        # Batch report download
        report_path = batch_out / "batch_report.json"
        if report_path.exists():
            with open(report_path, "rb") as f:
                st.download_button(
                    "⬇️ Download batch_report.json",
                    data=f.read(),
                    file_name="batch_report.json",
                    mime="application/json",
                    key="dl_batch_report",
                )
```

- [ ] **Step 3: Confirm the GUI launcher imports**

Run: `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"`
Expected: `GUI ok`.

- [ ] **Step 4: Manual smoke (no automated test in Phase 3 per spec)**

Run: `uv run pdf-ocr-gui`
Expected: GUI loads at `http://localhost:8501`. Verify:

1. Existing single-file flow still works (no regression).
2. New "Batch: process multiple PDFs at once" section appears below.
3. Drop 2-3 small PDFs and click "Process batch". Progress bar updates, results table populates, download buttons appear.

If you don't want to do a manual test now, defer to Phase 5 where browser smoke is the explicit deliverable. Note this in the commit message.

- [ ] **Step 5: Lint + format**

Run: `uv run black src/pdf_ocr_compress/gui/basic.py && uv run ruff check src/pdf_ocr_compress/gui/basic.py`
Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 3 task 8: GUI multi-file batch uploader"
```

---

## Task 9: Documentation updates

Mark Phase 3 closed in CLAUDE.md and ROADMAP.md.

**Files:**

- Modify: `CLAUDE.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Update `ROADMAP.md` Status block**

In `ROADMAP.md`, change line 12:

```markdown
- [ ] **Phase 3 — Batch**
```

to:

```markdown
- [x] **Phase 3 — Batch** (2026-04-29)
```

- [ ] **Step 2: Rewrite the "Where I left off" section in `CLAUDE.md`**

Replace the entire **"Where I left off"** section (the one that currently begins with "Phase 2 closed (2026-04-29)…" and ends just before the "Honest gaps still open" sub-section, plus the "Earlier on this branch" note) with a new section. The replacement text:

```markdown
## Where I left off

**Phase 3 closed (2026-04-29).** Folder-batch mode lands in
`core/batch.py` and is wired through CLI, GUI, and API. The pipeline
itself is unchanged: `run_batch` is a sequential `for` loop calling
`run_pipeline()` per file with a retry-once + end-of-batch second-pass
ladder. One bad PDF in the middle of a batch no longer kills the rest.
Pick up at **Phase 4 (API hardening)** — see `ROADMAP.md`.

**Phase 3 deliverables:**

- `core/batch.py` — `BatchResult`, `BatchReport`, `BatchJobState`
  dataclasses; `run_batch(input_dir, output_dir, *, mode, preset,
  lang, jobs, pdfa, force_ocr, progress_callback) -> BatchReport`.
- Failure ladder per file: initial → immediate retry → end-of-batch
  retry. Worst-case `attempts=3`. No backoff, no error classification
  (deterministic policy per CLAUDE.md "small focused modules" rule).
- `<output_dir>/batch_report.json` written every run, including
  zero-file folders. Schema = `BatchReport.to_dict()`; per-file
  results carry the full nested `ProcessResult.to_dict()`.
- CLI: `pdf-ocr batch <input_dir> [--output-dir Y] [--mode auto|ocr|
  compress] [--preset X] [--lang L] [--jobs N] [--pdfa] [--force-ocr]`.
  Defaults from `get_config().settings`. Per-file lines + summary +
  report path printed at end.
- GUI: new "Batch" section on `gui/basic.py` (still single page) —
  multi-file uploader, live progress bar + dataframe, per-file
  download buttons, `batch_report.json` download.
- API: `POST /api/batch` (server-side folder path JSON body, no
  upload) returns 202 + `{job_id, total_files}`. Processing runs in
  `BackgroundTasks` against the in-memory `batch_jobs` dict.
  `GET /api/batch/{job_id}/status` polls `BatchJobState`. Phase 4
  swaps the dict for SQLite without changing the wire shape.

**Tests:** test_batch.py covers dataclass serialization, happy path,
progress callback, ordering, retry-once / end-of-batch / final
failure, and real-binary integration (gated on Ghostscript /
Tesseract). test_cli_batch.py smoke-tests the CLI command via
`typer.testing.CliRunner`. No httpx-based API test in Phase 3 (Phase
4 covers via curl smoke). No automated GUI test in Phase 3 (Phase 5
covers browser click-through).

**Honest gaps still open after Phase 3 (deferred to later phases):**

- API endpoint integration (httpx / curl) — Phase 4 deliverable.
- GUI browser click-through — Phase 5 deliverable.
- `POST /api/batch/{job_id}/cancel` — explicitly deferred. Adding it
  later means polling a `should_cancel` flag inside `run_batch`; not
  hard, just not done.
- SQLite persistence for `batch_jobs` — Phase 4 deliverable.
- Existing single-file CLI/GUI/API surface defaults still hardcoded
  (Phase 5). The new `batch` surfaces already read from
  `get_config().settings`; the older `ocr` / `compress` / `process`
  commands and the single-file upload form do not.
```

- [ ] **Step 3: Strike batch from "Known issues / tech debt" in CLAUDE.md**

Locate the bullet in CLAUDE.md "Known issues / tech debt" that mentions Phase 3 batch as ahead-of-us:

```markdown
- **Phase 3 batch + Phase 4 API hardening + Phase 5 GUI catchup +
  Phase 6 docs polish** all ahead. ROADMAP has the scope.
```

Replace it with:

```markdown
- **Phase 4 API hardening + Phase 5 GUI catchup + Phase 6 docs
  polish** all ahead. ROADMAP has the scope.
```

- [ ] **Step 4: Run smoke checks**

Run: `uv run pdf-ocr --help`
Expected: Output includes the `batch` subcommand.

Run: `uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"`
Expected: `API ok`.

Run: `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"`
Expected: `GUI ok`.

Run: `uv run pytest -v`
Expected: All tests pass / appropriately skipped.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md ROADMAP.md
git commit -m "Phase 3 closure: doc updates after batch lands"
```

---

## Spec coverage check (self-review)

Cross-walk every spec section/requirement against the tasks above.

- [x] **Architecture: `core/batch.py` with dataclasses + `run_batch`** — Tasks 1, 2, 3.
- [x] **`BatchResult`, `BatchReport`, `BatchJobState` dataclasses + JSON serialization** — Task 1.
- [x] **`batch_report.json` lives at `<output_dir>/batch_report.json`** — Task 2 (write_json call) + Task 5 (real-binary integration test).
- [x] **Sequential loop, no async/threadpool** — Task 2 (sequential `for`).
- [x] **Retry-once + end-of-batch retry ladder, max 3 attempts** — Task 3.
- [x] **One bad apple doesn't kill the batch** — Task 3 (`test_run_batch_one_bad_apple_does_not_kill_batch`).
- [x] **Empty folder = zero-file report** — Task 2 (`test_run_batch_empty_folder_writes_zero_file_report`).
- [x] **Output dir created if missing** — Task 2 (`test_run_batch_creates_output_dir`).
- [x] **Progress callback `(current, total, current_path)`** — Task 2 (`test_run_batch_progress_callback_invoked_per_file`).
- [x] **CLI `pdf-ocr batch` with the documented flags** — Task 6.
- [x] **CLI defaults read from `get_config().settings` for batch** — Task 6.
- [x] **API `POST /api/batch` + `GET /api/batch/{job_id}/status` + in-memory `batch_jobs` + `BackgroundTasks`** — Task 7.
- [x] **API folder validation + writability check** — Task 7 (Step 2 logic).
- [x] **GUI multi-file uploader on `gui/basic.py`, single page** — Task 8.
- [x] **`corrupt_pdf` fixture** — Task 5.
- [x] **Real-binary integration tests** — Task 5.
- [x] **Doc updates: CLAUDE.md "Where I left off" + "Known issues" + ROADMAP.md Status** — Task 9.
- [x] **Deferred items called out (cancel, SQLite, httpx test, GUI click-through)** — Task 9 ("Honest gaps still open").

No gaps identified. Ready to execute.
