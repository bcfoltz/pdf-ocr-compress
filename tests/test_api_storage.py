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
