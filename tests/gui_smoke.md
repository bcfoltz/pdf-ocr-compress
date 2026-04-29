# GUI browser smoke test

Manual checklist run at the end of Phase 5 to close the
"GUI not click-through tested in a browser" gap from CLAUDE.md.

Run from a clean shell after `uv sync` succeeds. Tesseract +
Ghostscript must be on PATH for the OCR steps. Record results inline
(check the box, optionally annotate).

## Setup

- [ ] `uv run pdf-ocr-gui` boots without traceback.
- [ ] Streamlit lands at `http://localhost:8501` in the default browser.

## Defaults expander

- [ ] Sidebar "⚙️ Defaults (saved across sessions)" expander opens.
- [ ] Fields pre-fill with whatever is currently in
      `<config_dir>/settings.json` (or hardcoded defaults on first
      run: `default_preset=smallest`, `default_language=eng`, etc.).
- [ ] Change `Default preset` to `archival` → click "💾 Save defaults".
      `settings.json` now contains `"default_preset": "archival"`.
      Reload the tab; the per-run "Quality preset" selector now
      defaults to `archival` instead of `smallest`. Restore to
      `smallest` afterwards.
- [ ] Set `Default output directory` to a real path you can write to
      (e.g. `pdfs/_phase5_smoke/`). Save. Single-file processing in
      the next section should land output there.

## Single-file flow — browser upload

- [ ] Drop a small ScanSnap PDF (or any test PDF) into the upload
      widget. The "Selected:" line shows correct name + size.
- [ ] Click "Process". The pipeline runs to completion; the success
      banner shows preset / size delta / OCR routing.
- [ ] If `Default output directory` was set, the "📂 Saved to:" line
      shows a path inside it. Open the file from disk and verify it
      opens in a PDF viewer.
- [ ] The download button still produces a working file (named
      `<input_stem>_processed.pdf`).

## Single-file flow — local file path

- [ ] Switch "File source" to "Use local file path (no size limit)".
- [ ] Type the absolute path to the same PDF. The "Selected:" line
      shows correct name + size.
- [ ] Click "Process". Same banner / saved-to / download behavior.

## Friendly error display

- [ ] In local-path mode, type a path to a non-PDF file (e.g. a
      `.txt`). Click "Process". An `st.error` headline + suggestions
      bullets + `Error code:` caption appear. No raw traceback is
      shown to the user.
- [ ] (Optional, slow) Temporarily PATH-strip Tesseract or rename
      `gswin64c.exe`. Run a flow that needs it. Verify the friendly
      error has tool-installation suggestions.

## Batch — browser upload

- [ ] Switch "Source" radio to "Upload multiple PDFs in browser".
- [ ] Drop 2–3 small PDFs. Click "Process batch".
- [ ] Progress bar advances; live results table populates.
- [ ] On success, per-file download buttons appear; each downloads a
      working PDF. `batch_report.json` downloads as JSON.

## Batch — local folder path

- [ ] Switch "Source" radio to "Use local folder path".
- [ ] Type an input folder containing 2–3 small PDFs (e.g. a copy
      of `pdfs/`).
- [ ] Pre-flight info line shows the right PDF count and total size.
- [ ] Click "Process batch". Progress bar advances; live table
      populates.
- [ ] When `Default output directory` is set: outputs land in
      `<default_output_dir>/batch_YYYYMMDD-HHMMSS/`. The "📂 Outputs
      in:" caption shows that subfolder.
- [ ] When `Default output directory` is unset: outputs land in
      `<input_folder>/processed/`.
- [ ] No per-file download buttons in folder mode (correct — outputs
      already on disk).
- [ ] `batch_report.json` download works and contains correct per-
      file status entries.

## Tear-down

- [ ] Restore `Default output directory` to whatever it was (or
      blank).
- [ ] Restore `Default preset` to `smallest`.
- [ ] Stop the Streamlit server.

Run completed: <YYYY-MM-DD by name>
