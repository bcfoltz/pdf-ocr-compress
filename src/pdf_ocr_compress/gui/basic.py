"""Streamlit GUI for PDF OCR + Compression Tool."""

import io
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add src to path for imports
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

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


def setup_streamlit():
    """Configure Streamlit app settings."""
    st.set_page_config(
        page_title="PDF OCR + Compression", page_icon="🧰", layout="centered"
    )

    # Bump Streamlit limits for big uploads (has no effect on local-path mode).
    try:
        st.set_option("server.maxUploadSize", 4096)  # MB
        st.set_option("server.maxMessageSize", 4096)  # MB
    except Exception:
        pass


def _human(nbytes: int) -> str:
    """Convert bytes to human readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def _chunk_copy(
    src_file_like: io.BufferedReader, dst_path: Path, chunk_size: int = 16 * 1024 * 1024
):
    """Copy uploaded file to disk without loading it all into memory."""
    src_file_like.seek(0)
    with open(dst_path, "wb") as out_f:
        shutil.copyfileobj(src_file_like, out_f, length=chunk_size)


def _ensure_writable(path: Path) -> Path:
    """mkdir -p the path; raise OSError if it can't be created/written."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _collect_local_folder_inputs(folder_str: str) -> dict:
    """Pre-flight summary for the batch local-folder input field.

    Returns a dict with:
      - valid (bool):      True when the folder exists and contains >=1 PDF
      - msg (str):         the line to render via st.info / st.warning
      - pdf_count (int):   PDFs found (non-recursive; *.pdf in folder)
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


def _render_error(exc: Exception) -> None:
    """Render any exception via the user-friendly formatter.

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


_PRESET_CHOICES = ["smallest", "balanced", "archival"]
_OVERSIZE_CHOICES = ["fallback", "warn", "fail"]


def _render_defaults_panel(cfg) -> None:
    """Sidebar expander: edit and persist AppSettings.

    Per-run sidebar widgets below this expander pre-fill from the saved
    values. After 'Save defaults' click, settings.json is written and
    st.rerun() refreshes the page so per-run controls re-init.
    """
    s = cfg.settings
    with st.sidebar.expander("⚙️ Defaults (saved across sessions)", expanded=False):
        new_preset = st.selectbox(
            "Default preset",
            _PRESET_CHOICES,
            index=(
                _PRESET_CHOICES.index(s.default_preset)
                if s.default_preset in _PRESET_CHOICES
                else 0
            ),
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
        # Seed session_state from saved settings on first render so the
        # text_input + Browse button can both target the same key without
        # conflicting with a `value=` argument.
        if "def_output_dir" not in st.session_state:
            st.session_state["def_output_dir"] = (
                str(s.default_output_dir) if s.default_output_dir else ""
            )
        new_output_dir_str = st.text_input(
            "Default output directory (blank = unset)",
            placeholder="e.g. ~/Documents/scans/processed",
            key="def_output_dir",
        )
        st.button(
            "📁 Browse…",
            key="def_output_dir_browse",
            on_click=_on_browse_click,
            args=("def_output_dir", new_output_dir_str),
        )
        if browse_err := st.session_state.pop("_browse_err_def_output_dir", None):
            st.warning(browse_err)
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
            index=(
                _OVERSIZE_CHOICES.index(s.oversize_policy)
                if s.oversize_policy in _OVERSIZE_CHOICES
                else 0
            ),
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
            default_language=new_lang.strip(),
            default_jobs=int(new_jobs),
            default_output_dir=(
                Path(new_output_dir_str).expanduser()
                if new_output_dir_str.strip()
                else None
            ),
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


def _resolve_output_dir(
    cfg, override: Path | None, fallback_factory
) -> tuple[Path, str, OSError | None]:
    """Resolve where output files go, in priority order.

    Returns (path, source, detail) where source is one of:
      - "override":                   user-typed explicit path was used
      - "setting":                    cfg.settings.default_output_dir was used
      - "fallback":                   default_output_dir unset; factory used
      - "fallback_after_unwritable":  default_output_dir set but mkdir raised
    `detail` is the captured OSError on the unwritable branch (so the
    caller can surface str(exc) in the warning) and None otherwise.

    Caller decides whether to surface a "Saved to:" line, a one-shot
    warning about an unhonored setting, etc.
    """
    if override is not None:
        return _ensure_writable(override), "override", None

    setting = cfg.settings.default_output_dir
    if setting is not None:
        try:
            return _ensure_writable(Path(setting)), "setting", None
        except OSError as exc:
            return fallback_factory(), "fallback_after_unwritable", exc

    return fallback_factory(), "fallback", None


def _timestamped_batch_subdir(base: Path) -> Path:
    """Wrap `base` in a `batch_YYYYMMDD-HHMMSS-fff/` subfolder.

    Used in batch mode when the output dir comes from
    cfg.settings.default_output_dir to prevent batch_report.json
    collisions across consecutive runs. Microsecond resolution
    eliminates collisions when two batches start in the same second.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    sub = base / f"batch_{stamp}"
    sub.mkdir(parents=True, exist_ok=True)
    return sub


def _on_browse_click(target_key: str, initial_value: str) -> None:
    """`on_click` callback for the Browse buttons.

    Pops a native folder picker; if the user chooses a folder, writes
    it to `st.session_state[target_key]` (the linked text_input's key).
    Streamlit only allows writing to a widget-bound session_state key
    from inside a callback (or before the widget's first render in
    the current script run) — doing it after the `if st.button():`
    line raises StreamlitAPIException because the widget has already
    been instantiated.

    Any RuntimeError from `_pick_folder_dialog` (e.g. headless env)
    is parked in a sibling session_state slot so the post-rerun render
    path can surface a friendly warning without crashing the page.
    """
    try:
        chosen = _pick_folder_dialog(initialdir=initial_value or None)
        if chosen:
            st.session_state[target_key] = chosen
    except RuntimeError as exc:
        st.session_state[f"_browse_err_{target_key}"] = str(exc)


def _pick_folder_dialog(initialdir: str | None = None) -> str | None:
    """Pop a native OS folder picker and return the chosen path.

    Returns the chosen absolute path as a string, or None if the user
    cancelled. Raises RuntimeError if no GUI display is available
    (headless Linux), so callers can surface a friendly fallback.

    Streamlit itself can't open a native folder picker (browser sandbox
    blocks it), but this app is local-machine only — the Streamlit
    server runs on the same box as the user's browser, so a server-side
    Tk dialog opens in front of the user just fine.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        # Some minimal Linux installs ship the tkinter Python wrapper
        # without libtk's shared library, so the import itself fails.
        # Surface the same friendly fallback as the no-display case
        # below.
        raise RuntimeError(
            "Folder picker is unavailable in this environment "
            "(Tk libraries not installed). Type the path manually instead."
        ) from exc

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            "Folder picker requires a display (not available in headless "
            "environments). Type the path manually instead."
        ) from exc

    try:
        root.withdraw()
        # Force the dialog above the browser window — on Windows the Tk
        # dialog otherwise opens behind the active window roughly half
        # the time.
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            initialdir=initialdir or str(Path.home()),
            mustexist=True,
        )
    finally:
        root.destroy()

    return chosen or None


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
        st.write("""
        **✅ IDEAL for this tool:**
        - Scanned paper documents (receipts, forms, contracts)
        - Photos of documents taken with phone/camera
        - Image-based PDFs without searchable text
        - Old scanned files from legacy systems

        **❌ NOT needed for:**
        - PDFs exported from Word, Excel, PowerPoint
        - Web pages saved as PDF
        - Digital documents with selectable text

        **🔍 Not sure?** Use "Auto" mode - it detects if OCR is needed!
        """)

    # --- Sidebar options ---
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
            index=(
                _PRESET_CHOICES.index(s.default_preset)
                if s.default_preset in _PRESET_CHOICES
                else 0
            ),
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

    # --- File input widgets ---
    uploaded = None
    local_path_str = ""

    if source_mode == "Upload in browser":
        uploaded = st.file_uploader(
            "Choose a PDF (large files supported)", type=["pdf"]
        )
    else:
        local_path_str = st.text_input(
            "Absolute path to a PDF on this computer",
            placeholder=r"C:\path\to\your\huge.pdf",
        )

    # Process button logic
    btn_disabled = (
        (uploaded is None)
        if source_mode == "Upload in browser"
        else (not local_path_str.strip())
    )
    run_btn = st.button("Process", type="primary", disabled=btn_disabled)

    # --- Selected file info (size display) ---
    if source_mode == "Upload in browser" and uploaded:
        size = getattr(uploaded, "size", None)
        if size is None:
            try:
                pos = uploaded.tell()
                uploaded.seek(0, os.SEEK_END)
                size = uploaded.tell()
                uploaded.seek(pos, os.SEEK_SET)
            except Exception:
                size = 0
        st.info(f"Selected: **{uploaded.name}** • Size: {_human(size)}")

    if source_mode == "Use local file path (no size limit)" and local_path_str.strip():
        p = Path(local_path_str)
        if p.exists() and p.is_file():
            try:
                st.info(f"Selected: **{p.name}** • Size: {_human(p.stat().st_size)}")
            except Exception:
                st.info(f"Selected: **{p.name}**")
        else:
            st.warning("Path not found or not a file. Please check and try again.")

    # --- Main processing ---
    if run_btn:
        # Resolve where the produced file should land. _resolve_output_dir
        # honors cfg.settings.default_output_dir when set; otherwise a fresh
        # tempdir is created.
        out_dir, out_source, out_detail = _resolve_output_dir(
            cfg,
            override=None,
            fallback_factory=lambda: Path(tempfile.mkdtemp(prefix="pdfgui_")),
        )

        # Determine input path. Uploads still need a writable workdir to
        # land the input bytes; reuse a tempdir for that even when out_dir
        # is the user's default_output_dir.
        input_workdir = None
        if source_mode == "Upload in browser":
            input_workdir = Path(tempfile.mkdtemp(prefix="pdfgui_in_"))
            in_stem = Path(uploaded.name).stem
            in_path = input_workdir / "input.pdf"
            try:
                _chunk_copy(uploaded, in_path)
            except Exception as e:
                shutil.rmtree(input_workdir, ignore_errors=True)
                if out_source in ("fallback", "fallback_after_unwritable"):
                    shutil.rmtree(out_dir, ignore_errors=True)
                _render_error(e)
                st.stop()
        else:
            in_path = Path(local_path_str).expanduser()
            if not (in_path.exists() and in_path.is_file()):
                _render_error(FileNotFoundError(str(in_path)))
                st.stop()
            in_stem = in_path.stem

        out_base = out_dir / f"{in_stem}.pdf"

        if out_source == "fallback_after_unwritable":
            st.warning(
                f"default_output_dir ({cfg.settings.default_output_dir}) "
                f"isn't writable ({out_detail}); output landed in a temp "
                "folder instead."
            )

        # Analyze for OCR need (fast, first pages only)
        with st.status("Analyzing PDF…", expanded=False) as status:
            try:
                need_ocr = needs_ocr(in_path)
                status.update(
                    label=f"Analysis complete — OCR needed: {bool(force_ocr or need_ocr)}",
                    state="complete",
                )
            except Exception as e:
                need_ocr = True
                status.update(
                    label=f"Analysis failed, assuming OCR needed (ok): {e}",
                    state="complete",
                )

        # Map GUI mode buttons to run_pipeline modes.
        pipeline_mode = {
            "OCR only": "ocr",
            "Compress only": "compress",
        }.get(mode, "auto")

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
            if input_workdir is not None:
                shutil.rmtree(input_workdir, ignore_errors=True)
            if out_source in ("fallback", "fallback_after_unwritable"):
                shutil.rmtree(out_dir, ignore_errors=True)
            _render_error(e)
            st.stop()

        produced_path = result.output_path

        # Report & download
        try:
            delta_label = f"{abs(result.pct_change):.1f}% " + (
                "smaller" if result.pct_change < 0 else "larger"
            )
            op_label = (
                "OCR ran"
                if result.ocr_ran
                else f"OCR skipped ({result.ocr_skipped_reason})"
            )
            st.success(
                f"Done in {result.processing_seconds:.1f}s • "
                f"{_human(result.input_bytes)} → {_human(result.output_bytes)} "
                f"({delta_label}) • {op_label} • preset: "
                f"{result.preset_actually_used}"
            )
            if out_source in ("override", "setting"):
                st.caption(f"📂 Saved to: `{result.output_path}`")
            if not result.pdfminer_text_extractable:
                st.warning(
                    "pdfminer could not extract text from the output — RAG ingestion "
                    "may treat this PDF as image-only."
                )
            with st.expander("Full report"):
                st.json(result.to_dict())

            suffix = "_ocr" if mode == "OCR only" else "_processed"
            dl_name = f"{in_stem}{suffix}.pdf"

            with open(produced_path, "rb") as f:
                st.download_button(
                    "⬇️ Download processed PDF",
                    data=f.read(),
                    file_name=dl_name,
                    mime="application/pdf",
                )

            # Equivalent CLI (for reproducibility).
            # Use only the filename, not the full temp path — the temp dir
            # is an upload artifact that doesn't survive beyond this session
            # and contains local machine paths that would leak in screenshots.
            in_name = in_path.name
            out_name = out_base.name
            st.caption("Equivalent CLI you could run in a terminal:")
            if mode == "OCR only":
                st.code(
                    f'pdf-ocr ocr "{in_name}" "{out_name}" --lang {lang} --preset {preset}'
                    + (" --pdfa" if pdfa else "")
                    + (f" --jobs {jobs}" if jobs != 1 else "")
                    + (" --force-ocr" if force_ocr else ""),
                    language="bash",
                )
            elif mode == "Compress only":
                st.code(
                    f'pdf-ocr compress "{in_name}" "{out_name}" --preset {preset}',
                    language="bash",
                )
            else:
                st.code(
                    f'pdf-ocr process "{in_name}" "{out_name}" --lang {lang} --preset {preset}'
                    + (" --pdfa" if pdfa else "")
                    + (f" --jobs {jobs}" if jobs != 1 else "")
                    + (" --force-ocr" if force_ocr else ""),
                    language="bash",
                )
        finally:
            if input_workdir is not None:
                shutil.rmtree(input_workdir, ignore_errors=True)
            if out_source in ("fallback", "fallback_after_unwritable"):
                shutil.rmtree(out_dir, ignore_errors=True)

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
            placeholder="e.g. ~/Documents/scans/inbox",
            key="batch_in_folder",
        )
        st.button(
            "📁 Browse…",
            key="batch_in_browse",
            on_click=_on_browse_click,
            args=("batch_in_folder", batch_input_folder_str),
        )
        if browse_err := st.session_state.pop("_browse_err_batch_in_folder", None):
            st.warning(browse_err)
        batch_output_folder_str = st.text_input(
            "Output folder (optional)",
            placeholder="e.g. ~/Documents/scans/processed",
            help=(
                "Where processed PDFs go. Leave blank to use your saved "
                "default output directory (set in the sidebar Defaults "
                "expander). If you don't have one set either, outputs go "
                "into a `processed/` subfolder inside the input folder."
            ),
            key="batch_out_folder",
        )
        st.button(
            "📁 Browse…",
            key="batch_out_browse",
            on_click=_on_browse_click,
            args=(
                "batch_out_folder",
                batch_output_folder_str or batch_input_folder_str,
            ),
        )
        if browse_err := st.session_state.pop("_browse_err_batch_out_folder", None):
            st.warning(browse_err)
        try:
            folder_info = _collect_local_folder_inputs(batch_input_folder_str)
        except OSError as _e:
            folder_info = {
                "valid": False,
                "msg": f"Cannot read folder: {_e}",
                "pdf_count": 0,
                "total_bytes": 0,
            }
        if folder_info["msg"]:
            (st.info if folder_info["valid"] else st.warning)(folder_info["msg"])
        batch_btn_disabled = not folder_info["valid"]

    batch_btn = st.button(
        "Process batch",
        type="primary",
        disabled=batch_btn_disabled,
        key="batch_run",
    )

    if batch_btn:
        # Starting a fresh batch — drop any prior run's persisted results
        # so they don't show during the new run.
        st.session_state.pop("batch_results", None)

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
        batch_workdir = None
        if batch_source == "Upload multiple PDFs in browser":
            batch_workdir = Path(tempfile.mkdtemp(prefix="pdfgui_batch_"))
            batch_in = batch_workdir / "input"
            batch_in.mkdir()
            try:
                for uf in batch_uploads:
                    _chunk_copy(uf, batch_in / uf.name)
            except OSError as e:
                shutil.rmtree(batch_workdir, ignore_errors=True)
                _render_error(e)
                st.stop()

            out_dir, out_source, out_detail = _resolve_output_dir(
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
            out_dir, out_source, out_detail = _resolve_output_dir(
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
                f"isn't writable ({out_detail}); outputs landed in the "
                "fallback location instead."
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
            if batch_workdir is not None:
                shutil.rmtree(batch_workdir, ignore_errors=True)
            _render_error(e)
            st.stop()

        # Build the final results table (in-flight `live_table` gets
        # the rich version below).
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

        # Persist everything the results section needs so it survives
        # reruns triggered by the per-file download buttons. Streamlit
        # reruns the whole script on every widget interaction; without
        # this stash, clicking one download button would unmount the
        # rest of the result UI because `batch_btn` is False on rerun.
        st.session_state["batch_results"] = {
            "report_summary": report.one_line_summary(),
            "final_rows": final_rows,
            "batch_out": batch_out,
            "out_source": out_source,
            "batch_source": batch_source,
            "ok_outputs": [
                {
                    "input_name": r.input_path.name,
                    "output_path": r.output_path,
                    "output_name": r.output_path.name,
                }
                for r in report.results
                if r.status == "ok"
                and r.output_path is not None
                and r.output_path.exists()
            ],
            "report_json_path": batch_out / "batch_report.json",
        }

    # --- Persisted batch results section ---
    # Renders any time `st.session_state["batch_results"]` is populated.
    # Lives outside `if batch_btn:` so download-button reruns don't
    # tear it down.
    persisted = st.session_state.get("batch_results")
    if persisted:
        live_table = st.empty()
        live_table.dataframe(persisted["final_rows"], hide_index=True)

        st.success(persisted["report_summary"])
        if persisted["out_source"] in (
            "override",
            "setting",
            "fallback",
        ) and persisted["batch_source"].startswith("Use local"):
            st.caption(f"📂 Outputs in: `{persisted['batch_out']}`")

        # Per-file download buttons (upload mode only — outputs already on
        # disk where the user pointed in folder mode).
        if persisted["batch_source"] == "Upload multiple PDFs in browser":
            for i, item in enumerate(persisted["ok_outputs"]):
                output_path = item["output_path"]
                if output_path.exists():
                    with open(output_path, "rb") as f:
                        st.download_button(
                            f"⬇️ Download {item['input_name']}",
                            data=f.read(),
                            file_name=item["output_name"],
                            mime="application/pdf",
                            key=f"dl_{i}_{item['input_name']}",
                        )

        # Batch report download (every mode)
        report_path = persisted["report_json_path"]
        if report_path.exists():
            with open(report_path, "rb") as f:
                st.download_button(
                    "⬇️ Download batch_report.json",
                    data=f.read(),
                    file_name="batch_report.json",
                    mime="application/json",
                    key="dl_batch_report",
                )


if __name__ == "__main__":
    main()
