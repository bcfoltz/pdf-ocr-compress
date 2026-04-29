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

**Phase 2 closed (2026-04-29).** All six items shipped; all three
Phase 0 bugs are fixed; the structured output report flows through
every surface; the OCR pipeline actually produces extractable text.
Pick up at **Phase 3 (folder batch mode)** — see `ROADMAP.md`.

**Phase 2 deliverables (in order):**

- **Item 1 (`be2cc72`)** — `core/detect.needs_ocr` rewritten on
  pikepdf. Opens with the tolerant parser; checks first 5 pages for
  any `/Font` resource. Fixes Sample B's pdfminer-strict false-
  positive.
- **Item 2 (`d0793ea`)** — post-OCR Ghostscript pass dropped from CLI,
  GUI, and API. OCRmyPDF now owns optimization via `--optimize N`
  matching preset (archival=0, balanced=2, smallest=3, plus
  `--jbig2-lossy` on smallest).
- **Item 3 (`fcfdc8f`)** — `oversize_policy` enforced via new
  `core/oversize.py:enforce_oversize_policy`. `compress()` and
  `run_ocr()` both call it; the fallback retry recurses with
  `_enforce_oversize=False` to break the loop.
- **Item 4 (`5822209`/`afc062c`/`ce28a5f`/`9a12709`)** — structured
  output report. `ProcessResult` dataclass + `run_pipeline` in
  `core/pipeline.py`. CLI/GUI/API all call `run_pipeline` exclusively
  and surface the same report. API `ProcessResponse` gained 5 fields
  (`ocr_ran`, `ocr_skipped_reason`, `preset_actually_used`,
  `pdfminer_text_extractable`, `pct_change`); GUI shows them in a
  success banner with a JSON expander.
- **Item 5 (`a735361`)** — end-to-end pipeline-branch tests in
  `tests/test_pipeline_branches.py`. Three branches × three fixtures
  (`text_pdf` reused; new `image_only_pdf` from PIL; new
  `incompressible_pdf` with a random-bytes image so Ghostscript
  inflates under every preset). Gated on real Ghostscript/Tesseract
  via `requires_*` skipifs. **Caught and fixed a real runtime bug:**
  `core/ocr.py` was passing `--tesseract-timeout 0`, which in
  OCRmyPDF ≥13 means "0-second budget" not "unlimited"; Tesseract
  gave up immediately and emitted empty OCR layers on every real run.
  The unit tests in `test_pipeline.py` couldn't see it because they
  mock `_run_ocr`. Fix: omit the flag when
  `settings.tesseract_timeout <= 0`, letting OCRmyPDF's own default
  apply. Setting field semantics preserved (env-var override still
  works for non-zero values).
- **Item 6 (`65badf0`)** — text-fidelity round-trip in
  `tests/test_text_fidelity.py`. `text_paragraph_pdf` and
  `image_paragraph_pdf` fixtures (~45 tokens each, sharing a
  `PARAGRAPH_TEXT` constant in `conftest.py`). Both branches assert
  pdfminer extracts the same approximate token count ±10%, non-empty,
  not all `\f`. Test-local tokenizer splits on whitespace AND
  lowercase→uppercase transitions to handle pdfminer's habit of
  concatenating last-of-line + first-of-next-line at OCR Form-XObject
  boundaries (`dog` + `Pack` → `dogPack`); content is preserved, just
  whitespace-stripped.

**Tests:** 56 passing (was 21 at end of Phase 1). Black + ruff clean.

**"Three surfaces, one pipeline" is now load-bearing** — CLI, GUI,
and API all call exactly `core.pipeline.run_pipeline()` and surface
the same `ProcessResult`. Routing logic lives in one place.

**Phase 0 success criteria are now provable end-to-end:**

- OCR branch produces pdfminer-extractable text (item 6's OCR round-
  trip passes — proves Phase 0 bug #3 is fixed in practice, not just
  in the args list).
- Compress branch round-trips text 1:1 (item 6 compress test).
- Oversize-fallback chain terminates at passthrough when every preset
  inflates (item 5's passthrough test — enforces invariant #1).

**Pick up at Phase 3 — Batch.** Per ROADMAP.md Phase 3, the work is
folder-input mode across CLI/GUI/API:

- CLI: `pdf-ocr batch <folder> [--preset X] [--output-dir Y] [--mode
  auto|ocr|compress]`. Glob `*.pdf` in folder, sequential by default,
  per-file `ProcessResult`, summary at the end.
- GUI: multi-file uploader on `gui/basic.py` (still single page).
- API: `/api/batch` endpoint.
- **Out of scope reminder** (see "Out of scope" below): synchronous,
  sequential, no async/threadpool. Single-counter retry ladder, not a
  state machine. Don't reintroduce the deleted
  `core/batch_processor.py` shape.

**Honest gaps still open from Phase 2 (deferred to later phases):**

- Streamlit GUI not click-through tested in a browser after item 4d.
  Phase 5 covers it.
- API endpoint has no `httpx`-based test. Phase 4 slates
  `tests/api_smoke.sh`.
- CLI/GUI/API surface defaults still hardcoded (preset, jobs, lang).
  `run_pipeline` reads from `config.get_config()`; surface defaults
  don't yet. Phase 5.

**Earlier on this branch:** Phase 1 (`80ea6ae`); Phase 0 benchmarks
(`BENCHMARKS.md`, commit `1cc420e`); modernization Batches A–E
(`fa81517`..`1428564`).

## Known issues / tech debt

The three Phase 0 pipeline bugs are FIXED in Phase 2 items 1–3 (see
"Where I left off"). Remaining items below.

- **Starlette 1.0 major bump unverified at runtime.** Imports cleanly
  but no `/api/process` request exercised in a test. Phase 4 fix
  (`tests/api_smoke.sh`).
- **GUI not click-through tested in a browser.** Phase 5. The 4d
  refactor swapped the routing block but no manual smoke test was
  performed.
- **CLI/GUI/API hardcode their own defaults.** They don't yet read
  from `config.get_config()` for things like preset/jobs/lang
  defaults — `run_pipeline` does, but the surface-level Typer/
  Streamlit/Form defaults are still hardcoded. Phase 5 wires them in
  (settings UI, default output dir, oversize-policy surface).
- **Phase 3 batch + Phase 4 API hardening + Phase 5 GUI catchup +
  Phase 6 docs polish** all ahead. ROADMAP has the scope.

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
