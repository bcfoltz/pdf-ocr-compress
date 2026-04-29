# Phase 3 — Batch mode design

**Status:** Approved 2026-04-29. Implementation plan to follow via the
writing-plans skill. ROADMAP Phase 3.

## Goal

Add folder-batch mode across CLI, GUI, and API on top of the existing
`core.pipeline.run_pipeline()`. The pipeline itself does not change —
every Phase 0 / 1 / 2 invariant (size guard, oversize fallback, OCR
routing, structured `ProcessResult`) keeps applying per-file.

## Locked-in design choices

These were resolved during brainstorming. They are not open for
re-litigation during implementation; if a real reason emerges to change
one, update this section and re-run review.

1. **API batch surface = server-side folder path only.** No multi-file
   upload endpoint in Phase 3. Folder path is a parameter on every call;
   nothing is hardcoded to a particular drive or mount. Rationale:
   project is local-only (CLAUDE.md "no auth, no telemetry") and the
   primary input shape is folders of multi-GB book scans on a mounted
   drive — uploading them is the antipattern CLAUDE.local.md calls out.
2. **API batch is async with job_id.** `POST /api/batch` returns
   `{job_id, status: "queued"}` immediately; processing runs via
   FastAPI `BackgroundTasks`; `GET /api/batch/{job_id}/status` polls
   for state and final report. Job state lives in an in-memory dict
   for Phase 3; Phase 4 swaps that for SQLite without changing the
   wire shape. Rationale: a sync POST against a 100-book batch will
   hit timeouts (uvicorn default, reverse proxies, clients).
3. **Retry-once on every failure, no error classification.** Per-file
   loop: initial attempt → immediate retry on failure → continue with
   next file. End-of-batch second-pass retry of all still-failing
   files. Worst-case `attempts=3`. No transient/deterministic
   classifier. Rationale: cost is bounded; classifier is a premature
   abstraction.
4. **`batch_report.json` lives inside the output dir** at
   `<output_dir>/batch_report.json`. Co-located with the PDFs from the
   same batch.
5. **GUI is multi-file upload, not server-side folder path.**
   Streamlit's file picker is browser-side and cannot read server
   paths. The single-file flow stays as it is; batch is a new section
   on the same page.

## Architecture

One new module: `src/pdf_ocr_compress/core/batch.py`. Surfaces import
shapes and call `run_batch()`; they do not own batch logic.

```text
core/batch.py
  ├── BatchResult           dataclass — one file's outcome
  ├── BatchReport           dataclass — whole batch + summary
  ├── BatchJobState         dataclass — used by API for job records
  └── run_batch(            orchestrator
        input_dir, output_dir, *,
        mode, preset, lang, jobs,
        pdfa, force_ocr,
        progress_callback=None,
      ) -> BatchReport
```

The orchestrator is a sequential `for` loop calling `run_pipeline`. No
async, no thread pool, no concurrency knob beyond passing `jobs=`
through to OCRmyPDF (which already parallelizes Tesseract internally).
This matches CLAUDE.md's explicit "Out of scope" rule against
re-introducing `core/batch_processor.py`-style scaffolding.

## Data shapes

### `BatchResult` — one file

```python
@dataclass
class BatchResult:
    input_path: Path
    output_path: Path | None       # None when status == "failed"
    status: Literal["ok", "failed"]
    attempts: int                  # total run_pipeline calls (1, 2, or 3)
    error_msg: str | None          # populated when status == "failed"
    process_result: ProcessResult | None   # full Phase 2 report; None on failure
```

### `BatchReport` — whole batch

```python
@dataclass
class BatchReport:
    input_dir: Path
    output_dir: Path
    total_files: int
    succeeded: int
    failed: int
    started_at: str                # ISO-8601
    finished_at: str               # ISO-8601
    total_seconds: float
    total_input_bytes: int
    total_output_bytes: int        # successful files only
    results: list[BatchResult]

    def to_dict(self) -> dict: ...
    def write_json(self, path: Path) -> None: ...
    def one_line_summary(self) -> str: ...
```

`one_line_summary()` example output:

```text
47 ok, 2 failed | 4.2 GB -> 280 MB (-93.3%) | 1h 12m
```

### `batch_report.json` schema

```json
{
  "input_dir": "G:/My Drive/Book Scans/Marketing",
  "output_dir": "G:/My Drive/Book Scans/Marketing/processed",
  "total_files": 49,
  "succeeded": 47,
  "failed": 2,
  "started_at": "2026-04-29T10:14:03.221",
  "finished_at": "2026-04-29T11:26:18.554",
  "total_seconds": 4335.3,
  "total_input_bytes": 4515600000,
  "total_output_bytes": 281400000,
  "results": [
    {
      "input_path": ".../torres.pdf",
      "output_path": ".../processed/torres_processed_20260429-101403-221555.pdf",
      "status": "ok",
      "attempts": 1,
      "error_msg": null,
      "process_result": { "...": "full ProcessResult.to_dict()" }
    },
    {
      "input_path": ".../encrypted.pdf",
      "output_path": null,
      "status": "failed",
      "attempts": 3,
      "error_msg": "PDFProcessingError: file is encrypted",
      "process_result": null
    }
  ]
}
```

The nested per-file `process_result` is the same shape API consumers
already parse from `/api/process`. RAG-ingestion consumers can read
size deltas, OCR routing, and `pdfminer_text_extractable` per file
without a second call.

### `BatchJobState` — API only

```python
@dataclass
class BatchJobState:
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    started_at: str
    finished_at: str | None
    progress_current: int          # files processed so far
    progress_total: int            # total files
    report: BatchReport | None     # populated when status == "done"
    error_msg: str | None          # populated when status == "error"
```

`status="error"` means the orchestrator itself crashed (folder doesn't
exist, output dir not writable, unhandled exception in `run_batch`).
Per-file failures do **not** bubble to `status` — they live in
`report.results[i].status`.

## Surface bindings

### CLI — `pdf-ocr batch`

```text
$ pdf-ocr batch <input_dir> [OPTIONS]

Options:
  --output-dir PATH      Default: <input_dir>/processed
  --mode TEXT            auto | ocr | compress (default: auto)
  --preset TEXT          archival | balanced | smallest
                         (default: settings.default_preset)
  --lang TEXT            OCR language
                         (default: settings.default_language)
  --jobs INT             Per-file OCR parallelism
                         (default: settings.default_jobs)
  --pdfa                 PDF/A-2 output for files that go through OCR
  --force-ocr            Force OCR on every file regardless of needs_ocr()
```

Live output: Rich progress bar showing `current/total`, current
filename, elapsed time. End-of-run prints one line per file
(`ProcessResult.one_line_summary()` for successes, FAILED line for
failures), then the batch summary, then the report path.

### GUI — multi-file uploader on `gui/basic.py`

- Single page, no second file. Existing single-file flow is untouched.
- New section: `st.file_uploader("Or drop multiple PDFs",
  accept_multiple_files=True, type="pdf")`.
- Same preset / mode / language / jobs controls as the single-file
  flow, factored into a small shared helper to avoid duplication.
- "Process batch" button → save uploads to a temp dir → call
  `run_batch()` with a progress callback that updates `st.progress`
  and a live `st.dataframe` of per-file results.
- When done: download buttons for each successful PDF + a "Download
  report (JSON)" button. Failed rows are highlighted but not
  downloadable.

Rationale for upload-only on GUI: Streamlit runs in the browser, so
server-side folder paths aren't accessible from the file picker. The
local-folder workflow goes through CLI or API; GUI stays as the
diagnostics surface CLAUDE.md says it is.

### API — async with job_id

Existing `/api/process` and `/api/download/{file_id}` are unchanged.

**`POST /api/batch`** — JSON body, no upload:

```json
{
  "folder": "G:/My Drive/Book Scans/Marketing",
  "output_dir": "G:/My Drive/Book Scans/Marketing/processed",
  "mode": "auto",
  "preset": "smallest",
  "language": "eng",
  "jobs": 4,
  "pdfa": false,
  "force_ocr": false
}
```

- `folder` is required; must exist and be a directory. Empty folders
  are accepted and produce an empty report (`total_files=0`); this
  matches CLI behavior.
- `output_dir` is optional; defaults to `<folder>/processed`. If it
  exists, it must be a writable directory. If it doesn't exist, its
  parent must be a writable directory (so `mkdir` can succeed).
- All other fields are optional and default to `settings.*` values.
- On entry validation failure: `400` with the existing
  `HTTPException(detail=...)` shape (Phase 4 will replace this with
  the structured `APIError`).

Returns 202 Accepted:

```json
{ "status": "queued", "job_id": "ab12...", "total_files": 49 }
```

**`GET /api/batch/{job_id}/status`** — returns the `BatchJobState`
shape from the data-shapes section. Polled by clients until `status`
is `done` or `error`. The `report` field carries the full nested
`BatchReport` once done.

**Job lifecycle:** `queued` → `running` → `done` (or `error`). Job
records live in a module-scope `batch_jobs: dict[str, BatchJobState]`
alongside the existing `file_storage` dict. Same 1-hour TTL/cleanup
pattern. Phase 4 swaps for SQLite without changing the wire shape.

**No batch download endpoint.** Output PDFs land in the user-specified
`output_dir` on the same filesystem the API runs on (local-only
model). `/api/download/{file_id}` stays for the single-file
`/api/process` flow only.

## Failure handling

Retry-once policy, locked in:

```text
for path in pdfs:
    try:
        result = run_pipeline(path, ...)
        record OK (attempts=1)
    except Exception as e:
        try:
            result = run_pipeline(path, ...)         # immediate retry
            record OK (attempts=2)
        except Exception as e2:
            mark "to_retry_at_end" with the latest error

at end of batch, for path in to_retry_at_end:
    try:
        result = run_pipeline(path, ...)             # second-pass retry
        record OK (attempts increases by 1)
    except Exception as e3:
        record FAILED (attempts=3, error_msg=str(e3))
```

Specifics:

- `attempts` counts total `run_pipeline` calls for that file. Worst
  case = 3.
- No backoff, no sleep between retries. OCR/Tesseract failures are
  not network-flaky.
- Catch `Exception`, not `BaseException`. Ctrl-C (`KeyboardInterrupt`)
  propagates and stops the batch.
- No per-file wall-clock timeout in `run_batch`. OCRmyPDF already
  honors `--tesseract-timeout` (Phase 2 fixed). Adding another layer
  means killing subprocesses we didn't start.
- On final failure, unlink any half-written output before recording.
  The size guard inside `run_ocr`/`compress` prevents oversize outputs
  from shipping; this just handles partial writes from a crashed
  Tesseract.

## Tests — `tests/test_batch.py`

Real fixtures (most reuse Phase 2 additions; one new):

- `text_pdf` (existing)
- `image_only_pdf` (existing)
- `incompressible_pdf` (existing)
- `corrupt_pdf` **(new)** — non-PDF bytes with a `.pdf` extension;
  both pipeline attempts raise.

Test cases:

1. `test_batch_all_succeed` — 3 valid PDFs. All `status="ok"`,
   `attempts=1`, `batch_report.json` written, output PDFs are real
   PDFs.
2. `test_batch_mixed_outcomes` — 2 valid + 1 corrupt. 2 ok, 1 failed
   with `attempts=3` and non-empty `error_msg`. Valid files still
   succeed (one bad apple does not kill the batch — Phase 3 success
   criterion).
3. `test_batch_empty_folder` — folder exists, no `*.pdf`.
   `total_files=0`, no exception, report still written.
4. `test_batch_output_dir_created` — output_dir doesn't exist;
   created; files land in it.
5. `test_batch_retry_succeeds_on_second_attempt` — monkeypatch
   `run_pipeline` to fail once then succeed. `attempts=2`,
   `status="ok"`. Proves immediate-retry branch.
6. `test_batch_end_of_batch_retry` — monkeypatch to fail twice then
   succeed. `attempts=3`, `status="ok"`. Proves second-pass retry
   branch.
7. `test_batch_progress_callback_invoked` — assert callback is called
   once per file with `(current, total, current_path)`.

**Gating:** cases 1, 2, 4 need real Ghostscript/Tesseract — use the
existing `requires_ghostscript` / `requires_tesseract` skipifs. Cases
5, 6, 7 mock `run_pipeline` and run unconditionally.

## Out of scope for Phase 3 (deferred)

- **API endpoint integration test.** Phase 4 slates
  `tests/api_smoke.sh` (curl-based) for `/api/batch`. Adding an
  `httpx` test now duplicates that effort. The endpoint code itself
  is thin — `BackgroundTasks(run_batch, ...)` plus state-dict
  wiring — and the underlying logic is covered by `test_batch.py`.
- **GUI click-through test.** Streamlit doesn't have a great test
  runner; GUI smoke testing is Phase 5.
- **`POST /api/batch/{job_id}/cancel`.** Cancellation requires
  polling a `should_cancel` flag inside `run_batch` (since we run
  sequentially with no thread to interrupt). Not hard, but not free,
  and not in any current success criterion. Track for a later phase.
- **SQLite persistence for `batch_jobs`.** Explicitly Phase 4 work.
- **Wiring settings into the existing single-file CLI/GUI/API
  surfaces.** That is Phase 5 work and stays Phase 5 work — the
  pre-existing `ocr` / `compress` / `process` CLI commands and the
  single-file GUI/API forms keep their current hardcoded defaults
  (`preset="balanced"`, etc.) until Phase 5. Phase 3 deliberately
  does **not** retrofit them.

  The new batch surfaces — net-new code with no backwards-compat
  concern — read defaults from `get_config().settings` directly
  (`default_preset`, `default_language`, `default_jobs`). This is why
  the CLI options table above shows `default: settings.X` for batch
  flags. The implementation plan does not need to revisit this.

## Documentation updates as part of Phase 3

- `CLAUDE.md` — "Where I left off" → Phase 3 closed. "Known issues" →
  strike batch from the open list.
- `ROADMAP.md` — check Phase 3, note any items that slipped to a
  later phase.
- README — **not** updated. README polish is Phase 6.

## Success criteria (from ROADMAP)

- `pdf-ocr batch /path/to/folder/` runs end-to-end with size summary
  at end and `batch_report.json` written.
- One bad PDF in the middle of a batch doesn't kill the rest.
- API can be hit with `POST /api/batch` against a server-side folder
  path and returns a `job_id`; `GET /api/batch/{job_id}/status`
  returns the report when done.
- All Phase 1 / 2 / 3 tests pass; no regressions.
