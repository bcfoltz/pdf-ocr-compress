"""Tests for core.oversize.enforce_oversize_policy.

Phase 2 / Design rule #1: output never exceeds input size. The helper is
a pure-function policy engine — no Ghostscript, no Tesseract — so we can
exercise every branch with raw byte writes for the pretend "input" and
"output" files.
"""

from pathlib import Path

import pytest

from pdf_ocr_compress.core.oversize import enforce_oversize_policy
from pdf_ocr_compress.utils.errors import PDFProcessingError


def _write(path: Path, size: int) -> Path:
    path.write_bytes(b"x" * size)
    return path


def test_output_under_input_returns_unchanged(tmp_path):
    """No violation: helper is a no-op when output ≤ input."""
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 800)

    result = enforce_oversize_policy(inp, out, "fallback", can_retry=True)

    assert result == out
    assert out.stat().st_size == 800


def test_output_equal_to_input_returns_unchanged(tmp_path):
    """Boundary: equal sizes satisfy the invariant."""
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1000)

    result = enforce_oversize_policy(inp, out, "fallback", can_retry=True)

    assert result == out
    assert out.stat().st_size == 1000


def test_warn_keeps_oversize_output(tmp_path):
    """policy=warn keeps the larger output for the caller's report."""
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)

    result = enforce_oversize_policy(inp, out, "warn", can_retry=False)

    assert result == out
    assert out.stat().st_size == 1500


def test_fail_raises_and_deletes_output(tmp_path):
    """policy=fail surfaces a stable error_code and cleans up the bad file."""
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)

    with pytest.raises(PDFProcessingError) as excinfo:
        enforce_oversize_policy(inp, out, "fail", can_retry=False)

    assert excinfo.value.error_code == "OUTPUT_GREW_NO_FALLBACK"
    assert not out.exists()


def test_fallback_retry_succeeds(tmp_path):
    """policy=fallback + retry-with-smallest produces a smaller file: keep it."""
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)

    def retry_smallest():
        return _write(tmp_path / "out.pdf", 600)

    result = enforce_oversize_policy(
        inp, out, "fallback", can_retry=True, retry_with_smallest=retry_smallest
    )

    assert result == out
    assert out.stat().st_size == 600


def test_fallback_retry_also_oversize_passes_through(tmp_path):
    """policy=fallback + smallest still grows the file: copy input verbatim."""
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)

    def retry_smallest():
        return _write(tmp_path / "out.pdf", 1100)

    result = enforce_oversize_policy(
        inp, out, "fallback", can_retry=True, retry_with_smallest=retry_smallest
    )

    assert result == out
    assert out.stat().st_size == 1000
    assert out.read_bytes() == inp.read_bytes()


def test_fallback_no_retry_passes_through_directly(tmp_path):
    """When the original call was already preset=smallest (can_retry=False),
    skip the retry attempt and pass the input through unchanged.
    """
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)

    result = enforce_oversize_policy(inp, out, "fallback", can_retry=False)

    assert result == out
    assert out.stat().st_size == 1000
    assert out.read_bytes() == inp.read_bytes()


# --- outcome OUT-parameter records what actually happened --------------------


def test_outcome_no_violation(tmp_path):
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 800)
    outcome: dict = {}
    enforce_oversize_policy(inp, out, "fallback", outcome=outcome)
    assert outcome["status"] == "no_violation"


def test_outcome_warned(tmp_path):
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)
    outcome: dict = {}
    enforce_oversize_policy(inp, out, "warn", outcome=outcome)
    assert outcome["status"] == "warned"


def test_outcome_retry_succeeded(tmp_path):
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)

    def retry_smallest():
        return _write(tmp_path / "out.pdf", 600)

    outcome: dict = {}
    enforce_oversize_policy(
        inp,
        out,
        "fallback",
        can_retry=True,
        retry_with_smallest=retry_smallest,
        outcome=outcome,
    )
    assert outcome["status"] == "retry_succeeded"


def test_outcome_passthrough(tmp_path):
    inp = _write(tmp_path / "in.pdf", 1000)
    out = _write(tmp_path / "out.pdf", 1500)
    outcome: dict = {}
    enforce_oversize_policy(inp, out, "fallback", can_retry=False, outcome=outcome)
    assert outcome["status"] == "passthrough"


# --- Wiring tests: compress() actually plumbs the guard through ----------------


def test_compress_fallback_retries_then_passes_through(monkeypatch, tmp_path):
    """End-to-end wiring: when Ghostscript produces oversize output and
    policy=fallback, compress() retries with smallest (proving the retry
    closure points back at compress with preset='smallest'), and on a
    second oversize result passes the input through verbatim.

    Mocks ghostscript_compress + linearize so this test doesn't require
    a real Ghostscript install.
    """
    import shutil
    import sys

    import pdf_ocr_compress.config.settings as cfg_settings
    import pdf_ocr_compress.core.compress  # noqa: F401 — load submodule
    from pdf_ocr_compress.config.settings import AppSettings, ConfigManager

    # Project memory: `from .compress import compress` in core/__init__.py
    # shadows the submodule, so the ordinary attribute path returns the
    # function. Reach the module through sys.modules to monkeypatch its
    # internals.
    compress_mod = sys.modules["pdf_ocr_compress.core.compress"]

    fresh_cm = ConfigManager(config_dir=tmp_path / "cfg")
    fresh_cm._settings = AppSettings(oversize_policy="fallback")
    monkeypatch.setattr(cfg_settings, "_config_manager", fresh_cm)

    inp = tmp_path / "in.pdf"
    inp.write_bytes(b"%PDF-1.4\nfake input bytes\n" * 5)

    presets_seen: list[str] = []

    def fake_gs(input_pdf, output_pdf, preset="balanced"):
        presets_seen.append(preset)
        output_pdf.write_bytes(input_pdf.read_bytes() * 5)  # always oversize
        return output_pdf

    def fake_linearize(src, dst):
        if src != dst:
            shutil.copy2(src, dst)
        return dst

    monkeypatch.setattr(compress_mod, "ghostscript_compress", fake_gs)
    monkeypatch.setattr(compress_mod, "linearize", fake_linearize)

    out = tmp_path / "out.pdf"
    result = compress_mod.compress(inp, out, preset="balanced")

    assert presets_seen == ["balanced", "smallest"]
    assert result == out
    assert out.read_bytes() == inp.read_bytes()


def test_compress_smallest_skips_retry(monkeypatch, tmp_path):
    """When the user explicitly picks preset='smallest' and the result
    still grows the file, the guard goes straight to passthrough — no
    pointless retry of the same preset.
    """
    import shutil
    import sys

    import pdf_ocr_compress.config.settings as cfg_settings
    import pdf_ocr_compress.core.compress  # noqa: F401 — load submodule
    from pdf_ocr_compress.config.settings import AppSettings, ConfigManager

    # Project memory: `from .compress import compress` in core/__init__.py
    # shadows the submodule, so the ordinary attribute path returns the
    # function. Reach the module through sys.modules to monkeypatch its
    # internals.
    compress_mod = sys.modules["pdf_ocr_compress.core.compress"]

    fresh_cm = ConfigManager(config_dir=tmp_path / "cfg")
    fresh_cm._settings = AppSettings(oversize_policy="fallback")
    monkeypatch.setattr(cfg_settings, "_config_manager", fresh_cm)

    inp = tmp_path / "in.pdf"
    inp.write_bytes(b"%PDF-1.4\ninput\n" * 5)

    presets_seen: list[str] = []

    def fake_gs(input_pdf, output_pdf, preset="balanced"):
        presets_seen.append(preset)
        output_pdf.write_bytes(input_pdf.read_bytes() * 3)
        return output_pdf

    def fake_linearize(src, dst):
        if src != dst:
            shutil.copy2(src, dst)
        return dst

    monkeypatch.setattr(compress_mod, "ghostscript_compress", fake_gs)
    monkeypatch.setattr(compress_mod, "linearize", fake_linearize)

    out = tmp_path / "out.pdf"
    result = compress_mod.compress(inp, out, preset="smallest")

    assert presets_seen == ["smallest"]
    assert result == out
    assert out.read_bytes() == inp.read_bytes()
