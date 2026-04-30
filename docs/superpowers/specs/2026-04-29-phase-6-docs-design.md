# Phase 6 — Documentation polish (design)

**Date:** 2026-04-29
**Status:** approved (brainstorming complete; ready for writing-plans)
**Roadmap reference:** `ROADMAP.md` Phase 6
**Companion specs:** `2026-04-29-phase-3-batch-design.md`,
`2026-04-29-phase-5-gui-catchup-design.md`

## Goal

Close the Phase 6 documentation polish phase from `ROADMAP.md`. After
this phase the public README, API reference, and project guide
(`CLAUDE.md`) accurately describe what the tool does today, and the
roadmap is closed.

## Background

Phases 1–5 modernized the codebase: greenfield settings, pipeline fix,
folder-batch mode, API hardening with SQLite + structured errors, and
GUI catch-up against all of it. Documentation was updated *inside*
each phase's spec but the public-facing surface (`README.md`,
`N8N_BATCH_WORKFLOW.md`) was last touched in the original commit and
predates roughly half of what the project does. The README claims
`balanced` is the default preset (it's `smallest`), uses
`python -m pdf_ocr_compress` invocations (entry point is `pdf-ocr`),
documents no batch surface, no structured response, no error codes,
and links to an n8n workflow doc that uses `/api/process` in a per-file
loop instead of `/api/batch`.

Phase 6 brings the docs in line and then closes the roadmap.

## Non-goals

These are out of scope for Phase 6 even though they sit nearby:

- **Code changes.** No source files in `src/` are modified. Phase 6 is
  pure documentation. Open code debt is recorded in `CLAUDE.md`'s new
  "Open debt" section but not addressed.
- **The `/api/process` form's `preset="balanced"` default.**
  Contradicts design rule #4 and is recorded as known debt. Docs
  describe today's behavior; they do not flip the default.
- **`requirements.txt` edits.** Mirrors `pyproject.toml`; no docs
  change should diverge them.
- **`CLAUDE.local.md`.** Gitignored personal notes; out of scope.
- **`BENCHMARKS.md`.** Already accurate; the README cites the Sample B
  number from it.
- **The Streamlit GUI itself.** Phase 5 closed it. Only the README's
  screenshots of it are refreshed.

## Deliverables

Four commits on `main`, in this order. Each commit ships independently
so review is piecewise.

### Commit 1 — `docs: drop n8n integration scaffolding`

Purely deletions. Removes content the next commit would otherwise
have to rewrite.

- Delete `N8N_BATCH_WORKFLOW.md`.
- Delete `images/n8n_simple.png`.
- Delete the n8n section from `README.md` (the `### n8n Integration`
  block and the link to `N8N_BATCH_WORKFLOW.md`).

**Rationale:** the n8n doc was added in commit `bb815dd` ("Add
screenshorts to README") in the initial-commit era. It pitches n8n
calling `/api/process` in a per-file loop. After Phase 3 the right
pattern is `/api/batch` + polling; the n8n doc was never updated.
n8n is also not the user's actual workflow (LLM/RAG apps call the
API directly per `CLAUDE.local.md`). Same category as the ~2,400
lines of "enterprise scaffolding" deleted in the Phase-1 modernization
pass.

### Commit 2 — `docs: refresh README screenshots for Phase 5 GUI`

Image-binary-only commit. README continues to link to the existing
filenames; only the file contents change.

Three screenshots to capture, all driven via the Playwright MCP
server against a locally running `uv run pdf-ocr-gui` instance:

1. `images/streamlit_starting_ui.png` — initial GUI state showing
   the sidebar `⚙️ Defaults` expander (open), the Single-file tab
   selected, and the upload area empty.
2. `images/streamlit_processing_ui.png` — **renamed in scope; same
   filename retained** to avoid README link churn. New content: the
   **Batch** tab showing the folder-path input, the "Browse" button,
   the output-folder field, and the resolver-summary preview line.
   This trades an unhelpful "processing spinner" shot for a static
   UI state that screenshots cleanly and informs backend-y readers.
3. `images/streamlit_ending_ui.png` — post-process success state
   showing the new structured-report block (`preset_actually_used`,
   `pct_change`, `pdfminer_text_extractable`, OCR routing) and the
   download button.

**Capture protocol:**

- Start GUI in background: `uv run pdf-ocr-gui` via `Bash` with
  `run_in_background: true`. Wait for the Streamlit "ready" line in
  the log.
- Drive states via Playwright MCP: `browser_navigate` to
  `http://localhost:8501`, set form values via `browser_evaluate` /
  `browser_fill_form`, capture with `browser_take_screenshot`.
- For screenshot 3, use one of the small repo test fixtures in
  `tests/` so the call completes quickly.
- Tear down the GUI shell after capture.

The current README's image caption ("Processing in progress") becomes
inaccurate against screenshot 2's new content, but commit 2 does not
edit the README to fix that. Commit 4 rewrites the README from scratch
and the old caption is dropped wholesale at that point — fixing it in
commit 2 would require reverting a partial edit during commit 4.

### Commit 3 — `docs: add docs/API.md with full endpoint reference`

New file. ~350 lines. README does **not** yet link to it (that lands
in commit 4) so this commit can be reviewed standalone.

#### `docs/API.md` outline

```text
# pdf-ocr-compress API reference

Intro paragraph: REST API at port 8502 (Docker) or wherever uvicorn
binds. Single-machine assumption; no auth. Designed to be called
from RAG ingestion pipelines that need OCR + compression on large
scanned folders.

## Quickstart

  curl + python `requests` end-to-end example: upload one PDF,
  poll-not-needed (synchronous), download the result. ~15 lines.

## Endpoint reference

For each of the six endpoints:
  GET  /                            (service info + endpoint index)
  POST /api/process                 (one PDF in, file_id out)
  GET  /api/download/{file_id}      (retrieve, 1h TTL)
  POST /api/batch                   (queue folder job, returns job_id)
  GET  /api/batch/{job_id}/status   (poll job, returns full report)
  GET  /health                      (version + tool detection)

  Each endpoint section:
    - Method + path
    - Request schema (form parameters table for /process; JSON body
      for /batch; path parameter notes for downloads/status)
    - curl example
    - Python `requests` example
    - Response schema with field-by-field table
    - Status codes + which APIError codes land under each

## ProcessResponse schema

Field table covering both blocks:
  - Legacy block (back-compat for pre-Phase-2 consumers):
      status, message, file_id, mode, preset,
      original_size, output_size, reduction_percent, processing_time
  - Phase 2 block (structured report):
      ocr_ran, ocr_skipped_reason, preset_actually_used,
      pdfminer_text_extractable, pct_change

  Note explaining why both blocks coexist (back-compat) and that
  reduction_percent and pct_change are the same operation under
  inverted-sign conventions.

## BatchReport schema

  BatchReport
    input_dir, output_dir
    total_files, succeeded, failed
    started_at, finished_at, total_seconds
    total_input_bytes, total_output_bytes
    results: [ BatchResult, ... ]

  BatchResult
    input_path, output_path
    status: ok | failed
    attempts: 1 | 2 | 3
    error_msg
    process_result: ProcessResult | null
      (full per-file report; same shape as the /api/process response
      minus the file_id wrapper)

  Note: the BatchReport JSON is also written to
  <output_dir>/batch_report.json on disk; the on-disk file and the
  `report` field returned by /status share this schema.

## Failure ladder (per file in a batch)

  attempt 1 — initial run
  attempt 2 — immediate retry on failure
  attempt 3 — end-of-batch retry (after every other file has run)

  A file that succeeds on any attempt records that count in `attempts`.
  A file that fails all three is marked status="failed" with
  attempts=3 and the most recent exception in error_msg. One bad PDF
  does not abort the batch.

## Error responses

Every 4xx/5xx response body follows the APIError shape:

  { "error_code": "INPUT_NOT_PDF",
    "message": "File must be a PDF",
    "detail": null }

Stable error codes table (codes sourced from
src/pdf_ocr_compress/api/errors.py — read before writing so the doc
matches what is exported, no guesses):
  - INPUT_NOT_PDF (400)
  - INVALID_MODE (400)
  - INVALID_PRESET (400)
  - INVALID_FOLDER (400)
  - INVALID_OUTPUT_DIR (400)
  - FILE_NOT_FOUND (404)
  - BATCH_JOB_NOT_FOUND (404)
  - PROCESSING_FAILED (500)
  - OCR_TOOL_MISSING (503)
  - FILE_TOO_LARGE — reserved; not currently emitted (no
    max_upload_bytes setting yet — see CLAUDE.md "Open debt")

## --pdfa flag

What PDF/A-2 means and when you'd want it (archival use case;
self-contained file with embedded fonts and color profile; legal /
long-term storage).

Available on:
  - POST /api/process (form field: pdfa=true)
  - POST /api/batch (JSON body: "pdfa": true)
  - pdf-ocr process / ocr CLI commands (--pdfa)

Trade-off: PDF/A files are typically larger than non-PDF/A; the
size-invariant guard still applies, so a request with --pdfa that
would grow the file falls back per `oversize_policy`.

## Notes for integrators

  - Files retained 1 hour after /api/process; download or lose them.
  - Batch jobs retained 1 hour after completion.
  - SQLite store survives uvicorn restart (Phase 4); both file_ids
    and job_ids remain valid across restarts within the TTL window.
  - /api/batch takes a server-side folder path — the API process
    must have read access to it. No upload mode for batch.
  - /docs serves an interactive Swagger UI generated from the same
    schema this document describes.
```

**Source-of-truth rules for the doc:**

1. The error code list is read from `src/pdf_ocr_compress/api/errors.py`
   before writing; if the source exports a code not in the proposed
   table, the table is corrected to match.
2. The `/api/process` form's documented defaults match what the form
   currently accepts (`preset="balanced"`, etc.). The doc adds a
   recommendation note ("`smallest` is recommended for ScanSnap
   output per design rule #4") rather than silently lying about the
   default.
3. The `BatchReport` schema is read from `src/pdf_ocr_compress/core/batch.py`
   before writing.
4. `ProcessResponse` field shapes are read from
   `src/pdf_ocr_compress/api/server.py`.

### Commit 4 — `docs: rewrite README + close Phase 6 in CLAUDE.md`

#### README rewrite

Final structure (~250 lines, down from 418):

```text
# pdf-ocr-compress

One-paragraph framing: backend service for turning scanned PDFs into
clean, searchable, RAG-ready files. Three clients: GUI (friendliest),
Docker / API (backend), CLI (scripting). Single-machine, no auth, no
telemetry, no remote services.

Real-world result: 4.8 GB color textbook scan → 198 MB (-95.9%),
text layer preserved. (Sample B from BENCHMARKS.md.)

## What it does

  - Adds searchable text layers to scanned PDFs via Tesseract OCR
  - Compresses without destroying the OCR text layer (Phase 0 finding)
  - Enforces output ≤ input — never grows the file silently
  - Auto-detects which PDFs already have text and skips OCR on those
  - Folder-batch mode with per-file retry ladder + structured report

## Quick start

### Web GUI (easiest)
  uv sync; uv run pdf-ocr-gui  → http://localhost:8501
  1-2 sentences per panel + screenshot per state (3 images)

### Docker / backend service
  docker-compose up
  GUI on 8501, API on 8502, /docs on 8502/docs
  Pointer: "Calling the API from another app? See docs/API.md"

### Command line
  uv run pdf-ocr process input.pdf output.pdf
  uv run pdf-ocr batch /folder/of/scans --preset smallest
  uv run pdf-ocr ocr / compress subcommands

## System requirements

  - Tesseract OCR + Ghostscript on PATH (winget / brew / apt commands)
  - Python 3.10+ (matches pyproject.toml floor; current README says
    3.9 which is wrong — fixing)
  - uv recommended; `pip install -r requirements.txt` works

## Quality presets

  Table: archival | balanced | smallest. Note: `smallest` is the
  default and the only preset that consistently shrinks ScanSnap
  output (design rule #4). Other presets may trigger oversize-fallback
  to `smallest`.

## Output naming

  `_ocr_<ts>.pdf` / `_processed_<ts>.pdf` / `_compressed_<ts>.pdf`,
  microsecond-stamped, never overwrites originals.

## Troubleshooting

  Same shape as today — pruned to the items still relevant.

## License

  (Same as today.)
```

**Things dropped from the current README:**

- The "PDF Types ✅/❌" preamble (replaced by one sentence).
- All `python -m pdf_ocr_compress ...` invocations. The documented
  form is the installed `pdf-ocr` entry point declared in
  `pyproject.toml`.
- Inline API examples block (lives in `docs/API.md` after commit 3).
- Cloud deployment options list (AWS ECS, Cloud Run, Fly.io, etc.) —
  aspirational; the project is single-machine.
- Dependency list section (`ocrmypdf>=15.0.0`...) — `pyproject.toml`
  is the source of truth; copying it into the README guarantees drift.
- "File Output" section — folded into a one-liner under Output naming.

**Things corrected:**

- Default preset documented as `smallest` (was `balanced`).
- Python floor `3.10+` (was `3.9+`).
- CLI invocations use `pdf-ocr ...` (was `python -m pdf_ocr_compress ...`).
- Batch surface and structured response now appear in their
  respective doc surfaces (`docs/API.md` for the API, README for
  the CLI batch command).

#### CLAUDE.md update

Replace the Phase 5 narrative under "Where I left off" with a
status-and-debt-list shape. Concrete proposed text:

```markdown
## Where I left off

**Phase 6 closed (2026-04-29). Roadmap complete.** All six phases
of the modernization are done. The project is in maintenance:
bugfixes, small enhancements, and documentation patches as needed.
There is no Phase 7.

**Phase 6 deliverables:**

  - README rewritten as a real project README — GUI-first quickstart
    for casual readers, Docker / API for backend integrators, CLI
    for scripting. Sample B headline (4.8 GB → 198 MB) above the
    fold. Stale Streamlit screenshots refreshed against the Phase 5
    GUI. Old `python -m pdf_ocr_compress ...` invocations replaced
    with the installed `pdf-ocr` entry point. Python floor corrected
    from 3.9 to 3.10. Aspirational cloud-deployment list dropped.
  - `docs/API.md` — full reference for the six endpoints. curl +
    Python examples per endpoint, ProcessResponse + BatchReport
    schemas, failure-ladder explanation, stable APIError code table,
    `--pdfa` semantics across all surfaces.
  - N8N_BATCH_WORKFLOW.md and images/n8n_simple.png deleted — they
    predated Phase 3 (used /api/process in a per-file loop instead
    of /api/batch) and didn't match the actual workflow. Same
    category as the Phase-1 enterprise scaffolding cleanup.
  - This file: roadmap section trimmed to status; debt list elevated
    below.

## Open debt (not blocking; pick up when convenient)

These were noted across Phases 4–5 as "honest gaps" and remain open
after Phase 6 docs polish — none are documentation issues.

  - GUI tempdir leaks on pipeline failure (single-file +
    upload-mode batch).
  - CLI surface defaults still hardcoded (Typer commands + legacy
    /api/process form).
  - Recursion into batch input subfolders (CLI/API/GUI all
    inherit core/batch.py:_list_pdfs non-recursive behavior).
  - Per-run oversize_policy override on CLI/API.
  - POST /api/batch/{job_id}/cancel endpoint.
  - FILE_TOO_LARGE enforcement (no max_upload_bytes setting).
```

**Sections in `CLAUDE.md` that stay unchanged:**

- "What this is", "Design rules", "Stack", "How to run it", "Project
  structure", "Conventions in this project" — still accurate.
- "Out of scope" — the do-not-readd list is still load-bearing.

**Section that gets folded:** "Known issues / tech debt" — its content
merges into the new "Open debt" section so debt lives in one place
instead of two.

#### Memory file update

After commit 4 lands, update
`<user-claude-memory-dir>/project_phase_status.md`
to reflect "Phase 6 closed (2026-04-29); roadmap complete; project
in maintenance" so future sessions don't think there's still phase
work to do. `MEMORY.md` index entry gets a one-line update to match.

## Verification

Before marking Phase 6 done:

  - `uv run black src/`  — green (no source files changed; should pass).
  - `uv run ruff check src/`  — green (same reason).
  - `uv run pdf-ocr --help`  — CLI loads.
  - `uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"` — API imports.
  - `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"` — GUI imports.
  - All committed markdown renders cleanly (visual scan in a markdown
    viewer; in particular the API.md endpoint sections and code
    fences).
  - All anchor links inside README work (Quick start → CLI section,
    "see docs/API.md" link resolves).
  - Three new screenshots open and look correct (sidebar Defaults,
    batch tab, post-process structured report).

No new tests this phase — pure docs.

## Risks and mitigations

- **Risk:** screenshot capture flake (Streamlit timing, Playwright
  selectors). **Mitigation:** if screenshot-3 timing is too tight on
  a test fixture, fall back to two screenshots and update the README
  to match — recorded as a fallback option in section 5 of
  brainstorming. Not committing screenshots that don't match the
  current GUI is more important than having three.
- **Risk:** drift between `docs/API.md` and `api/errors.py` /
  `api/server.py` / `core/batch.py`. **Mitigation:** read those
  files before writing the relevant sections; quote field names
  verbatim; do not paraphrase code into prose.
- **Risk:** README link to `docs/API.md` in commit 4 lands while the
  file from commit 3 is still being reviewed (rare interleave issue).
  **Mitigation:** commits land in order on `main`; commit 3 ships
  the file before commit 4 ships the link.

## After Phase 6

The roadmap is closed. `MEMORY.md` and the project memory file are
updated to reflect maintenance mode. Future work is bugfixes against
the open-debt list or new feature requests, each starting from a
fresh brainstorming session — no global plan continues from here.
