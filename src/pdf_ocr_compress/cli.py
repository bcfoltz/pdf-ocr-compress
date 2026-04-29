"""CLI interface for PDF OCR + Compression Tool."""

from pathlib import Path

import typer

from .config import get_config
from .core.batch import run_batch
from .core.pipeline import run_pipeline

app = typer.Typer(
    no_args_is_help=True,
    help="OCR + compress SCANNED PDFs (cross-platform) — Designed for scanned documents, not native digital PDFs",
)


@app.command()
def ocr(
    input_pdf: Path,
    output_pdf: Path,
    lang: str = "eng",
    preset: str = typer.Option("balanced", help="archival | balanced | smallest"),
    pdfa: bool = False,
    jobs: int = 1,
    force_ocr: bool = False,
):
    """Add a searchable text layer to scanned pages; writes a brand-new file."""
    result = run_pipeline(
        input_pdf,
        output_pdf,
        mode="ocr",
        lang=lang,
        preset=preset,
        pdfa=pdfa,
        jobs=jobs,
        force_ocr=force_ocr,
    )
    typer.echo(result.one_line_summary())


@app.command()
def compress(
    input_pdf: Path,
    output_pdf: Path,
    preset: str = typer.Option("balanced", help="archival | balanced | smallest"),
):
    """Compress & linearize; writes a brand-new file."""
    result = run_pipeline(input_pdf, output_pdf, mode="compress", preset=preset)
    typer.echo(result.one_line_summary())


@app.command()
def process(
    input_pdf: Path,
    output_pdf: Path,
    lang: str = "eng",
    preset: str = typer.Option("balanced", help="archival | balanced | smallest"),
    pdfa: bool = False,
    jobs: int = 1,
    force_ocr: bool = False,
):
    """
    Auto pipeline for scanned documents:
    - Detects if PDF pages need OCR (no searchable text)
    - Runs OCR on scanned pages with OCRmyPDF's --optimize matching preset
    - Skips OCR if text already exists (unless --force-ocr)
    - Optimized for scanned/image-based PDFs
    """
    result = run_pipeline(
        input_pdf,
        output_pdf,
        mode="auto",
        lang=lang,
        preset=preset,
        pdfa=pdfa,
        jobs=jobs,
        force_ocr=force_ocr,
    )
    typer.echo(result.one_line_summary())


@app.command()
def batch(
    input_dir: Path,
    output_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--output-dir",
        help="Where to write processed PDFs. Default: <input_dir>/processed.",
    ),
    mode: str = typer.Option(
        "auto", help="Per-file pipeline mode: auto | ocr | compress"
    ),
    preset: str = typer.Option(
        None, help="archival | balanced | smallest. Default from settings."
    ),
    lang: str = typer.Option(
        None, "--lang", help="OCR language(s). Default from settings."
    ),
    jobs: int = typer.Option(
        None, help="Per-file OCR parallelism. Default from settings."
    ),
    pdfa: bool = typer.Option(False, help="Produce PDF/A-2 output for OCR'd files."),
    force_ocr: bool = typer.Option(
        False, "--force-ocr", help="Force OCR on every file regardless of needs_ocr()."
    ),
):
    """Process every *.pdf in INPUT_DIR; write results + batch_report.json to --output-dir.

    Failures are retried once immediately and once at end of batch (max 3 attempts
    per file). One bad PDF doesn't kill the rest of the batch.
    """
    settings = get_config().settings
    effective_preset = preset if preset is not None else settings.default_preset
    effective_lang = lang if lang is not None else settings.default_language
    effective_jobs = jobs if jobs is not None else settings.default_jobs
    effective_output_dir = (
        output_dir if output_dir is not None else input_dir / "processed"
    )

    typer.echo(f"Batch: {input_dir} -> {effective_output_dir}")
    report = run_batch(
        input_dir,
        effective_output_dir,
        mode=mode,  # type: ignore[arg-type]
        preset=effective_preset,
        lang=effective_lang,
        jobs=effective_jobs,
        pdfa=pdfa,
        force_ocr=force_ocr,
    )

    # Per-file lines
    for r in report.results:
        if r.status == "ok" and r.process_result is not None:
            typer.echo(r.process_result.one_line_summary())
        else:
            typer.echo(
                f"{r.input_path.name}: FAILED after {r.attempts} attempts: {r.error_msg}"
            )

    # Batch summary
    typer.echo("")
    typer.echo(f"Batch summary: {report.one_line_summary()}")
    typer.echo(f"Report: {effective_output_dir / 'batch_report.json'}")


def main():
    """Entry point for the CLI application."""
    app()


if __name__ == "__main__":
    main()
