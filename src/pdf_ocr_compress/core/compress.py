# compress.py — ALWAYS writes a brand-new file; never in-place
from pathlib import Path
from subprocess import run, CalledProcessError
import tempfile, time, shutil
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
            "-dColorImageDownsampleType=/Bicubic","-dColorImageResolution=300",
            "-dGrayImageDownsampleType=/Bicubic","-dGrayImageResolution=300",
            "-dMonoImageDownsampleType=/Subsample","-dMonoImageResolution=600",
            "-dCompressFonts=true","-dSubsetFonts=true",
        ]
    if preset == "smallest":
        return [
            "-dPDFSETTINGS=/screen",
            "-dDetectDuplicateImages=true",
            "-dColorImageDownsampleType=/Bicubic","-dColorImageResolution=150",
            "-dGrayImageDownsampleType=/Bicubic","-dGrayImageResolution=150",
            "-dMonoImageDownsampleType=/Subsample","-dMonoImageResolution=400",
            "-dCompressFonts=true","-dSubsetFonts=true",
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

def ghostscript_compress(input_pdf: Path, output_pdf: Path, preset: str = "balanced") -> Path:
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
        "-dNOPAUSE", "-dQUIET", "-dBATCH",
        *_gs_args_for_preset(preset),
        f"-sOutputFile={output_pdf}",
        str(input_pdf),
    ]
    try:
        run(args, check=True)
    except CalledProcessError as e:
        raise RuntimeError(f"Ghostscript compression failed: {e}")
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
    No in-place writes; no overwrites.
    """
    # 1) Ghostscript to a fresh path (not the input)
    gs_out = ghostscript_compress(input_pdf, output_pdf, preset=preset)

    # 2) Linearize into a fresh final file
    final_out = output_pdf.with_name(output_pdf.stem + "_processed.pdf")
    final_out = linearize(gs_out, final_out)

    # 3) Cleanup the GS intermediate
    try:
        if gs_out.exists() and gs_out != final_out:
            gs_out.unlink()
    except Exception:
        pass

    return final_out
