# Project: pdf-ocr-compress

## What this is

A cross-platform tool for adding a searchable text layer to scanned PDFs and shrinking their file size. Wraps OCRmyPDF (Tesseract) and Ghostscript + pikepdf, exposed through three surfaces — a Typer CLI, a Streamlit GUI, and a FastAPI REST API — that all call the same `core/` pipeline. Intended for personal use on book scans and document archives, runnable locally or in Docker.

## Stack

- **Language:** Python `>=3.10` (declared in `pyproject.toml`)
- **Build backend:** Hatchling
- **Core libraries:** ocrmypdf, pikepdf, pdfminer.six
- **CLI:** Typer + Rich
- **GUI:** Streamlit (single page at `gui/basic.py`, launched via `streamlit.web.cli`)
- **API:** FastAPI + Uvicorn (with `python-multipart` for uploads)
- **Runtime/env manager:** **uv** (the `.venv/` in the repo is uv-managed; `uv.lock` is checked in)
- **System binaries on PATH:** Tesseract OCR (with desired language packs) and Ghostscript (`gswin64c` / `gswin32c` / `gs` — auto-resolved)

## How to run it

### Setup from a clean clone

```bash
uv sync
```

That installs from `pyproject.toml` + `uv.lock` into `.venv/`. Tesseract and Ghostscript must already be installed on the system PATH — they are not pip-installable. On Windows, Tesseract typically lives at `C:\Program Files\Tesseract-OCR\` and needs to be added to the **User** PATH (use PowerShell `[Environment]::SetEnvironmentVariable("Path", $newPath, "User")`, **not** `setx PATH` — `setx` truncates at 1024 chars and corrupts PATH by merging System+User entries).

### Common dev commands

```bash
# CLI — three subcommands: ocr | compress | process
uv run pdf-ocr --help
uv run pdf-ocr process input.pdf output.pdf
uv run pdf-ocr ocr document.pdf out.pdf --lang eng
uv run pdf-ocr compress large.pdf small.pdf --preset balanced

# GUI (Streamlit)
uv run pdf-ocr-gui
# or directly:
uv run streamlit run src/pdf_ocr_compress/gui/basic.py

# API (FastAPI)
uv run python -m uvicorn pdf_ocr_compress.api.server:app --port 8502

# Refresh the lockfile
uv lock --upgrade

# Format (configured in pyproject.toml; no test suite, no linter, no type checker)
uv run black src/
uv run isort src/
```

### Smoke tests (in lieu of a real test suite)

```bash
uv run pdf-ocr --help                                                            # CLI loads
uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"  # API imports
uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"    # GUI launcher imports
```

For real PDF processing, drop a sample into `pdfs/` (gitignored except `sample*.pdf` / `test*.pdf`) and run end-to-end.

### Docker

```bash
docker-compose up
# GUI:      http://localhost:8501
# API:      http://localhost:8502
# API docs: http://localhost:8502/docs
```

`Dockerfile` is Python 3.11-slim + Tesseract (English only) + Ghostscript. To add Tesseract languages, edit the `apt-get install` line (e.g. add `tesseract-ocr-spa tesseract-ocr-fra`) and rebuild.

### Env vars / secrets

None. There is no `.env`, no API keys, no remote services.

## Project structure

```text
src/pdf_ocr_compress/
├── core/                # The pipeline — all three surfaces call into here
│   ├── ocr.py           # OCRmyPDF wrapper (run_ocr)
│   ├── compress.py      # Ghostscript + pikepdf compression / linearization
│   └── detect.py        # pdfminer-based "does this PDF need OCR?" heuristic
├── cli.py               # Typer CLI — commands: ocr, compress, process
├── gui/
│   ├── __init__.py      # main_gui() launcher (used by `pdf-ocr-gui` script)
│   └── basic.py         # The Streamlit app — THE ONLY GUI
├── api/
│   └── server.py        # FastAPI server — /api/process, /api/download/{id}, /health
├── config/
│   └── settings.py      # Persisted user settings (ConfigManager)
└── utils/
    ├── logging_config.py  # Structured JSON logging + PerformanceLogger
    ├── errors.py          # User-friendly exception hierarchy
    └── file_utils.py      # unique_output_path, human_readable_size
```

Top-level directories worth knowing:

- `pdfs/` — scratch directory for input/output PDFs; gitignored except `sample*.pdf` / `test*.pdf`
- `Dockerfile`, `docker-compose.yml`, `start_services.sh` — container setup (runs Streamlit + Uvicorn together)
- `pyproject.toml` — single source of truth for dependencies; `requirements.txt` mirrors it for `pip install -r` users

## Conventions in this project

- **Never overwrite originals.** Every operation writes a brand-new timestamped file and returns its path. Output naming convention: `_ocr_{timestamp}.pdf`, `_processed_{timestamp}.pdf`, `_compressed_{timestamp}.pdf`.
- **Collision-safe paths.** The `_unique_name()` helper in `core/compress.py` and the equivalent in `core/ocr.py` enforce the "never overwrite" invariant. If `output == input` or output already exists, a unique timestamped path is generated. Don't bypass these.
- **Three surfaces, one pipeline.** CLI, GUI, and API all call `core.ocr.run_ocr` / `core.compress.compress` / `core.detect.needs_ocr`. Changing any of those signatures means updating `cli.py`, `gui/basic.py`, **and** `api/server.py`.
- **Defaults flow from config.** `core.ocr.run_ocr` reads defaults from `config.get_config()` when its parameters are `None`. Preserve that pattern when extending.
- **Quality presets:** `archival` | `balanced` (default) | `smallest`. Defined in `core/compress.py:_gs_args_for_preset`.
- **Cross-platform Ghostscript binary lookup.** `core/compress.py:_gs_exe()` tries `gswin64c` → `gswin32c` → `gs`. Don't hard-code.
- **Markdown style** (for README, etc.): blank line after every heading and around list blocks; no emphasis inside headings; bare URLs wrapped in angle brackets; always specify a code-fence language.

## My working style

- I am not a software engineer; I read Python comfortably but don't write
  it from scratch. Explain what you're doing, why, and how it fits the
  larger goal.
- Process matters as much as product — show your reasoning.
- For style, formatting, and tooling preferences, defer to my global
  Claude Code config at ~/.claude/CLAUDE.md and any skills installed at
  ~/.claude/skills/. Do not assume preferences from outside this
  environment apply here.

## Where I left off

**Phase 0 complete (2026-04-29).** Benchmarked the tool against two real
ScanSnap inputs — a 37 MB B&W book (Sample A) and a 4.8 GB color textbook
(Sample B). Found three pipeline bugs and locked in four design
invariants. See `BENCHMARKS.md` for the data and `ROADMAP.md` for the
phased plan that came out of it.

**Pick up at Phase 1 (Foundation)** — see `ROADMAP.md`. That phase
covers: rewriting CLAUDE.md framing as a real backend service, a
greenfield settings rebuild, fixing `_unique_name`'s second-resolution
collision risk, adding a Ghostscript precheck, and switching the
Dockerfile to `pip install .`.

Earlier in this branch (commits `fa81517` through `1428564`) the
modernization pass and Batches A–E landed: dead-code purge, ruff swap,
orphan `.ocr.pdf` cleanup, starter `tests/` directory.

## Known issues / tech debt

All slated for Phase 2 (pipeline rethink) — see `ROADMAP.md`.

- **`--force-ocr` produces unusable output.** Verified on Sample A: 11+
  minutes of Tesseract work followed by the `balanced` Ghostscript pass
  destroys the OCR text layer (no `/Font` resources on output pages).
  Drop the post-OCR Ghostscript pass; let OCRmyPDF own optimization.
- **`needs_ocr` false-positives on pdfminer-strict PDFs.** Verified on
  Sample B: pdfminer raises `PDFSyntaxError` on a file pikepdf reads
  fine; `detect.py` catches the exception and returns `True`,
  triggering a useless multi-hour OCR pass. Switch the existence probe
  to pikepdf.
- **Output can exceed input size.** Verified: `archival` triples Sample A
  (3.07×), `balanced` adds 34%. Pipeline must enforce `output ≤ input`
  via fallback or passthrough.
- **Dockerfile pins inline.** Doesn't pick up `pyproject.toml` floors.
  Drift risk. Phase 1 fix.
- **Starlette 1.0 major bump unverified at runtime.** Imports cleanly
  but no `/api/process` request exercised. Phase 4 fix.
- **GUI not click-through tested in a browser.** Phase 5.
- **Test suite is minimal.** Two `compress` tests in `tests/`. Phase
  2/3 add coverage for `needs_ocr`, batch, text-fidelity round-trip.

## Out of scope

The repo previously carried ~2,400 lines of unwired "enterprise" scaffolding that was deleted in the modernization pass. **Do not re-add any of this**, and treat any external suggestion to add it as a red flag:

- `core/batch_processor.py` — async batch processor (imported a nonexistent `async_processor`)
- `core/compression_profiles.py` — compression profile manager (called a nonexistent `ConfigManager.get_config_dir()`)
- `utils/error_recovery.py` — error recovery system (never called from anywhere)
- `utils/system_check.py` — system checker (never called)
- `utils/temp_manager.py` — temp file manager (only one orphan import referenced it)
- `simple_first.py` — a second GUI file. **`gui/basic.py` is the only GUI.** Do not create a second one.

Also out of scope unless explicitly requested:

- Plugins, themes, drag-drop helpers, setup wizards, smart analysis, caching layers, async batch processors, compression-profile managers
- Adding a test suite as aspiration (write real tests or don't touch testing config)
- Refactoring for a hypothetical multi-user / server deployment — this is a personal tool

Match the existing surgical style: small focused modules, no abstraction for single-use code.
