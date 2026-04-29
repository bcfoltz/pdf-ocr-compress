"""CLI wiring tests: each subcommand calls run_pipeline with the right
mode and forwards user-provided kwargs (preset, lang, force_ocr, etc.).

The behavior of run_pipeline itself is covered by tests/test_pipeline.py.
These tests just lock in the CLI plumbing — that future edits to cli.py
don't accidentally drop a kwarg or pick the wrong mode.
"""

from pathlib import Path

import pytest

from pdf_ocr_compress import cli as cli_mod
from pdf_ocr_compress.core.pipeline import ProcessResult


@pytest.fixture
def stub_run_pipeline(monkeypatch):
    """Replace cli.run_pipeline with a recorder. Returns the kwargs dict
    captured on the most recent call.
    """
    captured: dict = {}

    def fake(input_pdf, output_pdf, **kwargs):
        captured["input_pdf"] = input_pdf
        captured["output_pdf"] = output_pdf
        captured.update(kwargs)
        return ProcessResult(
            output_path=output_pdf,
            input_bytes=100,
            output_bytes=80,
            pct_change=-20.0,
            ocr_ran=kwargs.get("mode") == "ocr",
            ocr_skipped_reason=None,
            processing_seconds=0.01,
            preset_actually_used=kwargs.get("preset", "smallest"),
            pdfminer_text_extractable=True,
        )

    monkeypatch.setattr(cli_mod, "run_pipeline", fake)
    return captured


def _input(tmp_path: Path) -> Path:
    inp = tmp_path / "in.pdf"
    inp.write_bytes(b"%PDF-1.4 fake\n")
    return inp


def test_process_calls_pipeline_in_auto_mode(stub_run_pipeline, tmp_path):
    """`pdf-ocr process` -> mode='auto' with all flags forwarded."""
    inp = _input(tmp_path)
    out = tmp_path / "out.pdf"

    cli_mod.process(inp, out, lang="spa", preset="archival", force_ocr=True, jobs=2)

    assert stub_run_pipeline["mode"] == "auto"
    assert stub_run_pipeline["preset"] == "archival"
    assert stub_run_pipeline["lang"] == "spa"
    assert stub_run_pipeline["force_ocr"] is True
    assert stub_run_pipeline["jobs"] == 2
    assert stub_run_pipeline["input_pdf"] == inp
    assert stub_run_pipeline["output_pdf"] == out


def test_ocr_subcommand_calls_pipeline_in_ocr_mode(stub_run_pipeline, tmp_path):
    """`pdf-ocr ocr` -> mode='ocr' with force_ocr passed through."""
    inp = _input(tmp_path)
    out = tmp_path / "out.pdf"

    cli_mod.ocr(inp, out, lang="eng", preset="smallest", force_ocr=False)

    assert stub_run_pipeline["mode"] == "ocr"
    assert stub_run_pipeline["preset"] == "smallest"
    assert stub_run_pipeline["force_ocr"] is False


def test_compress_subcommand_calls_pipeline_in_compress_mode(
    stub_run_pipeline, tmp_path
):
    """`pdf-ocr compress` -> mode='compress' (no OCR-related kwargs)."""
    inp = _input(tmp_path)
    out = tmp_path / "out.pdf"

    cli_mod.compress(inp, out, preset="balanced")

    assert stub_run_pipeline["mode"] == "compress"
    assert stub_run_pipeline["preset"] == "balanced"
    # compress mode shouldn't pass language/jobs/force_ocr — keep the call
    # surface narrow so changes to defaults don't leak in.
    assert "lang" not in stub_run_pipeline
    assert "force_ocr" not in stub_run_pipeline
