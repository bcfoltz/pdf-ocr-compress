# Phase 5 GUI Catchup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `gui/basic.py` in line with everything Phase 1–4 added — wire defaults to `AppSettings`, add a sidebar Defaults expander, add local-folder-path batch mode, plug Phase 4's friendly error helper into every exception site, and close the "GUI not click-through tested" gap with a documented browser smoke test.

**Architecture:** Single file (`src/pdf_ocr_compress/gui/basic.py`) gains four private helpers (two pure, two Streamlit-side). Every per-run sidebar widget pre-fills from `get_config().settings`. Output destination flows through one `_resolve_output_dir(cfg, override, fallback_factory) -> (path, source)` helper used by all three flows (single-file, upload-batch, folder-batch). All exception sites route through `_render_error()` which delegates to existing `utils/errors.py:format_error_for_user`. No new core capability, no new modules.

**Tech Stack:** Python 3.10+, Streamlit, uv, pytest, ruff, black. Reads from existing `core/`, `config/`, `utils/`.

---

## File Structure

**Files to modify:**
- `src/pdf_ocr_compress/gui/basic.py` — sole GUI module; gains four private helpers and rewires `main()` to read defaults from `get_config()`.
- `CLAUDE.md` — Phase 5 closure: remove "GUI not click-through tested" from Known issues, update "Where I left off" to point at Phase 6.
- `ROADMAP.md` — check off Phase 5.

**Files to create:**
- `tests/test_gui_helpers.py` — unit tests for the two pure helpers (`_resolve_output_dir`, `_collect_local_folder_inputs`).
- `tests/gui_smoke.md` — manual browser click-through checklist (filled in during Task 7).

**Files NOT to create (locked by spec):**
- No `gui/_components.py`, `gui/settings_panel.py`, `gui/error.py`, etc. Everything stays in `gui/basic.py`.
- No `pages/` directory (no Streamlit multi-page nav).

---

## Task 1: Pure helper `_resolve_output_dir` (TDD)

**Files:**
- Create: `tests/test_gui_helpers.py`
- Modify: `src/pdf_ocr_compress/gui/basic.py` (add private helper; do not call from `main()` yet)

The helper resolves output destination for every flow. Returns `(Path, source)` where `source ∈ {"override", "setting", "fallback", "fallback_after_unwritable"}`. Pure: no `st.*` calls inside.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui_helpers.py` with the full suite up front (5 tests). The helper isn't defined yet, so every test should fail at import.

```python
"""Unit tests for pure helpers in pdf_ocr_compress.gui.basic.

The Streamlit GUI is not unit-tested as a whole (UI code, no TDD
requirement). These tests cover the pure path/file helpers that the
GUI uses to decide where output goes and to render folder-mode pre-
flight summaries.
"""
from pathlib import Path

import pytest

from pdf_ocr_compress.config.settings import AppSettings, ConfigManager
from pdf_ocr_compress.gui.basic import _resolve_output_dir


def _cfg_with(tmp_path, **overrides) -> ConfigManager:
    """Return a ConfigManager whose settings reflect the given overrides.

    `tmp_path` is used as the config_dir so we never touch the user's
    real settings.json.
    """
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    for k, v in overrides.items():
        setattr(cfg.settings, k, v)
    return cfg


def test_resolve_output_dir_override_wins(tmp_path):
    cfg = _cfg_with(tmp_path, default_output_dir=tmp_path / "should_be_ignored")
    override = tmp_path / "user_typed"
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        return tmp_path / "fallback"

    path, source = _resolve_output_dir(cfg, override=override, fallback_factory=fallback)

    assert path == override
    assert source == "override"
    assert override.is_dir()
    assert fallback_calls["n"] == 0


def test_resolve_output_dir_setting_used_when_writable(tmp_path):
    setting_dir = tmp_path / "setting"
    cfg = _cfg_with(tmp_path, default_output_dir=setting_dir)
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        return tmp_path / "fallback"

    path, source = _resolve_output_dir(cfg, override=None, fallback_factory=fallback)

    assert path == setting_dir
    assert source == "setting"
    assert setting_dir.is_dir()
    assert fallback_calls["n"] == 0


def test_resolve_output_dir_fallback_when_setting_unset(tmp_path):
    cfg = _cfg_with(tmp_path, default_output_dir=None)
    fallback_dir = tmp_path / "fallback"
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        fallback_dir.mkdir()
        return fallback_dir

    path, source = _resolve_output_dir(cfg, override=None, fallback_factory=fallback)

    assert path == fallback_dir
    assert source == "fallback"
    assert fallback_calls["n"] == 1


def test_resolve_output_dir_fallback_after_unwritable(tmp_path, monkeypatch):
    """If default_output_dir is set but mkdir raises, fall back and report it."""
    setting_dir = tmp_path / "unwritable"
    cfg = _cfg_with(tmp_path, default_output_dir=setting_dir)
    fallback_dir = tmp_path / "fallback"

    real_mkdir = Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if self == setting_dir:
            raise OSError("simulated read-only filesystem")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    def fallback():
        fallback_dir.mkdir()
        return fallback_dir

    path, source = _resolve_output_dir(cfg, override=None, fallback_factory=fallback)

    assert path == fallback_dir
    assert source == "fallback_after_unwritable"


def test_resolve_output_dir_factory_invoked_at_most_once(tmp_path):
    """Factory must be called only on the actual fallback paths."""
    cfg = _cfg_with(tmp_path, default_output_dir=tmp_path / "setting")
    calls = {"n": 0}

    def fallback():
        calls["n"] += 1
        return tmp_path / "never"

    _resolve_output_dir(cfg, override=None, fallback_factory=fallback)
    assert calls["n"] == 0
```

- [ ] **Step 2: Run tests — verify they fail at import**

Run: `uv run pytest tests/test_gui_helpers.py -v`

Expected: All 5 tests fail or error with `ImportError: cannot import name '_resolve_output_dir' from 'pdf_ocr_compress.gui.basic'`.

- [ ] **Step 3: Implement `_resolve_output_dir`**

Add the helper to `src/pdf_ocr_compress/gui/basic.py`. Insert near the existing `_human` / `_chunk_copy` helpers, above `main()`.

```python
def _ensure_writable(path: Path) -> Path:
    """mkdir -p the path; raise OSError if it can't be created/written."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_output_dir(
    cfg, override: Path | None, fallback_factory
) -> tuple[Path, str]:
    """Resolve where output files go, in priority order.

    Returns (path, source) where source is one of:
      - "override":                   user-typed explicit path was used
      - "setting":                    cfg.settings.default_output_dir was used
      - "fallback":                   default_output_dir unset; factory used
      - "fallback_after_unwritable":  default_output_dir set but mkdir raised

    Caller decides whether to surface a "Saved to:" line, a one-shot
    warning about an unhonored setting, etc.
    """
    if override is not None:
        return _ensure_writable(override), "override"

    setting = cfg.settings.default_output_dir
    if setting is not None:
        try:
            return _ensure_writable(Path(setting)), "setting"
        except OSError:
            return fallback_factory(), "fallback_after_unwritable"

    return fallback_factory(), "fallback"
```

Also add `from pathlib import Path` at the import block — verify it's already there (it is in the existing file).

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/test_gui_helpers.py -v`

Expected: 5 passed.

- [ ] **Step 5: Lint + format**

Run: `uv run ruff check src/ tests/` and `uv run black --check src/ tests/`

Expected: both clean. If `black --check` fails, run `uv run black src/ tests/` to fix and re-verify.

- [ ] **Step 6: Commit**

```bash
git add tests/test_gui_helpers.py src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 5 task 1: _resolve_output_dir pure helper + tests"
```

---

## Task 2: Pure helper `_collect_local_folder_inputs` (TDD)

**Files:**
- Modify: `tests/test_gui_helpers.py` (append tests)
- Modify: `src/pdf_ocr_compress/gui/basic.py` (add second helper)

The helper provides the pre-flight summary line for the new local-folder batch mode. Given a typed string, returns a dict the GUI can render. Pure: no `st.*` calls.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui_helpers.py` (after the existing imports and tests):

```python
from pdf_ocr_compress.gui.basic import _collect_local_folder_inputs


def test_collect_inputs_empty_string():
    info = _collect_local_folder_inputs("")
    assert info == {"valid": False, "msg": "", "pdf_count": 0, "total_bytes": 0}


def test_collect_inputs_path_does_not_exist(tmp_path):
    info = _collect_local_folder_inputs(str(tmp_path / "does_not_exist"))
    assert info["valid"] is False
    assert "not found" in info["msg"].lower() or "does not exist" in info["msg"].lower()
    assert info["pdf_count"] == 0


def test_collect_inputs_path_is_a_file_not_a_folder(tmp_path):
    file_path = tmp_path / "actually_a_file.pdf"
    file_path.write_bytes(b"%PDF-1.4\n%EOF\n")
    info = _collect_local_folder_inputs(str(file_path))
    assert info["valid"] is False
    assert "folder" in info["msg"].lower() or "directory" in info["msg"].lower()


def test_collect_inputs_folder_with_zero_pdfs(tmp_path):
    (tmp_path / "readme.txt").write_text("not a pdf")
    info = _collect_local_folder_inputs(str(tmp_path))
    assert info["valid"] is False
    assert "no" in info["msg"].lower() and "pdf" in info["msg"].lower()
    assert info["pdf_count"] == 0


def test_collect_inputs_folder_with_pdfs_reports_count_and_bytes(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 1000)
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4\n" + b"y" * 2000)
    (tmp_path / "ignored.txt").write_text("ignore me")
    info = _collect_local_folder_inputs(str(tmp_path))
    assert info["valid"] is True
    assert info["pdf_count"] == 2
    expected_bytes = (tmp_path / "a.pdf").stat().st_size + (tmp_path / "b.pdf").stat().st_size
    assert info["total_bytes"] == expected_bytes
    assert "2 PDFs" in info["msg"]


def test_collect_inputs_expanduser(tmp_path, monkeypatch):
    """Ensure ~ in the typed path is expanded."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF\n")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows
    info = _collect_local_folder_inputs("~")
    assert info["valid"] is True
    assert info["pdf_count"] == 1
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/test_gui_helpers.py -v`

Expected: 5 prior tests pass; 6 new tests fail with `ImportError: cannot import name '_collect_local_folder_inputs'`.

- [ ] **Step 3: Implement `_collect_local_folder_inputs`**

Add to `src/pdf_ocr_compress/gui/basic.py` next to `_resolve_output_dir`:

```python
def _collect_local_folder_inputs(folder_str: str) -> dict:
    """Pre-flight summary for the batch local-folder input field.

    Returns a dict with:
      - valid (bool):     True when the folder exists and contains >=1 PDF
      - msg (str):        the line to render via st.info / st.warning
      - pdf_count (int):  PDFs found (non-recursive; *.pdf in folder)
      - total_bytes (int): sum of stat sizes
    Empty string returns valid=False with empty msg (used to disable the
    button without displaying anything noisy on first render).
    """
    if not folder_str.strip():
        return {"valid": False, "msg": "", "pdf_count": 0, "total_bytes": 0}

    folder = Path(folder_str).expanduser()
    if not folder.exists():
        return {
            "valid": False,
            "msg": f"Path not found: {folder}",
            "pdf_count": 0,
            "total_bytes": 0,
        }
    if not folder.is_dir():
        return {
            "valid": False,
            "msg": f"Not a folder (this is a file): {folder}",
            "pdf_count": 0,
            "total_bytes": 0,
        }

    pdfs = sorted(p for p in folder.glob("*.pdf") if p.is_file())
    if not pdfs:
        return {
            "valid": False,
            "msg": f"No PDFs found in {folder} (non-recursive)",
            "pdf_count": 0,
            "total_bytes": 0,
        }

    total_bytes = sum(p.stat().st_size for p in pdfs)
    return {
        "valid": True,
        "msg": f"Found {len(pdfs)} PDFs ({_human(total_bytes)}) in {folder}",
        "pdf_count": len(pdfs),
        "total_bytes": total_bytes,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/test_gui_helpers.py -v`

Expected: 11 passed (5 from Task 1 + 6 from Task 2).

- [ ] **Step 5: Lint + format**

Run: `uv run ruff check src/ tests/` and `uv run black --check src/ tests/`. Fix with `uv run black src/ tests/` if needed.

- [ ] **Step 6: Commit**

```bash
git add tests/test_gui_helpers.py src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 5 task 2: _collect_local_folder_inputs pure helper + tests"
```

---

## Task 3: Streamlit shim `_render_error`

**Files:**
- Modify: `src/pdf_ocr_compress/gui/basic.py` (add helper; do not call from `main()` yet)

Streamlit-side helper. Calls `format_error_for_user` from `utils/errors.py` and renders `st.error` + `st.info` (suggestions) + `st.caption` (error code). UI code, no unit test (per global rules: UI code, no TDD requirement). Coverage comes from the browser smoke test in Task 7.

- [ ] **Step 1: Add the import**

In `src/pdf_ocr_compress/gui/basic.py`, find the existing `try/except ImportError` block that imports from `.core.*` / `pdf_ocr_compress.core.*`. Add a parallel block for `utils.errors`:

```python
try:
    from .core.batch import run_batch
    from .core.detect import needs_ocr
    from .core.pipeline import run_pipeline
    from .utils.errors import format_error_for_user
except ImportError:
    from pdf_ocr_compress.core.batch import run_batch
    from pdf_ocr_compress.core.detect import needs_ocr
    from pdf_ocr_compress.core.pipeline import run_pipeline
    from pdf_ocr_compress.utils.errors import format_error_for_user
```

- [ ] **Step 2: Add the helper**

Insert below `_resolve_output_dir` / `_collect_local_folder_inputs`:

```python
def _render_error(exc: Exception) -> None:
    """Render any exception via Phase 4's user-friendly formatter.

    Replaces ad-hoc `st.error(f"...{e}")` strings in the GUI. The
    formatter (utils/errors.format_error_for_user) handles
    PDFProcessingError / SystemToolError plus common Python exceptions
    and falls back to a generic message for anything else.
    """
    user_msg, suggestions, error_code = format_error_for_user(exc)
    st.error(user_msg)
    if suggestions:
        bullets = "\n".join(f"- {s}" for s in suggestions)
        st.info(bullets)
    if error_code:
        st.caption(f"Error code: `{error_code}`")
```

- [ ] **Step 3: Verify import smoke test still passes**

Run: `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"`

Expected: `GUI ok` printed, no exceptions.

- [ ] **Step 4: Lint + format**

Run: `uv run ruff check src/` and `uv run black --check src/`.

- [ ] **Step 5: Commit**

```bash
git add src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 5 task 3: _render_error wraps format_error_for_user for the GUI"
```

---

## Task 4: Sidebar Defaults expander + per-run widget rewiring

**Files:**
- Modify: `src/pdf_ocr_compress/gui/basic.py` (add `_render_defaults_panel`; rewire sidebar widgets in `main()`)

This is the biggest cosmetic change. The Defaults expander persists `AppSettings`; per-run widgets pre-fill from those saved settings.

- [ ] **Step 1: Add `_render_defaults_panel` helper**

Insert in `src/pdf_ocr_compress/gui/basic.py` near the other private helpers. The helper is a thin Streamlit shim — it reads the current `cfg.settings`, renders form widgets in an expander, and on Save click builds a new `AppSettings`, validates the output dir, calls `cfg.save_settings(new)`, and `st.rerun()`s.

```python
try:
    from .config.settings import AppSettings
except ImportError:
    from pdf_ocr_compress.config.settings import AppSettings


_PRESET_CHOICES = ["smallest", "balanced", "archival"]
_OVERSIZE_CHOICES = ["fallback", "warn", "fail"]


def _render_defaults_panel(cfg) -> None:
    """Sidebar expander: edit and persist AppSettings.

    Per-run sidebar widgets below this expander pre-fill from the saved
    values. After 'Save defaults' click, settings.json is written and
    st.rerun() refreshes the page so per-run controls re-init.
    """
    s = cfg.settings
    with st.sidebar.expander("⚙️  Defaults (saved across sessions)", expanded=False):
        new_preset = st.selectbox(
            "Default preset",
            _PRESET_CHOICES,
            index=_PRESET_CHOICES.index(s.default_preset)
            if s.default_preset in _PRESET_CHOICES
            else 0,
            key="def_preset",
        )
        new_lang = st.text_input(
            "Default OCR languages", value=s.default_language, key="def_lang"
        )
        new_jobs = st.slider(
            "Default parallel jobs",
            min_value=1,
            max_value=max(1, min(32, os.cpu_count() or 8)),
            value=int(s.default_jobs),
            key="def_jobs",
        )
        new_output_dir_str = st.text_input(
            "Default output directory (blank = unset)",
            value=str(s.default_output_dir) if s.default_output_dir else "",
            placeholder=r"e.g. G:\My Drive\Book Scans\Processed",
            key="def_output_dir",
        )
        new_batch_concurrency = st.slider(
            "Batch concurrency",
            min_value=1,
            max_value=8,
            value=int(s.batch_concurrency),
            key="def_batch_conc",
        )
        new_oversize = st.selectbox(
            "Oversize policy",
            _OVERSIZE_CHOICES,
            index=_OVERSIZE_CHOICES.index(s.oversize_policy)
            if s.oversize_policy in _OVERSIZE_CHOICES
            else 0,
            help=(
                "fallback = retry with smallest preset, then passthrough; "
                "warn = keep larger output but warn; "
                "fail = raise an error."
            ),
            key="def_oversize",
        )
        new_tess_timeout = st.number_input(
            "Tesseract timeout (seconds; 0 = no timeout)",
            min_value=0,
            value=int(s.tesseract_timeout),
            step=10,
            key="def_tess_timeout",
        )

        candidate = AppSettings(
            default_preset=new_preset,
            default_language=new_lang,
            default_jobs=int(new_jobs),
            default_output_dir=Path(new_output_dir_str).expanduser()
            if new_output_dir_str.strip()
            else None,
            batch_concurrency=int(new_batch_concurrency),
            oversize_policy=new_oversize,
            tesseract_timeout=int(new_tess_timeout),
        )
        is_dirty = candidate != s

        if st.button("💾 Save defaults", disabled=not is_dirty, key="def_save"):
            try:
                if candidate.default_output_dir is not None:
                    candidate.default_output_dir.mkdir(parents=True, exist_ok=True)
                cfg.save_settings(candidate)
                st.success("Defaults saved.")
                st.rerun()
            except OSError as exc:
                _render_error(exc)
```

Note: `os`, `Path`, and `st` are already imported at the top of the file. `AppSettings` is added in this step. The `_OVERSIZE_CHOICES` / `_PRESET_CHOICES` lists are module-level constants so they're built once.

- [ ] **Step 2: Add `get_config` import**

In the existing import-fallback block, add the `config` import:

```python
try:
    from .config import get_config
    from .config.settings import AppSettings
    from .core.batch import run_batch
    from .core.detect import needs_ocr
    from .core.pipeline import run_pipeline
    from .utils.errors import format_error_for_user
except ImportError:
    from pdf_ocr_compress.config import get_config
    from pdf_ocr_compress.config.settings import AppSettings
    from pdf_ocr_compress.core.batch import run_batch
    from pdf_ocr_compress.core.detect import needs_ocr
    from pdf_ocr_compress.core.pipeline import run_pipeline
    from pdf_ocr_compress.utils.errors import format_error_for_user
```

(Move `AppSettings` from Step 1 here — single import block.)

- [ ] **Step 3: Wire `cfg` into `main()` and call the panel renderer**

In `main()`, near the top (after `setup_streamlit()` and the title/caption block, before the `with st.sidebar:` block):

```python
def main():
    """Main Streamlit application."""
    setup_streamlit()

    st.title("🧰 PDF OCR + Compression")
    st.caption(
        "Process SCANNED PDFs with OCRmyPDF + Ghostscript. "
        "Designed for scanned documents, not native digital PDFs. "
        "• Never overwrites originals • Always writes brand-new files • Handles very large PDFs."
    )

    cfg = get_config()
    _render_defaults_panel(cfg)
    s = cfg.settings  # shorthand for per-run pre-fill below

    with st.expander("📄 Is this tool right for your PDF?"):
        ...  # unchanged
```

- [ ] **Step 4: Rewire per-run sidebar widgets to pre-fill from `s`**

Inside the existing `with st.sidebar:` block, edit the four affected widgets:

```python
    with st.sidebar:
        st.header("Options")
        source_mode = st.radio(
            "File source",
            ["Upload in browser", "Use local file path (no size limit)"],
            help="Local path mode reads directly from disk and bypasses any browser upload limit.",
        )
        mode = st.radio(
            "Processing mode",
            ["Auto (OCR if needed)", "OCR only", "Compress only"],
            help="Auto: Detects scanned pages needing OCR, then compresses. OCR only: Force text recognition on scanned content. Compress only: Skip OCR, just optimize file size.",
        )
        preset = st.selectbox(
            "Quality preset",
            _PRESET_CHOICES,
            index=_PRESET_CHOICES.index(s.default_preset)
            if s.default_preset in _PRESET_CHOICES
            else 0,
            help="smallest = most aggressive (default for ScanSnap); balanced = high quality/smaller; archival = minimal change.",
        )
        lang = st.text_input(
            "OCR languages (Tesseract codes)",
            value=s.default_language,
            help="Use + to combine, e.g. eng+spa",
        )
        pdfa = st.checkbox("Produce PDF/A-2", value=False)
        force_ocr = st.checkbox("Force OCR (even if text exists)", value=False)

        max_jobs = max(1, min(32, os.cpu_count() or 8))
        jobs = st.slider(
            "Parallel jobs",
            min_value=1,
            max_value=max_jobs,
            value=min(int(s.default_jobs), max_jobs),
            step=1,
        )
```

The four behavior changes vs. today:
1. `preset` list reordered to `_PRESET_CHOICES` (`smallest` first).
2. `preset` index computed from `s.default_preset` instead of hardcoded `0`.
3. `lang` value from `s.default_language` instead of `"eng"`.
4. `jobs` value clamped from `s.default_jobs` instead of hardcoded `4`.

- [ ] **Step 5: Verify imports + module loads**

Run: `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"`

Expected: `GUI ok` with no errors. (Import-time failure here would mean a typo or missing import.)

- [ ] **Step 6: Verify the unit tests still pass**

Run: `uv run pytest tests/test_gui_helpers.py -v`

Expected: 11 passed (Task 1 + 2 tests still green; this task didn't touch them but the import surface changed).

- [ ] **Step 7: Lint + format**

Run: `uv run ruff check src/` and `uv run black --check src/`.

- [ ] **Step 8: Commit**

```bash
git add src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 5 task 4: sidebar Defaults expander; per-run widgets read from settings"
```

---

## Task 5: Single-file flow rewire

**Files:**
- Modify: `src/pdf_ocr_compress/gui/basic.py` (the single-file processing block inside `main()`)

Three behavior changes:
1. Output destination flows through `_resolve_output_dir(cfg, override=None, fallback_factory=tempdir_factory)` — landing in `default_output_dir` when set, else a tempdir.
2. `out_base` filename uses the input stem (e.g. `book_scan.pdf` → `book_scan_processed_TIMESTAMP.pdf`) instead of the literal `output.pdf` artifact.
3. Both `st.error(f"...{e}")` blocks switch to `_render_error(e)`.

- [ ] **Step 1: Replace `out_base` resolution and add Saved-to surface**

Find the block that today reads:

```python
    if run_btn:
        workdir = Path(tempfile.mkdtemp(prefix="pdfgui_"))
        out_base = (
            workdir / "output.pdf"
        )  # base name; functions will create unique outputs

        # Determine input path
        if source_mode == "Upload in browser":
            in_path = workdir / "input.pdf"
            try:
                _chunk_copy(uploaded, in_path)
            except Exception as e:
                st.error(f"Failed to save uploaded file: {e}")
                st.stop()
        else:
            in_path = Path(local_path_str).expanduser()
            if not (in_path.exists() and in_path.is_file()):
                st.error("Local file not found. Please check the path.")
                st.stop()
```

Replace it with:

```python
    if run_btn:
        # Resolve where the produced file should land. _resolve_output_dir
        # honors cfg.settings.default_output_dir when set; otherwise a fresh
        # tempdir is created.
        out_dir, out_source = _resolve_output_dir(
            cfg,
            override=None,
            fallback_factory=lambda: Path(tempfile.mkdtemp(prefix="pdfgui_")),
        )

        # Determine input path. Uploads still need a writable workdir to
        # land the input bytes; reuse a tempdir for that even when out_dir
        # is the user's default_output_dir.
        if source_mode == "Upload in browser":
            input_workdir = Path(tempfile.mkdtemp(prefix="pdfgui_in_"))
            in_stem = Path(uploaded.name).stem
            in_path = input_workdir / "input.pdf"
            try:
                _chunk_copy(uploaded, in_path)
            except Exception as e:
                _render_error(e)
                st.stop()
        else:
            in_path = Path(local_path_str).expanduser()
            if not (in_path.exists() and in_path.is_file()):
                st.error("Local file not found. Please check the path.")
                st.stop()
            in_stem = in_path.stem

        out_base = out_dir / f"{in_stem}.pdf"

        if out_source == "fallback_after_unwritable":
            st.warning(
                f"default_output_dir ({cfg.settings.default_output_dir}) "
                "isn't writable; output landed in a temp folder instead."
            )
```

Behavior summary of the diff:
- `_chunk_copy` failure now goes through `_render_error` (was `st.error(f"...{e}")`).
- `out_base` carries the input stem so `run_pipeline`'s collision-safe naming produces e.g. `<stem>_processed_TIMESTAMP.pdf`.
- Old single shared `workdir` is split: `input_workdir` for uploaded bytes (only in upload mode), `out_dir` from the resolver for the produced file.

- [ ] **Step 2: Replace the pipeline-error path with `_render_error`**

Find:

```python
        try:
            with st.status(
                "Processing… (large PDFs may take a while)", expanded=True
            ) as status:
                st.write(f"Running pipeline (mode={pipeline_mode}, preset={preset})")
                result = run_pipeline(
                    in_path,
                    out_base,
                    mode=pipeline_mode,
                    lang=lang,
                    preset=preset,
                    pdfa=pdfa,
                    jobs=jobs,
                    force_ocr=force_ocr,
                )
                status.update(label="Processing complete ✅", state="complete")
        except Exception as e:
            st.error(f"Processing failed: {e}")
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass
            st.stop()
```

Replace with:

```python
        try:
            with st.status(
                "Processing… (large PDFs may take a while)", expanded=True
            ) as status:
                st.write(f"Running pipeline (mode={pipeline_mode}, preset={preset})")
                result = run_pipeline(
                    in_path,
                    out_base,
                    mode=pipeline_mode,
                    lang=lang,
                    preset=preset,
                    pdfa=pdfa,
                    jobs=jobs,
                    force_ocr=force_ocr,
                )
                status.update(label="Processing complete ✅", state="complete")
        except Exception as e:
            _render_error(e)
            st.stop()
```

(The `shutil.rmtree(workdir, ...)` cleanup is removed — `workdir` no longer exists as a single variable, and tempdir cleanup on failure is best-effort anyway.)

- [ ] **Step 3: Add the "Saved to:" line to the success banner**

Find this block:

```python
            st.success(
                f"Done in {result.processing_seconds:.1f}s • "
                f"{_human(result.input_bytes)} → {_human(result.output_bytes)} "
                f"({delta_label}) • {op_label} • preset: "
                f"{result.preset_actually_used}"
            )
```

Add immediately after it:

```python
            if out_source in ("override", "setting"):
                st.caption(f"📂 Saved to: `{result.output_path}`")
```

- [ ] **Step 4: Update the `dl_name` to reuse `in_stem`**

Find:

```python
            # Suggested download name
            stem = (
                Path(local_path_str).stem
                if source_mode.startswith("Use local")
                else Path(uploaded.name).stem
            )
            suffix = "_ocr" if mode == "OCR only" else "_processed"
            dl_name = f"{stem}{suffix}.pdf"
```

Replace with:

```python
            suffix = "_ocr" if mode == "OCR only" else "_processed"
            dl_name = f"{in_stem}{suffix}.pdf"
```

(`in_stem` is now in scope from Step 1.)

- [ ] **Step 5: Verify the import smoke test passes**

Run: `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"`

Expected: `GUI ok` with no errors.

- [ ] **Step 6: Verify all existing tests still pass**

Run: `uv run pytest -v`

Expected: every prior test still green; the GUI helper tests are still 11 passed.

- [ ] **Step 7: Lint + format**

Run: `uv run ruff check src/` and `uv run black --check src/`.

- [ ] **Step 8: Commit**

```bash
git add src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 5 task 5: single-file flow honors default_output_dir + friendly errors"
```

---

## Task 6: Batch section — Source radio + local-folder mode

**Files:**
- Modify: `src/pdf_ocr_compress/gui/basic.py` (the batch section near the bottom of `main()`)

Add a `Source` radio mirroring the single-file pattern. Two branches:
- **Upload mode** (existing behavior, plus `_resolve_output_dir` for the output dir and `_render_error` for the orchestrator-level error path).
- **Local folder mode** (new). Two text inputs (input folder required, output folder optional). Pre-flight summary via `_collect_local_folder_inputs`. Calls `run_batch(input_folder, output_folder, ...)` directly. When output goes through `default_output_dir`, nest in a `batch_YYYYMMDD-HHMMSS/` subfolder.

- [ ] **Step 1: Add a small helper for the timestamped subfolder**

Insert near the other helpers in `gui/basic.py`:

```python
from datetime import datetime


def _timestamped_batch_subdir(base: Path) -> Path:
    """Wrap `base` in a `batch_YYYYMMDD-HHMMSS/` subfolder.

    Used in batch mode when the output dir comes from
    cfg.settings.default_output_dir to prevent batch_report.json
    collisions across consecutive runs.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sub = base / f"batch_{stamp}"
    sub.mkdir(parents=True, exist_ok=True)
    return sub
```

If `from datetime import datetime` already exists at the top, don't duplicate it.

- [ ] **Step 2: Replace the batch section's input UI**

Find the existing block:

```python
    # --- Batch upload section ---
    st.divider()
    st.subheader("📦 Batch: process multiple PDFs at once")
    st.caption(
        "Drop several PDFs; each is processed with the same settings. A "
        "batch_report.json summarizing every file is downloadable when done."
    )

    batch_uploads = st.file_uploader(
        "Drop multiple PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key="batch_uploader",
    )

    batch_btn = st.button(
        "Process batch",
        type="primary",
        disabled=not batch_uploads,
        key="batch_run",
    )
```

Replace with:

```python
    # --- Batch section ---
    st.divider()
    st.subheader("📦 Batch: process multiple PDFs at once")
    st.caption(
        "Process several PDFs with the same settings. A batch_report.json "
        "summarizing every file is written next to the outputs."
    )

    batch_source = st.radio(
        "Source",
        ["Upload multiple PDFs in browser", "Use local folder path (no size limit)"],
        key="batch_source",
        help=(
            "Upload mode reads files through the browser (subject to "
            "Streamlit's upload limit). Local folder mode points at a "
            "directory on disk — required for multi-GB inputs."
        ),
    )

    batch_uploads = None
    batch_input_folder_str = ""
    batch_output_folder_str = ""
    folder_info = None

    if batch_source == "Upload multiple PDFs in browser":
        batch_uploads = st.file_uploader(
            "Drop multiple PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            key="batch_uploader",
        )
        batch_btn_disabled = not batch_uploads
    else:
        batch_input_folder_str = st.text_input(
            "Input folder (contains PDFs to process)",
            placeholder=r"e.g. G:\My Drive\Book Scans\Inbox",
            key="batch_in_folder",
        )
        batch_output_folder_str = st.text_input(
            "Output folder (blank = use default_output_dir, else <input>/processed/)",
            placeholder="leave blank to follow your settings",
            key="batch_out_folder",
        )
        folder_info = _collect_local_folder_inputs(batch_input_folder_str)
        if folder_info["msg"]:
            (st.info if folder_info["valid"] else st.warning)(folder_info["msg"])
        batch_btn_disabled = not folder_info["valid"]

    batch_btn = st.button(
        "Process batch",
        type="primary",
        disabled=batch_btn_disabled,
        key="batch_run",
    )
```

- [ ] **Step 3: Replace the batch-execution block**

Find the existing block beginning `if batch_btn and batch_uploads:` (it's the next block after the button) and ending at the report download. Replace the whole block with:

```python
    if batch_btn:
        pipeline_mode = {
            "OCR only": "ocr",
            "Compress only": "compress",
        }.get(mode, "auto")

        # Resolve input dir + output dir based on mode. run_batch's
        # internal `output_dir.mkdir(parents=True, exist_ok=True)` (see
        # core/batch.py:172) handles directory creation for the factory-
        # returned paths, so we only call _timestamped_batch_subdir when
        # the resolver returned the user's `default_output_dir` directly
        # (out_source == "setting").
        if batch_source == "Upload multiple PDFs in browser":
            batch_workdir = Path(tempfile.mkdtemp(prefix="pdfgui_batch_"))
            batch_in = batch_workdir / "input"
            batch_in.mkdir()
            for uf in batch_uploads:
                _chunk_copy(uf, batch_in / uf.name)

            out_dir, out_source = _resolve_output_dir(
                cfg,
                override=None,
                fallback_factory=lambda: batch_workdir / "output",
            )
            if out_source == "setting":
                out_dir = _timestamped_batch_subdir(out_dir)
            batch_out = out_dir
        else:
            batch_in = Path(batch_input_folder_str).expanduser()
            user_typed_out = batch_output_folder_str.strip()
            override = Path(user_typed_out).expanduser() if user_typed_out else None
            out_dir, out_source = _resolve_output_dir(
                cfg,
                override=override,
                fallback_factory=lambda: batch_in / "processed",
            )
            if out_source == "setting":
                out_dir = _timestamped_batch_subdir(out_dir)
            batch_out = out_dir

        if out_source == "fallback_after_unwritable":
            st.warning(
                f"default_output_dir ({cfg.settings.default_output_dir}) "
                "isn't writable; outputs landed in the fallback location instead."
            )

        progress_bar = st.progress(0.0, text="Starting batch…")
        live_table = st.empty()
        rows: list[dict] = []

        def _cb(current: int, total: int, current_path: Path) -> None:
            progress_bar.progress(
                min(current / max(total, 1), 1.0),
                text=f"{current}/{total} — {current_path.name}",
            )
            rows.append(
                {"file": current_path.name, "status": "processing", "delta": "—"}
            )
            live_table.dataframe(rows, hide_index=True)

        try:
            with st.status("Running batch…", expanded=True) as status:
                report = run_batch(
                    batch_in,
                    batch_out,
                    mode=pipeline_mode,
                    preset=preset,
                    lang=lang,
                    jobs=jobs,
                    pdfa=pdfa,
                    force_ocr=force_ocr,
                    progress_callback=_cb,
                )
                progress_bar.progress(1.0, text="Done")
                status.update(label="Batch complete ✅", state="complete")
        except Exception as e:
            _render_error(e)
            st.stop()

        # Final results table
        final_rows = []
        for r in report.results:
            if r.status == "ok" and r.process_result is not None:
                pct = r.process_result.pct_change
                sign = "-" if pct < 0 else "+"
                final_rows.append(
                    {
                        "file": r.input_path.name,
                        "status": "ok",
                        "delta": f"{sign}{abs(pct):.1f}%",
                        "attempts": r.attempts,
                        "error": "",
                    }
                )
            else:
                final_rows.append(
                    {
                        "file": r.input_path.name,
                        "status": "FAILED",
                        "delta": "—",
                        "attempts": r.attempts,
                        "error": r.error_msg or "",
                    }
                )
        live_table.dataframe(final_rows, hide_index=True)

        st.success(report.one_line_summary())
        if out_source in ("override", "setting", "fallback") and batch_source.startswith("Use local"):
            st.caption(f"📂 Outputs in: `{batch_out}`")

        # Per-file download buttons (upload mode only — outputs already on
        # disk where the user pointed in folder mode).
        if batch_source == "Upload multiple PDFs in browser":
            for r in report.results:
                if (
                    r.status == "ok"
                    and r.output_path is not None
                    and r.output_path.exists()
                ):
                    with open(r.output_path, "rb") as f:
                        st.download_button(
                            f"⬇️ Download {r.input_path.name}",
                            data=f.read(),
                            file_name=r.output_path.name,
                            mime="application/pdf",
                            key=f"dl_{r.input_path.name}",
                        )

        # Batch report download (every mode)
        report_path = batch_out / "batch_report.json"
        if report_path.exists():
            with open(report_path, "rb") as f:
                st.download_button(
                    "⬇️ Download batch_report.json",
                    data=f.read(),
                    file_name="batch_report.json",
                    mime="application/json",
                    key="dl_batch_report",
                )
```

- [ ] **Step 4: Verify imports + module loads**

Run: `uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"`

Expected: `GUI ok` with no errors.

- [ ] **Step 5: Verify all tests still pass**

Run: `uv run pytest -v`

Expected: every prior test still green.

- [ ] **Step 6: Lint + format**

Run: `uv run ruff check src/` and `uv run black --check src/`.

- [ ] **Step 7: Commit**

```bash
git add src/pdf_ocr_compress/gui/basic.py
git commit -m "Phase 5 task 6: batch local-folder mode + Source radio + nested batch subdir"
```

---

## Task 7: Browser smoke test + Phase 5 closure

**Files:**
- Create: `tests/gui_smoke.md` (manual checklist; filled in during the run)
- Modify: `CLAUDE.md` (Known issues + Where I left off + Phase 5 closure note)
- Modify: `ROADMAP.md` (check Phase 5 box)

This is the deliverable that closes the long-standing "GUI not click-through tested" gap.

- [ ] **Step 1: Create the smoke-test checklist file**

Write `tests/gui_smoke.md`:

```markdown
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
```

- [ ] **Step 2: Run the smoke test**

Boot the GUI:

```bash
uv run pdf-ocr-gui
```

Walk every checkbox in `tests/gui_smoke.md`. Tick boxes inline as you go (edit the file with the Edit tool). When something doesn't work, fix it (cosmetic adjustments are explicitly allowed per the spec's locked-in choice #9), commit the fix as a separate `Phase 5 task 7 fix: …` commit, and re-run the affected step.

If something ships as a real defect (not a cosmetic fix), record what was wrong in the checklist line as `[x] (was: <what was wrong, fixed in commit <sha>>)`.

- [ ] **Step 3: Update CLAUDE.md "Known issues"**

Open `CLAUDE.md`. In the "Known issues / tech debt" section, find:

```markdown
- **GUI not click-through tested in a browser.** Phase 5. The 4d
  refactor swapped the routing block but no manual smoke test was
  performed.
- **CLI/GUI/API hardcode their own defaults.** They don't yet read
  from `config.get_config()` for things like preset/jobs/lang
  defaults — `run_pipeline` does, but the surface-level Typer/
  Streamlit/Form defaults are still hardcoded. Phase 5 wires them in
  (settings UI, default output dir, oversize-policy surface).
- **Phase 4 API hardening + Phase 5 GUI catchup + Phase 6 docs
  polish** all ahead. ROADMAP has the scope.
```

Replace those three bullets with:

```markdown
- **CLI hardcodes its own defaults.** The CLI's `ocr` / `compress` /
  `process` commands and the API's single-file upload form still
  hardcode preset/jobs/lang. The GUI was wired in Phase 5; the CLI
  and the legacy API single-file form are the remaining items. Small
  follow-up; not gating Phase 6.
- **Phase 6 docs polish** is the only remaining roadmap phase.
  ROADMAP has the scope.
```

- [ ] **Step 4: Update CLAUDE.md "Where I left off"**

Find the `## Where I left off` section. Replace its contents with:

```markdown
**Phase 5 closed (2026-04-29).** GUI is now in line with everything
Phase 1–4 added: defaults flow from `get_config().settings` (sidebar
"⚙️ Defaults" expander persists the new `AppSettings`), `oversize_policy`
is editable, the batch section accepts a server-side folder path
(matches the Google-Drive-mounted ScanSnap workflow — multi-GB inputs
no longer require a browser upload), and every exception site routes
through `_render_error()` → `format_error_for_user`. Browser click-
through smoke test recorded in `tests/gui_smoke.md`. Pick up at
**Phase 6 (Documentation polish)** — see `ROADMAP.md`.

**Phase 5 deliverables:**

- `gui/basic.py` — three pure helpers (`_resolve_output_dir`,
  `_collect_local_folder_inputs`, `_timestamped_batch_subdir`) plus
  two Streamlit-side shims (`_render_defaults_panel`,
  `_render_error`). All renderer state goes through the existing
  `ConfigManager` / `format_error_for_user` surfaces — no new core
  capability, no new modules.
- Fixed: per-run `preset` selector now defaults to
  `cfg.settings.default_preset` (was hardcoded to `"balanced"`,
  contradicting design rule #4).
- `_resolve_output_dir(cfg, override, fallback_factory) -> (Path,
  source)` is the single resolver used by single-file, upload-batch,
  and folder-batch flows. Batch into `default_output_dir` nests in a
  timestamped `batch_YYYYMMDD-HHMMSS/` subfolder so consecutive
  batches don't clobber each other's `batch_report.json`.
- `tests/test_gui_helpers.py` — 11 tests covering both pure helpers.
- `tests/gui_smoke.md` — manual browser checklist, walked end-to-end.

**Honest gaps still open after Phase 5 (deferred to later phases):**

- Recursion into subfolders for batch input — `core/batch.py:148`
  (`_list_pdfs`) is non-recursive. Adding recursion is new core
  capability touching CLI + API + GUI; it stayed out of scope as
  "GUI catchup." Clean follow-up if a user's folder layout actually
  requires it.
- Per-run `oversize_policy` override (sidebar radio + plumbing
  through `run_pipeline` / `compress` / `run_ocr`). Locked-in choice
  #3 of the Phase 5 spec deferred this — the current setting-only
  surface covers the realistic use cases.
- CLI surface defaults (`pdf-ocr ocr|compress|process`) and the
  legacy API single-file upload form still hardcode preset/jobs/lang.
```

- [ ] **Step 5: Check Phase 5 in ROADMAP.md**

In `ROADMAP.md`, find the Status block and change:

```markdown
- [ ] **Phase 5 — GUI catchup**
```

to:

```markdown
- [x] **Phase 5 — GUI catchup** (2026-04-29)
```

- [ ] **Step 6: Verify everything still passes**

Run all three:

```bash
uv run pytest -v
uv run ruff check src/ tests/
uv run black --check src/ tests/
```

Expected: green across the board. The new GUI helper tests are 11 passed; the existing 118 tests are still 118 passed (so total 129 passing).

Also re-confirm the import smoke tests:

```bash
uv run pdf-ocr --help
uv run python -c "from pdf_ocr_compress.api.server import app; print('API ok')"
uv run python -c "from pdf_ocr_compress.gui import main_gui; print('GUI ok')"
```

- [ ] **Step 7: Commit Phase 5 closure**

```bash
git add tests/gui_smoke.md CLAUDE.md ROADMAP.md
git commit -m "Phase 5 closure: browser smoke test recorded; CLAUDE.md + ROADMAP updated"
```

---

## Self-review (run after writing the plan)

Run this checklist against the plan, fix any issues inline:

1. **Spec coverage:**
   - Sidebar Defaults expander → Task 4 ✓
   - Per-run defaults wiring (preset list reorder included) → Task 4 ✓
   - `oversize_policy` exposure (settings-only) → Task 4 ✓
   - Single-file output destination + input-stem filename → Task 5 ✓
   - Friendly error display via `format_error_for_user` → Task 3 (helper) + Tasks 4/5/6 (call sites) ✓
   - Local-folder batch mode → Task 6 ✓
   - Batch-into-default-dir timestamped subfolder → Task 6 ✓
   - `_resolve_output_dir` pure helper + tests → Task 1 ✓
   - `_collect_local_folder_inputs` pure helper + tests → Task 2 ✓
   - Browser smoke test + CLAUDE.md / ROADMAP updates → Task 7 ✓

2. **Placeholder scan:** No "TBD", no "TODO", no "implement appropriate error handling," no "similar to Task N." Every code block contains real code.

3. **Type/name consistency:**
   - Helper signature `_resolve_output_dir(cfg, override, fallback_factory) -> (Path, str)` is identical in spec, Task 1 implementation, Task 5 call site, and Task 6 call site.
   - `_collect_local_folder_inputs(folder_str)` returns the same dict shape across Task 2 implementation and Task 6 call site (`valid`, `msg`, `pdf_count`, `total_bytes`).
   - `_PRESET_CHOICES` / `_OVERSIZE_CHOICES` defined once in Task 4, referenced in Task 4 sidebar widgets only — internally consistent.
   - `out_source` strings are the same set everywhere: `"override"`, `"setting"`, `"fallback"`, `"fallback_after_unwritable"`.

4. **Build order:** Pure helpers → Streamlit shims → main() rewires (sidebar → single-file → batch) → smoke test. Each task leaves the GUI importable and the test suite green.
