# Project: pdf-ocr-compress

## What this is

A backend service for turning scanned PDFs into clean, searchable, RAG-ready files at scale. Wraps OCRmyPDF (Tesseract) and Ghostscript + pikepdf around a single `core/` pipeline, then exposes that pipeline through three first-class clients:

- **CLI** (Typer) — interactive use, scripting, cron jobs.
- **GUI** (Streamlit, single page) — drop-a-file diagnostics for one-off inputs.
- **REST API** (FastAPI) — the load-bearing surface, intended to be called from other apps that ingest large folders of scanned books into LLM/RAG pipelines.

Designed for real-world scanner output (B&W book scans through multi-GB color textbook scans), not toy PDFs. Runs locally or in Docker. No remote services, no auth, no telemetry.

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
- `Dockerfile`, `docker-compose.yml`, `start_services.sh` — container setup (runs Streamlit + Uvicorn together)
- `pyproject.toml` — single source of truth for dependencies; `requirements.txt` mirrors it for `pip install -r` users

## Conventions in this project

- **Never overwrite originals.** Every operation writes a brand-new timestamped file and returns its path. Output naming convention: `_ocr_{timestamp}.pdf`, `_processed_{timestamp}.pdf`, `_compressed_{timestamp}.pdf`.
- **Collision-safe paths.** `utils.file_utils.unique_output_path` is the single source of truth — microsecond-resolution timestamp plus integer counter fallback. Both `core/compress.py` and `core/ocr.py` import it. Don't reintroduce per-module copies.
- **Three surfaces, one pipeline.** CLI, GUI, and API all call `core.pipeline.run_pipeline(input, output, *, mode, ...)` and surface its `ProcessResult` (size deltas, OCR routing, preset_actually_used, pdfminer text-extractability check, processing_seconds). Routing logic and the structured report live in `core/pipeline.py` only — don't reintroduce per-surface routing.
- **Defaults flow from config.** `core.ocr.run_ocr` reads defaults from `config.get_config().settings` when its parameters are `None`. Preserve that pattern when extending. (CLI/GUI/API still hardcode their own defaults — wiring them into settings is Phase 5.)
- **Quality presets:** `archival` | `balanced` | `smallest` (default). Defined in `core/compress.py:_gs_args_for_preset`.
- **Cross-platform Ghostscript binary lookup.** `core/compress.py:_gs_exe()` tries `gswin64c` → `gswin32c` → `gs` and raises `SystemToolError("ghostscript", ...)` if none are found. Don't hard-code, and don't catch the precheck error to silently substitute a default.
- **Markdown style** (for README, etc.): blank line after every heading and around list blocks; no emphasis inside headings; bare URLs wrapped in angle brackets; always specify a code-fence language.

## Where I left off

**Phase 4 closed (2026-04-29).** API is now real backend service
material: SQLite persistence (file IDs and batch jobs survive a
uvicorn restart), stable `APIError` wire shape on every 4xx/5xx,
environment-aware `/health`, accurate OpenAPI docs at `/docs`, and a
curl + jq smoke test that exercises everything end-to-end. Pick up at
**Phase 5 (GUI catchup)** — see `ROADMAP.md`.

**Phase 4 deliverables:**

- `api/errors.py` — `APIError` Pydantic model + `APIException` carrier
  + `install_exception_handlers(app)`. Three handlers wire into the
  FastAPI app: `APIException` (server-raised), `PDFProcessingError`
  (domain leak from `run_pipeline`), `RequestValidationError`
  (FastAPI's automatic 422 wrapped to the same shape). Stable code
  constants: `INPUT_NOT_PDF`, `INVALID_MODE`, `INVALID_PRESET`,
  `INVALID_FOLDER`, `INVALID_OUTPUT_DIR`, `FILE_NOT_FOUND`,
  `BATCH_JOB_NOT_FOUND`, `OCR_TOOL_MISSING`,
  `GHOSTSCRIPT_TOOL_MISSING`, `PROCESSING_FAILED`,
  `OUTPUT_GREW_NO_FALLBACK`, `VALIDATION_ERROR`, plus reserved
  `FILE_TOO_LARGE` (no enforcement path yet).
- `api/storage.py` — single SQLite owner. Tables: `files (file_id PK,
  original_name, output_path, workdir, mode, preset, created_at,
  expires_at)` and `batch_jobs (job_id PK, status, started_at,
  finished_at, progress_current, progress_total, error_msg,
  report_json)`. `Storage.__init__` runs `_mark_stale_running_jobs()`
  once at boot, so any queued/running rows from a dead previous
  process come back as `status='error'` with
  `error_msg='server restarted mid-job'`. WAL journaling +
  `check_same_thread=False` so BackgroundTasks workers can write
  per-file progress while polls read.
- `/health` reports: `version` (importlib.metadata),
  `ghostscript_binary`, `tesseract_binary`, `tesseract_languages`
  (parsed from `tesseract --list-langs`, handles stdout-or-stderr
  builds), `queue_depth` (queued+running batch jobs). Binary detection
  never raises — missing tools surface as null paths and an empty
  language list, so monitoring can distinguish "API up" from "API up
  but Tesseract missing".
- OpenAPI: `responses=` declarations on every error path point at
  `APIError`; `ProcessResponse` / `BatchRequest` /
  `BatchAcceptedResponse` carry `json_schema_extra` examples so /docs
  Try-it forms pre-fill with realistic values. Endpoint summaries +
  tightened descriptions explain mode/preset semantics and the batch
  failure ladder.
- `tests/api_smoke.sh` — bash + curl + jq. Drives /health, /process
  happy path + 400 INVALID_MODE error path, /download, /batch with a
  2-file folder, polls /status until done, hits an unknown job_id for
  404. Cross-platform path handling via `cygpath -w` on git-bash
  (no-op on Linux/macOS). Exits 0 (PARTIAL PASS) when Ghostscript is
  missing.

**Tests added:** `test_api_errors.py` (15), `test_api_storage.py`
(11), `test_api_health.py` (5), `test_api_openapi.py` (11). 118/118
total tests pass; ruff + black green; smoke script passes against a
live uvicorn in ~3s on Windows git-bash.

**Honest gaps still open after Phase 4 (deferred to later phases):**

- GUI browser click-through — Phase 5 deliverable.
- `POST /api/batch/{job_id}/cancel` — still deferred. Adding it later
  means polling a `should_cancel` flag inside `run_batch`; not hard,
  just not done.
- Existing single-file CLI/GUI/API surface defaults still hardcoded.
  The `batch` surfaces and `run_pipeline` already read from
  `get_config().settings`; the older `ocr` / `compress` / `process`
  commands and the single-file upload form do not (Phase 5).
- `FILE_TOO_LARGE` is reserved as a stable error code but has no
  enforcement (no `max_upload_bytes` setting yet). Adding it means a
  config setting + chunked upload handling.

## Known issues / tech debt

The three Phase 0 pipeline bugs are FIXED in Phase 2 items 1–3 (see
"Where I left off"). Remaining items below.

- **~~Starlette 1.0 major bump unverified at runtime.~~** Fixed in
  Phase 4: `tests/api_smoke.sh` posts a real PDF through `/api/process`
  end-to-end against a live uvicorn process.
- **GUI not click-through tested in a browser.** Phase 5. The 4d
  refactor swapped the routing block but no manual smoke test was
  performed.
- **CLI/GUI/API hardcode their own defaults.** They don't yet read
  from `config.get_config()` for things like preset/jobs/lang
  defaults — `run_pipeline` does, but the surface-level Typer/
  Streamlit/Form defaults are still hardcoded. Phase 5 wires them in
  (settings UI, default output dir, oversize-policy surface).
- **Phase 4 API hardening + Phase 5 GUI catchup + Phase 6 docs
  polish** all ahead. ROADMAP has the scope.

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
