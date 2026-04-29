"""Streamlit GUI for PDF OCR + Compression Tool."""

import io
import os
import shutil
import sys
import tempfile
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
            default_language=new_lang,
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
            st.error(f"Processing failed: {e}")
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass
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
            if not result.pdfminer_text_extractable:
                st.warning(
                    "pdfminer could not extract text from the output — RAG ingestion "
                    "may treat this PDF as image-only."
                )
            with st.expander("Full report"):
                st.json(result.to_dict())

            # Suggested download name
            stem = (
                Path(local_path_str).stem
                if source_mode.startswith("Use local")
                else Path(uploaded.name).stem
            )
            suffix = "_ocr" if mode == "OCR only" else "_processed"
            dl_name = f"{stem}{suffix}.pdf"

            with open(produced_path, "rb") as f:
                st.download_button(
                    "⬇️ Download processed PDF",
                    data=f.read(),
                    file_name=dl_name,
                    mime="application/pdf",
                )

            # Equivalent CLI (for reproducibility)
            st.caption("Equivalent CLI you could run in a terminal:")
            if mode == "OCR only":
                st.code(
                    f'pdf-ocr ocr "{in_path}" "{out_base}" --lang {lang} --preset {preset}'
                    + (" --pdfa" if pdfa else "")
                    + (f" --jobs {jobs}" if jobs != 1 else "")
                    + (" --force-ocr" if force_ocr else ""),
                    language="bash",
                )
            elif mode == "Compress only":
                st.code(
                    f'pdf-ocr compress "{in_path}" "{out_base}" --preset {preset}',
                    language="bash",
                )
            else:
                st.code(
                    f'pdf-ocr process "{in_path}" "{out_base}" --lang {lang} --preset {preset}'
                    + (" --pdfa" if pdfa else "")
                    + (f" --jobs {jobs}" if jobs != 1 else "")
                    + (" --force-ocr" if force_ocr else ""),
                    language="bash",
                )
        finally:
            # Temp dir stays for the session; manual cleanup is fine for very large outputs.
            pass

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

    if batch_btn and batch_uploads:
        batch_workdir = Path(tempfile.mkdtemp(prefix="pdfgui_batch_"))
        batch_in = batch_workdir / "input"
        batch_out = batch_workdir / "output"
        batch_in.mkdir()

        # Persist uploads to disk (chunked).
        for uf in batch_uploads:
            _chunk_copy(uf, batch_in / uf.name)

        pipeline_mode = {
            "OCR only": "ocr",
            "Compress only": "compress",
        }.get(mode, "auto")

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
            st.error(f"Batch failed at the orchestrator level: {e}")
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

        # Per-file download buttons (successful files only)
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

        # Batch report download
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


if __name__ == "__main__":
    main()
