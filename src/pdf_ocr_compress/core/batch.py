"""Folder-batch orchestrator.

Loops core.pipeline.run_pipeline() over *.pdf files in a folder, applies a
retry-once / second-pass-at-end-of-batch failure ladder, and emits a
BatchReport (also written to <output_dir>/batch_report.json). The pipeline
itself is unchanged: every pipeline invariant (size guard, oversize fallback,
OCR routing, structured ProcessResult) keeps applying per-file.
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..utils.file_utils import human_readable_size
from .pipeline import Mode, ProcessResult, run_pipeline

BatchStatus = Literal["queued", "running", "done", "error"]
FileStatus = Literal["ok", "failed", "skipped"]

ProgressCallback = Callable[[int, int, Path], None]


@dataclass
class BatchResult:
    """Outcome for a single file in a batch."""

    input_path: Path
    output_path: Path | None
    status: FileStatus
    attempts: int  # run_pipeline calls for this file (1-3; 0 when skipped)
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
    total_input_bytes: int  # processed files only (skipped excluded)
    total_output_bytes: int  # successful files only
    results: list[BatchResult]
    # Inputs skipped because a same-name output already existed
    # (incremental batch; run with force=True to reprocess). Defaulted so
    # pre-existing constructions stay valid.
    skipped: int = 0

    def to_dict(self) -> dict:
        return {
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "total_files": self.total_files,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
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

        skipped_part = f", {self.skipped} skipped" if self.skipped else ""
        return (
            f"{self.succeeded} ok, {self.failed} failed{skipped_part} | "
            f"{in_size} -> {out_size} ({delta}) | {duration}"
        )


@dataclass
class BatchJobState:
    """API job record. Serialised by Storage into the SQLite batch_jobs table."""

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
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> BatchReport:
    """Process every *.pdf in input_dir and return a BatchReport.

    Incremental by default: an input whose same-name output already
    exists in output_dir is skipped (status='skipped', attempts=0), so
    re-running over a growing folder only processes new files. Pass
    force=True to reprocess everything. Limitation: the check is
    existence-only — a rescanned input with an unchanged name is
    considered done until force is used.

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

    skipped_results: dict[Path, BatchResult] = {}
    had_existing: set[Path] = set()
    to_process: list[Path] = []
    for pdf in pdfs:
        existing = output_dir / pdf.name
        if existing.exists():
            if force:
                # Force-reprocess: the stale output will be replaced in
                # place once the fresh output succeeds (F-023).
                had_existing.add(pdf)
                to_process.append(pdf)
            else:
                skipped_results[pdf] = BatchResult(
                    input_path=pdf,
                    output_path=existing,
                    status="skipped",
                    attempts=0,
                    error_msg=None,
                    process_result=None,
                )
        else:
            to_process.append(pdf)

    # Byte totals cover processed files only — counting skipped inputs
    # with no matching output bytes would distort the size-delta summary.
    total_input_bytes = sum(p.stat().st_size for p in to_process)

    # Per-file outcomes after initial + immediate retry; the second-pass
    # retry runs after the main loop. `pending_retry` is keyed by input
    # path and carries the prior-attempt count + the most recent error.
    successes: dict[Path, BatchResult] = {}
    pending_retry: dict[Path, tuple[int, Exception]] = {}

    for i, pdf in enumerate(to_process, start=1):
        if progress_callback:
            progress_callback(i, len(to_process), pdf)

        # Initial attempt
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
        if result is not None:
            successes[pdf] = _success_result(
                pdf,
                result,
                attempts=1,
                output_dir=output_dir,
                replace_stale=pdf in had_existing,
            )
            continue

        # Immediate retry
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
        if result is not None:
            successes[pdf] = _success_result(
                pdf,
                result,
                attempts=2,
                output_dir=output_dir,
                replace_stale=pdf in had_existing,
            )
            continue

        # Both attempts failed; defer to end-of-batch second pass.
        pending_retry[pdf] = (2, error)  # type: ignore[assignment]

    # End-of-batch second pass
    final_failures: dict[Path, BatchResult] = {}
    for pdf, (prior_attempts, _prior_error) in pending_retry.items():
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
        total_attempts = prior_attempts + 1
        if result is not None:
            successes[pdf] = _success_result(
                pdf,
                result,
                attempts=total_attempts,
                output_dir=output_dir,
                replace_stale=pdf in had_existing,
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
        elif pdf in skipped_results:
            results.append(skipped_results[pdf])
        else:
            results.append(final_failures[pdf])

    finished_at = _now_iso()
    elapsed = time.time() - start_t

    succeeded = sum(1 for r in results if r.status == "ok")
    skipped = len(skipped_results)
    failed = len(results) - succeeded - skipped
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
        skipped=skipped,
    )
    report.write_json(output_dir / "batch_report.json")
    return report


def _success_result(
    pdf: Path,
    result: ProcessResult,
    *,
    attempts: int,
    output_dir: Path,
    replace_stale: bool,
) -> BatchResult:
    """Record a per-file success; under force-reprocess, replace the
    stale same-name output in place (F-023).

    Scoped exception to the never-overwrite rule: batch OUTPUTS only,
    only under force=True, and only after the fresh output fully
    succeeded — a failed rerun leaves the stale file untouched. The
    fresh file was collision-renamed by the pipeline (the stale target
    existed), so os.replace moves it over the stale copy.
    """
    if replace_stale:
        target = output_dir / pdf.name
        if result.output_path != target:
            os.replace(result.output_path, target)
            result.output_path = target
    return BatchResult(
        input_path=pdf,
        output_path=result.output_path,
        status="ok",
        attempts=attempts,
        error_msg=None,
        process_result=result,
    )


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
