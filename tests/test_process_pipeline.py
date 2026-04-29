"""Tests for the process pipeline routing.

Phase 2 / Design rule #3: never run a Ghostscript pass on OCRmyPDF output.
The post-OCR pdfwrite step strips the /Font resources OCRmyPDF just wrote,
silently destroying the text layer. OCRmyPDF gets `--optimize N` matching
the requested preset and owns optimization end-to-end on the OCR branch.
"""

from pathlib import Path

import pytest

from pdf_ocr_compress import cli as cli_mod


@pytest.fixture
def stub_pipeline(monkeypatch, tmp_path):
    """Replace run_ocr / do_compress / needs_ocr with call-recording stubs."""
    calls: list[tuple[str, dict]] = []

    def fake_run_ocr(**kwargs):
        calls.append(("run_ocr", kwargs))
        out = kwargs["output_pdf"]
        out.write_bytes(b"%PDF-1.4 ocr-output\n")
        return out

    def fake_compress(input_pdf: Path, output_pdf: Path, preset: str = "balanced"):
        calls.append(
            (
                "compress",
                {"input_pdf": input_pdf, "output_pdf": output_pdf, "preset": preset},
            )
        )
        output_pdf.write_bytes(b"%PDF-1.4 compress-output\n")
        return output_pdf

    monkeypatch.setattr(cli_mod, "run_ocr", fake_run_ocr)
    monkeypatch.setattr(cli_mod, "do_compress", fake_compress)
    return calls


def _make_input(tmp_path: Path) -> Path:
    inp = tmp_path / "in.pdf"
    inp.write_bytes(b"%PDF-1.4 input\n")
    return inp


def test_process_ocr_branch_does_not_compress(stub_pipeline, monkeypatch, tmp_path):
    """When OCR runs, no Ghostscript compress pass should follow.

    Bug fix proof: pre-fix, process called do_compress on run_ocr's output,
    which stripped the /Font resources OCRmyPDF wrote. Now run_ocr writes
    directly to the final path with --optimize matching the preset.
    """
    monkeypatch.setattr(cli_mod, "needs_ocr", lambda _: True)

    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"
    cli_mod.process(inp, out, preset="smallest")

    op_names = [c[0] for c in stub_pipeline]
    assert op_names == ["run_ocr"], f"Expected only run_ocr; got {op_names}"


def test_process_ocr_branch_targets_final_output(stub_pipeline, monkeypatch, tmp_path):
    """OCR branch must write directly to the user's chosen output path,
    not to an intermediate '<stem>.ocr.pdf' file.
    """
    monkeypatch.setattr(cli_mod, "needs_ocr", lambda _: True)

    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"
    cli_mod.process(inp, out)

    ocr_call = stub_pipeline[0]
    assert ocr_call[0] == "run_ocr"
    assert ocr_call[1]["output_pdf"] == out


def test_process_no_ocr_branch_only_compresses(stub_pipeline, monkeypatch, tmp_path):
    """When the PDF already has text, only the compress path runs."""
    monkeypatch.setattr(cli_mod, "needs_ocr", lambda _: False)

    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"
    cli_mod.process(inp, out)

    op_names = [c[0] for c in stub_pipeline]
    assert op_names == ["compress"], f"Expected only compress; got {op_names}"


def test_process_ocr_passes_preset_through(stub_pipeline, monkeypatch, tmp_path):
    """The user-requested preset must reach run_ocr unchanged so OCRmyPDF
    can pick the right --optimize level (archival=0, balanced=2, smallest=3).
    """
    monkeypatch.setattr(cli_mod, "needs_ocr", lambda _: True)

    inp = _make_input(tmp_path)
    out = tmp_path / "out.pdf"
    cli_mod.process(inp, out, preset="archival")

    assert stub_pipeline[0][1]["preset"] == "archival"
