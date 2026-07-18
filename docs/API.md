# pdf-ocr-compress API reference

REST API for the pdf-ocr-compress backend service. Designed to be
called from RAG ingestion pipelines that need OCR + compression on
large folders of scanned PDFs.

The server binds to port 8502 by default (`uv run python -m uvicorn
pdf_ocr_compress.api.server:app --port 8502`). There is no
authentication — single-machine assumption. Files processed via
`/api/process` and batch jobs queued via `/api/batch` are retained
for 1 hour and survive uvicorn restarts.

**Do not expose port 8502 to untrusted networks.** The API accepts
arbitrary server-side filesystem paths in `POST /api/batch` and has
no authentication. The single-machine assumption is the security
model; running this behind a reverse proxy without auth on a public
network — or passing `--host 0.0.0.0` to uvicorn on an open network
— would let any caller trigger processing of any directory the API
process can read.

## Quickstart

Process one PDF end-to-end with curl:

```bash
# Upload and process
RESPONSE=$(curl -sS -X POST "http://localhost:8502/api/process" \
  -F "file=@document.pdf" \
  -F "mode=auto" \
  -F "preset=smallest")

# Extract file_id from the JSON
FILE_ID=$(echo "$RESPONSE" | python -c "import sys, json; print(json.load(sys.stdin)['file_id'])")

# Download the processed file
curl -sS "http://localhost:8502/api/download/$FILE_ID" -o processed.pdf
```

Same flow in Python:

```python
import requests

with open("document.pdf", "rb") as f:
    r = requests.post(
        "http://localhost:8502/api/process",
        files={"file": f},
        data={"mode": "auto", "preset": "smallest"},
    )
r.raise_for_status()
result = r.json()
file_id = result["file_id"]

dl = requests.get(f"http://localhost:8502/api/download/{file_id}")
dl.raise_for_status()
with open("processed.pdf", "wb") as f:
    f.write(dl.content)
```

## Endpoint reference

### `GET /`

Service info and endpoint index. Useful for confirming the API is
reachable.

```bash
curl http://localhost:8502/
```

Response (JSON):

```json
{
  "service": "PDF OCR + Compression API",
  "version": "1.0.0",
  "endpoints": {
    "POST /api/process": "Process one PDF",
    "GET /api/download/{file_id}": "Download a processed PDF",
    "POST /api/batch": "Queue a folder-batch job",
    "GET /api/batch/{job_id}/status": "Poll a batch job",
    "GET /health": "Service + tool detection",
    "GET /docs": "Interactive OpenAPI docs"
  }
}
```

### `POST /api/process`

Process one PDF and return a `file_id` to retrieve the result with.

Form parameters:

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | file (multipart) | required | PDF to process. Filename must end in `.pdf`. |
| `mode` | string | `auto` | `auto` runs OCR only when needed; `ocr` always runs OCR; `compress` skips OCR. |
| `preset` | string | settings default (factory: `smallest`) | One of `archival`, `balanced`, `smallest`. **Recommended:** `smallest` for ScanSnap-family scanner output (the only preset that consistently shrinks; the size-invariant guard will fall back to `smallest` automatically if another preset would grow the file). |
| `language` | string | settings default (factory: `eng`) | Tesseract language codes joined by `+` (e.g. `eng`, `eng+spa`). |
| `pdfa` | bool | `false` | Produce PDF/A-2 output. See "PDF/A flag" below. |
| `force_ocr` | bool | `false` | Force OCR even if a text layer is already present. |
| `jobs` | int | settings default (factory: `4`) | Number of parallel OCR workers passed to OCRmyPDF. |
| `background` | bool | `false` | Return `202` immediately and process in the background. See "Background processing" below. Recommended for large files — the synchronous path holds the HTTP connection for the entire run (potentially hours). |

curl example:

```bash
curl -X POST "http://localhost:8502/api/process" \
  -F "file=@scan.pdf" \
  -F "mode=auto" \
  -F "preset=smallest" \
  -F "language=eng" \
  -F "jobs=4"
```

Python example:

```python
import requests

with open("scan.pdf", "rb") as f:
    r = requests.post(
        "http://localhost:8502/api/process",
        files={"file": f},
        data={
            "mode": "auto",
            "preset": "smallest",
            "language": "eng",
            "jobs": 4,
        },
    )
r.raise_for_status()
print(r.json())
```

Response: `ProcessResponse` (see schema section below).

Status codes:

- `200` — success (synchronous path)
- `202` — accepted (`background=true`; body `{"status": "queued", "job_id": "..."}`)
- `400` — `INPUT_NOT_PDF`, `INVALID_MODE`, `INVALID_PRESET`
- `413` — `FILE_TOO_LARGE` (only when `max_upload_bytes` is set)
- `422` — `VALIDATION_ERROR` (request body failed pydantic validation)
- `500` — `PROCESSING_FAILED`, `OUTPUT_GREW_NO_FALLBACK`
- `503` — `OCR_TOOL_MISSING`, `GHOSTSCRIPT_TOOL_MISSING`

#### Background processing

With `background=true` the endpoint validates the request, saves the
upload, and returns `202` with a `job_id` — only the pipeline run is
deferred. The `job_id` doubles as the `file_id`:

1. Poll `GET /api/batch/{job_id}/status` — same endpoint batch jobs use.
   `status` moves `queued` → `running` → `done` (or `error`, with the
   message in `error_msg`). On `done`, `report.process_result` carries
   the full `ProcessResult`.
2. Download with `GET /api/download/{job_id}`.

Notes: validation failures (bad mode/preset/file, `FILE_TOO_LARGE`) are
still synchronous 4xx responses — a `202` means the upload was accepted.
The 1-hour retention clock starts when processing completes, not when
the job is queued. If the server restarts mid-job, the job is marked
`error` ("server restarted mid-job") on the next startup, like any
batch job.

### `GET /api/download/{file_id}`

Retrieve the processed PDF for a given `file_id`. Returns the file
itself (`Content-Type: application/pdf`) with the original filename
preserved in the `Content-Disposition` header.

Files are retained for 1 hour after `/api/process` completes; after
that the row is deleted from the SQLite store and the on-disk artifact
is removed. Subsequent download requests return 404.

```bash
curl "http://localhost:8502/api/download/0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f" \
  -o processed.pdf
```

Status codes:

- `200` — success (binary PDF body)
- `404` — `FILE_NOT_FOUND` (unknown ID, or expired and cleaned up)

### `POST /api/batch`

Queue a folder-batch job. The folder must exist on the server's
filesystem; there is no upload mode for batch (it is designed for
folders local to the machine running the API).
Returns immediately with a `job_id`; processing runs in the
background.

JSON body:

| Field | Type | Default | Description |
|---|---|---|---|
| `folder` | string | required | Absolute path to a folder containing `*.pdf` files. Non-recursive. |
| `output_dir` | string | `<folder>/processed` | Absolute path; created if it doesn't exist (parent must be writable). |
| `mode` | string | `auto` | Same semantics as `/api/process`. |
| `preset` | string | settings default | Same semantics as `/api/process`. |
| `language` | string | settings default | Same semantics as `/api/process`. |
| `jobs` | int | settings default | Same semantics as `/api/process`. |
| `pdfa` | bool | `false` | Same semantics as `/api/process`. |
| `force_ocr` | bool | `false` | Same semantics as `/api/process`. |
| `force` | bool | `false` | Reprocess inputs whose same-name output already exists in `output_dir`. Batches are incremental by default: such inputs are skipped (`status: "skipped"` in the report), so re-running over a growing folder only processes new files. The check is existence-only — a rescanned input with an unchanged filename counts as done until `force` is used. On a forced rerun the fresh output **replaces the previous one in place** once processing succeeds; a failed rerun keeps the previous output. (Scoped exception to the never-overwrite rule: batch outputs only — inputs are never touched.) |

curl example:

```bash
curl -X POST "http://localhost:8502/api/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "folder": "/data/scans/incoming",
    "output_dir": "/data/scans/processed",
    "mode": "auto",
    "preset": "smallest"
  }'
```

Python example:

```python
import requests

r = requests.post(
    "http://localhost:8502/api/batch",
    json={
        "folder": "/data/scans/incoming",
        "output_dir": "/data/scans/processed",
        "mode": "auto",
        "preset": "smallest",
    },
)
r.raise_for_status()
job_id = r.json()["job_id"]
```

Response (`202 Accepted`):

```json
{
  "status": "queued",
  "job_id": "0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f",
  "total_files": 47
}
```

Status codes:

- `202` — queued
- `400` — `INVALID_MODE`, `INVALID_PRESET`, `INVALID_FOLDER`, `INVALID_OUTPUT_DIR`
- `422` — `VALIDATION_ERROR`

### `GET /api/batch/{job_id}/status`

Poll a batch job. Returns the job's current state and, once status is
`done`, the full `BatchReport`.

```bash
curl "http://localhost:8502/api/batch/0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f/status"
```

Response while running:

```json
{
  "job_id": "0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f",
  "status": "running",
  "started_at": "2026-04-29T14:30:22.123",
  "finished_at": null,
  "progress_current": 12,
  "progress_total": 47,
  "report": null,
  "error_msg": null
}
```

Response when done:

```json
{
  "job_id": "0e1d4a8b-3f96-4b3a-9c87-21be4d4d2c5f",
  "status": "done",
  "started_at": "2026-04-29T14:30:22.123",
  "finished_at": "2026-04-29T15:01:55.987",
  "progress_current": 47,
  "progress_total": 47,
  "report": { ...BatchReport... },
  "error_msg": null
}
```

Polling pattern in Python:

```python
import time
import requests

while True:
    r = requests.get(f"http://localhost:8502/api/batch/{job_id}/status")
    r.raise_for_status()
    state = r.json()
    if state["status"] in ("done", "error"):
        break
    print(f"{state['progress_current']}/{state['progress_total']}")
    time.sleep(5)

if state["status"] == "error":
    raise RuntimeError(state["error_msg"])

report = state["report"]
```

The `BatchReport` is also written to
`<output_dir>/batch_report.json` on disk; the on-disk file and the
`report` field share the same schema.

Batch jobs are retained for 1 hour after completion; after that the
row is removed from the SQLite store and `/status` returns 404.

Status codes:

- `200` — success
- `404` — `BATCH_JOB_NOT_FOUND` (unknown ID, or expired)

### `GET /health`

Reports environment state. Useful for monitoring; distinguishes "API
up" from "API up but Tesseract missing on PATH".

```bash
curl http://localhost:8502/health
```

Response:

```json
{
  "status": "healthy",
  "service": "pdf-ocr-compress-api",
  "version": "1.0.0",
  "ghostscript_binary": "C:\\Program Files\\gs\\gs10.04.0\\bin\\gswin64c.exe",
  "tesseract_binary": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
  "tesseract_languages": ["eng", "osd"],
  "queue_depth": 0
}
```

`ghostscript_binary` and `tesseract_binary` are `null` when the
respective binary is not on PATH. `tesseract_languages` is empty when
Tesseract isn't found or `--list-langs` fails. `queue_depth` is the
count of `queued` + `running` batch jobs.

`/health` always returns `200`; it never raises.

## ProcessResponse schema

Returned by `POST /api/process`. Every field is always present.

| Field | Type | Description |
|---|---|---|
| `status` | string | Always `"success"` for 200 responses. |
| `message` | string | Human-readable status message. |
| `file_id` | string | UUID for use with `/api/download/{file_id}`. |
| `mode` | string | The mode the request was processed in. |
| `preset` | string | The preset that was *requested*. May differ from `preset_actually_used` if the size-invariant guard fired. |
| `original_size` | int | Input file size in bytes. |
| `output_size` | int | Output file size in bytes. |
| `reduction_percent` | float | Positive when output is smaller. Same magnitude as `pct_change`, opposite sign. |
| `processing_time` | float | Wall-clock seconds. |
| `ocr_ran` | bool | Whether OCR was executed. |
| `ocr_skipped_reason` | string \| null | Reason OCR was skipped. `null` when OCR ran. Short snake_case tokens; current values are `"input_has_text_layer"` (auto-routing detected an existing text layer) and `"compress_only_mode"` (caller passed `mode=compress`). |
| `preset_actually_used` | string | The preset that produced the output file. May differ from `preset` if the requested preset would have grown the file (oversize fallback ladder: requested → `smallest` → passthrough). |
| `pdfminer_text_extractable` | bool | Post-hoc fidelity check, derived from the coverage fields below (`text_pages_with_text > 0`). A `false` value when `ocr_ran` is `true` indicates a serious problem (OCR ran but produced no extractable text layer). |
| `pct_change` | float | Negative when output shrunk; positive when output grew. |
| `text_pages_sampled` | int | Pages probed for extractable text: up to 10, spread evenly across the output (always including first and last). `0` when the output could not be parsed. |
| `text_pages_with_text` | int | Sampled pages with any extractable text. A value below `text_pages_sampled` means partial coverage — some pages are image-only to a RAG ingestion pipeline. |
| `text_words` | int | Whitespace-delimited words extracted across the sampled pages. A per-file gating signal for downstream ingestion. |

The `original_size` / `output_size` / `reduction_percent` /
`processing_time` block is kept for back-compat with consumers that
branch on the older field names. The newer
fields (`ocr_ran`, `ocr_skipped_reason`, `preset_actually_used`,
`pdfminer_text_extractable`, `pct_change`) describe the same
operation in more detail.

## BatchReport schema

The `report` field returned by `GET /api/batch/{job_id}/status` (when
`status == "done"`) and the contents of `<output_dir>/batch_report.json`
share this schema.

```text
BatchReport
  input_dir          : string  (absolute path)
  output_dir         : string  (absolute path)
  total_files        : int
  succeeded          : int
  failed             : int
  skipped            : int  (inputs skipped because their output already existed)
  started_at         : string  (ISO-8601, millisecond precision)
  finished_at        : string  (ISO-8601, millisecond precision)
  total_seconds      : float
  total_input_bytes  : int  (processed files only; skipped excluded)
  total_output_bytes : int  (successful files only)
  results            : [ BatchResult, ... ]

BatchResult
  input_path     : string  (absolute path)
  output_path    : string | null  (absolute path; null if file failed;
                   for skipped files, the pre-existing output)
  status         : "ok" | "failed" | "skipped"
  attempts       : 0 | 1 | 2 | 3   (0 = skipped; see "Failure ladder" below)
  error_msg      : string | null
  process_result : ProcessResult | null
                   (full per-file report for successes; null otherwise)

ProcessResult  (the per-file report inside BatchResult.process_result)
  input_path                 : string
  output_path                : string
  input_bytes                : int
  output_bytes               : int
  pct_change                 : float
  ocr_ran                    : bool
  ocr_skipped_reason         : string | null
  preset_actually_used       : string
  pdfminer_text_extractable  : bool  (derived: text_pages_with_text > 0)
  processing_seconds         : float
  text_pages_sampled         : int   (sampled text coverage — see the
  text_pages_with_text       : int    ProcessResponse field table)
  text_words                 : int
```

`results` is in the same order as the input folder's `*.pdf` glob
(sorted by path).

## Failure ladder (per file in a batch)

A bad PDF in the middle of a batch does not abort the rest. Each file
gets up to three attempts:

1. **Initial attempt** — the file is processed.
2. **Immediate retry** — on failure, the file is processed again
   right away.
3. **End-of-batch retry** — if both attempts failed, the file is
   queued for one more attempt after every other file in the batch
   has been processed.

A file that succeeds on any attempt is recorded with `attempts` equal
to the count it took (1, 2, or 3). A file that fails all three is
recorded with `status="failed"`, `attempts=3`, and the most recent
exception's message in `error_msg`.

## Error responses

Every 4xx/5xx response uses a single canonical JSON shape:

```json
{
  "error_code": "INPUT_NOT_PDF",
  "message": "File must be a PDF",
  "suggestions": []
}
```

| Field | Type | Description |
|---|---|---|
| `error_code` | string | Stable machine-readable identifier. Branch consumer code on this. |
| `message` | string | Human-readable English. |
| `suggestions` | string[] | Optional remediation hints; may be empty. Sourced from internal `PDFProcessingError.suggestions`. |

Stable error codes:

| Code | Status | Meaning |
|---|---|---|
| `INPUT_NOT_PDF` | 400 | Uploaded file is not a PDF. |
| `INVALID_MODE` | 400 | `mode` must be `auto`, `ocr`, or `compress`. |
| `INVALID_PRESET` | 400 | `preset` must be `archival`, `balanced`, or `smallest`. |
| `INVALID_FOLDER` | 400 | The `folder` path doesn't exist or isn't a directory. |
| `INVALID_OUTPUT_DIR` | 400 | The `output_dir` (or its parent for non-existent dirs) is not writable. |
| `FILE_NOT_FOUND` | 404 | `file_id` is unknown or has expired (1-hour TTL). |
| `BATCH_JOB_NOT_FOUND` | 404 | `job_id` is unknown or has expired (1-hour TTL). |
| `OCR_TOOL_MISSING` | 503 | Tesseract not on PATH or unable to run. |
| `GHOSTSCRIPT_TOOL_MISSING` | 503 | Ghostscript not on PATH. |
| `PROCESSING_FAILED` | 500 | Pipeline raised an unhandled exception. |
| `OUTPUT_GREW_NO_FALLBACK` | 500 | Size-invariant guard fired with `oversize_policy=fail`. |
| `VALIDATION_ERROR` | 422 | Request body failed pydantic validation; per-field details in `suggestions`. |
| `FILE_TOO_LARGE` | 413 | Upload exceeds the `max_upload_bytes` setting. Only emitted when that setting is nonzero (factory default `0` = unlimited). |

## PDF/A flag

The `pdfa` flag (form field on `/api/process`, JSON field on
`/api/batch`, `--pdfa` on the CLI) requests PDF/A-2 output —
self-contained, archival-grade PDFs with embedded fonts and color
profiles, suitable for legal or long-term storage.

PDF/A files are typically larger than non-PDF/A. The size-invariant
guard still applies: if `--pdfa` produces output larger than the
input, the request falls back per `oversize_policy` (default
`fallback`, which retries with `smallest` and then with passthrough
if even `smallest` would grow the file).

PDF/A is only meaningful when there is a text layer. If `mode=compress`
and the input has no OCR layer, requesting `pdfa=true` produces an
archival-format file whose textual content is still image-only.

## Notes for integrators

- **Retention.** Files from `/api/process` are retained 1 hour after
  the response is returned. Batch jobs are retained 1 hour after
  completion. Both survive uvicorn restarts (SQLite-backed).
- **Server-side folders.** `/api/batch` requires the API process to
  have read access to `folder`. There is no upload-batch mode.
- **Single machine.** No auth, no rate limiting, no per-user
  isolation. Run behind a reverse proxy if you need any of those.
- **Interactive docs.** `/docs` (Swagger UI) is generated from the
  same OpenAPI schema this document describes; it's the canonical
  cross-check if anything here goes out of date.
- **Uploads stream to disk in 16 MB chunks.** The `/api/process`
  endpoint no longer buffers the whole upload in memory, so multi-GB
  uploads are safe RAM-wise (they still cost upload time; for very
  large local files, `POST /api/batch` with a server-side folder path
  avoids the upload entirely). An upload size limit is off by default;
  set `max_upload_bytes` in settings (or the `PDF_OCR_MAX_UPLOAD_BYTES`
  env var) to a nonzero byte count to reject larger uploads with
  `FILE_TOO_LARGE` (HTTP 413).
