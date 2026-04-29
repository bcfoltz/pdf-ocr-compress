"""Tests for core.pipeline.run_pipeline.

run_pipeline is the single entry point that all three surfaces (CLI / GUI
/ API) call. It builds the ProcessResult report — size deltas, OCR
routing decisions, the preset that actually shipped, a pdfminer
text-extractability smoke check, and elapsed time.

The underlying compress() and run_ocr() are mocked so these tests don't
need a real Ghostscript or OCRmyPDF install. _pdfminer_text_extractable
is also mocked because the fake outputs are not real PDFs.
"""

import sys

import pytest

import pdf_ocr_compress.core.pipeline  # noqa: F401 — load submodule
from pdf_ocr_compress.core.pipeline import ProcessResult, run_pipeline

# Submodule-shadowing workaround (see project memory): reach the module
# through sys.modules so monkeypatch can replace _compress / _run_ocr.
_pipeline = sys.modules["pdf_ocr_compress.core.pipeline"]


@pytest.fixture
def stub_pipeline_internals(monkeypatch, tmp_path):
    """Replace _compress, _run_ocr, needs_ocr, and the pdfminer smoke check
    with deterministic stubs. Returns a list of (op, kwargs) calls.
    """
    calls: list[tuple[str, dict]] = []

    def fake_compress(input_pdf, output_pdf, preset="balanced", *, _result=None):
        calls.append(
            (
                "compress",
                {"input_pdf": input_pdf, "output_pdf": output_pdf, "preset": preset},
            )
        )
        output_pdf.write_bytes(b"%PDF-1.4 compress-output\n")
        if _result is not None:
            _result["preset_used"] = preset
        return output_pdf

    def fake_run_ocr(**kwargs):
        calls.append(("run_ocr", kwargs))
        out = kwargs["output_pdf"]
        out.write_bytes(b"%PDF-1.4 ocr-output\n")
        if kwargs.get("_result") is not None:
            kwargs["_result"]["preset_used"] = kwargs.get("preset") or "smallest"
        return out

    monkeypatch.setattr(_pipeline, "_compress", fake_compress)
    monkeypatch.setattr(_pipeline, "_run_ocr", fake_run_ocr)
    monkeypatch.setattr(_pipeline, "_pdfminer_text_extractable", lambda _p: True)
    return calls


def _make_input(tmp_path):
    inp = tmp_path / "in.pdf"
    inp.write_bytes(b"%PDF-1.4 fake input bytes for testing\n")
    return inp


def test_auto_with_text_layer_runs_compress_only(
    stub_pipeline_internals, monkeypatch, tmp_path
):
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="auto", preset="smallest")

    assert isinstance(result, ProcessResult)
    assert result.ocr_ran is False
    assert result.ocr_skipped_reason == "input_has_text_layer"
    assert [c[0] for c in stub_pipeline_internals] == ["compress"]


def test_auto_with_image_only_runs_ocr(stub_pipeline_internals, monkeypatch, tmp_path):
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: True)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="auto", preset="smallest")

    assert result.ocr_ran is True
    assert result.ocr_skipped_reason is None
    assert [c[0] for c in stub_pipeline_internals] == ["run_ocr"]
    # auto branch hardcodes force_ocr=True (see Phase 2 item 2 reasoning)
    assert stub_pipeline_internals[0][1]["force_ocr"] is True


def test_auto_force_ocr_skips_needs_ocr_check(
    stub_pipeline_internals, monkeypatch, tmp_path
):
    """force_ocr=True takes the OCR branch even when needs_ocr says False."""
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="auto", force_ocr=True)

    assert result.ocr_ran is True
    assert [c[0] for c in stub_pipeline_internals] == ["run_ocr"]


def test_mode_ocr_always_runs_ocr(stub_pipeline_internals, monkeypatch, tmp_path):
    """needs_ocr is irrelevant for explicit mode='ocr'."""
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="ocr", preset="balanced")

    assert result.ocr_ran is True
    assert result.ocr_skipped_reason is None
    assert [c[0] for c in stub_pipeline_internals] == ["run_ocr"]


def test_mode_ocr_passes_force_ocr_through(stub_pipeline_internals, tmp_path):
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    run_pipeline(inp, out, mode="ocr", force_ocr=False)

    assert stub_pipeline_internals[0][1]["force_ocr"] is False


def test_mode_compress_skips_ocr(stub_pipeline_internals, monkeypatch, tmp_path):
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: True)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="compress", preset="archival")

    assert result.ocr_ran is False
    assert result.ocr_skipped_reason == "compress_only_mode"
    assert [c[0] for c in stub_pipeline_internals] == ["compress"]


def test_preset_actually_used_reflects_underlying_choice(
    stub_pipeline_internals, monkeypatch, tmp_path
):
    """When the underlying compress() reports it shipped 'passthrough'
    (oversize fallback fired), ProcessResult.preset_actually_used follows.
    """

    def fake_compress(input_pdf, output_pdf, preset="balanced", *, _result=None):
        output_pdf.write_bytes(input_pdf.read_bytes())  # passthrough copy
        if _result is not None:
            _result["preset_used"] = "passthrough"
        return output_pdf

    monkeypatch.setattr(_pipeline, "_compress", fake_compress)
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)

    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"
    result = run_pipeline(inp, out, mode="auto", preset="archival")

    assert result.preset_actually_used == "passthrough"


def test_size_deltas_and_pct_change(stub_pipeline_internals, monkeypatch, tmp_path):
    """input_bytes / output_bytes / pct_change come from real stat() calls."""
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)
    inp = _make_input(tmp_path)
    expected_input_size = inp.stat().st_size
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="auto")

    assert result.input_bytes == expected_input_size
    assert result.output_bytes > 0
    assert result.output_bytes == out.stat().st_size
    expected_pct = (
        100.0 * (result.output_bytes - expected_input_size) / expected_input_size
    )
    assert result.pct_change == pytest.approx(expected_pct)


def test_to_dict_is_json_friendly(stub_pipeline_internals, monkeypatch, tmp_path):
    """API serialization needs str paths and primitive values."""
    import json

    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="auto")
    d = result.to_dict()

    assert isinstance(d["output_path"], str)
    json.dumps(d)  # raises if any field is not JSON-serializable


def test_one_line_summary_includes_key_fields(
    stub_pipeline_internals, monkeypatch, tmp_path
):
    monkeypatch.setattr(_pipeline, "needs_ocr", lambda _: False)
    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"

    result = run_pipeline(inp, out, mode="auto", preset="smallest")
    summary = result.one_line_summary()

    assert out.name in summary
    assert "smallest" in summary
    assert "compress" in summary  # operation label
    assert "text" in summary  # text-extractable status
