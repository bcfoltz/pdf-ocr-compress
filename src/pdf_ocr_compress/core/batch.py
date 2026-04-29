"""Folder-batch orchestrator. Phase 3 — see docs/superpowers/specs/.

Loops core.pipeline.run_pipeline() over *.pdf files in a folder, applies a
retry-once / second-pass-at-end-of-batch failure ladder, and emits a
BatchReport (also written to <output_dir>/batch_report.json). The pipeline
itself is unchanged: every Phase 0/1/2 invariant (size guard, oversize
fallback, OCR routing, structured ProcessResult) keeps applying per-file.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..utils.file_utils import human_readable_size
from .pipeline import Mode, ProcessResult, run_pipeline

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
    except (
        Exception
    ) as e:  # noqa: BLE001 — intentional: retry policy treats any exception alike
        return None, e
