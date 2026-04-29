"""CLI interface for PDF OCR + Compression Tool."""

from pathlib import Path

import typer

from .core.compress import compress as do_compress
from .core.detect import needs_ocr
from .core.ocr import run_ocr

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
    out = run_ocr(
        input_pdf=input_pdf,
        output_pdf=output_pdf,
        lang=lang,
        preset=preset,
        pdfa=pdfa,
        jobs=jobs,
        force_ocr=force_ocr,
    )
    typer.echo(f"Output: {out}")


@app.command()
def compress(
    input_pdf: Path,
    output_pdf: Path,
    preset: str = typer.Option("balanced", help="archival | balanced | smallest"),
):
    """Compress & linearize; writes a brand-new file."""
    out = do_compress(input_pdf, output_pdf, preset=preset)
    typer.echo(f"Output: {out}")


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
    - Runs OCR on scanned pages, then compresses
    - Skips OCR if text already exists (unless --force-ocr)
    - Optimized for scanned/image-based PDFs
    """
    if force_ocr or needs_ocr(input_pdf):
        # OCRmyPDF owns optimization on this branch via --optimize N matching
        # the requested preset (archival=0, balanced=2, smallest=3). A second
        # Ghostscript pass would strip the /Font resources OCRmyPDF just
        # wrote, silently destroying the text layer (Phase 0 finding,
        # codified as Design rule #3).
        final_out = run_ocr(
            input_pdf=input_pdf,
            output_pdf=output_pdf,
            lang=lang,
            preset=preset,
            pdfa=pdfa,
            jobs=jobs,
            force_ocr=True,
        )
    else:
        final_out = do_compress(input_pdf, output_pdf, preset=preset)
    typer.echo(f"Output: {final_out}")


def main():
    """Entry point for the CLI application."""
    app()


if __name__ == "__main__":
    main()
