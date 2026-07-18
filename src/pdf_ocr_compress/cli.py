"""CLI interface for PDF OCR + Compression Tool."""

import os
from dataclasses import fields as dc_fields
from pathlib import Path

import typer

from .config import get_config
from .config.settings import AppSettings, ConfigManager
from .core.batch import run_batch
from .core.pipeline import run_pipeline
from .utils.errors import PDFProcessingError
from .utils.logging_config import setup_logging

app = typer.Typer(
    no_args_is_help=True,
    help="OCR + compress SCANNED PDFs (cross-platform) — Designed for scanned documents, not native digital PDFs",
)

config_app = typer.Typer(
    no_args_is_help=True,
    help="View or change the persisted defaults (settings.json).",
)
app.add_typer(config_app, name="config")


@app.command()
def ocr(
    input_pdf: Path,
    output_pdf: Path,
    lang: str = typer.Option(None, help="OCR language(s). Default from settings."),
    preset: str = typer.Option(
        None, help="archival | balanced | smallest. Default from settings."
    ),
    pdfa: bool = False,
    jobs: int = typer.Option(None, help="OCR parallelism. Default from settings."),
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
    preset: str = typer.Option(
        None, help="archival | balanced | smallest. Default from settings."
    ),
):
    """Compress & linearize; writes a brand-new file."""
    result = run_pipeline(input_pdf, output_pdf, mode="compress", preset=preset)
    typer.echo(result.one_line_summary())


@app.command()
def process(
    input_pdf: Path,
    output_pdf: Path,
    lang: str = typer.Option(None, help="OCR language(s). Default from settings."),
    preset: str = typer.Option(
        None, help="archival | balanced | smallest. Default from settings."
    ),
    pdfa: bool = False,
    jobs: int = typer.Option(None, help="OCR parallelism. Default from settings."),
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
    force: bool = typer.Option(
        False,
        "--force",
        help="Reprocess inputs whose outputs already exist (default: skip them).",
    ),
):
    """Process every *.pdf in INPUT_DIR; write results + batch_report.json to --output-dir.

    Incremental by default: inputs whose same-name output already exists in
    the output dir are skipped, so re-runs over a growing folder only touch
    new files (--force reprocesses everything). Failures are retried once
    immediately and once at end of batch (max 3 attempts per file). One bad
    PDF doesn't kill the rest of the batch.
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
        force=force,
    )

    # Per-file lines
    for r in report.results:
        if r.status == "ok" and r.process_result is not None:
            typer.echo(r.process_result.one_line_summary())
        elif r.status == "skipped":
            typer.echo(
                f"{r.input_path.name}: skipped (output exists; use --force to redo)"
            )
        else:
            typer.echo(
                f"{r.input_path.name}: FAILED after {r.attempts} attempts: {r.error_msg}"
            )

    # Batch summary
    typer.echo("")
    typer.echo(f"Batch summary: {report.one_line_summary()}")
    typer.echo(f"Report: {effective_output_dir / 'batch_report.json'}")


# Settings whose values are restricted to a fixed choice set.
_CONFIG_CHOICES = {
    "default_preset": ("archival", "balanced", "smallest"),
    "oversize_policy": ("fallback", "warn", "fail"),
}


def _env_var_for(field_name: str) -> str:
    """PDF_OCR_* env var for a settings field (apply_env_overrides convention)."""
    return f"PDF_OCR_{field_name.upper()}"


@config_app.command("show")
def config_show():
    """Print persisted settings, the file location, and env overrides in effect."""
    # Fresh manager: file-backed values only. get_config() would show
    # env-overridden values without saying so.
    manager = ConfigManager()
    s = manager.settings
    typer.echo(f"Settings file: {manager.config_file}")
    for f in dc_fields(AppSettings):
        typer.echo(f"  {f.name} = {getattr(s, f.name)}")
    overrides = [
        (env, val)
        for f in dc_fields(AppSettings)
        if (val := os.getenv(env := _env_var_for(f.name)))
    ]
    if overrides:
        typer.echo("Environment overrides in effect (per-session, not persisted):")
        for env, val in overrides:
            typer.echo(f"  {env} = {val}")


@config_app.command("set")
def config_set(key: str, value: str):
    """Set one setting and persist it (e.g. `pdf-ocr config set default_preset smallest`)."""
    valid = {f.name: f for f in dc_fields(AppSettings)}
    if key not in valid:
        typer.echo(f"Unknown setting {key!r}. Valid keys: {', '.join(valid)}", err=True)
        raise typer.Exit(code=2)
    if key in _CONFIG_CHOICES and value not in _CONFIG_CHOICES[key]:
        typer.echo(f"{key} must be one of: {', '.join(_CONFIG_CHOICES[key])}", err=True)
        raise typer.Exit(code=2)

    coerced: object = value
    if valid[key].type is int:
        try:
            coerced = int(value)
        except ValueError:
            typer.echo(f"{key} must be an integer, got {value!r}", err=True)
            raise typer.Exit(code=2) from None
    elif key == "default_output_dir":
        coerced = Path(value).expanduser() if value.strip() else None

    # Fresh manager so PDF_OCR_* env overrides (applied to the get_config()
    # singleton) are never baked into the persisted file.
    manager = ConfigManager()
    settings = manager.settings
    setattr(settings, key, coerced)
    manager.save_settings(settings)
    typer.echo(f"{key} = {coerced} (saved to {manager.config_file})")


def main():
    """Entry point for the CLI application.

    Domain errors (missing system tools, corrupt PDFs, oversize-policy
    failures) render their user_message + suggestions instead of a
    traceback; anything unexpected still tracebacks for bug reports.
    """
    # Attach a console handler so pipeline INFO messages (notably the
    # oversize-fallback audit trail in core/oversize.py) are visible;
    # without this, only WARNING+ escapes via Python's last-resort handler.
    setup_logging(structured_logging=False)
    try:
        app()
    except PDFProcessingError as exc:
        typer.echo(exc.user_message, err=True)
        for suggestion in exc.suggestions:
            typer.echo(f"- {suggestion}", err=True)
        if exc.error_code:
            typer.echo(f"Error code: {exc.error_code}", err=True)
        # typer.Exit only works inside app(); out here SystemExit is the
        # clean way to set the exit code without a traceback.
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
