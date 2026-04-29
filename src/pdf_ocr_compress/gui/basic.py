"""Streamlit GUI for PDF OCR + Compression Tool."""

import io
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Add src to path for imports
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

try:
    from .core.compress import compress as run_compress
    from .core.detect import needs_ocr
    from .core.ocr import run_ocr
except ImportError:
    from pdf_ocr_compress.core.compress import compress as run_compress
    from pdf_ocr_compress.core.detect import needs_ocr
    from pdf_ocr_compress.core.ocr import run_ocr


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


def main():
    """Main Streamlit application."""
    setup_streamlit()

    st.title("🧰 PDF OCR + Compression")
    st.caption(
        "Process SCANNED PDFs with OCRmyPDF + Ghostscript. "
        "Designed for scanned documents, not native digital PDFs. "
        "• Never overwrites originals • Always writes brand-new files • Handles very large PDFs."
    )

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
            ["balanced", "archival", "smallest"],
            index=0,
            help="archival = minimal change; balanced = high quality/smaller; smallest = most aggressive.",
        )
        lang = st.text_input(
            "OCR languages (Tesseract codes)",
            value="eng",
            help="Use + to combine, e.g. eng+spa",
        )
        pdfa = st.checkbox("Produce PDF/A-2", value=False)
        force_ocr = st.checkbox("Force OCR (even if text exists)", value=False)

        max_jobs = max(1, min(32, os.cpu_count() or 8))
        jobs = st.slider(
            "Parallel jobs",
            min_value=1,
            max_value=max_jobs,
            value=min(4, max_jobs),
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

        start = time.time()
        try:
            with st.status(
                "Processing… (large PDFs may take a while)", expanded=True
            ) as status:
                if mode == "OCR only":
                    st.write("Step 1/1: OCR")
                    produced_path = run_ocr(
                        input_pdf=in_path,
                        output_pdf=out_base,
                        lang=lang,
                        preset=preset,
                        pdfa=pdfa,
                        jobs=jobs,
                        force_ocr=force_ocr,
                    )
                elif mode == "Compress only":
                    st.write("Step 1/1: Compress")
                    produced_path = run_compress(in_path, out_base, preset=preset)
                else:
                    # Auto
                    if force_ocr or need_ocr:
                        st.write("Step 1/2: OCR (no text detected or forced)")
                        ocr_out = run_ocr(
                            input_pdf=in_path,
                            output_pdf=workdir / "ocr.pdf",
                            lang=lang,
                            preset=preset,
                            pdfa=pdfa,
                            jobs=jobs,
                            force_ocr=True,
                        )
                        st.write("Step 2/2: Compress")
                        produced_path = run_compress(ocr_out, out_base, preset=preset)
                    else:
                        st.write("Step 1/1: Compress (text already present)")
                        produced_path = run_compress(in_path, out_base, preset=preset)

                status.update(label="Processing complete ✅", state="complete")
        except Exception as e:
            st.error(f"Processing failed: {e}")
            try:
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass
            st.stop()

        # Report & download
        try:
            in_size = in_path.stat().st_size if in_path.exists() else 0
            out_size = produced_path.stat().st_size
            elapsed = time.time() - start
            st.success(
                f"Done in {elapsed:.1f}s • Original: {_human(in_size)} → Output: {_human(out_size)} "
                f"({(100.0 * (1 - out_size / max(in_size, 1))):.1f}% smaller)"
            )

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


if __name__ == "__main__":
    main()
