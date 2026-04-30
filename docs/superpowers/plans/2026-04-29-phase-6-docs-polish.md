# Phase 6 Documentation Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `README.md`, public docs, and `CLAUDE.md` into alignment with the Phase 1–5 codebase, factor API material into `docs/API.md`, refresh stale Streamlit screenshots, drop residual n8n scaffolding, and close the roadmap.

**Architecture:** Pure documentation work in four sequential commits on `main`. No source files in `src/` are modified. Each commit is independently reviewable. Source-of-truth files (`api/errors.py`, `api/server.py`, `core/batch.py`) are read at write time so docs match what is exported, not what is remembered.

**Tech Stack:** Markdown, Playwright MCP server (for screenshot capture against a local Streamlit instance), `git`, `uv`.

**Spec:** `docs/superpowers/specs/2026-04-29-phase-6-docs-design.md` (committed as `5af5eda`).

---

## Context for the implementing engineer

You are operating in a Windows + bash environment (`<repo>`). All `git` commits should be authored by the user's standard identity — do not pass `--no-verify` and do not change `git config`.

You have these tools available without further setup:

- `uv` (Python package manager). The project's venv is `.venv/` at the repo root.
- `git` (current branch is `main`).
- The Playwright MCP server (`mcp__plugin_playwright_playwright__browser_*` tools).

**Three project rules to keep in front of you while working:**

1. **CLAUDE.md is the source of truth for project conventions.** Re-read it before touching `CLAUDE.md` or anywhere it's referenced.
2. **The repo is public.** Any new docs must not include the user's email, full name beyond the public git identity, or local file paths under `G:\My Drive\...`. Use generic example paths (`/data/scans/incoming`).
3. **Match existing markdown style.** Blank line after every heading and around list blocks; no emphasis inside headings; bare URLs wrapped in angle brackets; always specify a code-fence language (`bash`, `python`, `text`, `json`, `dockerfile`).

If at any task you find a contradiction between this plan and what the source actually exports today, stop and surface the contradiction — do not silently paper over it.

---

## File Structure

**Files this plan deletes:**

- `N8N_BATCH_WORKFLOW.md` (Task 1)
- `images/n8n_simple.png` (Task 1)

**Files this plan modifies:**

- `images/streamlit_starting_ui.png` (Task 2 — content replaced; filename retained)
- `images/streamlit_processing_ui.png` (Task 2 — content replaced; filename retained, new content is the Batch tab not the spinner)
- `images/streamlit_ending_ui.png` (Task 2 — content replaced; filename retained)
- `README.md` (Task 1 partial deletion of n8n section; Task 4 full rewrite)
- `CLAUDE.md` (Task 4 — "Where I left off" replaced; "Known issues / tech debt" merged into "Open debt"; nothing else touched)

**Files this plan creates:**

- `docs/API.md` (Task 3)

**Files outside the repo that this plan updates** (not under `git`):

- `<user-claude-memory-dir>/project_phase_status.md` (Task 5)
- `<user-claude-memory-dir>/MEMORY.md` (Task 5 — one-line index update)

**Files this plan must not touch:**

- Anything under `src/`
- `pyproject.toml`, `uv.lock`, `requirements.txt`
- `BENCHMARKS.md` (already accurate; the README cites Sample B from it)
- `CLAUDE.local.md` (gitignored personal notes)
- `tests/`

---

## Task 1: Drop n8n integration scaffolding

**Why first:** deletion-only commit. Removes content the README rewrite would otherwise have to rewrite. Smallest blast radius; cleanest review.

**Files:**

- Delete: `N8N_BATCH_WORKFLOW.md`
- Delete: `images/n8n_simple.png`
- Modify: `README.md` (remove the n8n section and the link to `N8N_BATCH_WORKFLOW.md`)

- [ ] **Step 1.1: Verify clean working tree before starting**

Run:

```bash
git status --short
```

Expected: empty output. If anything is staged or modified, stop and surface it before proceeding.

- [ ] **Step 1.2: Delete the n8n workflow doc and screenshot**

Run:

```bash
git rm N8N_BATCH_WORKFLOW.md images/n8n_simple.png
```

Expected output (similar):

```text
rm 'N8N_BATCH_WORKFLOW.md'
rm 'images/n8n_simple.png'
```

- [ ] **Step 1.3: Remove the n8n section from `README.md`**

Use `Edit` to remove the entire `### n8n Integration` block from `README.md`. The block to delete (verify exact text by reading the current `README.md` first; the block starts with `### n8n Integration` and ends with the line referencing `N8N_BATCH_WORKFLOW.md`):

```markdown
### n8n Integration

![n8n Workflow Example](images/n8n_simple.png)

1. Add **HTTP Request** node
2. Method: `POST`
3. URL: `http://localhost:8502/api/process`
4. Body Content Type: `Multipart-Form`
5. Add fields:
   - `file` (binary data from previous node)
   - `mode` = `auto`
   - `preset` = `balanced`
6. Add second **HTTP Request** node to download using `file_id` from response

See [N8N_BATCH_WORKFLOW.md](N8N_BATCH_WORKFLOW.md) for complete workflow examples including Google Drive and Dropbox integration.

```

Replace the entire block (and the trailing blank line) with nothing. Do not adjust other surrounding sections — those get the larger rewrite in Task 4.

- [ ] **Step 1.4: Verify the README no longer references n8n**

Run:

```bash
git grep -n -i "n8n" README.md || echo "no matches"
```

Expected: `no matches`.

Also verify there are no other lingering references:

```bash
git grep -n -i "n8n" -- ':!docs/superpowers/' || echo "no matches"
```

Expected: `no matches`. (`:!docs/superpowers/` excludes the spec/plan files which legitimately reference n8n in their decision rationale.)

- [ ] **Step 1.5: Commit**

Run:

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: drop n8n integration scaffolding

The n8n workflow doc and screenshot were added in the initial-commit
era and predate Phase 3's /api/batch endpoint — they show n8n calling
/api/process in a per-file loop, which is no longer the right pattern.
n8n is also not the actual integration target for this project; it
was leftover marketing scaffolding.

- delete N8N_BATCH_WORKFLOW.md
- delete images/n8n_simple.png
- remove the n8n section + cross-link from README.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit creates one commit, three files changed (one binary image deletion, two text deletions / edits).

---

## Task 2: Refresh README screenshots for Phase 5 GUI

**Why before the README rewrite:** The README rewrite (Task 4) will reference the new screenshot content. Capturing screenshots first means Task 4 can write captions against known images rather than against placeholders.

**Files:**

- Modify: `images/streamlit_starting_ui.png` (binary; replaced)
- Modify: `images/streamlit_processing_ui.png` (binary; replaced — new content is the **Batch** tab, not the processing spinner; filename is retained so README link doesn't churn during this commit)
- Modify: `images/streamlit_ending_ui.png` (binary; replaced)

**Capture protocol:**

The GUI runs locally on the same machine as Claude Code. Streamlit serves on `http://localhost:8501`. Capture is driven via the Playwright MCP browser tools. The GUI process is started with `Bash run_in_background: true` and torn down at the end of the task.

- [ ] **Step 2.1: Start the GUI in the background**

Run (background):

```bash
uv run pdf-ocr-gui
```

Use `run_in_background: true`. Capture the returned shell ID — you will need it to read logs and to kill the GUI at the end.

- [ ] **Step 2.2: Wait for Streamlit to be ready**

Read the background shell's output (use the `BashOutput` tool with the captured shell ID) until you see one of these readiness signals:

```text
You can now view your Streamlit app in your browser.
Local URL: http://localhost:8501
```

If after ~15 seconds there is no readiness line, stop and surface the issue (likely missing dependency or port conflict).

- [ ] **Step 2.3: Open the GUI in the headless browser**

Run:

```text
mcp__plugin_playwright_playwright__browser_navigate({url: "http://localhost:8501"})
```

Then take a snapshot to confirm the Streamlit app loaded:

```text
mcp__plugin_playwright_playwright__browser_snapshot()
```

Expected: snapshot shows the Streamlit chrome, the sidebar, and the main page tabs ("Single File", "Batch", or whatever the current Phase 5 GUI labels them — confirm by reading `src/pdf_ocr_compress/gui/basic.py` if labels are unclear).

- [ ] **Step 2.4: Capture screenshot 1 — `streamlit_starting_ui.png` (sidebar Defaults open + Single-file tab empty)**

Open the sidebar `⚙️ Defaults` expander by clicking it (use `browser_snapshot` first to grab the element ref, then `browser_click`). Confirm via another snapshot that the expander is open and showing the form (default preset, default language, jobs, default output dir, batch concurrency, oversize policy, Tesseract timeout, Save button).

Confirm the Single-file tab is selected (it is the default in the current GUI; do not change tabs yet).

Capture:

```text
mcp__plugin_playwright_playwright__browser_take_screenshot({
  filename: "streamlit_starting_ui.png",
  fullPage: false,
  type: "png"
})
```

Move the captured PNG to `images/streamlit_starting_ui.png` (overwriting the existing file). The screenshot tool's default save location is platform-dependent; if necessary, capture to a temporary path and `mv` it. Verify with:

```bash
ls -l images/streamlit_starting_ui.png
```

- [ ] **Step 2.5: Capture screenshot 2 — `streamlit_processing_ui.png` (Batch tab with folder picker, no processing in progress)**

Click into the Batch tab. Confirm via `browser_snapshot` that the visible UI shows:

- Plain-language label for the input folder ("Folder of PDFs to process" or whatever the current label is — confirm against `gui/basic.py`)
- The native-folder-picker Browse button next to the input field
- The output-folder field with its own Browse button
- The resolver-summary preview line (shown once a folder path is typed in)

Optional: type a sample folder path into the input (e.g. `<repo>\pdfs`) so the resolver-summary preview ("N PDFs, X.X MB total") is visible in the screenshot. Use a generic-looking path; do not include personal Drive paths.

Capture:

```text
mcp__plugin_playwright_playwright__browser_take_screenshot({
  filename: "streamlit_processing_ui.png",
  fullPage: false,
  type: "png"
})
```

Move to `images/streamlit_processing_ui.png` (overwriting the existing file).

- [ ] **Step 2.6: Capture screenshot 3 — `streamlit_ending_ui.png` (post-process structured report)**

Switch back to the Single-file tab. Pick a small test fixture from the repo to upload — first list candidates:

```bash
ls -la tests/*.pdf 2>/dev/null; ls -la pdfs/sample*.pdf pdfs/test*.pdf 2>/dev/null
```

Use the smallest available `.pdf`. If no test PDF is committed in the repo, use one of the gitignored `pdfs/*.pdf` files; the screenshot does not commit the input file itself.

Upload the file via the Streamlit uploader (use `browser_file_upload` with the file's absolute path). Click the "Process" / "Start Processing" / equivalent button (verify exact label by snapshot). Wait for the success state.

Confirm the success state shows the structured report block — fields visible should include:

- Input bytes / Output bytes
- `pct_change` or "size change %"
- `preset_actually_used`
- OCR routing (`ocr_ran` / `ocr_skipped_reason`)
- `pdfminer_text_extractable` (or its plain-language equivalent)
- Download button

Capture:

```text
mcp__plugin_playwright_playwright__browser_take_screenshot({
  filename: "streamlit_ending_ui.png",
  fullPage: false,
  type: "png"
})
```

Move to `images/streamlit_ending_ui.png`.

- [ ] **Step 2.7: Tear down the browser and the background GUI**

Close the browser:

```text
mcp__plugin_playwright_playwright__browser_close()
```

Kill the background GUI shell using the shell ID captured in step 2.1:

```text
KillShell({shell_id: "<the captured ID>"})
```

- [ ] **Step 2.8: Verify the three images are present and non-empty**

Run:

```bash
ls -l images/streamlit_starting_ui.png images/streamlit_processing_ui.png images/streamlit_ending_ui.png
```

Expected: three files, each > 10 KB. (PNG screenshots of a Streamlit UI are typically 50–300 KB.)

Open one of the images locally to eyeball the result if you can — the `Read` tool can read PNGs.

- [ ] **Step 2.9: Commit**

Run:

```bash
git add images/streamlit_starting_ui.png images/streamlit_processing_ui.png images/streamlit_ending_ui.png
git commit -m "$(cat <<'EOF'
docs: refresh README screenshots for Phase 5 GUI

The committed screenshots predated Phase 5 and showed none of the
sidebar Defaults expander, Batch tab with folder picker, or structured
report. Replaced all three:

- streamlit_starting_ui.png — sidebar Defaults open, Single-file tab
  empty
- streamlit_processing_ui.png — repurposed: now shows the Batch tab
  with native folder picker (more informative than a stale
  "processing spinner" shot)
- streamlit_ending_ui.png — post-process success state showing the
  structured ProcessResult report

Filenames retained so README links remain valid; README captions are
rewritten in the Task-4 README rewrite.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit, three binary files modified.

---

## Task 3: Add `docs/API.md` with full endpoint reference

**Why before the README rewrite:** The README will link to `docs/API.md`; the file must exist before the link is added in Task 4.

**Files:**

- Create: `docs/API.md`

**Source-of-truth reads required before writing:**

- `src/pdf_ocr_compress/api/errors.py` — error code list (already known: `INPUT_NOT_PDF`, `INVALID_MODE`, `INVALID_PRESET`, `INVALID_FOLDER`, `INVALID_OUTPUT_DIR`, `FILE_NOT_FOUND`, `BATCH_JOB_NOT_FOUND`, `OCR_TOOL_MISSING`, `GHOSTSCRIPT_TOOL_MISSING`, `PROCESSING_FAILED`, `OUTPUT_GREW_NO_FALLBACK`, `VALIDATION_ERROR`, `FILE_TOO_LARGE`-reserved). The wire shape is `{error_code, message, suggestions: list[str]}` — there is no `detail` field.
- `src/pdf_ocr_compress/api/server.py` — endpoint signatures, `ProcessResponse` field list, `BatchRequest` body, `BatchAcceptedResponse` body, `/health` response shape.
- `src/pdf_ocr_compress/core/batch.py` — `BatchReport` and `BatchResult` dataclass field lists.
- `src/pdf_ocr_compress/core/pipeline.py` — `ProcessResult` field list (used for the `process_result` field nested inside each `BatchResult`).

If any field name in the doc you write does not match what these source files export, the doc is wrong; correct it before committing.

- [ ] **Step 3.1: Read all source-of-truth files**

Use the `Read` tool on each of:

- `src/pdf_ocr_compress/api/errors.py`
- `src/pdf_ocr_compress/api/server.py`
- `src/pdf_ocr_compress/core/batch.py`
- `src/pdf_ocr_compress/core/pipeline.py`

Note specifically: the `ProcessResult` field list (this becomes the nested schema in `BatchResult.process_result`).

- [ ] **Step 3.2: Write `docs/API.md`**

Use `Write` with the file path `<repo>\docs\API.md`. The full content to write:

`````markdown
# pdf-ocr-compress API reference

REST API for the pdf-ocr-compress backend service. Designed to be
called from RAG ingestion pipelines that need OCR + compression on
large folders of scanned PDFs.

The server binds to port 8502 by default (Docker, `start_services.sh`,
or `uv run python -m uvicorn pdf_ocr_compress.api.server:app --port 8502`).
There is no authentication — single-machine assumption. Files
processed via `/api/process` and batch jobs queued via `/api/batch`
are retained for 1 hour and survive uvicorn restarts (SQLite-backed,
Phase 4).

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
| `preset` | string | `balanced` | One of `archival`, `balanced`, `smallest`. **Recommended:** `smallest` for ScanSnap-family scanner output (the only preset that consistently shrinks; the size-invariant guard will fall back to `smallest` automatically if another preset would grow the file). |
| `language` | string | `eng` | Tesseract language codes joined by `+` (e.g. `eng`, `eng+spa`). |
| `pdfa` | bool | `false` | Produce PDF/A-2 output. See "PDF/A flag" below. |
| `force_ocr` | bool | `false` | Force OCR even if a text layer is already present. |
| `jobs` | int | `4` | Number of parallel OCR workers passed to OCRmyPDF. |

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

- `200` — success
- `400` — `INPUT_NOT_PDF`, `INVALID_MODE`, `INVALID_PRESET`
- `422` — `VALIDATION_ERROR` (request body failed pydantic validation)
- `500` — `PROCESSING_FAILED`, `OUTPUT_GREW_NO_FALLBACK`
- `503` — `OCR_TOOL_MISSING`, `GHOSTSCRIPT_TOOL_MISSING`

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
folders mounted into the container or local to the API process).
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
| `ocr_skipped_reason` | string \| null | Reason OCR was skipped. `null` when OCR ran. Common values include `"input already has text layer"`. |
| `preset_actually_used` | string | The preset that produced the output file. May differ from `preset` if the requested preset would have grown the file (oversize fallback ladder: requested → `smallest` → passthrough). |
| `pdfminer_text_extractable` | bool | Post-hoc fidelity check: pdfminer was able to extract text from the output. A `false` value when `ocr_ran` is `true` indicates a serious problem (Phase 0 bug #3 territory). |
| `pct_change` | float | Negative when output shrunk; positive when output grew. |

The `original_size` / `output_size` / `reduction_percent` /
`processing_time` block predates Phase 2 and is kept for back-compat
with consumers that branch on the older field names. The newer
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
  started_at         : string  (ISO-8601, millisecond precision)
  finished_at        : string  (ISO-8601, millisecond precision)
  total_seconds      : float
  total_input_bytes  : int
  total_output_bytes : int  (successful files only)
  results            : [ BatchResult, ... ]

BatchResult
  input_path     : string  (absolute path)
  output_path    : string | null  (absolute path; null if file failed)
  status         : "ok" | "failed"
  attempts       : 1 | 2 | 3   (see "Failure ladder" below)
  error_msg      : string | null
  process_result : ProcessResult | null
                   (full per-file report for successes; null for failures)

ProcessResult  (the per-file report inside BatchResult.process_result)
  input_path                 : string
  output_path                : string
  input_bytes                : int
  output_bytes               : int
  pct_change                 : float
  ocr_ran                    : bool
  ocr_skipped_reason         : string | null
  preset_actually_used       : string
  pdfminer_text_extractable  : bool
  processing_seconds         : float
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
| `FILE_TOO_LARGE` | reserved | Reserved for a future upload-size limit. Not currently emitted; consumers can wire branches against it now. |

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
  completion. Both survive uvicorn restarts (Phase 4 SQLite
  persistence).
- **Server-side folders.** `/api/batch` requires the API process to
  have read access to `folder`. There is no upload-batch mode.
- **Single machine.** No auth, no rate limiting, no per-user
  isolation. Run behind a reverse proxy if you need any of those.
- **Interactive docs.** `/docs` (Swagger UI) is generated from the
  same OpenAPI schema this document describes; it's the canonical
  cross-check if anything here goes out of date.
`````

- [ ] **Step 3.3: Verify the file matches the source code**

Run the following sanity checks:

```bash
# All error codes documented above must be exported by api/errors.py
for code in INPUT_NOT_PDF INVALID_MODE INVALID_PRESET INVALID_FOLDER INVALID_OUTPUT_DIR FILE_NOT_FOUND BATCH_JOB_NOT_FOUND OCR_TOOL_MISSING GHOSTSCRIPT_TOOL_MISSING PROCESSING_FAILED OUTPUT_GREW_NO_FALLBACK VALIDATION_ERROR FILE_TOO_LARGE; do
  grep -q "^$code:" src/pdf_ocr_compress/api/errors.py && echo "OK: $code" || echo "MISSING: $code"
done
```

Expected: `OK:` for every code. Any `MISSING:` means either the doc invented a code or the source removed one — investigate before continuing.

```bash
# All ProcessResponse fields documented above must be on the model
grep -E "^    (status|message|file_id|mode|preset|original_size|output_size|reduction_percent|processing_time|ocr_ran|ocr_skipped_reason|preset_actually_used|pdfminer_text_extractable|pct_change):" src/pdf_ocr_compress/api/server.py | wc -l
```

Expected: `14` (every field listed in the table is on the model).

```bash
# All BatchReport fields documented must be on the dataclass
grep -E "^    (input_dir|output_dir|total_files|succeeded|failed|started_at|finished_at|total_seconds|total_input_bytes|total_output_bytes|results):" src/pdf_ocr_compress/core/batch.py | wc -l
```

Expected: `11` (every field).

If any count is wrong, re-read the source and fix `docs/API.md` before committing.

- [ ] **Step 3.4: Render-check the markdown**

Run:

```bash
git diff --stat
```

Expected: `docs/API.md` listed, ~600 lines added.

Read the file back via `Read` and visually confirm:

- All code fences have a language tag (`bash`, `python`, `json`, `text`).
- Tables render (no broken pipes).
- All cross-section anchor references resolve (none defined in this doc; OK).

- [ ] **Step 3.5: Commit**

Run:

```bash
git add docs/API.md
git commit -m "$(cat <<'EOF'
docs: add docs/API.md with full endpoint reference

Reference document for the pdf-ocr-compress backend API. Covers all
six endpoints (/, /api/process, /api/download/{id}, /api/batch,
/api/batch/{id}/status, /health) with curl + Python requests
examples, full ProcessResponse + BatchReport + APIError schemas,
the per-file failure ladder, the stable error code table, and
PDF/A flag semantics across all surfaces.

Source-of-truth checks: error codes verified against api/errors.py;
ProcessResponse fields verified against api/server.py; BatchReport
fields verified against core/batch.py.

README link to this doc is added in the Phase 6 README rewrite
commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit, one new file (~600 lines).

---

## Task 4: Rewrite README + close Phase 6 in CLAUDE.md

**Why combined:** The README rewrite and the CLAUDE.md status update are both closing acts of Phase 6 and reference each other (the README assumes the docs structure described in CLAUDE.md; CLAUDE.md describes the new README state). Shipping them in one commit means main is never in a state where one is updated and the other isn't.

**Files:**

- Modify: `README.md` (full rewrite)
- Modify: `CLAUDE.md` (replace "Where I left off" block; merge "Known issues / tech debt" into "Open debt")

- [ ] **Step 4.1: Re-read current `README.md` and current `CLAUDE.md`**

Use `Read` on both. Note specifically:

- The current `CLAUDE.md` "Where I left off" content (the long Phase 5 narrative) — this is what gets replaced.
- The current `CLAUDE.md` "Known issues / tech debt" content — its items get folded into the new "Open debt" section.
- Any sections of `README.md` that already contain useful prose worth keeping (e.g. troubleshooting tips that are still accurate) — preserve them where they fit the new structure.

- [ ] **Step 4.2: Write the new `README.md`**

Use `Write` to overwrite `README.md`. Full new content:

`````markdown
# pdf-ocr-compress

A backend service for turning scanned PDFs into clean, searchable,
RAG-ready files at scale. Wraps OCRmyPDF (Tesseract) and Ghostscript +
pikepdf around a single pipeline, exposed through three first-class
clients:

- **GUI** (Streamlit, single page) — easiest place to start; drag a
  file in, get a processed file out.
- **Docker / REST API** (FastAPI) — the load-bearing surface for
  programmatic use; designed to be called from other apps that
  ingest folders of scanned books into LLM/RAG pipelines.
- **CLI** (Typer) — for scripting and cron jobs.

Single-machine, single-user. No auth, no telemetry, no remote
services.

**Real-world result:** 4.8 GB color textbook scan → 198 MB (-95.9%),
text layer preserved end-to-end. (Sample B from `BENCHMARKS.md`.)

## What it does

- Adds searchable text layers to scanned PDFs via Tesseract OCR.
- Compresses without destroying the OCR text layer (the post-OCR
  Ghostscript pass that strips fonts is explicitly disabled).
- Enforces output ≤ input — never silently grows the file. If the
  requested preset would grow the file, falls back to a working
  preset, or to a passthrough copy if even `smallest` grows it.
- Auto-detects which PDFs already have a text layer and skips OCR
  on those (using a tolerant pikepdf-based check, not pdfminer).
- Folder-batch mode with a per-file retry ladder and a structured
  JSON report.

## Quick start

### Web GUI (easiest)

The GUI is a single Streamlit page with two tabs (Single file,
Batch) and a sidebar for default settings.

```bash
uv sync                # one-time setup; reads pyproject.toml + uv.lock
uv run pdf-ocr-gui     # serves http://localhost:8501
```

![Starting interface — sidebar Defaults open, Single-file tab](images/streamlit_starting_ui.png)

Switch to the Batch tab to process a folder of PDFs at once. The
"Browse" buttons open a native folder picker (works because this is
a local-machine app — same machine as the browser).

![Batch tab with native folder picker](images/streamlit_processing_ui.png)

After processing, the GUI shows a structured report — input vs
output size, which preset was actually used (the size-invariant
guard may have substituted `smallest`), whether OCR ran, and a
post-hoc text-extractability smoke check.

![Post-process structured report](images/streamlit_ending_ui.png)

### Docker / backend service

The Docker image runs the GUI and the API together. Compose is the
easiest way:

```bash
docker-compose up
# GUI:      http://localhost:8501
# API:      http://localhost:8502
# API docs: http://localhost:8502/docs   (interactive Swagger UI)
```

To add Tesseract languages, edit the `apt-get install` line in
`Dockerfile` (e.g. `tesseract-ocr-spa tesseract-ocr-fra`) and
rebuild.

**Calling the API from another app?** See [`docs/API.md`](docs/API.md)
for the full endpoint reference, request/response schemas, error
codes, and curl + Python examples.

### Command line

The CLI has four subcommands: `process` (auto-route to OCR or
compress), `ocr`, `compress`, and `batch`.

```bash
# Single file — auto-routes to OCR or compress
uv run pdf-ocr process input.pdf output.pdf

# Folder of PDFs (writes <folder>/processed/ + batch_report.json)
uv run pdf-ocr batch /path/to/scans --preset smallest

# OCR only, with a specific language
uv run pdf-ocr ocr scan.pdf scan_ocr.pdf --lang eng+spa

# Compress only, with a specific preset
uv run pdf-ocr compress big.pdf small.pdf --preset smallest

# See all flags
uv run pdf-ocr --help
```

Batch mode applies the same per-file failure ladder as the API: each
PDF gets an initial attempt, an immediate retry on failure, and one
end-of-batch retry. One bad PDF doesn't kill the rest. The full
report is written to `<output_dir>/batch_report.json` (schema in
[`docs/API.md`](docs/API.md#batchreport-schema)).

## System requirements

- **Python 3.10+** (declared in `pyproject.toml`).
- **Tesseract OCR** on PATH, with the language packs you need.
- **Ghostscript** on PATH (auto-detects `gswin64c` / `gswin32c` /
  `gs`).
- **uv** is recommended; `pip install -r requirements.txt` works
  too. The Docker image installs everything.

### Installing system tools

Windows:

```powershell
winget install UB-Mannheim.TesseractOCR
winget install AGPL.Ghostscript
```

macOS:

```bash
brew install tesseract tesseract-lang ghostscript
```

Linux (Debian/Ubuntu):

```bash
sudo apt install tesseract-ocr ghostscript
```

## Quality presets

Three named presets, defined in `core/compress.py`:

| Preset | Description | Use case |
|---|---|---|
| `smallest` | **Default.** Maximum compression. The only preset that consistently shrinks scanner output across sizes and color depths. | General use; everything that ends up in a RAG corpus. |
| `balanced` | Moderate compression; may grow already-compressed scanner output. | Mixed-content documents. |
| `archival` | Minimal compression; preserves original quality. May significantly grow scanner output. | Legal documents, archival. |

The size-invariant guard runs after every compression pass. If the
requested preset would grow the file, the pipeline falls back to
`smallest`; if even `smallest` would grow the file, the input is
passed through unchanged. The response (or CLI summary) reports the
preset that was actually used in `preset_actually_used`.

## Output naming

All operations create new files with microsecond-precision
timestamps; originals are never overwritten:

- `<stem>_processed_<timestamp>.pdf`
- `<stem>_ocr_<timestamp>.pdf`
- `<stem>_compressed_<timestamp>.pdf`

## Troubleshooting

"Command not found" errors:

- Verify the system tools are reachable: `tesseract --version` and
  `gs --version` (or `gswin64c -v` on Windows).
- On Windows: restart your shell after installing — the new PATH
  entries don't apply to existing sessions.

OCR accuracy issues:

- Scanned documents need at least 300 DPI for reliable OCR.
- Specify the right `--lang` codes for the document's languages.

Output is unexpectedly large:

- The size-invariant guard means the output is never larger than the
  input. If the requested preset would grow the file, the response
  reports `preset_actually_used` set to the fallback that was
  applied. To force a specific preset and fail-loud when it would
  grow the file, set `oversize_policy=fail` (settings or env var).

## License

Provided as-is. Tesseract and Ghostscript carry their own licenses;
ensure you have appropriate rights for your use case.
`````

- [ ] **Step 4.3: Verify README references resolve**

Run:

```bash
# All image links point to existing files
for img in streamlit_starting_ui streamlit_processing_ui streamlit_ending_ui; do
  test -f "images/$img.png" && echo "OK: $img.png" || echo "MISSING: $img.png"
done

# The docs/API.md link resolves
test -f "docs/API.md" && echo "OK: docs/API.md" || echo "MISSING: docs/API.md"

# No leftover python -m pdf_ocr_compress invocations
grep -n "python -m pdf_ocr_compress" README.md && echo "FOUND BAD INVOCATIONS" || echo "OK: clean"

# No leftover n8n references
grep -i -n "n8n\|N8N" README.md && echo "FOUND n8n REFS" || echo "OK: clean"
```

Expected: every check prints `OK:`.

- [ ] **Step 4.4: Update `CLAUDE.md` — replace the "Where I left off" section**

Use `Edit` on `CLAUDE.md`. Replace the entire current "Where I left off" section (from the heading `## Where I left off` through to the heading immediately following it — likely `## Known issues / tech debt`, which gets handled in step 4.5).

The old block to replace begins with `## Where I left off` and ends just before `## Known issues / tech debt`. Replace its full content with:

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

```

- [ ] **Step 4.5: Update `CLAUDE.md` — replace the "Known issues / tech debt" section with a consolidated "Open debt" section**

Use `Edit` to replace the entire current `## Known issues / tech debt` section through to the next top-level heading (likely `## Out of scope`).

The replacement content:

```markdown
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

```

- [ ] **Step 4.6: Verify the CLAUDE.md edits are well-formed**

Run:

```bash
# Phase 6 is recorded as closed
grep -n "Phase 6 closed" CLAUDE.md && echo "OK"

# Old Phase 5 narrative removed
grep -n "Phase 5 closed (2026-04-29)" CLAUDE.md && echo "STALE NARRATIVE STILL PRESENT" || echo "OK: removed"

# Open debt section exists; old "Known issues" is gone
grep -n "## Open debt" CLAUDE.md && echo "OK"
grep -n "## Known issues / tech debt" CLAUDE.md && echo "OLD HEADING STILL PRESENT" || echo "OK: removed"

# All listed debt items match the spec
for item in "tempdir leaks" "defaults still hardcoded" "Recursion into batch" "oversize_policy" "batch/{job_id}/cancel" "FILE_TOO_LARGE"; do
  grep -q "$item" CLAUDE.md && echo "OK: $item" || echo "MISSING: $item"
done
```

Expected: every check returns `OK:`.

- [ ] **Step 4.7: Run the smoke tests one more time**

These should all pass since no source code changed; running them confirms no inadvertent breakage.

```bash
uv run pdf-ocr --help                                                              # CLI loads
uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"    # API imports
uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"      # GUI imports
uv run black --check src/                                                          # formatter clean
uv run ruff check src/                                                             # linter clean
uv run pytest                                                                      # 129/129 pass
```

Expected: all six commands exit 0. (`pdf-ocr --help` prints help, the imports print `API ok` / `GUI ok`, black/ruff print no errors, pytest prints `129 passed`.)

If pytest count differs from 129 because someone added or removed tests outside this plan, that's fine — what matters is that pytest passes.

- [ ] **Step 4.8: Commit**

Run:

```bash
git add README.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: rewrite README and close Phase 6 in CLAUDE.md

README:
- Reframed as a real project README with three first-class clients.
  GUI-first quickstart (friendliest on-ramp for casual readers),
  Docker / backend service second (with link to docs/API.md for
  programmatic integration), CLI third.
- Sample B headline (4.8 GB color textbook scan -> 198 MB,
  -95.9%) lifted above the fold.
- Defaults corrected: preset is `smallest` (was `balanced`),
  Python floor is 3.10+ (was 3.9+), CLI invocations use the
  installed `pdf-ocr` entry point (was `python -m pdf_ocr_compress`).
- Inline API examples replaced with a pointer to docs/API.md
  (added in the previous commit).
- Aspirational cloud-deployment list dropped (the project is
  single-machine).
- Dependency list section dropped (pyproject.toml is the source
  of truth).

CLAUDE.md:
- "Where I left off" replaced with a tight Phase 6 deliverables
  block + roadmap-complete status.
- "Known issues / tech debt" section folded into a single
  "Open debt" section listing the still-open items: GUI tempdir
  leak on failure, CLI defaults hardcoded, batch recursion,
  per-run oversize_policy override, /api/batch cancel endpoint,
  FILE_TOO_LARGE enforcement.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit, two files changed.

---

## Task 5: Update auto-memory and final verification

**Why last:** memory file lives outside the repo (no git commit). Updating it last keeps the in-repo commit log clean and runs after the actual work has landed on `main`.

**Files (outside repo):**

- Modify: `<user-claude-memory-dir>/project_phase_status.md`
- Modify: `<user-claude-memory-dir>/MEMORY.md` (one-line index update)

- [ ] **Step 5.1: Read the current memory files**

Use `Read` on both:

- `<user-claude-memory-dir>/project_phase_status.md`
- `<user-claude-memory-dir>/MEMORY.md`

- [ ] **Step 5.2: Rewrite `project_phase_status.md`**

Use `Write` to replace the file's content. New body:

```markdown
---
name: Project phase status
description: Roadmap completion state and date — drives whether new sessions should pick up phase work or treat the project as in maintenance
type: project
---

**Phase 6 closed (2026-04-29). Roadmap complete.** All six phases of
the modernization are done. The project is in maintenance: bugfixes,
small enhancements, and documentation patches as needed. There is no
Phase 7.

**Why:** The roadmap in `ROADMAP.md` was the multi-session plan that
came out of the Phase 0 benchmark investigation. Phase 6 (docs polish)
was the last phase; closing it means the planned modernization arc
is over.

**How to apply:** New sessions should start from a fresh
brainstorming session for any non-trivial work, rather than looking
to ROADMAP.md for the next thing to do. ROADMAP.md is now historical
context. The current open-debt list lives in `CLAUDE.md` under
"Open debt" and includes: GUI tempdir leaks on failure, CLI
defaults hardcoded, batch recursion, per-run oversize_policy override,
/api/batch cancel endpoint, and FILE_TOO_LARGE enforcement.
```

- [ ] **Step 5.3: Update the `MEMORY.md` index entry**

Use `Edit` on `MEMORY.md`. The current entry is:

```text
- [Project phase status](project_phase_status.md) — Phase 5 done 2026-04-29; pick up at Phase 6 (docs polish: README rewrite, API examples, batch-flag docs)
```

Replace it with:

```text
- [Project phase status](project_phase_status.md) — Phase 6 closed 2026-04-29; roadmap complete; project in maintenance — open debt list in CLAUDE.md
```

- [ ] **Step 5.4: Final verification — confirm everything is in order**

From the repo root, run:

```bash
git log --oneline -5
```

Expected output (the four Phase 6 commits, plus the spec commit):

```text
<sha> docs: rewrite README and close Phase 6 in CLAUDE.md
<sha> docs: add docs/API.md with full endpoint reference
<sha> docs: refresh README screenshots for Phase 5 GUI
<sha> docs: drop n8n integration scaffolding
<sha> docs(spec): Phase 6 documentation polish design
```

```bash
git status --short
```

Expected: empty output (clean working tree).

```bash
ls -la docs/API.md
```

Expected: file exists, several hundred lines.

```bash
ls -la N8N_BATCH_WORKFLOW.md images/n8n_simple.png 2>&1 | grep -E "No such|cannot find"
```

Expected: both files reported as not found (i.e., they were successfully deleted).

```bash
grep -c "Phase 6 closed" CLAUDE.md
```

Expected: at least `1`.

- [ ] **Step 5.5: Inform the user that Phase 6 is complete**

Once all checks pass, report back to the user with:

- The four commit SHAs (from `git log --oneline -5`).
- Confirmation that `docs/API.md` exists and the README links to it.
- Confirmation that the memory file has been updated.
- A reminder that the roadmap is now closed and any future feature work should start from a fresh brainstorming session.

---

## Self-review checklist (run before declaring the plan done)

The implementing engineer should not need to consult the spec to do this work — every spec requirement should be reflected in a task above. The author of this plan ran the following checks:

- [x] **Spec coverage:** every section of `2026-04-29-phase-6-docs-design.md` (Goal, Non-goals, four-commit deliverables, Verification, Risks, After Phase 6) maps to a task here. Tasks 1–4 implement the four commits; Task 5 implements the After-Phase-6 memory update; Step 4.7 implements the Verification section.
- [x] **Placeholder scan:** no "TBD" / "TODO" / "fill in details" appear in the steps. Every code block contains the actual content the engineer needs.
- [x] **Type consistency:** field names in `docs/API.md` match the source files referenced for verification in step 3.3. The `APIError` shape uses `suggestions: list[str]` (not `detail`) — corrected from the spec's earlier draft after reading `api/errors.py`.
- [x] **Git hygiene:** every commit uses HEREDOC for the message body and includes the project's standard `Co-Authored-By` trailer. No `--no-verify`, no force pushes, no destructive operations.

---

## Risks and mitigations (from the spec, restated for the executor)

- **Screenshot capture flake.** If Streamlit timing or Playwright selectors don't cooperate, fall back to two screenshots (`starting` + `ending`, drop `processing`) and update the README copy in step 4.2 to match (remove the second image link). Better to ship two correct screenshots than three uncertain ones.
- **Docs drift between `docs/API.md` and the source.** Mitigated by the source-of-truth read in step 3.1 and the verification grep in step 3.3. If those checks fail, fix the doc, never the source — Phase 6 is docs-only.
- **Order-of-commits hazard.** Tasks must run in order (1 → 2 → 3 → 4 → 5). Each task's commit lands on `main` immediately. There is no branching/PR workflow in this plan; if you want to change that, surface it before starting.
