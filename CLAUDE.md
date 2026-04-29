# Project: pdf-ocr-compress

## What this is

A backend service for turning scanned PDFs into clean, searchable, RAG-ready files at scale. Wraps OCRmyPDF (Tesseract) and Ghostscript + pikepdf around a single `core/` pipeline, then exposes that pipeline through three first-class clients:

- **CLI** (Typer) — interactive use, scripting, cron jobs.
- **GUI** (Streamlit, single page) — drop-a-file diagnostics for one-off inputs.
- **REST API** (FastAPI) — the load-bearing surface, called from other apps in the user's workflow to ingest a large folder of scanned books at /path/to/folder into LLM/RAG pipelines.

Inputs are real-world scans from a ScanSnap (B&W books, color textbooks up to ~5 GB), not toy PDFs. Runs locally or in Docker. No remote services, no auth, no telemetry.

## Design rules

These are non-negotiable. They came from real benchmarks in Phase 0 (see `BENCHMARKS.md`); breaking any of them silently wastes hours of compute or destroys output integrity.

1. **Output ≤ input size, always.** No pipeline branch may produce a file larger than its input. If the requested preset would grow the file, fall back to a working preset, or to a passthrough copy if even `smallest` grows it. Behavior is governed by the `oversize_policy` setting (`fallback` / `warn` / `fail`); `fallback` is the default.
2. **`needs_ocr` must use a tolerant parser.** pikepdf, not pdfminer. pdfminer false-positives on real ScanSnap output and triggers multi-hour OCR passes that produce no value. (Phase 2 fix; tracked under "Known issues".)
3. **Never run a Ghostscript pass on OCRmyPDF output.** The post-OCR `pdfwrite` rebuild strips the `/Font` resources OCRmyPDF just wrote. Let OCRmyPDF own optimization via `--optimize 0/2/3` keyed off the requested preset. (Phase 2 fix; tracked under "Known issues".)
4. **`smallest` is the default preset.** It's the only preset that consistently shrinks ScanSnap-family input across sizes and color depths (Sample A: -17%, Sample B: -95.9%). `archival` triples Sample A; `balanced` adds 34%.

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

# Format + lint
uv run black src/
uv run ruff check src/

# Tests
uv run pytest
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
│   └── settings.py      # Single flat AppSettings dataclass + ConfigManager
└── utils/
    ├── logging_config.py  # Structured JSON logging + PerformanceLogger
    ├── errors.py          # User-friendly exception hierarchy
    └── file_utils.py      # unique_output_path (microsecond-stamped, shared by ocr+compress), human_readable_size
```

Top-level directories worth knowing:

- `pdfs/` — scratch directory for input/output PDFs; gitignored except `sample*.pdf` / `test*.pdf`
- `Dockerfile`, `docker-compose.yml`, `start_services.sh` — container setup (runs Streamlit + Uvicorn together)
- `pyproject.toml` — single source of truth for dependencies; `requirements.txt` mirrors it for `pip install -r` users

## Conventions in this project

- **Never overwrite originals.** Every operation writes a brand-new timestamped file and returns its path. Output naming convention: `_ocr_{timestamp}.pdf`, `_processed_{timestamp}.pdf`, `_compressed_{timestamp}.pdf`.
- **Collision-safe paths.** `utils.file_utils.unique_output_path` is the single source of truth — microsecond-resolution timestamp plus integer counter fallback. Both `core/compress.py` and `core/ocr.py` import it. Don't reintroduce per-module copies.
- **Three surfaces, one pipeline.** CLI, GUI, and API all call `core.ocr.run_ocr` / `core.compress.compress` / `core.detect.needs_ocr`. Changing any of those signatures means updating `cli.py`, `gui/basic.py`, **and** `api/server.py`.
- **Defaults flow from config.** `core.ocr.run_ocr` reads defaults from `config.get_config().settings` when its parameters are `None`. Preserve that pattern when extending. (CLI/GUI/API still hardcode their own defaults — wiring them into settings is Phase 5.)
- **Quality presets:** `archival` | `balanced` | `smallest` (default). Defined in `core/compress.py:_gs_args_for_preset`.
- **Cross-platform Ghostscript binary lookup.** `core/compress.py:_gs_exe()` tries `gswin64c` → `gswin32c` → `gs` and raises `SystemToolError("ghostscript", ...)` if none are found. Don't hard-code, and don't catch the precheck error to silently substitute a default.
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

**Phase 1 complete (2026-04-29).** Foundation is in place:

- Settings rebuilt as a single flat `AppSettings` dataclass with
  `default_preset="smallest"`, `oversize_policy="fallback"`, and an
  env-var override for each field. Old `UISettings` / `SystemSettings`
  / `temp_settings()` deleted.
- `_unique_name` collision bug fixed by consolidating three near-
  duplicate helpers into `utils.file_utils.unique_output_path` (now
  microsecond-stamped). `core/compress.py` and `core/ocr.py` both
  import it.
- `_gs_exe()` raises `SystemToolError("ghostscript", ...)` when no
  Ghostscript binary is on PATH, instead of returning `"gswin64c"`
  and letting subprocess fail with a cryptic `[WinError 2]`.
- Dockerfile now does `pip install .` so the image picks up
  `pyproject.toml` floors instead of drifting against inline pins.

**Pick up at Phase 2 (Pipeline rethink)** — see `ROADMAP.md`. That
phase fixes the three confirmed Phase 0 bugs: rewrite `needs_ocr`
on pikepdf, drop the post-OCR Ghostscript pass, and enforce the
size invariant.

Earlier on this branch: Phase 0 benchmarks (`BENCHMARKS.md`,
commit `1cc420e`); modernization Batches A–E (`fa81517`..`1428564`).

## Known issues / tech debt

All slated for Phase 2 (pipeline rethink) — see `ROADMAP.md`.

- **`--force-ocr` produces unusable output.** Verified on Sample A: 11+
  minutes of Tesseract work followed by the `balanced` Ghostscript pass
  destroys the OCR text layer (no `/Font` resources on output pages).
  Drop the post-OCR Ghostscript pass; let OCRmyPDF own optimization.
  Codified as Design rule #3.
- **`needs_ocr` false-positives on pdfminer-strict PDFs.** Verified on
  Sample B: pdfminer raises `PDFSyntaxError` on a file pikepdf reads
  fine; `detect.py` catches the exception and returns `True`,
  triggering a useless multi-hour OCR pass. Switch the existence probe
  to pikepdf. Codified as Design rule #2.
- **Output can exceed input size.** Verified: `archival` triples Sample A
  (3.07×), `balanced` adds 34%. The settings model now carries
  `oversize_policy` but the pipeline does not yet honor it. Codified
  as Design rule #1.
- **Starlette 1.0 major bump unverified at runtime.** Imports cleanly
  but no `/api/process` request exercised. Phase 4 fix.
- **GUI not click-through tested in a browser.** Phase 5.
- **CLI/GUI/API hardcode their own defaults.** They don't yet read from
  `config.get_config()`. Phase 5 wires them in (settings UI, default
  output dir, oversize-policy surface).
- **Test suite is minimal.** Phase 2/3 add coverage for `needs_ocr`,
  batch, text-fidelity round-trip.

## Out of scope

The repo previously carried ~2,400 lines of unwired "enterprise"
scaffolding that was deleted in the modernization pass. The lesson
isn't "don't add features" — folder batching, a real settings system,
and persistent API state are all in scope (Phases 3–5). The lesson is
**don't add bad implementations of those features**.

Specifically, do not re-add:

- `core/batch_processor.py` — async batch processor that imported a
  nonexistent `async_processor` module. The Phase 3 batch should be
  synchronous, sequential by default, with a single-counter retry
  ladder. No asyncio, no thread pools.
- `core/compression_profiles.py` — abstract compression-profile
  manager that called a nonexistent `ConfigManager.get_config_dir()`.
  Three named presets in a function are enough; don't introduce a
  manager class for static data.
- `utils/error_recovery.py`, `utils/system_check.py`,
  `utils/temp_manager.py` — never-called scaffolding around standard
  library functionality.
- `simple_first.py` — a second GUI file. **`gui/basic.py` is the only
  GUI.** Do not create a second one.

Genuinely out of scope unless explicitly requested:

- Plugins, themes, drag-and-drop helpers, setup wizards, "smart
  analysis" features, in-process caching layers.
- Multi-user / multi-tenant API features — auth, rate limiting,
  per-user storage. Single-user single-machine assumption.
- Async / threadpool work in the pipeline. The bottleneck is
  Tesseract; OCRmyPDF already parallelizes via `--jobs`. Don't add
  another layer.
- Adding tests as aspiration ("test framework setup PR" with no real
  tests). Either write real tests or don't touch testing config.

Match the existing surgical style: small focused modules, no
abstraction for single-use code, explicit over clever.
