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
- **Defaults flow from config.** `core.ocr.run_ocr` reads defaults from `config.get_config().settings` when its parameters are `None`. Preserve that pattern when extending. (The GUI was wired into settings in Phase 5; the CLI's `ocr` / `compress` / `process` commands and the API's single-file upload form still hardcode their own defaults — that's the remaining cleanup.)
- **Quality presets:** `archival` | `balanced` | `smallest` (default). Defined in `core/compress.py:_gs_args_for_preset`.
- **Cross-platform Ghostscript binary lookup.** `core/compress.py:_gs_exe()` tries `gswin64c` → `gswin32c` → `gs` and raises `SystemToolError("ghostscript", ...)` if none are found. Don't hard-code, and don't catch the precheck error to silently substitute a default.
- **Markdown style** (for README, etc.): blank line after every heading and around list blocks; no emphasis inside headings; bare URLs wrapped in angle brackets; always specify a code-fence language.

## Where I left off

**Phase 5 closed (2026-04-29).** GUI is now in line with everything
Phase 1–4 added: defaults flow from `get_config().settings` (sidebar
"⚙️ Defaults" expander persists the new `AppSettings`, with a Save
button that round-trips through `ConfigManager.save_settings`); the
batch section accepts a server-side folder path (matches the
Google-Drive-mounted ScanSnap workflow — multi-GB inputs no longer
require a browser upload); every exception site routes through
`_render_error()` → `format_error_for_user`; three Browse buttons
pop a native folder picker via `tkinter.filedialog` (works because
this is a local-machine app — same machine as the browser; raises
`RuntimeError` with a friendly message in headless / Docker
environments). Browser click-through smoke test recorded in
`tests/gui_smoke.md`. Pick up at **Phase 6 (Documentation polish)**
— see `ROADMAP.md`.

**Phase 5 deliverables:**

- `gui/basic.py` — five new private helpers, all in one file (no
  second GUI module per the "Out of scope" rule):
  - `_resolve_output_dir(cfg, override, fallback_factory) -> (Path, source, OSError|None)`
    — single resolver used by single-file, upload-batch, and
    folder-batch flows. Returns the captured `OSError` on the
    `fallback_after_unwritable` branch so the warning message can
    show str(exc) (matters when Google Drive mounts intermittently
    refuse writes).
  - `_collect_local_folder_inputs(folder_str)` — pre-flight summary
    for the new batch local-folder input (count + total bytes +
    sensible message; non-recursive; expands `~`).
  - `_render_error(exc)` — wraps the existing
    `utils.errors.format_error_for_user` and renders st.error +
    suggestions list + Error-code caption.
  - `_render_defaults_panel(cfg)` — sidebar expander for editing
    persistent `AppSettings` (preset, language, jobs, output dir,
    batch concurrency, oversize policy, Tesseract timeout). Save
    button is disabled while form values match saved values; on
    click round-trips through `ConfigManager.save_settings` then
    `st.rerun()`s so per-run controls re-init from the new defaults.
  - `_timestamped_batch_subdir(base)` — wraps base in
    `batch_YYYYMMDD-HHMMSS-fff/`. Microsecond resolution prevents
    consecutive-batch report collisions.
  - `_pick_folder_dialog(initialdir)` + `_on_browse_click(target_key, initial_value)`
    — native folder picker. The `on_click=` callback pattern is
    load-bearing: writing to a widget-bound session_state key from a
    post-button-click `if` block raises StreamlitAPIException; the
    callback fires before the rerun and is allowed to mutate.
- Fixed: per-run `preset` selector now defaults to
  `cfg.settings.default_preset` (was hardcoded to `"balanced"`,
  contradicting design rule #4 — that's why the GUI shipped wrong
  before Phase 5).
- Fixed: batch download buttons survive Streamlit reruns triggered
  by per-file download clicks. Result-rendering block reads from
  `st.session_state["batch_results"]` outside `if batch_btn:`. The
  same trap (Streamlit reruns the entire script on every widget
  interaction) bites anywhere result UI lives inside an
  `if button:` block; the single-file flow is technically vulnerable
  too but only has one download button so the issue is invisible.
- `tests/test_gui_helpers.py` — 11 unit tests covering both pure
  helpers (5 for `_resolve_output_dir` including the OSError detail
  capture, 6 for `_collect_local_folder_inputs`).
- `tests/gui_smoke.md` — manual browser checklist, walked end-to-end.
  Findings section at bottom records the four issues that surfaced
  and were fixed live during the walkthrough.

**Tests added:** `test_gui_helpers.py` (11). 129/129 total tests
pass; ruff + black green; GUI import smoke test (`from
pdf_ocr_compress.gui import main_gui`) green; Streamlit serves 200
OK at `:8501`.

**Honest gaps still open after Phase 5 (deferred to later phases):**

- **Tempdir cleanup on GUI failure paths.** Phase 5 dropped the
  pre-existing `shutil.rmtree(workdir, ignore_errors=True)` cleanup
  from the single-file pipeline-error block (`workdir` no longer
  exists as a single variable after the resolver split). Single-file
  uploads (`pdfgui_in_*` containing the input bytes) and upload-mode
  batches (`pdfgui_batch_*` containing all uploaded inputs) leak on
  failure. For 5 GB textbook scans (the user's real workload) that
  can leak gigabytes per failed run. Fix: try/finally the run
  blocks; cheap follow-up.
- **Recursion into batch input subfolders.** `core/batch.py:148`
  (`_list_pdfs`) is non-recursive and the GUI inherits that.
  Touching recursion requires CLI + API + GUI changes — out of
  scope for "GUI catchup."
- **Per-run `oversize_policy` override.** Locked-in choice #3 of
  the Phase 5 spec deferred this — the current setting-only surface
  covers realistic use cases. Adding a per-run radio means plumbing
  through `run_pipeline` / `compress` / `run_ocr`.
- **CLI surface defaults still hardcoded.** The `pdf-ocr ocr` /
  `pdf-ocr compress` / `pdf-ocr process` Typer commands and the
  legacy API single-file upload form still hardcode preset/jobs/lang.
  The GUI and `pdf-ocr batch` already read from `get_config().settings`.
- `POST /api/batch/{job_id}/cancel` — still deferred from Phase 4.
- `FILE_TOO_LARGE` is reserved as a stable API error code but has
  no enforcement (no `max_upload_bytes` setting yet).

## Known issues / tech debt

The three Phase 0 pipeline bugs are FIXED in Phase 2 items 1–3 (see
"Where I left off"). Remaining items below.

- **~~Starlette 1.0 major bump unverified at runtime.~~** Fixed in
  Phase 4: `tests/api_smoke.sh` posts a real PDF through `/api/process`
  end-to-end against a live uvicorn process.
- **~~GUI not click-through tested in a browser.~~** Closed in
  Phase 5: `tests/gui_smoke.md` walked end-to-end; four real defects
  caught and fixed during the walkthrough (recorded in the file's
  Findings section).
- **CLI surface defaults still hardcoded.** The `pdf-ocr ocr` /
  `pdf-ocr compress` / `pdf-ocr process` Typer commands and the
  legacy API single-file upload form still hardcode preset/jobs/lang.
  The GUI was wired into settings in Phase 5; `pdf-ocr batch` and
  `run_pipeline` already read from `get_config().settings`. Cheap
  cleanup whenever someone touches those entry points.
- **GUI tempdir leaks on pipeline failure.** Phase 5 dropped the
  pre-existing `shutil.rmtree(workdir)` cleanup when `workdir` got
  split into `input_workdir` + the resolver-returned `out_dir`.
  Single-file uploads and upload-mode batches now leak `pdfgui_in_*`
  / `pdfgui_batch_*` directories on failure. For 5 GB textbook
  scans that can leak gigabytes per failed run. Cheap follow-up:
  try/finally around the run blocks.
- **Phase 6 docs polish** is the only remaining roadmap phase.
  ROADMAP has the scope.

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
