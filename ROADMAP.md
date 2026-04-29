# Roadmap: rebuild pdf-ocr-compress as a real backend service

This is the multi-session plan that came out of the Phase 0 benchmark
investigation (see `BENCHMARKS.md`). Each phase is one focused chunk of
work, gated on the prior one. Pick up at the next non-completed phase.

## Status

- [x] **Phase 0 — Investigate** (2026-04-28/29) — see `BENCHMARKS.md`
- [ ] **Phase 1 — Foundation**
- [ ] **Phase 2 — Pipeline rethink**
- [ ] **Phase 3 — Batch**
- [ ] **Phase 4 — API hardening**
- [ ] **Phase 5 — GUI catchup**
- [ ] **Phase 6 — Documentation polish**

## Locked-in design invariants from Phase 0

These are non-negotiable constraints for everything that follows. They
came from real-input benchmarks on a 38 MB B&W book scan (Sample A) and a
4.8 GB color textbook scan (Sample B) — both already-OCR'd scanner output.

1. **Output ≤ input size, always.** No pipeline branch may produce
   output larger than input. If the requested preset would grow the
   file, the pipeline must fall back to a working preset, or to a
   passthrough copy if even `smallest` grows it.
2. **`needs_ocr` must use a tolerant parser** (pikepdf, not pdfminer).
   Today's pdfminer-based check false-positives on PDFs that pikepdf
   can read but pdfminer can't, triggering useless multi-hour OCR
   passes. Cost a real ~40 minutes of wasted compute during Phase 0.
3. **The post-OCR Ghostscript pass destroys the OCR text layer.**
   Verified: page 10 of `--force-ocr --preset balanced` output has no
   `/Font` resources (vs balanced compress-only: present). 11+ minutes
   of Tesseract work thrown away. Drop the post-OCR Ghostscript pass
   entirely; let OCRmyPDF own optimization via `--optimize 0/2/3`.
4. **`smallest` is the right default for ScanSnap-family input** of any
   size or color depth. It's the only preset that consistently shrinks
   (Sample A: -17%, Sample B: -95.9%). `archival` triples Sample A;
   `balanced` adds 34%.

## Phase 1 — Foundation (1 session)

**Goal:** Set up the load-bearing infrastructure for everything else.
No behavior changes the user can see; this is groundwork.

**Work items:**

1. **Update CLAUDE.md framing.** The current "personal use" phrasing
   undersells what this tool is now. Rewrite "What this is" to position
   it as a real backend service with three first-class clients (CLI,
   GUI, API) used to feed huge scans into LLM/RAG workflows. Add the
   four design invariants above to a "Design rules" section. Revise
   "Out of scope" to ban *the bad implementation patterns* (async
   batch processor, abstract profile manager) rather than the *use
   cases* — folder batching and a real settings system are now in
   scope.
2. **Greenfield settings rebuild.** Delete the existing `UISettings`,
   `SystemSettings`, and the unused-half of `OCRSettings`/
   `CompressionSettings`. Rebuild against the actual surface area we
   need. Concrete proposed schema (confirm before coding):
   - `default_preset: str = "smallest"` (was: balanced)
   - `default_language: str = "eng"`
   - `default_jobs: int = 4`
   - `default_output_dir: Path | None = None`
   - `batch_concurrency: int = 1` (sequential by default; tuneable)
   - `oversize_policy: Literal["fallback", "warn", "fail"] = "fallback"`
     — what to do when a preset would grow the file
   - `tesseract_timeout: int = 0` (keep — already used in core/ocr.py)
   - Env-var overrides: keep the `apply_env_overrides()` pattern, drop
     the dead UI/system entries.
3. **Fix `_unique_name` collision resolution** in
   `core/compress.py` and `core/ocr.py`. Today both use
   second-resolution timestamps (`%Y%m%d-%H%M%S`); a 50-file batch
   completing in the same second collides before the integer
   disambiguator helps. Switch to millisecond resolution or always
   include a counter when batch context is active.
4. **Ghostscript precheck** in `core/compress.py` mirroring the
   `shutil.which("ocrmypdf")` check in `core/ocr.py`. Currently
   `_gs_exe()` returns `"gswin64c"` even if no Ghostscript is on PATH;
   subprocess then fails with a cryptic error. Convert to a
   `SystemToolError` with installation hint.
5. **Dockerfile cleanup.** Switch from inline-pinned `pip install` to
   `pip install .` so the image picks up `pyproject.toml` floors.
   Prevents silent drift between local and container.
6. **Update CLAUDE.md "Out of scope" + "Known issues"** to reflect what
   Phase 0 found (force-OCR broken, needs_ocr false-positive, output
   sometimes larger than input). These stay listed as Phase 2 targets
   so we don't forget what we're fixing.

**Success criteria:**

- `uv run pdf-ocr --help` and the GUI/API import smoke tests still
  pass.
- New settings module exports a `get_config()` returning the new
  schema. Old field names removed cleanly.
- `_unique_name` test added to `tests/` covering rapid back-to-back
  calls.
- Ghostscript precheck test added (mock `shutil.which`).
- All ruff + black checks green.

## Phase 2 — Pipeline rethink (1–2 sessions)

**Goal:** Fix the three Phase 0 bugs and implement the size-invariant
guard. After this phase the tool actually does what it claims for both
sample inputs.

**Work items:**

1. **Rewrite `core/detect.needs_ocr`** to use pikepdf:
   - Open with pikepdf (more lenient than pdfminer).
   - Probe first N pages for `/Font` resources OR for any extractable
     text via pikepdf's text extraction.
   - Treat "pikepdf can't open it either" as the only `True` case for
     auto-OCR (genuinely unreadable → must be image-only).
   - Add tests with: ScanSnap PDF (False), genuinely image-only PDF
     (True), corrupt PDF (True), Sample B-style malformed-but-
     readable PDF (False).
2. **Drop the post-OCR Ghostscript pass.** Today `cli.py:process` runs
   OCR → writes intermediate `<stem>.ocr.pdf` → runs `do_compress` on
   that → unlinks intermediate. The `do_compress` call destroys the
   text layer (Phase 0 finding). New flow:
   - When OCR is needed: call OCRmyPDF with `--optimize N` matching the
     requested preset (0=archival, 2=balanced, 3=smallest). OCRmyPDF
     handles compression internally and preserves the text layer.
   - When OCR is not needed: only then run the Ghostscript+pikepdf
     compress pass.
   - Verify with a force-OCR test on Sample A that the output now has
     extractable text via pdfminer.
3. **Implement the size-invariant guard.** After any pipeline branch
   produces output, compare to input. If output > input:
   - `oversize_policy == "fallback"`: retry with `smallest`. If
     `smallest` is also too big, copy input to output unchanged and
     log it.
   - `oversize_policy == "warn"`: keep the larger output but emit a
     visible warning in CLI/GUI/API response.
   - `oversize_policy == "fail"`: raise `PDFProcessingError` with
     "would grow" message.
4. **Output report.** All three surfaces should return/print a small
   structured report after each operation:
   - `input_bytes`, `output_bytes`, `pct_change`
   - `ocr_ran: bool`, `ocr_skipped_reason: str | None`
   - `processing_seconds`
   - `preset_actually_used: str` (in case fallback kicked in)
   - `pdfminer_text_extractable: bool` (post-hoc fidelity smoke check)
   - CLI prints a one-line summary; API includes in JSON; GUI shows
     in success banner.
5. **Tests for the new pipeline branches.** Need fixtures for:
   - A PDF that already has text (compress-only path)
   - A PDF that needs OCR (OCR + integrated optimization path)
   - A PDF where every preset would grow the file (passthrough path)
6. **Text-fidelity round-trip test.** Operational version of "output
   is RAG-usable": pdfminer-extract on output is non-empty, contains
   the same approximate token count as input ±10%, and does not
   consist entirely of `\f` form-feeds. Marked as
   `@requires_ghostscript` and `@requires_tesseract`.

**Success criteria:**

- Force-OCR on Sample A produces an output where pdfminer extracts
  meaningful text (proves bug #3 fixed).
- `process` on Sample B doesn't trigger OCR (proves bug #2 fixed).
- `compress --preset archival` on Sample A falls back to a smaller
  preset and reports `preset_actually_used: smallest` (proves
  invariant #1 enforced).
- All Phase 1 + Phase 2 tests pass; no regressions in Batch A–E tests.

## Phase 3 — Batch (1 session)

**Goal:** Folder-input mode across CLI/GUI/API with proper failure
handling. This is the user's primary stated workflow.

**Work items:**

1. **CLI:** add `pdf-ocr batch <folder> [--preset X] [--output-dir Y]
   [--mode auto|ocr|compress]`. Glob `*.pdf` in folder. Defaults:
   output to `<folder>/processed/`, preset from settings.
2. **Failure ladder** (per user spec):
   - First failure on a file → retry once.
   - Still fails → skip and continue with next file.
   - At end of batch → second-pass retry of all skipped files.
   - Final failures → write `batch_report.json` next to output dir
     with per-file `{path, status, error_msg, attempts}`.
3. **Per-file progress** in CLI (Rich progress bar showing
   `current/total` and elapsed). API streams progress via SSE or
   returns a job_id and a separate `/api/batch/{job_id}/status`
   endpoint (defer SSE; job_id polling is simpler).
4. **GUI:** folder picker + progress queue UI. Streamlit's
   `st.progress` + `st.dataframe` for live results. Per-file size delta
   visible.
5. **API:** new `/api/batch` endpoint accepting either multi-file
   POST OR a server-side folder path + auth token. Returns `job_id`;
   `/api/batch/{job_id}/status` returns the report.
6. **Tests:** batch run with mixed valid/invalid PDFs; assert
   `batch_report.json` has correct status for each.

**Success criteria:**

- `pdf-ocr batch /path/to/folder/` runs end-to-end with
  size summary at end and `batch_report.json` written.
- One bad PDF in the middle of a batch doesn't kill the rest.
- API can be hit with a multi-file POST and returns a job_id.

## Phase 4 — API hardening (1–2 sessions)

**Goal:** Make the API a real backend service, not a demo. The user
calls it from other projects; silent breakage costs them.

**Work items:**

1. **SQLite persistence.** Replace the in-memory `file_storage` dict
   with a SQLite DB at `<temp_dir>/pdf_ocr_api.db`. Schema:
   - `files (file_id TEXT PRIMARY KEY, original_name TEXT, output_path TEXT, mode TEXT, preset TEXT, created_at TEXT, expires_at TEXT)`
   - `batch_jobs (job_id TEXT PRIMARY KEY, status TEXT, total_files INT, completed_files INT, started_at TEXT, finished_at TEXT, report_json TEXT)`
   - Cleanup query: `DELETE FROM files WHERE expires_at < ?`
2. **Structured error responses.** Define an `APIError` model with
   stable `error_code` strings (`INPUT_NOT_PDF`, `OCR_TOOL_MISSING`,
   `PROCESSING_FAILED`, `FILE_TOO_LARGE`, `OUTPUT_GREW_NO_FALLBACK`,
   etc.). All 4xx/5xx responses use this shape. Add to OpenAPI as
   the `responses=` schema for each endpoint.
3. **OpenAPI accuracy.** Audit each endpoint's `description=`,
   parameter docs, and response schemas. Ensure `/docs` actually
   reflects behavior. Add example request/response bodies for the
   common cases.
4. **`POST /api/batch`** endpoint per Phase 3.
5. **`GET /api/health`** improvement: include version, Ghostscript
   binary detected, Tesseract binary detected, available languages,
   queue depth.
6. **Curl smoke tests** committed as `tests/api_smoke.sh`. Run against
   a local uvicorn instance: process one file, batch two files, hit
   `/health`, check error responses for invalid input.

**Success criteria:**

- `/api/process` survives a uvicorn restart with file IDs intact.
- All error responses follow the `APIError` schema.
- `/docs` is accurate enough that a stranger could call the API
  without reading source.
- `tests/api_smoke.sh` passes.

## Phase 5 — GUI catchup (1 session, scope TBD)

**Goal:** Bring the Streamlit GUI in line with everything Phase 1–4
added. Per user direction: only touch what other phases require.
Don't redesign for its own sake.

**Likely work items** (confirm scope before starting):

- New settings UI surfacing the Phase 1 settings (default preset,
  oversize policy, default output dir).
- Output report display matching the new structured report from
  Phase 2.
- Folder picker + progress queue from Phase 3.
- Error display matching the structured error codes from Phase 4.

**Success criteria:** browser-test all three primary flows
(single-file process, batch a folder, change settings).

## Phase 6 — Documentation polish (alongside each phase, then a final pass)

**Goal:** Make the project legible to a stranger (and to future Claude
sessions).

**Work items:**

- README rewrite reflecting what the tool actually does, not the
  demo. Include the Sample B headline number (4.8 GB → 198 MB).
- API examples doc with curl + Python `requests` snippets for each
  endpoint.
- Document `--pdfa` option for archival use case.
- Document batch flags + `batch_report.json` schema.
- Update CLAUDE.md "Where I left off" + "Known issues" sections at
  the end of each phase.

## Reading order for tomorrow

1. This file (`ROADMAP.md`) — phase plan + invariants.
2. `BENCHMARKS.md` — concrete numbers backing the design rules.
3. `CLAUDE.md` — project guide (will be updated in Phase 1).

Phase 0 ended with no untracked changes pending. The `pdfs/`
directory contains all benchmark inputs/outputs (gitignored except
the two re-runnable tooling scripts `_benchmark.py` and `_run_one.py`).
