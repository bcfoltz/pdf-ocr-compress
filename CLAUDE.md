# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

A cross-platform PDF OCR and compression tool for **scanned PDFs**. Wraps OCRmyPDF (Tesseract) and Ghostscript + pikepdf, exposed through three surfaces that share the same core pipeline:

- **CLI** — `pdf-ocr` (Typer)
- **Streamlit GUI** — `pdf-ocr-gui` or `streamlit run src/pdf_ocr_compress/gui/basic.py`
- **FastAPI REST API** — `uvicorn pdf_ocr_compress.api.server:app --port 8502`

## Architecture

```text
src/pdf_ocr_compress/
├── core/                    # The pipeline
│   ├── ocr.py              # OCRmyPDF wrapper
│   ├── compress.py         # Ghostscript + pikepdf compression / linearization
│   └── detect.py           # pdfminer-based "does this PDF need OCR?" heuristic
├── cli.py                  # Typer CLI (commands: ocr, compress, process)
├── gui/
│   ├── __init__.py         # `main_gui()` launcher for the `pdf-ocr-gui` console script
│   └── basic.py            # The Streamlit app (THE ONLY GUI)
├── api/
│   └── server.py           # FastAPI server (endpoints: /api/process, /api/download/{id}, /health)
├── config/
│   └── settings.py         # Persisted user settings (ConfigManager)
└── utils/
    ├── logging_config.py   # Structured JSON logging + PerformanceLogger
    ├── errors.py           # User-friendly exception hierarchy
    └── file_utils.py       # unique_output_path, human_readable_size
```

## Core Design Rules

- **Never overwrite originals.** Every operation writes a brand-new timestamped file and returns its path.
- **No in-place modifications.** If output==input or output exists, generate a new unique path.
- **Cross-platform.** Windows / macOS / Linux all supported; Ghostscript binary name resolves to `gswin64c` / `gswin32c` / `gs` automatically.

## Environment

This project uses **uv** (not conda). The `.venv/` directory in the repo is uv-managed.

```bash
# Install / sync deps from pyproject.toml + uv.lock
uv sync

# Run any command in the project venv
uv run pdf-ocr --help
uv run streamlit run src/pdf_ocr_compress/gui/basic.py
uv run python -m uvicorn pdf_ocr_compress.api.server:app --port 8502

# Bump the lockfile to latest compatible versions
uv lock --upgrade
```

System tools (must be on PATH):
- **Tesseract OCR** (with desired language packs)
- **Ghostscript**

## Common Commands

### Docker (recommended for end users)

```bash
docker-compose up
# GUI:      http://localhost:8501
# API:      http://localhost:8502
# API docs: http://localhost:8502/docs
```

### CLI

```bash
# Auto pipeline: OCR-if-needed, then compress
uv run pdf-ocr process input.pdf output.pdf

# OCR only
uv run pdf-ocr ocr document.pdf out.pdf --lang eng

# Compress only
uv run pdf-ocr compress large.pdf small.pdf --preset balanced
```

Quality presets: `archival` | `balanced` (default) | `smallest`.

## File Naming Conventions

Outputs are timestamped to prevent overwrites:
- `_ocr_{timestamp}.pdf` — OCR-only
- `_processed_{timestamp}.pdf` — Auto pipeline
- `_compressed_{timestamp}.pdf` — Compression-only

## Working in this Repo

### Keep It Simple

This codebase was previously bloated with abandoned "enterprise" scaffolding (batch processors, profile managers, error-recovery systems, system checkers) that was never wired up and broke import. **Do not re-add any of that.** Specifically:

- **DO NOT** create `simple_first.py` or any new GUI files. `gui/basic.py` is the only GUI.
- **DO NOT** add plugins, themes, drag-drop helpers, setup wizards, smart analysis, caching layers, async batch processors, or compression-profile managers.
- **DO NOT** add tests-as-aspiration. Either write real tests in a `tests/` folder, or don't touch testing config.
- Match the existing surgical style — small focused modules, no abstraction for single-use code.

### When Editing the Core Pipeline

- All three surfaces (CLI, GUI, API) call into `core.ocr.run_ocr` / `core.compress.compress` / `core.detect.needs_ocr`. Changing any of those signatures means updating `cli.py`, `gui/basic.py`, AND `api/server.py`.
- `core.ocr.run_ocr` reads defaults from `config.get_config()` when its parameters are `None` — preserve that pattern if extending.
- The `_unique_output()` / `_unique_name()` helpers in `core/ocr.py` and `core/compress.py` enforce the "never overwrite" invariant — don't bypass them.

### Smoke-Testing Changes

There is no test suite. Before claiming a change works, manually verify all three surfaces:

```bash
uv run pdf-ocr --help                                                            # CLI loads
uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"  # API imports
uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"    # GUI launcher imports
```

For real PDF processing, drop a sample into `pdfs/` (gitignored except `sample*.pdf` / `test*.pdf`) and run end-to-end.

## Docker

- `Dockerfile` — Python 3.11-slim base + Tesseract (English only) + Ghostscript
- `docker-compose.yml` — wires GUI:8501 and API:8502, mounts `./pdfs:/pdfs`, sets resource limits (2 CPU / 2 GB RAM)
- `start_services.sh` — launches both Streamlit and Uvicorn in the container

To add Tesseract languages, edit the `apt-get install` line in `Dockerfile` (e.g. add `tesseract-ocr-spa tesseract-ocr-fra`) and rebuild with `docker-compose up --build`.

## Markdown Style (for README.md, API_EXAMPLES.md, etc.)

- Blank line after every heading, after every closing code fence, and around list blocks
- No emphasis (`**` / `*`) inside headings — the heading is already emphasized
- Wrap bare URLs in angle brackets: `<http://example.com>`
- Always specify a code-fence language (`bash`, `python`, `text`, `yaml`, `json`)
