"""SQLite-backed persistence for the API server (Phase 4 item 1).

Replaces the in-memory `file_storage` and `batch_jobs` dicts in
`server.py` so processed-file IDs and batch-job state survive a uvicorn
restart. Schema deliberately mirrors what the dicts carried so the wire
shape (response fields, status payloads) doesn't change.

Why a class with a configurable path: tests need an isolated DB; the
production app uses one shared DB at `<TEMP_DIR>/pdf_ocr_api.db`. The
module exposes a `default_storage()` singleton built on first call.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Default expiry — matches the 1-hour cleanup window the in-memory dict used.
DEFAULT_TTL = timedelta(hours=1)

_FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_id       TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    output_path   TEXT NOT NULL,
    workdir       TEXT NOT NULL,
    mode          TEXT NOT NULL,
    preset        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
)
"""

# Phase 4 item 1 part B — `report_json` carries the serialized
# `BatchReport` (matches `report = BatchReport.to_dict()` shape) so a
# completed job is fully reconstructable from the row.
_BATCH_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS batch_jobs (
    job_id           TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total   INTEGER NOT NULL DEFAULT 0,
    error_msg        TEXT,
    report_json      TEXT
)
"""


class Storage:
    """Thread-safe-enough SQLite wrapper for the API server.

    `check_same_thread=False` lets FastAPI's BackgroundTasks (run in
    threadpool workers) write progress updates without erroring. WAL
    journaling keeps reads non-blocking while a background task writes.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we write tiny rows
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(_FILES_SCHEMA)
        self.conn.execute(_BATCH_JOBS_SCHEMA)
        # Phase 4 item 1 part B — any job that was running when the
        # server died is unrecoverable (its background thread is gone).
        # Mark stale once at startup so /status reflects reality.
        self._mark_stale_running_jobs()

    # --- files table --------------------------------------------------------

    def insert_file(
        self,
        *,
        file_id: str,
        original_name: str,
        output_path: Path,
        workdir: Path,
        mode: str,
        preset: str,
        ttl: timedelta = DEFAULT_TTL,
    ) -> None:
        now = datetime.now()
        self.conn.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file_id,
                original_name,
                str(output_path),
                str(workdir),
                mode,
                preset,
                now.isoformat(),
                (now + ttl).isoformat(),
            ),
        )

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM files WHERE file_id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def cleanup_expired_files(self) -> int:
        """Delete rows past `expires_at` and remove their on-disk artifacts.

        Returns the number of rows removed. Disk-side errors are
        swallowed (mirrors the prior in-memory implementation) — the
        DB row goes regardless so a phantom file_id can't pile up.
        """
        import shutil  # local import; cleanup is rare-path

        now_iso = datetime.now().isoformat()
        rows = self.conn.execute(
            "SELECT file_id, output_path, workdir FROM files WHERE expires_at < ?",
            (now_iso,),
        ).fetchall()
        for row in rows:
            try:
                p = Path(row["output_path"])
                if p.exists():
                    p.unlink()
            except Exception:
                pass
            try:
                w = Path(row["workdir"])
                if w.exists():
                    shutil.rmtree(w, ignore_errors=True)
            except Exception:
                pass
        self.conn.execute("DELETE FROM files WHERE expires_at < ?", (now_iso,))
        return len(rows)

    # --- batch_jobs table ---------------------------------------------------

    def insert_batch_job(
        self,
        *,
        job_id: str,
        status: str,
        started_at: str,
        progress_total: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO batch_jobs "
            "(job_id, status, started_at, progress_current, progress_total) "
            "VALUES (?, ?, ?, 0, ?)",
            (job_id, status, started_at, progress_total),
        )

    def update_batch_progress(
        self, job_id: str, *, progress_current: int, progress_total: int
    ) -> None:
        self.conn.execute(
            "UPDATE batch_jobs "
            "SET progress_current = ?, progress_total = ?, status = 'running' "
            "WHERE job_id = ?",
            (progress_current, progress_total, job_id),
        )

    def finish_batch_job(
        self,
        job_id: str,
        *,
        status: str,
        finished_at: str,
        report_json: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        self.conn.execute(
            "UPDATE batch_jobs SET status = ?, finished_at = ?, "
            "report_json = ?, error_msg = ? WHERE job_id = ?",
            (status, finished_at, report_json, error_msg, job_id),
        )

    def get_batch_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM batch_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        # Re-inflate the embedded report so callers see a structured dict
        # (the column stores JSON to keep the schema flat).
        if d.get("report_json"):
            try:
                d["report"] = json.loads(d["report_json"])
            except json.JSONDecodeError:
                d["report"] = None
        else:
            d["report"] = None
        d.pop("report_json", None)
        return d

    def cleanup_expired_batch_jobs(self, ttl: timedelta = DEFAULT_TTL) -> int:
        """Delete batch_job rows older than `ttl`. Mirrors the file TTL."""
        cutoff = (datetime.now() - ttl).isoformat()
        rows = self.conn.execute(
            "SELECT job_id FROM batch_jobs WHERE started_at < ?", (cutoff,)
        ).fetchall()
        self.conn.execute("DELETE FROM batch_jobs WHERE started_at < ?", (cutoff,))
        return len(rows)

    def queue_depth(self) -> int:
        """Count batch jobs that are queued or actively running.

        Used by /health for /api/batch backlog visibility.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM batch_jobs "
            "WHERE status IN ('queued', 'running')"
        ).fetchone()
        return int(row["c"]) if row else 0

    def _mark_stale_running_jobs(self) -> None:
        """Recover-on-startup: any job left in queued/running is dead.

        The background thread that drove it is gone with the previous
        process. Mark them as error with an explicit message so a polling
        client sees the failure instead of a job that never finishes.
        """
        finished_at = datetime.now().isoformat(timespec="milliseconds")
        self.conn.execute(
            "UPDATE batch_jobs SET status = 'error', "
            "finished_at = COALESCE(finished_at, ?), "
            "error_msg = COALESCE(error_msg, 'server restarted mid-job') "
            "WHERE status IN ('queued', 'running')",
            (finished_at,),
        )

    def close(self) -> None:
        self.conn.close()


# --- module-level default singleton -----------------------------------------

_DEFAULT_DB_PATH = Path(tempfile.gettempdir()) / "pdf_ocr_api" / "pdf_ocr_api.db"
_default_instance: Storage | None = None


def default_storage() -> Storage:
    """Lazy module singleton at <TEMP_DIR>/pdf_ocr_api/pdf_ocr_api.db.

    Tests build their own `Storage(tmp_path / "x.db")` and either
    monkeypatch `pdf_ocr_compress.api.server.STORAGE` to it or call
    `Storage` methods directly.
    """
    global _default_instance
    if _default_instance is None:
        _default_instance = Storage(_DEFAULT_DB_PATH)
    return _default_instance
