# Phase 0 benchmarks

Real-input benchmarks against two representative scanner outputs. The
data here justifies every design rule in `CLAUDE.md` and every Phase
2 work item in `ROADMAP.md`.

> **Caveat (2026-07-18):** OCR-branch numbers for the `smallest` preset
> were measured when the pipeline still passed `--jbig2-lossy` to
> OCRmyPDF. Upstream has since removed lossy JBIG2 (character-
> substitution risk) and the pipeline no longer passes the flag, so
> `smallest` OCR-branch output may be somewhat larger on current
> OCRmyPDF versions than recorded here. Compress-only numbers
> (Ghostscript path) are unaffected.

## Headline findings

1. **Two of three presets *grow* the file.** On already-OCR'd scanner
   input, `archival` triples size (3.07×), `balanced` adds 34%, only
   `smallest` shrinks (-17%).
2. **Text fidelity is essentially perfect across all three
   compress-only presets** (within 0.09% of the scanner baseline) —
   Ghostscript preserves the existing text layer.
3. **`--force-ocr` followed by the default `balanced` pipeline
   destroys the OCR text layer.** ~12 minutes of Tesseract work
   produces an output with zero extractable text. Verified at the
   PDF structure level: pages have no `/Font` resources after the
   post-OCR Ghostscript pass.

## Sample A: B&W book scan

**Profile:** 231 pages, 37.8 MB, scanner with embedded ABBYY OCR.
This is the lower-end representative input — small page count, B&W
content, already-OCR'd at scan time.

### Compress-only preset comparison (auto pipeline; `needs_ocr` returned False)

| Preset | Output size | vs input | Time | Text words extracted | Δ vs raw |
|---|---|---|---|---|---|
| **raw input** | 37.8 MB | — | — | 64,376 | — |
| archival | 116.1 MB | **+207%** (3.07×) | 37.0s | 64,319 | -57 (-0.09%) |
| balanced | 50.8 MB | **+34%** | 63.1s | 64,319 | -57 (-0.09%) |
| smallest | 31.4 MB | **-17%** | 99.0s | 64,319 | -57 (-0.09%) |

Raw scanner text and text from each compressed output share
identical first-400 and mid-400 character samples and identical
unique-word counts (8,902). The 57-word delta appears to be
Ghostscript canonicalizing whitespace/encoding artifacts — content
fidelity is intact.

**Why archival/balanced grow the file:** Ghostscript's `/prepress`
and `/ebook` PDFSETTINGS re-encode embedded images at higher quality
than the scanner's native PDF engine produced, while preserving the
text layer overlay. Net result: bigger images, same text, larger
file.

### Force-OCR result (`--force-ocr --preset balanced`)

| Metric | Value |
|---|---|
| Output size | 50.6 MB |
| Time | 11m 43s (703s) |
| pdfminer extracted chars | 231 (all `\f` form-feeds — page breaks only) |
| pdfminer extracted words | **0** |
| Page 10 `/Font` resources | **none** (vs balanced compress-only: present) |

**This is a bug in the current pipeline.** OCRmyPDF runs Tesseract
over every page (the 11+ minute cost) and writes an invisible text
overlay. The subsequent Ghostscript `/ebook` pass then strips
fonts/text from the rasterized output, destroying the OCR layer.
The PDF still *renders* (it has 231 pages of images) but is no
longer searchable, indexable, or RAG-usable.

Likely causes (to investigate in Phase 2):

- Ghostscript `/ebook` rasterizes vector content including the OCR
  text overlay
- Missing flags like `-dPrinted=false`, `-dPreserveAnnots`,
  `-dPreserveMarkedContent` may be needed to keep invisible text
- Or the OCRmyPDF→Ghostscript handoff itself is broken at this
  PDFSETTINGS level

**Operational impact:** `pdf-ocr process --force-ocr` on a real book
scan currently produces unusable output for the stated primary use
case (LLM/RAG ingestion). This is the highest-priority Phase 2
finding.

## Sample B: color textbook scan (4.82 GB, 765 pages)

A second benchmark on a much harder representative input: a
full-color college textbook scan, also already-OCR'd. This is the
upper end of the input size range the tool is built for —
4.82 GB raw.

### Headline result (smallest preset, compress-only)

| Metric | Value |
|---|---|
| Input | 4.82 GB |
| Output | **198 MB** |
| Reduction | **-95.9%** (4.63 GB saved) |
| Time | 3 min 32 sec |
| Words extracted from output | 409,125 |
| Unique words | 40,106 |

The textbook prose extracts cleanly. OCR garbage appears on page
furniture (decorative borders, small marginalia) but does not
affect main content extraction. Suitable for LLM/RAG ingestion.

`archival` and `balanced` were not benchmarked on Sample B per the
design invariant established in this run: **output must never
exceed input size**. Given the Sample A results (archival +207%,
balanced +34% on a *much smaller* input), running them on a 4.8 GB
color file would only confirm a worse failure mode at higher cost.

### Two additional bugs surfaced by this sample

3. **`needs_ocr` false-positives on PDFs that pikepdf parses but
   pdfminer doesn't.** pdfminer raised `PDFSyntaxError("No /Root
   object!")` on the raw Sample B file; `detect.py` catches all
   exceptions and returns `True` (assume needs OCR). This wasted
   ~40 minutes of wall time before we caught it — `pdf-ocr process`
   started a full 765-page color OCR pass on a file that already
   had text. Fix candidate: switch `needs_ocr` to use pikepdf for
   the existence probe (parse → check first N pages for `/Font`
   resources or extractable text via pikepdf's own extractor)
   instead of relying on pdfminer's stricter parser.

4. **pdfminer cannot extract text from the raw 4.82 GB file at
   all.** The same `PDFSyntaxError` blocks any text-fidelity
   baseline measurement on the original. *Mitigation found by
   accident:* pdfminer extracts cleanly from the
   Ghostscript-processed output (Ghostscript appears to canonicalize
   whatever malformation pdfminer chokes on). So *post-compression*
   fidelity validation works; pre-compression baseline does not.
   For batch processing, this means the LLM-fidelity check has to
   happen on output, not input — which is what we want anyway.

## Locked-in design invariants for Phase 2

1. **Output ≤ input size, always.** No Phase 2 pipeline branch may
   produce output larger than input. Implementation can be
   (a) pre-emptive — skip `/prepress` and `/ebook` Ghostscript
   settings on already-OCR'd inputs, or (b) post-hoc — measure
   output, retry with `smallest`, fall back to passthrough copy if
   even `smallest` grows it.
2. **`needs_ocr` must use a tolerant parser** (pikepdf, not
   pdfminer) to avoid false positives that trigger expensive
   useless OCR passes.
3. **Force-OCR followed by current Ghostscript settings produces
   broken output** (text layer destroyed). Fix in Phase 2 — likely
   by dropping the post-OCR Ghostscript pass entirely and letting
   OCRmyPDF's `--optimize 0/2/3` handle compression.
4. **`smallest` is the safe default for both B&W book scans and
   color textbook scans.** It's the only preset that actually
   shrinks already-OCR'd scanner output, and on color textbooks the
   reduction is staggering (96%).

## What these benchmarks did NOT measure

- **Tesseract OCR quality vs the scanner's native OCR** — couldn't
  compare because the force-OCR pipeline destroys the text layer
  (Sample A) and the raw file isn't pdfminer-parseable (Sample B).
  Defer until the force-OCR pipeline is fixed in Phase 2.
- **Multi-file batch behavior** — single files only. Folder-batch
  UX work in Phase 3.
- **Non-book scans** (forms, receipts, mixed-content PDFs) — out of
  scope for the current samples.
- **Streamlit/API surface behavior** — CLI only. Surface-specific
  testing in later phases.

## Reproducing these benchmarks

The `pdfs/` directory ships with two parameterized scripts (everything
else in `pdfs/` is gitignored):

- `pdfs/_benchmark.py <input.pdf> [--force-ocr]` — full 3-preset
  benchmark on any PDF you supply. Writes a JSON report next to the
  input.
- `pdfs/_run_one.py <input.pdf> <output.pdf> <preset>` — single
  preset run with text-extraction stats.

Drop your own scanner output into `pdfs/` and run either script.
