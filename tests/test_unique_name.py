"""Tests for utils.file_utils.unique_output_path.

Phase 1 fix: replaced second-resolution timestamps that would collide
under rapid back-to-back calls (50-file batch in <1s) with microsecond
resolution + counter fallback.
"""

from pathlib import Path

from pdf_ocr_compress.utils.file_utils import unique_output_path


def test_back_to_back_calls_produce_distinct_paths(tmp_path):
    """Rapid back-to-back calls in the same second must not collide.

    The Phase 0-era helper used `%Y%m%d-%H%M%S` and relied on the
    counter only kicking in when the candidate already existed on
    disk. Touching files between calls is the exact pattern a batch
    runner exhibits — this test would have failed against the old
    code.
    """
    base = tmp_path / "doc.pdf"
    seen: set[Path] = set()
    for _ in range(50):
        candidate = unique_output_path(base)
        assert candidate not in seen, "duplicate path produced in same loop"
        seen.add(candidate)
        candidate.touch()
    assert len(seen) == 50


def test_preserves_original_suffix(tmp_path):
    out = unique_output_path(tmp_path / "doc.pdf")
    assert out.suffix == ".pdf"

    out = unique_output_path(tmp_path / "report.PDF")
    assert out.suffix == ".PDF"


def test_uses_provided_suffix_marker(tmp_path):
    out = unique_output_path(tmp_path / "x.pdf", suffix="_linearized")
    assert "_linearized_" in out.stem


def test_default_suffix_marker(tmp_path):
    out = unique_output_path(tmp_path / "x.pdf")
    assert out.stem.startswith("x_processed_")


def test_returns_path_in_same_directory(tmp_path):
    base = tmp_path / "subdir" / "x.pdf"
    base.parent.mkdir()
    out = unique_output_path(base)
    assert out.parent == base.parent
