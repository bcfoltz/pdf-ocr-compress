"""Smoke test for `pdf-ocr batch`. Mocks run_batch to keep it fast."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from pdf_ocr_compress.cli import app
from pdf_ocr_compress.core.batch import BatchReport


def _empty_report(in_dir: Path, out_dir: Path) -> BatchReport:
    return BatchReport(
        input_dir=in_dir,
        output_dir=out_dir,
        total_files=0,
        succeeded=0,
        failed=0,
        started_at="2026-04-29T10:00:00.000",
        finished_at="2026-04-29T10:00:00.000",
        total_seconds=0.0,
        total_input_bytes=0,
        total_output_bytes=0,
        results=[],
    )


def test_cli_batch_invokes_run_batch_with_defaults(tmp_path):
    in_dir = tmp_path / "in"
    in_dir.mkdir()

    runner = CliRunner()
    with patch("pdf_ocr_compress.cli.run_batch") as mock_run_batch:
        mock_run_batch.return_value = _empty_report(in_dir, in_dir / "processed")
        result = runner.invoke(app, ["batch", str(in_dir)])

    assert result.exit_code == 0, result.output
    mock_run_batch.assert_called_once()
    kwargs = mock_run_batch.call_args.kwargs
    args = mock_run_batch.call_args.args
    # First positional is input_dir, second is output_dir (default <in>/processed)
    assert Path(args[0]) == in_dir
    assert Path(args[1]) == in_dir / "processed"
    assert kwargs["mode"] == "auto"


def test_cli_batch_passes_explicit_options(tmp_path):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()

    runner = CliRunner()
    with patch("pdf_ocr_compress.cli.run_batch") as mock_run_batch:
        mock_run_batch.return_value = _empty_report(in_dir, out_dir)
        result = runner.invoke(
            app,
            [
                "batch",
                str(in_dir),
                "--output-dir",
                str(out_dir),
                "--mode",
                "compress",
                "--preset",
                "archival",
                "--lang",
                "eng+spa",
                "--jobs",
                "8",
                "--pdfa",
                "--force-ocr",
            ],
        )

    assert result.exit_code == 0, result.output
    kwargs = mock_run_batch.call_args.kwargs
    args = mock_run_batch.call_args.args
    assert Path(args[0]) == in_dir
    assert Path(args[1]) == out_dir
    assert kwargs["mode"] == "compress"
    assert kwargs["preset"] == "archival"
    assert kwargs["lang"] == "eng+spa"
    assert kwargs["jobs"] == 8
    assert kwargs["pdfa"] is True
    assert kwargs["force_ocr"] is True


def test_cli_batch_prints_summary_and_report_path(tmp_path):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()

    runner = CliRunner()
    with patch("pdf_ocr_compress.cli.run_batch") as mock_run_batch:
        mock_run_batch.return_value = _empty_report(in_dir, out_dir)
        result = runner.invoke(
            app, ["batch", str(in_dir), "--output-dir", str(out_dir)]
        )

    assert result.exit_code == 0
    assert "0 ok, 0 failed" in result.output
    assert "batch_report.json" in result.output
