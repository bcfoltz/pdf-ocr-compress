"""Phase 4 item 1 — SQLite-backed `files` table.

Covers the success criterion ROADMAP states explicitly: file IDs survive
a uvicorn restart. We simulate a restart by closing the Storage
instance and opening a new one against the same DB path.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from pdf_ocr_compress.api.storage import Storage


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "api.db")


def _insert_sample(
    storage: Storage,
    tmp_path: Path,
    file_id: str = "abc",
    *,
    ttl: timedelta = timedelta(hours=1),
) -> tuple[Path, Path]:
    workdir = tmp_path / file_id
    workdir.mkdir()
    output_path = workdir / "output.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%mock\n")
    storage.insert_file(
        file_id=file_id,
        original_name="orig.pdf",
        output_path=output_path,
        workdir=workdir,
        mode="auto",
        preset="smallest",
        ttl=ttl,
    )
    return output_path, workdir


def test_insert_and_get_round_trip(storage: Storage, tmp_path: Path) -> None:
    _insert_sample(storage, tmp_path, "fid-1")
    row = storage.get_file("fid-1")
    assert row is not None
    assert row["file_id"] == "fid-1"
    assert row["original_name"] == "orig.pdf"
    assert row["mode"] == "auto"
    assert row["preset"] == "smallest"


def test_get_file_unknown_returns_none(storage: Storage) -> None:
    assert storage.get_file("nope") is None


def test_file_id_survives_restart(tmp_path: Path) -> None:
    """Success criterion #1: file IDs survive a uvicorn restart."""
    db_path = tmp_path / "api.db"
    s1 = Storage(db_path)
    _insert_sample(s1, tmp_path, "fid-restart")
    s1.close()

    s2 = Storage(db_path)
    row = s2.get_file("fid-restart")
    assert row is not None
    assert row["file_id"] == "fid-restart"
    s2.close()


def test_cleanup_removes_expired_rows(storage: Storage, tmp_path: Path) -> None:
    """Past-expiry rows go; their on-disk artifacts go too."""
    output_path, workdir = _insert_sample(
        storage, tmp_path, "fid-old", ttl=timedelta(seconds=-1)
    )
    assert output_path.exists() and workdir.exists()

    removed = storage.cleanup_expired_files()

    assert removed == 1
    assert storage.get_file("fid-old") is None
    assert not output_path.exists()
    assert not workdir.exists()


def test_cleanup_preserves_non_expired_rows(storage: Storage, tmp_path: Path) -> None:
    output_path, _ = _insert_sample(storage, tmp_path, "fid-fresh")
    storage.cleanup_expired_files()

    assert storage.get_file("fid-fresh") is not None
    assert output_path.exists()


# --- batch_jobs table -------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime as dt

    return dt.now().isoformat(timespec="milliseconds")


def test_batch_job_insert_progress_finish(storage: Storage) -> None:
    """Round-trip a job through queued -> running -> done with a report."""
    storage.insert_batch_job(
        job_id="job-1", status="queued", started_at=_now_iso(), progress_total=3
    )
    row = storage.get_batch_job("job-1")
    assert row is not None
    assert row["status"] == "queued"
    assert row["progress_total"] == 3
    assert row["progress_current"] == 0
    assert row["report"] is None

    storage.update_batch_progress("job-1", progress_current=2, progress_total=3)
    row = storage.get_batch_job("job-1")
    assert row["status"] == "running"
    assert row["progress_current"] == 2

    storage.finish_batch_job(
        "job-1",
        status="done",
        finished_at=_now_iso(),
        report_json='{"succeeded": 3, "failed": 0}',
    )
    row = storage.get_batch_job("job-1")
    assert row["status"] == "done"
    assert row["report"] == {"succeeded": 3, "failed": 0}
    assert row["error_msg"] is None


def test_batch_job_error_path(storage: Storage) -> None:
    storage.insert_batch_job(
        job_id="job-bad", status="queued", started_at=_now_iso(), progress_total=1
    )
    storage.finish_batch_job(
        "job-bad", status="error", finished_at=_now_iso(), error_msg="boom"
    )
    row = storage.get_batch_job("job-bad")
    assert row["status"] == "error"
    assert row["error_msg"] == "boom"
    assert row["report"] is None


def test_batch_job_unknown_returns_none(storage: Storage) -> None:
    assert storage.get_batch_job("nope") is None


def test_queue_depth_counts_active_jobs(storage: Storage) -> None:
    storage.insert_batch_job(
        job_id="q1", status="queued", started_at=_now_iso(), progress_total=1
    )
    storage.insert_batch_job(
        job_id="r1", status="queued", started_at=_now_iso(), progress_total=1
    )
    storage.update_batch_progress("r1", progress_current=0, progress_total=1)
    storage.insert_batch_job(
        job_id="d1", status="queued", started_at=_now_iso(), progress_total=1
    )
    storage.finish_batch_job("d1", status="done", finished_at=_now_iso())

    assert storage.queue_depth() == 2  # q1 (queued) + r1 (running); d1 excluded


def test_running_job_marked_stale_on_restart(tmp_path: Path) -> None:
    """ROADMAP success criterion: queued/running jobs from a previous
    process show up as error after a restart.
    """
    db_path = tmp_path / "api.db"
    s1 = Storage(db_path)
    s1.insert_batch_job(
        job_id="zombie",
        status="queued",
        started_at=_now_iso(),
        progress_total=5,
    )
    s1.update_batch_progress("zombie", progress_current=2, progress_total=5)
    s1.close()

    s2 = Storage(db_path)
    row = s2.get_batch_job("zombie")
    assert row is not None
    assert row["status"] == "error"
    assert row["error_msg"] == "server restarted mid-job"
    assert row["finished_at"] is not None
    s2.close()


def test_cleanup_expired_batch_jobs(storage: Storage) -> None:
    """Past-cutoff jobs go; recent ones stay."""
    from datetime import datetime as dt
    from datetime import timedelta as td

    storage.insert_batch_job(
        job_id="old",
        status="done",
        started_at=(dt.now() - td(hours=2)).isoformat(timespec="milliseconds"),
        progress_total=1,
    )
    storage.insert_batch_job(
        job_id="fresh", status="done", started_at=_now_iso(), progress_total=1
    )

    removed = storage.cleanup_expired_batch_jobs()

    assert removed == 1
    assert storage.get_batch_job("old") is None
    assert storage.get_batch_job("fresh") is not None
