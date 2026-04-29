"""Benchmark a PDF: 3 presets compress-only, optional force-OCR.

Usage: uv run python pdfs/_benchmark.py <input.pdf> [--force-ocr]

Writes results to pdfs/_benchmark_<stem>.json. Not committed.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from pdfminer.high_level import extract_text

if len(sys.argv) < 2:
    print("Usage: uv run python pdfs/_benchmark.py <input.pdf> [--force-ocr]")
    sys.exit(1)

INPUT = Path(sys.argv[1])
INCLUDE_FORCE_OCR = "--force-ocr" in sys.argv[2:]
STEM = INPUT.stem.replace("_raw", "")
RESULTS_PATH = Path(f"pdfs/_benchmark_{STEM}.json")
PROGRESS_PATH = Path(f"pdfs/_benchmark_{STEM}.log")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with PROGRESS_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def measure_text(pdf_path):
    t0 = time.time()
    text = extract_text(str(pdf_path)) or ""
    elapsed = time.time() - t0
    words = text.split()
    return {
        "extract_seconds": round(elapsed, 1),
        "chars": len(text),
        "words": len(words),
        "unique_words": len(set(w.lower() for w in words)),
        "first_400": text[:400],
        "mid_400": text[len(text) // 2 : len(text) // 2 + 400],
    }


def run_process(preset, force_ocr=False):
    tag = f"{preset}{'_forceocr' if force_ocr else ''}"
    out_path = Path(f"pdfs/{STEM}_{tag}.pdf")
    if out_path.exists():
        out_path.unlink()

    cmd = [
        "uv", "run", "pdf-ocr", "process",
        str(INPUT), str(out_path),
        "--preset", preset,
    ]
    if force_ocr:
        cmd.append("--force-ocr")

    log(f"  -> spawning: {' '.join(cmd[2:])}")
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    log(f"  -> exit={result.returncode} elapsed={elapsed:.1f}s")

    actual = None
    for line in result.stdout.splitlines():
        if line.startswith("Output:"):
            actual = Path(line.split(":", 1)[1].strip())
            break

    return {
        "preset": preset,
        "force_ocr": force_ocr,
        "exit_code": result.returncode,
        "process_seconds": round(elapsed, 1),
        "input_bytes": INPUT.stat().st_size,
        "output_path": str(actual) if actual else None,
        "output_bytes": actual.stat().st_size if actual and actual.exists() else None,
        "stdout_tail": result.stdout[-500:],
        "stderr_tail": result.stderr[-500:],
    }


def main():
    PROGRESS_PATH.write_text("", encoding="utf-8")
    log(f"Input: {INPUT} ({INPUT.stat().st_size:,} bytes)")

    log("Step 1/6: extract baseline text from raw")
    raw_metrics = measure_text(INPUT)
    log(f"  raw words={raw_metrics['words']:,} chars={raw_metrics['chars']:,}")

    runs = []
    total_steps = 5 if INCLUDE_FORCE_OCR else 4
    for i, preset in enumerate(["archival", "balanced", "smallest"], start=2):
        log(f"Step {i}/{total_steps+1}: compress-only preset={preset}")
        r = run_process(preset, force_ocr=False)
        if r["output_path"] and Path(r["output_path"]).exists():
            log(f"  extracting text from {r['output_path']}")
            r["text"] = measure_text(Path(r["output_path"]))
            log(f"  output {r['output_bytes']:,} bytes ({100*(1-r['output_bytes']/r['input_bytes']):.1f}% smaller)")
        runs.append(r)

    if INCLUDE_FORCE_OCR:
        log(f"Step 5/{total_steps+1}: force-OCR preset=balanced (Tesseract pass)")
        r = run_process("balanced", force_ocr=True)
        if r["output_path"] and Path(r["output_path"]).exists():
            log(f"  extracting text from {r['output_path']}")
            r["text"] = measure_text(Path(r["output_path"]))
            log(f"  output {r['output_bytes']:,} bytes ({100*(1-r['output_bytes']/r['input_bytes']):.1f}% smaller)")
        runs.append(r)

    log(f"Step {total_steps+1}/{total_steps+1}: writing results JSON")
    out = {
        "input_path": str(INPUT),
        "input_bytes": INPUT.stat().st_size,
        "raw_text": raw_metrics,
        "runs": runs,
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"DONE — wrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
