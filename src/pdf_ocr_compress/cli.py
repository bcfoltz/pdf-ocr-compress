"""CLI interface for PDF OCR + Compression Tool."""

from pathlib import Path

import typer

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


def main():
    """Entry point for the CLI application."""
    app()


if __name__ == "__main__":
    main()
