# GUI browser smoke test

Manual checklist run at the end of Phase 5 to close the
"GUI not click-through tested in a browser" gap from CLAUDE.md.

Run from a clean shell after `uv sync` succeeds. Tesseract +
Ghostscript must be on PATH for the OCR steps. Record results inline
(check the box, optionally annotate).

## Setup

- [X] `uv run pdf-ocr-gui` boots without traceback.
- [X] Streamlit lands at `http://localhost:8501` in the default browser.

## Defaults expander

- [X] Sidebar "⚙️ Defaults (saved across sessions)" expander opens.
- [X] Fields pre-fill with whatever is currently in
      `<config_dir>/settings.json` (or hardcoded defaults on first
      run: `default_preset=smallest`, `default_language=eng`, etc.).
- [X] Change `Default preset` to `archival` → click "💾 Save defaults".
      `settings.json` now contains `"default_preset": "archival"`.
      Reload the tab; the per-run "Quality preset" selector now
      defaults to `archival` instead of `smallest`. Restore to
      `smallest` afterwards.
- [X] Set `Default output directory` to a real path you can write to
      (e.g. `pdfs/_phase5_smoke/`). Save. Single-file processing in
      the next section should land output there.

## Single-file flow — browser upload

- [X] Drop a small ScanSnap PDF (or any test PDF) into the upload
      widget. The "Selected:" line shows correct name + size.
- [X] Click "Process". The pipeline runs to completion; the success
      banner shows preset / size delta / OCR routing.
- [X] If `Default output directory` was set, the "📂 Saved to:" line
      shows a path inside it. Open the file from disk and verify it
      opens in a PDF viewer.
- [X] The download button still produces a working file (named
      `<input_stem>_processed.pdf`).

## Single-file flow — local file path

- [X] Switch "File source" to "Use local file path (no size limit)".
- [X] Type the absolute path to the same PDF. The "Selected:" line
      shows correct name + size.
- [X] Click "Process". Same banner / saved-to / download behavior.
- [X] **Real-world load-bearing case**: point local-path mode at one
      of the multi-GB ScanSnap textbook scans (e.g. the Longenecker
      sample). Verify the GUI doesn't choke on the size and the
      pipeline runs end-to-end. This is the workflow shape the
      project is designed for; the upload mode physically can't
      handle it.

## Friendly error display

- [X] In local-path mode, type a path that doesn't exist (e.g.
      `C:\does\not\exist.pdf`). Click "Process". A friendly
      `FILE_NOT_FOUND` error renders via `_render_error` (headline +
      suggestions + `Error code:` caption). This was previously a
      bare `st.error` line; verify the change took.
- [X] In local-path mode, type a path to a non-PDF file (e.g. a
      `.txt`). Click "Process". An `st.error` headline + suggestions
      bullets + `Error code:` caption appear. No raw traceback is
      shown to the user.
- [X] **Unwritable `default_output_dir`**: temporarily set
      `Default output directory` to a path you can't write to (e.g.
      `C:\Windows\System32\__readonly_test\` on a non-admin account,
      or any read-only mount). Save. Run a single-file process. The
      yellow warning surfaces with the path AND the OS error reason
      (e.g. `[WinError 5] Access is denied`). Output still lands
      successfully in a tempdir. Restore the setting after.
- [ ] (Optional, slow) Temporarily PATH-strip Tesseract or rename
      `gswin64c.exe`. Run a flow that needs it. Verify the friendly
      error has tool-installation suggestions. *(skipped — optional)*

## Batch — browser upload

- [X] Switch "Source" radio to "Upload multiple PDFs in browser".
- [X] Drop 2–3 small PDFs. Click "Process batch".
- [X] Progress bar advances; live results table populates.
- [X] On success, per-file download buttons appear; each downloads a
      working PDF. `batch_report.json` downloads as JSON.
      *(initially failed: clicking the first download button caused
      the rest to vanish — fixed in commit `b530946` by stashing the
      run results in `st.session_state` and rendering outside the
      `if batch_btn:` block.)*

## Batch — local folder path

- [X] Switch "Source" radio to "Use local folder path".
- [X] Type an input folder containing 2–3 small PDFs (e.g. a copy
      of `pdfs/`).
- [X] Pre-flight info line shows the right PDF count and total size.
- [X] Click "Process batch". Progress bar advances; live table
      populates.
- [X] When `Default output directory` is set: outputs land in
      `<default_output_dir>/batch_YYYYMMDD-HHMMSS-fff/`. The "📂
      Outputs in:" caption shows that subfolder.
- [X] When `Default output directory` is unset: outputs land in
      `<input_folder>/processed/`.
- [X] No per-file download buttons in folder mode (correct — outputs
      already on disk).
- [X] `batch_report.json` download works and contains correct per-
      file status entries.
- [X] **Two consecutive batches into the same `default_output_dir`**:
      with the setting still pointing at your smoke folder, run two
      back-to-back batches (re-click "Process batch" immediately).
      Confirm both runs land in distinct
      `batch_YYYYMMDD-HHMMSS-fff/` subfolders — i.e. neither run
      clobbers the other's `batch_report.json`. The microsecond
      suffix is what makes this safe.

## Tempdir audit (post-failure)

- [X] After running the friendly-error tests above (which deliberately
      crash the pipeline), open `%TEMP%` (Windows) or `/tmp`
      (Unix) and look for orphaned `pdfgui_*`, `pdfgui_in_*`, or
      `pdfgui_batch_*` directories. They're expected to leak on
      failure today (deferred in Phase 5; see CLAUDE.md "Honest gaps
      after Phase 5"). Note any size that surprised you.

## Tear-down

- [X] Restore `Default output directory` to whatever it was (or
      blank).
- [X] Restore `Default preset` to `smallest`.
- [X] Stop the Streamlit server.

Run completed: 2026-04-29 by Brandon Foltz.

## Findings (issues surfaced and fixed live)

Four real defects came up during the walkthrough. All were fixed in
follow-up commits before the run was marked complete; recording them
here for the historical record.

1. **Batch download buttons disappeared after first click.** Streamlit
   reruns the script on every widget interaction; the result UI lived
   inside `if batch_btn:`, so any download click made `batch_btn=False`
   on the rerun and unmounted everything. Fixed in `b530946` by
   stashing `report_summary`, `final_rows`, `batch_out`, `out_source`,
   `batch_source`, the list of OK outputs, and the report path in
   `st.session_state["batch_results"]`, then rendering outside
   `if batch_btn:` so reruns don't tear it down.
2. **Batch output-folder label leaked internal terminology.**
   `"Output folder (blank = use default_output_dir, else <input>/processed/)"`
   was unreadable to a non-engineer. Fixed in `2d5a1d8` by collapsing
   the label to `"Output folder (optional)"` with the fallback rules
   moved into the `help=` tooltip; gave the placeholder a real-shaped
   path.
3. **No native folder picker.** Pasting absolute paths is annoying
   when Explorer is right there. Fixed in `32d0bdc` by adding a
   `_pick_folder_dialog` helper that pops `tkinter.filedialog.askdirectory`
   (works because the Streamlit server runs on the same machine as
   the browser — single-user local app), wired up Browse buttons next
   to the Defaults expander's `default_output_dir` field and both
   batch local-folder fields. Headless / Docker fallback raises
   `RuntimeError` with a friendly message.
4. **Browse button crashed the page on click.** Streamlit raises
   `StreamlitAPIException` when you mutate `st.session_state[k]` after
   a widget keyed on `k` has been instantiated in the current run.
   The original Browse handlers wrote to session_state from the
   `if st.button():` block (post-instantiation). Fixed in `d9360b5`
   by switching to the `on_click=` callback pattern; mutations from
   inside an `on_click` callback fire before the rerun, when the
   widget hasn't been re-created for the new run yet.
