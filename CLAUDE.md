# Project: pdf-ocr-compress

## What this is

A backend service for turning scanned PDFs into clean, searchable, RAG-ready files at scale. Wraps OCRmyPDF (Tesseract) and Ghostscript + pikepdf around a single `core/` pipeline, then exposes that pipeline through three first-class clients:

- **CLI** (Typer) — interactive use, scripting, cron jobs.
- **GUI** (Streamlit, single page) — drop-a-file diagnostics for one-off inputs.
- **REST API** (FastAPI) — the load-bearing surface, intended to be called from other apps that ingest large folders of scanned books into LLM/RAG pipelines.

Designed for real-world scanner output (B&W book scans through multi-GB color textbook scans), not toy PDFs. Runs natively on Windows / macOS / Linux. No remote services, no auth, no telemetry.

## Design rules

These are non-negotiable. They came from real benchmarks in Phase 0 (see `BENCHMARKS.md`); breaking any of them silently wastes hours of compute or destroys output integrity.

1. **Output ≤ input size, always.** No pipeline branch may produce a file larger than its input. If the requested preset would grow the file, fall back to a working preset, or to a passthrough copy if even `smallest` grows it. Behavior is governed by the `oversize_policy` setting (`fallback` / `warn` / `fail`); `fallback` is the default.
2. **`needs_ocr` must use a tolerant parser.** pikepdf, not pdfminer. pdfminer false-positives on real scanner output and triggers multi-hour OCR passes that produce no value. (Phase 2 fix; tracked under "Known issues".)
3. **Never run a Ghostscript pass on OCRmyPDF output.** The post-OCR `pdfwrite` rebuild strips the `/Font` resources OCRmyPDF just wrote. Let OCRmyPDF own optimization via `--optimize 0/2/3` keyed off the requested preset. (Phase 2 fix; tracked under "Known issues".)
4. **`smallest` is the default preset.** It's the only preset that consistently shrinks already-OCR'd scanner output across sizes and color depths (Sample A: -17%, Sample B: -95.9% — see `BENCHMARKS.md`). `archival` and `balanced` both grow the file on Sample A.

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

### Env vars / secrets

None. There is no `.env`, no API keys, no remote services.

## Project structure

```text
src/pdf_ocr_compress/
├── core/                # The pipeline — all three surfaces call into here
│   ├── pipeline.py      # run_pipeline(input, output, *, mode, ...) -> ProcessResult
│   ├── ocr.py           # OCRmyPDF wrapper (run_ocr); applies oversize guard
│   ├── compress.py      # Ghostscript + pikepdf compression; applies oversize guard
│   ├── detect.py        # pikepdf-based "does this PDF need OCR?" heuristic
│   └── oversize.py      # enforce_oversize_policy — the size-invariant guard
├── cli.py               # Typer CLI — commands: ocr, compress, process (all -> run_pipeline)
├── gui/
│   ├── __init__.py      # main_gui() launcher (used by `pdf-ocr-gui` script)
│   └── basic.py         # The Streamlit app — THE ONLY GUI (calls run_pipeline)
├── api/
│   └── server.py        # FastAPI server — /api/process (calls run_pipeline), /api/download/{id}, /health
├── config/
│   └── settings.py      # Single flat AppSettings dataclass + ConfigManager
└── utils/
    ├── logging_config.py  # Structured JSON logging + PerformanceLogger
    ├── errors.py          # User-friendly exception hierarchy
    └── file_utils.py      # unique_output_path (microsecond-stamped, shared by ocr+compress), human_readable_size
```

Top-level directories worth knowing:

- `pdfs/` — scratch directory for input/output PDFs; gitignored except `sample*.pdf` / `test*.pdf`
- `pyproject.toml` — single source of truth for dependencies; `requirements.txt` mirrors it for `pip install -r` users

## Conventions in this project

- **Never overwrite originals.** Every operation writes a brand-new timestamped file and returns its path. Output naming convention: `_ocr_{timestamp}.pdf`, `_processed_{timestamp}.pdf`, `_compressed_{timestamp}.pdf`.
- **Collision-safe paths.** `utils.file_utils.unique_output_path` is the single source of truth — microsecond-resolution timestamp plus integer counter fallback. Both `core/compress.py` and `core/ocr.py` import it. Don't reintroduce per-module copies.
- **Three surfaces, one pipeline.** CLI, GUI, and API all call `core.pipeline.run_pipeline(input, output, *, mode, ...)` and surface its `ProcessResult` (size deltas, OCR routing, preset_actually_used, pdfminer text-extractability check, processing_seconds). Routing logic and the structured report live in `core/pipeline.py` only — don't reintroduce per-surface routing.
- **Defaults flow from config.** `core.ocr.run_ocr` reads defaults from `config.get_config().settings` when its parameters are `None`. Preserve that pattern when extending. (The GUI was wired into settings in Phase 5; the CLI's `ocr` / `compress` / `process` commands and the API's single-file upload form still hardcode their own defaults — that's the remaining cleanup.)
- **Quality presets:** `archival` | `balanced` | `smallest` (default). Defined in `core/compress.py:_gs_args_for_preset`.
- **Cross-platform Ghostscript binary lookup.** `core/compress.py:_gs_exe()` tries `gswin64c` → `gswin32c` → `gs` and raises `SystemToolError("ghostscript", ...)` if none are found. Don't hard-code, and don't catch the precheck error to silently substitute a default.
- **Markdown style** (for README, etc.): blank line after every heading and around list blocks; no emphasis inside headings; bare URLs wrapped in angle brackets; always specify a code-fence language.

## Where I left off

**Phase 6 closed (2026-04-29). Roadmap complete.** All six phases
of the modernization are done. The project is in maintenance:
bugfixes, small enhancements, and documentation patches as needed.
There is no Phase 7.

**Post-Phase-6 cleanup (2026-04-30):** Docker support removed
(`Dockerfile`, `docker-compose.yml`, `start_services.sh`,
`.dockerignore`). The maintainer's actual workflow is native
Windows + Google Drive paths, where bind-mounting Drive File Stream
into a container is slow and flaky and the GUI's Tk folder picker
can't traverse the host filesystem from inside the container.
Native `uv run` is the only supported runtime now. Don't
reintroduce Docker scaffolding without a real use case.

**Phase 6 deliverables:**

- README rewritten as a real project README — GUI-first quickstart
  for casual readers, REST API for backend integrators, CLI for
  scripting. Sample B headline (4.8 GB → 198 MB) above the
  fold. Stale Streamlit screenshots refreshed against the Phase 5
  GUI. Old `python -m pdf_ocr_compress ...` invocations replaced
  with the installed `pdf-ocr` entry point. Python floor corrected
  from 3.9 to 3.10. Aspirational cloud-deployment list dropped.
- `docs/API.md` — full reference for the six endpoints (`/`,
  `/api/process`, `/api/download/{file_id}`, `/api/batch`,
  `/api/batch/{job_id}/status`, `/health`). curl + Python examples
  per endpoint, ProcessResponse + BatchReport + APIError schemas,
  the per-file failure ladder explained, the stable error-code
  table, and `--pdfa` semantics across all surfaces.
- `N8N_BATCH_WORKFLOW.md` and `images/n8n_simple.png` deleted —
  they predated Phase 3 (used `/api/process` in a per-file loop
  instead of `/api/batch`) and didn't match the actual workflow.
  Same category as the Phase-1 enterprise scaffolding cleanup.
- This file: roadmap section trimmed to status; debt list elevated
  below.

## Open debt (not blocking; pick up when convenient)

These items were noted across Phases 4–5 as "honest gaps" and remain
open after Phase 6 docs polish — none of them are documentation
issues.

- **GUI tempdir leaks on pipeline failure.** Phase 5 dropped the
  pre-existing `shutil.rmtree(workdir)` cleanup when `workdir` got
  split into `input_workdir` + the resolver-returned `out_dir`.
  Single-file uploads (`pdfgui_in_*`) and upload-mode batches
  (`pdfgui_batch_*`) leak on failure. For 5 GB scans that's
  gigabytes per failed run. Fix: try/finally around the run blocks.
- **CLI surface defaults still hardcoded.** The `pdf-ocr ocr` /
  `pdf-ocr compress` / `pdf-ocr process` Typer commands and the
  legacy `/api/process` upload form still hardcode preset
  (`balanced` for the API form) and other per-flag defaults. The
  GUI and `pdf-ocr batch` already read from `get_config().settings`.
  Cheap cleanup whenever someone touches those entry points.
- **Recursion into batch input subfolders.** `core/batch.py:_list_pdfs`
  is non-recursive; CLI/API/GUI all inherit that. Multi-surface
  change.
- **Per-run `oversize_policy` override on CLI/API.** Setting-only
  surface today; no per-call override. Realistic use cases are
  covered by the setting.
- **`POST /api/batch/{job_id}/cancel`.** Deferred from Phase 4;
  jobs run to completion or until uvicorn dies.
- **`FILE_TOO_LARGE` enforcement.** The error code is reserved and
  documented in `docs/API.md` but no `max_upload_bytes` setting
  exists yet to trigger it.

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
