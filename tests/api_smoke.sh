#!/usr/bin/env bash
# Phase 4 item 6 — end-to-end smoke test against a live uvicorn process.
# Drives /health, /api/process (happy path + invalid-input error path),
# /api/download, /api/batch, and /api/batch/{job_id}/status with curl.
# Exits nonzero on the first failure.
#
# Prerequisites:
#   - uv (project's package/runner)
#   - jq (JSON parsing)
#   - Ghostscript on PATH (Tesseract optional — script uses mode=compress
#     so OCR isn't exercised; missing-tool paths still surface via /health)
#
# Usage:
#   bash tests/api_smoke.sh
#
# Override the listen port via SMOKE_PORT (default 8590) if 8590 is busy.

set -euo pipefail

PORT="${SMOKE_PORT:-8590}"
BASE_URL="http://127.0.0.1:${PORT}"
WORKDIR="$(mktemp -d -t pdf-ocr-smoke-XXXXXX)"

# Convert to a path the local Python/curl/server can resolve. On
# git-bash/MSYS, mktemp returns a POSIX path like /tmp/... that Windows
# Python interprets literally as \tmp\... (broken). cygpath -w gives the
# real Windows path; on Linux/macOS the function is a no-op.
to_native_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        echo "$1"
    fi
}
WORKDIR_NATIVE="$(to_native_path "${WORKDIR}")"

LOG_FILE="${WORKDIR}/uvicorn.log"
SAMPLE_PDF_NATIVE="${WORKDIR_NATIVE}/sample.pdf"
BATCH_DIR_NATIVE="${WORKDIR_NATIVE}/batch_in"
BATCH_OUT_NATIVE="${WORKDIR_NATIVE}/batch_out"
UVICORN_PID=""

cleanup() {
    if [ -n "${UVICORN_PID}" ] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
        kill "${UVICORN_PID}" 2>/dev/null || true
        wait "${UVICORN_PID}" 2>/dev/null || true
    fi
    rm -rf "${WORKDIR}"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; [ -f "${LOG_FILE}" ] && tail -40 "${LOG_FILE}" >&2; exit 1; }
ok()   { echo "  ok: $*"; }

command -v jq >/dev/null 2>&1 || fail "jq is required (install via your package manager)"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v uv >/dev/null 2>&1 || fail "uv is required"

# --- 1. Build fixture PDFs --------------------------------------------------

echo "[setup] creating fixture PDFs in ${WORKDIR_NATIVE}"
uv run python -c "
import pikepdf
from pathlib import Path
import sys

work = Path(sys.argv[1])
sample = work / 'sample.pdf'
batch_in = work / 'batch_in'
batch_in.mkdir(exist_ok=True)

for path in (sample, batch_in / 'one.pdf', batch_in / 'two.pdf'):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(path)
" "${WORKDIR_NATIVE}" || fail "fixture build failed"
ok "fixtures built (sample.pdf + 2 batch PDFs)"

# --- 2. Launch uvicorn ------------------------------------------------------

echo "[start] uvicorn on port ${PORT}"
uv run uvicorn pdf_ocr_compress.api.server:app \
    --host 127.0.0.1 --port "${PORT}" \
    > "${LOG_FILE}" 2>&1 &
UVICORN_PID=$!

# Wait up to ~15s for /health to come up.
for i in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null || echo 000)"
    if [ "${code}" = "200" ]; then
        ok "uvicorn healthy after ${i} polls"
        break
    fi
    sleep 0.5
    if [ "$i" -eq 30 ]; then
        fail "uvicorn did not become healthy"
    fi
done

# --- 3. /health schema ------------------------------------------------------

echo "[/health]"
HEALTH=$(curl -fsS "${BASE_URL}/health")
echo "${HEALTH}" | jq -e '.status == "healthy"' >/dev/null || fail "/health status"
echo "${HEALTH}" | jq -e 'has("version")' >/dev/null || fail "/health.version missing"
echo "${HEALTH}" | jq -e 'has("ghostscript_binary")' >/dev/null || fail "/health.ghostscript_binary missing"
echo "${HEALTH}" | jq -e 'has("tesseract_binary")' >/dev/null || fail "/health.tesseract_binary missing"
echo "${HEALTH}" | jq -e '.tesseract_languages | type == "array"' >/dev/null || fail "/health.tesseract_languages not array"
echo "${HEALTH}" | jq -e '.queue_depth | type == "number"' >/dev/null || fail "/health.queue_depth not number"
ok "/health shape (version, binaries, languages, queue_depth)"

GS_PATH=$(echo "${HEALTH}" | jq -r '.ghostscript_binary')
if [ "${GS_PATH}" = "null" ]; then
    echo "[skip] Ghostscript not on PATH — skipping pipeline-dependent tests"
    echo "PARTIAL PASS (/health only)"
    exit 0
fi
ok "Ghostscript detected at ${GS_PATH}"

# --- 4. Error path: invalid mode -------------------------------------------

echo "[/api/process error path: invalid mode]"
HTTP=$(curl -s -o "${WORKDIR}/err.json" -w "%{http_code}" -X POST \
    -F "file=@${SAMPLE_PDF_NATIVE};type=application/pdf" \
    -F "mode=bogus" -F "preset=smallest" \
    "${BASE_URL}/api/process")
[ "${HTTP}" = "400" ] || fail "expected 400 for bogus mode, got ${HTTP}"
jq -e '.error_code == "INVALID_MODE"' "${WORKDIR}/err.json" >/dev/null \
    || fail "expected error_code=INVALID_MODE"
jq -e '.message | type == "string"' "${WORKDIR}/err.json" >/dev/null \
    || fail "expected error message string"
ok "INVALID_MODE returns 400 with APIError shape"

# --- 5. Happy path: /api/process -------------------------------------------

echo "[/api/process happy path (mode=compress)]"
HTTP=$(curl -s -o "${WORKDIR}/process.json" -w "%{http_code}" -X POST \
    -F "file=@${SAMPLE_PDF_NATIVE};type=application/pdf" \
    -F "mode=compress" -F "preset=smallest" \
    "${BASE_URL}/api/process")
[ "${HTTP}" = "200" ] || fail "expected 200 from /api/process, got ${HTTP} ($(cat ${WORKDIR}/process.json))"
FILE_ID=$(jq -r '.file_id' "${WORKDIR}/process.json")
[ -n "${FILE_ID}" ] && [ "${FILE_ID}" != "null" ] || fail "no file_id in response"
jq -e '.preset_actually_used | type == "string"' "${WORKDIR}/process.json" >/dev/null \
    || fail "expected preset_actually_used in response (Phase 2 report fields)"
ok "/api/process returned file_id=${FILE_ID}"

# --- 6. /api/download ------------------------------------------------------

echo "[/api/download/{file_id}]"
HTTP=$(curl -s -o "${WORKDIR}/downloaded.pdf" -w "%{http_code}" \
    "${BASE_URL}/api/download/${FILE_ID}")
[ "${HTTP}" = "200" ] || fail "expected 200 from /api/download, got ${HTTP}"
[ -s "${WORKDIR}/downloaded.pdf" ] || fail "downloaded file is empty"
ok "/api/download returned non-empty PDF"

# --- 7. /api/batch + status polling ----------------------------------------

echo "[/api/batch]"
BATCH_REQ=$(jq -n --arg folder "${BATCH_DIR_NATIVE}" --arg outdir "${BATCH_OUT_NATIVE}" \
    '{folder: $folder, output_dir: $outdir, mode: "compress", preset: "smallest"}')
HTTP=$(curl -s -o "${WORKDIR}/batch.json" -w "%{http_code}" -X POST \
    -H "Content-Type: application/json" -d "${BATCH_REQ}" \
    "${BASE_URL}/api/batch")
[ "${HTTP}" = "202" ] || fail "expected 202 from /api/batch, got ${HTTP} ($(cat ${WORKDIR}/batch.json))"
JOB_ID=$(jq -r '.job_id' "${WORKDIR}/batch.json")
TOTAL_FILES=$(jq -r '.total_files' "${WORKDIR}/batch.json")
[ "${TOTAL_FILES}" = "2" ] || fail "expected total_files=2, got ${TOTAL_FILES}"
ok "/api/batch queued job_id=${JOB_ID} (2 files)"

echo "[poll /api/batch/{job_id}/status]"
for i in $(seq 1 60); do
    STATUS=$(curl -fsS "${BASE_URL}/api/batch/${JOB_ID}/status" | jq -r '.status')
    case "${STATUS}" in
        done)
            ok "batch completed after ${i} polls"
            break
            ;;
        error)
            ERR=$(curl -fsS "${BASE_URL}/api/batch/${JOB_ID}/status" | jq -r '.error_msg')
            fail "batch ended in error: ${ERR}"
            ;;
    esac
    sleep 1
    [ "$i" -eq 60 ] && fail "batch did not complete within 60s"
done

# Final report shape
FINAL=$(curl -fsS "${BASE_URL}/api/batch/${JOB_ID}/status")
SUCCEEDED=$(echo "${FINAL}" | jq -r '.report.succeeded')
[ "${SUCCEEDED}" = "2" ] || fail "expected 2 succeeded, got ${SUCCEEDED}"
echo "${FINAL}" | jq -e '.report.results | type == "array" and length == 2' >/dev/null \
    || fail "report.results should be a 2-element array"
ok "batch report.succeeded=2 with 2 results"

# --- 8. Error path: unknown job_id (404) -----------------------------------

echo "[/api/batch/{unknown}/status]"
HTTP=$(curl -s -o "${WORKDIR}/notfound.json" -w "%{http_code}" \
    "${BASE_URL}/api/batch/00000000-0000-0000-0000-000000000000/status")
[ "${HTTP}" = "404" ] || fail "expected 404 for unknown job, got ${HTTP}"
jq -e '.error_code == "BATCH_JOB_NOT_FOUND"' "${WORKDIR}/notfound.json" >/dev/null \
    || fail "expected BATCH_JOB_NOT_FOUND code"
ok "unknown job_id returns 404 with APIError shape"

echo "PASS"
