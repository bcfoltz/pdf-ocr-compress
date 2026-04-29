# compress.py — ALWAYS writes a brand-new file; never in-place
import shutil
import time
from pathlib import Path
from subprocess import CalledProcessError, run

import pikepdf


def _gs_exe() -> str:
    for name in ("gswin64c", "gswin32c", "gs"):
        exe = shutil.which(name)
        if exe:
            return exe
    return "gswin64c"


def _gs_args_for_preset(preset: str) -> list[str]:
    if preset == "archival":
        return [
            "-dPDFSETTINGS=/prepress",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
        ]
    if preset == "balanced":
        return [
            "-dPDFSETTINGS=/ebook",
            "-dDetectDuplicateImages=true",
            "-dColorImageDownsampleType=/Bicubic",
            "-dColorImageResolution=300",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dGrayImageResolution=300",
            "-dMonoImageDownsampleType=/Subsample",
            "-dMonoImageResolution=600",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
        ]
    if preset == "smallest":
        return [
            "-dPDFSETTINGS=/screen",
            "-dDetectDuplicateImages=true",
            "-dColorImageDownsampleType=/Bicubic",
            "-dColorImageResolution=150",
            "-dGrayImageDownsampleType=/Bicubic",
            "-dGrayImageResolution=150",
            "-dMonoImageDownsampleType=/Subsample",
            "-dMonoImageResolution=400",
            "-dCompressFonts=true",
            "-dSubsetFonts=true",
        ]
    raise ValueError("preset must be one of: archival, balanced, smallest")


def _unique_name(base: Path, suffix: str = "_processed") -> Path:
    """Return a non-existing path next to base with timestamp to avoid collisions."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    cand = base.with_name(f"{base.stem}{suffix}_{ts}.pdf")
    i = 0
    while cand.exists():
        i += 1
        cand = base.with_name(f"{base.stem}{suffix}_{ts}_{i}.pdf")
    return cand


def ghostscript_compress(
    input_pdf: Path, output_pdf: Path, preset: str = "balanced"
) -> Path:
    """
    Runs Ghostscript and writes to a NEW file path (never the input).
    Returns the path GS actually wrote.
    """
    # Ensure target is not the input and does not exist
    if output_pdf.resolve() == input_pdf.resolve() or output_pdf.exists():
        output_pdf = _unique_name(output_pdf)

    args = [
        _gs_exe(),
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        *_gs_args_for_preset(preset),
        f"-sOutputFile={output_pdf}",
        str(input_pdf),
    ]
    try:
        run(args, check=True)
    except CalledProcessError as e:
        raise RuntimeError(f"Ghostscript compression failed: {e}") from e
    return output_pdf


def linearize(src: Path, dst: Path) -> Path:
    """
    Linearizes by reading src and writing a BRAND-NEW dst (never same file).
    Returns dst.
    """
    if dst.exists() or dst.resolve() == src.resolve():
        dst = _unique_name(dst, suffix="_linearized")
    with pikepdf.open(src) as pdf:
        pdf.save(dst, linearize=True)
    return dst


def compress(input_pdf: Path, output_pdf: Path, preset: str = "balanced") -> Path:
    """
    Full compress pipeline that ALWAYS produces a fresh file and returns its path.
    No in-place writes; no overwrites. The user's requested output filename is
    honored (only altered if it collides with the input or an existing file).
    """
    # Resolve the final output path up front so the user's chosen name is honored.
    if output_pdf.resolve() == input_pdf.resolve() or output_pdf.exists():
        output_pdf = _unique_name(output_pdf)

    # 1) Ghostscript writes to a private intermediate so we can linearize into the final path.
    gs_tmp = output_pdf.with_name(output_pdf.stem + "__gs_tmp" + output_pdf.suffix)
    if gs_tmp.exists():
        gs_tmp = _unique_name(gs_tmp, suffix="__gs_tmp")
    gs_out = ghostscript_compress(input_pdf, gs_tmp, preset=preset)

    # 2) Linearize into the user's chosen final path.
    try:
        linearize(gs_out, output_pdf)
    finally:
        # 3) Cleanup the GS intermediate.
        try:
            if gs_out.exists():
                gs_out.unlink()
        except Exception:
            pass

    return output_pdf
