# Phase 5 — GUI catchup design

**Status:** Approved 2026-04-29. Implementation plan to follow via the
writing-plans skill. ROADMAP Phase 5.

## Goal

Bring `src/pdf_ocr_compress/gui/basic.py` (the only GUI) in line with
everything Phase 1–4 added: persistent settings, the
`ProcessResult` report shape, folder-input batch (matches the user's
real workflow on a mounted drive), and Phase 4's user-friendly error
helper. End the phase with a documented browser smoke test that closes
the "GUI not click-through tested" gap CLAUDE.md flags.

This phase does not add new core capability. Every behavior change is
a wiring change in `gui/basic.py` against existing
`core/`/`config/`/`utils/` surfaces.

## Locked-in design choices

These were resolved during brainstorming. They are not open for
re-litigation during implementation; if a real reason emerges to
change one, update this section and re-run review.

1. **One file, no second GUI module.** `gui/basic.py` stays the only
   GUI file; new logic lives in private functions inside it
   (`_render_defaults_panel`, `_collect_local_folder_inputs`,
   `_resolve_output_dir`, `_render_error`). Rationale: CLAUDE.md "Out
   of scope" explicitly bans a second GUI file (`simple_first.py`
   precedent). Estimated final size ~550 lines, comfortable for a
   single-page Streamlit app. If it ever crosses ~700 lines, extract a
   `gui/_components.py` then — not now.
2. **Settings UI = sidebar Defaults expander, collapsed by default.**
   Single-page app; no Streamlit `pages/` multi-page nav. Per-run
   sidebar widgets pre-fill from saved defaults but stay session-
   overridable. Rationale: lowest surface area, no boot-time
   restructuring, matches existing sidebar idiom.
3. **`oversize_policy` is settings-only.** No per-run override radio,
   no plumbing change to `run_pipeline` / `compress` / `run_ocr`.
   Today the policy is read from `get_config().settings` inside
   `core/compress.py:155` and `core/ocr.py:209`; that stays. The GUI
   only exposes the setting in the Defaults expander. Rationale: the
   default ("fallback") is correct for ~all real inputs; per-run
   override is a Phase 5 cross-cutting refactor, not GUI catchup.
4. **Batch input = existing browser multi-upload + new local folder
   path radio.** Mirror the single-file section's "Source" pattern:
   add a sibling option "Use local folder path (no size limit)".
   Rationale: lowest regression risk, same idiom that already works
   for single-file. Per `CLAUDE.local.md`, the user's real input shape
   is multi-GB ScanSnap output on a mounted Google Drive — browser-
   uploading is impossible, so this is the load-bearing addition.
5. **Local-folder batch reads inputs in place; no tempdir copy.**
   `run_batch(input_folder, output_folder, ...)` is called with the
   user-typed path directly. Rationale: copying a 4.8 GB textbook into
   a tempdir before processing defeats the whole point of folder mode.
6. **Output destination follows the `default_output_dir` setting when
   set.** Precedence (highest wins) is the same in every flow: (a)
   user-typed explicit output path for that run, (b)
   `cfg.settings.default_output_dir` if set and writable, (c) flow-
   specific fallback. Fallbacks: single-file → fresh tempdir; local-
   folder batch → `<input_folder>/processed/`; upload batch →
   fresh tempdir. Rationale: a setting that does nothing is dead
   code; tying it to actual output placement makes it useful.
   **Batch-into-default-dir nests in a timestamped subfolder**:
   when (b) is the chosen branch in batch mode, the GUI writes into
   `<default_output_dir>/batch_YYYYMMDD-HHMMSS/` rather than the bare
   default dir, so consecutive batches don't clobber each other's
   `batch_report.json`. Single-file does not nest (collision-safe
   timestamped filenames already come from `core/file_utils.py`).
7. **No "Recurse into subfolders" checkbox.** `core/batch.py:148`
   (`_collect_pdfs`) is non-recursive today and Phase 5 inherits that.
   Rationale: recursion is new core capability touching CLI + API +
   GUI; out of scope for "GUI catchup." Clean follow-up if the user's
   folder layout actually requires it.
8. **Error display uses `format_error_for_user()` only.** The Phase 4
   API stable error codes (`api/errors.py`) are HTTP-shape; the GUI
   doesn't go through HTTP. The existing `utils/errors.py:147`
   helper already returns `(user_message, suggestions, error_code)`
   for any exception including `PDFProcessingError` /
   `SystemToolError`; the GUI plugs that in instead of inventing a
   parallel mapping.
9. **Sidebar layout details are tuneable during the smoke test.**
   Exact widget order, label wording, expander vs. collapsible, and
   spacing are explicitly allowed to shift during the final browser
   smoke test session. The architecture and wiring (which widget
   reads from which setting field, save-defaults flow, source radios)
   are load-bearing; cosmetics are not.

## Architecture

One file, four new private renderer/helper functions, no new modules.
Call sites all live inside `main()`.

```
gui/basic.py
├── setup_streamlit()                           (existing)
├── _human(nbytes)                              (existing)
├── _chunk_copy(src, dst)                       (existing)
├── _render_defaults_panel(cfg) -> None         (NEW: sidebar expander)
├── _collect_local_folder_inputs(folder_path)   (NEW: pure; pre-flight summary)
│       -> {"pdf_count": int, "total_bytes": int, "valid": bool, "msg": str}
├── _resolve_output_dir(cfg, override) -> Path  (NEW: pure; tempdir-or-setting)
├── _render_error(exc) -> None                  (NEW: format_error_for_user wrapper)
└── main()                                      (existing, edited)
    ├── cfg = get_config()
    ├── _render_defaults_panel(cfg)             # at top of sidebar
    ├── (per-run sidebar widgets — pre-fill from cfg.settings)
    ├── single-file form
    └── batch section (with new "Source" radio)
```

The four new helpers stay pure (no `st.*` calls inside the two
collect/resolve helpers; the panel/error renderers do call `st.*` and
are tested only via import + smoke test, not unit).

## Components

### `_render_defaults_panel(cfg: ConfigManager)`

Renders an `st.sidebar.expander("⚙️ Defaults (saved across sessions)",
expanded=False)`. Inside:

- One widget per `AppSettings` field:
  - `default_preset`: selectbox over `["smallest", "balanced", "archival"]`
  - `default_language`: text input
  - `default_jobs`: slider 1..max_jobs
  - `default_output_dir`: text input (blank string treated as `None`)
  - `batch_concurrency`: slider 1..8
  - `oversize_policy`: selectbox `["fallback", "warn", "fail"]`
  - `tesseract_timeout`: number input (seconds; 0 = no timeout)
- Below the widgets: `st.button("💾 Save defaults")`. Click handler
  builds an `AppSettings(**form_values)` and calls
  `cfg.save_settings(new_settings)`, then `st.rerun()` so per-run
  controls re-init from the new defaults.
- The button is disabled while form values match saved values
  (cheap dict comparison) so it can never be a no-op click.
- Path validation for `default_output_dir`: if non-blank, attempt
  `Path(value).expanduser().mkdir(parents=True, exist_ok=True)` inside
  the save handler; on `OSError` show `st.error` with the original
  exception and don't save.

### Per-run sidebar widgets (existing block, edited)

Every per-run widget switches from a hardcoded literal to a value
sourced from `cfg.settings`:

| Widget | Today (literal) | After Phase 5 (from settings) |
|---|---|---|
| `preset` selectbox | `index=0` of `["balanced", "archival", "smallest"]` | computed `index` of `cfg.settings.default_preset` in `["smallest", "balanced", "archival"]` |
| `lang` text_input | `value="eng"` | `value=cfg.settings.default_language` |
| `jobs` slider | `value=min(4, max_jobs)` | `value=min(cfg.settings.default_jobs, max_jobs)` |
| `pdfa` checkbox | `value=False` | `value=False` (no setting field) |
| `force_ocr` checkbox | `value=False` | `value=False` (no setting field) |
| `source_mode` radio | first option default | first option default (no change) |
| `mode` radio | first option default | first option default (no change) |

The preset list reorder (`smallest` first) is intentional and aligns
with design rule #4 ("`smallest` is the default preset"). It also
makes the dropdown read top-to-bottom in the order most users want.

### `_resolve_output_dir(cfg, override, fallback_factory) -> tuple[Path, str]`

Pure helper used by every flow. Returns `(path, source)` where
`source` is one of `"override"`, `"setting"`, `"fallback"`,
`"fallback_after_unwritable"` so the caller can decide whether to
show a "Saved to:" line, a one-shot warning, etc.

```
def _resolve_output_dir(cfg, override, fallback_factory):
    if override is not None:
        return _ensure_writable(override), "override"
    if cfg.settings.default_output_dir is not None:
        try:
            return _ensure_writable(cfg.settings.default_output_dir), "setting"
        except OSError:
            return fallback_factory(), "fallback_after_unwritable"
    return fallback_factory(), "fallback"
```

- Single-file: `fallback_factory = lambda: Path(tempfile.mkdtemp(prefix="pdfgui_"))`.
- Local-folder batch: `fallback_factory = lambda: input_folder / "processed"`.
  In batch mode, when `source == "setting"` the caller wraps the
  returned path in a timestamped subfolder per locked-in choice #6
  (`base / f"batch_{timestamp}"`).
- Upload batch: `fallback_factory = lambda: Path(tempfile.mkdtemp(prefix="pdfgui_batch_"))`.

When `source == "fallback_after_unwritable"`, the caller emits a one-
shot `st.warning` via a session-state flag so the user knows their
`default_output_dir` setting wasn't honored.

### `_collect_local_folder_inputs(folder_str: str) -> dict`

Pure helper for the folder-mode pre-flight summary. Given a typed
path, returns a dict with `pdf_count`, `total_bytes`, `valid` (bool),
`msg` (the line to show in `st.info`/`st.warning`). Empty string
returns `{valid: False, msg: ""}`. Non-existent path returns warning.
Folder with zero PDFs returns warning. Folder with PDFs returns info
line `"Found N PDFs, total X.X GB. Output → <path>."`.

This is the only batch-mode helper that's a real unit test target.

### `_render_error(exc: Exception)`

Calls `format_error_for_user(exc)` from `utils/errors.py`, then:
- `st.error(user_message)`
- if `suggestions`: `st.info` with bullet list
- `st.caption(f"Error code: {error_code}")`

Used everywhere the GUI today does `st.error(f"...{e}")`.

### Single-file flow changes (inside `main()`)

1. Replace each hardcoded sidebar default with the matching
   `cfg.settings.*` value (per the table above).
2. Resolve output destination via
   `out_dir, source = _resolve_output_dir(cfg, override=None,
   fallback_factory=lambda: Path(tempfile.mkdtemp(prefix="pdfgui_")))`.
   Compute `out_base = out_dir / f"{input_stem}.pdf"` where
   `input_stem` is `Path(local_path_str).stem` for local-path mode or
   `Path(uploaded.name).stem` for upload mode. (`run_pipeline`'s
   collision-safe naming then produces e.g.
   `<input_stem>_processed_TIMESTAMP.pdf`, matching what users
   expect when files land in a real folder rather than a tempdir.)
3. Replace both `st.error(f"...{e}")` blocks with `_render_error(e)`.
4. Add a `Saved to: <path>` line to the success banner when
   `source in ("override", "setting")` (not for tempdir — the
   download button is the affordance there). When
   `source == "fallback_after_unwritable"`, also emit the one-shot
   `st.warning` about the unhonored setting.

### Batch flow changes (inside `main()`)

1. Add a `st.radio("Source", ["Upload multiple PDFs in browser", "Use
   local folder path (no size limit)"])` above the existing file
   uploader.
2. Branch on the radio:
   - **Upload mode**: existing behavior unchanged in shape — uploads
     are written to a `pdfgui_batch_` tempdir as today (resolved via
     `_resolve_output_dir(cfg, override=None,
     fallback_factory=lambda: Path(tempfile.mkdtemp(prefix="pdfgui_batch_")))`
     so a configured `default_output_dir` is still honored). Per-
     file download buttons stay only in this mode.
   - **Local folder mode**:
     - Two text inputs: input folder (required), output folder
       (optional). Output resolution per locked-in choice #6:
       (a) typed output folder if non-blank → that path.
       (b) `default_output_dir` if set and writable →
       `<default_output_dir>/batch_YYYYMMDD-HHMMSS/`.
       (c) fallback → `<input_folder>/processed/`.
     - On any change to the input field, call
       `_collect_local_folder_inputs` and render the pre-flight info
       line. Disable the Process button when `valid=False`.
     - Process click calls `run_batch(input_folder, output_folder,
       ...)` directly with no tempdir copy.
3. Replace the orchestrator-level `st.error(f"...{e}")` with
   `_render_error(e)`.
4. After successful local-folder batch: show
   `st.success(f"Outputs in: {output_folder}")` plus
   `batch_report.json` download. No per-file download buttons.

## Data flow

```
.------------.       .--------------.       .------------------.
| settings.  | <---> | ConfigManager| <---> | _render_defaults_|
| json       |       |  (cfg)       |       |   panel()        |
'------------'       '--------------'       '------------------'
                            |
                            v
                     .--------------.
                     | cfg.settings | -- pre-fills --> per-run widgets
                     '--------------'                       |
                                                            v
                                                  .---------------------.
                                                  | run_pipeline()  /   |
                                                  | run_batch()         |
                                                  '---------------------'
                                                            |
                                                            v
                                              .------------------.
                                              | ProcessResult /  |
                                              | BatchReport      |
                                              '------------------'
                                                            |
                                                            v
                                              .--------------------.
                                              | success banner +   |
                                              | downloads / paths  |
                                              '--------------------'

(any exception) ---> _render_error() ---> st.error + st.info + st.caption
```

`oversize_policy`, `tesseract_timeout`, and `batch_concurrency` flow
into the pipeline implicitly via `get_config().settings` reads inside
`core/`; no kwargs added to GUI call sites.

## Error handling

All exception handling in `gui/basic.py` routes through
`_render_error(exc)`:

- `needs_ocr` analyze step: today's `try/except Exception`
  fallback-to-`True` path stays — the GUI continues silently if
  detection fails (already correct). No error rendering needed there.
- Single-file `run_pipeline` block: catch `Exception`, call
  `_render_error(e)`, clean up workdir, `st.stop()`.
- Single-file save-defaults handler: catch `OSError` from
  `default_output_dir.mkdir(...)`, call `_render_error(e)`, do not
  save.
- Batch `run_batch` block: catch `Exception`, call `_render_error(e)`,
  `st.stop()`. Per-file failures inside `run_batch` are already
  surfaced via the `BatchReport.results` table; that path doesn't
  change.

No new exception types introduced. The Phase 4 stable error code
strings (`INPUT_NOT_PDF`, etc.) are HTTP wire-shape concerns and stay
inside `api/`.

## Testing

### Unit tests (`tests/test_gui_helpers.py`, NEW)

Pure-helper coverage. No Streamlit imports; just import the helpers
and exercise them.

- `_resolve_output_dir`:
  - override given → returns `(override, "override")`.
  - `default_output_dir` set and writable → returns
    `(default_output_dir, "setting")` (uses `tmp_path`).
  - `default_output_dir` set but unwritable → calls fallback factory
    and returns `(<factory_path>, "fallback_after_unwritable")` (mock
    `Path.mkdir` to raise `OSError`).
  - `default_output_dir` unset → calls fallback factory and returns
    `(<factory_path>, "fallback")`.
  - fallback factory is invoked exactly once when reached (assert via
    a counter closure).
- `_collect_local_folder_inputs`:
  - empty string → `valid=False`, empty `msg`.
  - non-existent path → `valid=False`, warning message.
  - folder with zero PDFs → `valid=False`, warning message.
  - folder with N PDFs → `valid=True`, `pdf_count=N`, correct byte
    sum, info-shape message.

### Existing import smoke tests (no change)

```bash
uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"
```

Stays as today. Validates the file imports without crashing — the
ceiling of what's testable for a Streamlit GUI without a browser.

### Browser click-through smoke test (`tests/gui_smoke.md`, NEW)

Manual checklist file. Phase 5 deliverable: walk it on a real browser,
record results inline, commit. Closes the CLAUDE.md "GUI not click-
through tested" gap.

- [ ] `uv run pdf-ocr-gui` launches at `http://localhost:8501`.
- [ ] Sidebar Defaults expander opens; current `settings.json` values
      pre-fill the fields.
- [ ] Change `default_preset` to `archival`, click Save defaults;
      reload tab; verify the saved value persists in `settings.json`
      and the per-run preset selector now defaults to `archival`.
- [ ] Single-file flow, browser upload: small ScanSnap PDF → Process →
      success banner shows preset/size delta/OCR routing → download
      works.
- [ ] Single-file flow, local path: same PDF via local-path radio →
      output lands in `default_output_dir` if set, else tempdir →
      "Saved to:" line shows correct path when the setting is set.
- [ ] Force an error: point local path at a non-PDF (e.g. a `.txt`) →
      friendly headline + suggestions list + error code caption all
      visible.
- [ ] Batch flow, browser upload: 2-3 small PDFs → progress bar
      advances → results table populates → `batch_report.json`
      downloads.
- [ ] Batch flow, local folder path: point at a small folder of PDFs
      (e.g. 3 from `pdfs/`) → outputs appear in the chosen folder on
      disk → success banner shows correct output path → no per-file
      download buttons (correct) → `batch_report.json` correct.
- [ ] Tool-missing error: temporarily PATH-strip Tesseract or
      Ghostscript, run a flow that needs it, verify `SystemToolError`
      surfaces with the correct installation suggestions.

After all boxes check: edit CLAUDE.md "Known issues" to remove the
"GUI not click-through tested in a browser" line.

## Build sequence

The implementation plan (writing-plans skill) will sequence this; the
expected build order:

1. New helpers (`_resolve_output_dir`, `_collect_local_folder_inputs`,
   `_render_error`) + their unit tests, before any GUI editing. Pure
   functions, TDD-eligible (per global rules: pure-logic modules
   write failing test first).
2. `_render_defaults_panel` rendered into the sidebar; per-run widgets
   rewired to read from `cfg.settings`. Verify save-defaults round-
   trips through `ConfigManager` via the smoke test step on Defaults.
3. Single-file flow swap-in of `_resolve_output_dir` + `_render_error`.
4. Batch section's Source radio + local-folder branch.
5. Browser smoke test, fix any cosmetics, update CLAUDE.md.

## Out of scope

Explicitly NOT in Phase 5 (deferred to later phases or future work):

- Multi-page Streamlit nav (`pages/` directory).
- Second GUI file (`simple_first.py`-style — banned by CLAUDE.md).
- Async, thread pools, in-process caching layers.
- New core capability:
  - `core/batch.py` recursion into subfolders.
  - `FILE_TOO_LARGE` enforcement (no `max_upload_bytes` setting).
  - Batch-job cancellation (Phase 4 deferred this; Phase 5 doesn't
    revisit).
  - Per-run `oversize_policy` override plumbing through
    `run_pipeline` / `compress` / `run_ocr`.
- CLI changes. The CLI's hardcoded surface defaults (preset/lang/jobs)
  stay hardcoded for now — fixing that is its own follow-up.
- README / API examples / `--pdfa` docs / batch-flag docs — that's
  Phase 6 (documentation polish).
- Mapping API stable error codes (`INPUT_NOT_PDF` etc.) into the GUI.
  Those are HTTP wire-shape; the GUI talks to `core/` directly and
  uses `format_error_for_user` for friendliness.

## Success criteria

- All seven CLAUDE.md gaps for Phase 5 are closed (defaults wired,
  settings UI present, default preset corrected, oversize policy
  visible, folder batch mode, friendly errors, browser smoke test).
- `tests/test_gui_helpers.py` exists with 8+ passing tests covering
  `_resolve_output_dir` and `_collect_local_folder_inputs`.
- `tests/gui_smoke.md` exists with all checklist items checked off
  from a recorded run.
- `uv run pytest` is green; `uv run ruff check src/` and
  `uv run black src/` are green.
- CLAUDE.md "Known issues" no longer mentions GUI click-through gap;
  "Where I left off" section updated to point at Phase 6.
- ROADMAP.md Phase 5 box is checked.
