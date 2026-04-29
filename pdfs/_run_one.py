"""Run one pdf-ocr preset on one input, time it, capture sizes, extract text.

Usage: uv run python pdfs/_run_one.py <input.pdf> <output.pdf> <preset>
Writes JSON next to output: <output>.json
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from pdfminer.high_level import extract_text

if len(sys.argv) != 4:
    print("Usage: uv run python pdfs/_run_one.py <input.pdf> <output.pdf> <preset>")
    sys.exit(1)

inp = Path(sys.argv[1])
out_requested = Path(sys.argv[2])
preset = sys.argv[3]

if out_requested.exists():
    out_requested.unlink()

cmd = ["uv", "run", "pdf-ocr", "compress", str(inp), str(out_requested), "--preset", preset]
print(f"[{time.strftime('%H:%M:%S')}] starting: {' '.join(cmd[2:])}", flush=True)

t0 = time.time()
result = subprocess.run(cmd, capture_output=True, text=True)
elapsed = time.time() - t0

print(f"[{time.strftime('%H:%M:%S')}] exit={result.returncode} elapsed={elapsed:.1f}s", flush=True)

actual = None
for line in result.stdout.splitlines():
    if line.startswith("Output:"):
        actual = Path(line.split(":", 1)[1].strip())
        break

data = {
    "preset": preset,
    "input": str(inp),
    "input_bytes": inp.stat().st_size,
    "output_path": str(actual) if actual else None,
    "output_bytes": actual.stat().st_size if actual and actual.exists() else None,
    "process_seconds": round(elapsed, 1),
    "exit_code": result.returncode,
    "stdout_tail": result.stdout[-500:],
    "stderr_tail": result.stderr[-500:],
}

if actual and actual.exists():
    data["pct_change"] = round(100 * (data["output_bytes"] / data["input_bytes"] - 1), 1)
    print(f"[{time.strftime('%H:%M:%S')}] extracting text from {actual}", flush=True)
    t0 = time.time()
    text = extract_text(str(actual)) or ""
    extract_seconds = time.time() - t0
    words = text.split()
    data["text"] = {
        "extract_seconds": round(extract_seconds, 1),
        "chars": len(text),
        "words": len(words),
        "unique_words": len(set(w.lower() for w in words)),
        "first_400": text[:400],
        "mid_400": text[len(text) // 2 : len(text) // 2 + 400],
    }
    print(
        f"[{time.strftime('%H:%M:%S')}] text: {data['text']['words']:,} words, "
        f"{data['text']['chars']:,} chars",
        flush=True,
    )

json_path = out_requested.with_suffix(".json")
json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[{time.strftime('%H:%M:%S')}] DONE — wrote {json_path}", flush=True)
