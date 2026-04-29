# compress.py — ALWAYS writes a brand-new file; never in-place
import shutil
from pathlib import Path
from subprocess import CalledProcessError, run

import pikepdf

from ..config import get_config
from ..utils.errors import SystemToolError
from ..utils.file_utils import unique_output_path
from .oversize import enforce_oversize_policy


def _gs_exe() -> str:
    for name in ("gswin64c", "gswin32c", "gs"):
        exe = shutil.which(name)
        if exe:
            return exe
    raise SystemToolError(
        "ghostscript",
        "Ghostscript not found in PATH (looked for gswin64c, gswin32c, gs)",
    )


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


def ghostscript_compress(
    input_pdf: Path, output_pdf: Path, preset: str = "balanced"
) -> Path:
    """
    Runs Ghostscript and writes to a NEW file path (never the input).
    Returns the path GS actually wrote.
    """
    # Ensure target is not the input and does not exist
    if output_pdf.resolve() == input_pdf.resolve() or output_pdf.exists():
        output_pdf = unique_output_path(output_pdf)

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
        dst = unique_output_path(dst, suffix="_linearized")
    with pikepdf.open(src) as pdf:
        pdf.save(dst, linearize=True)
    return dst


def compress(
    input_pdf: Path,
    output_pdf: Path,
    preset: str = "balanced",
    *,
    _enforce_oversize: bool = True,
    _result: dict | None = None,
) -> Path:
    """
    Full compress pipeline that ALWAYS produces a fresh file and returns its path.
    No in-place writes; no overwrites. The user's requested output filename is
    honored (only altered if it collides with the input or an existing file).

    `_enforce_oversize` is private: when True (default), the configured
    oversize_policy is applied at the end (Design rule #1, output ≤ input).
    The policy's "fallback retry" recurses with _enforce_oversize=False to
    avoid an infinite loop.

    `_result` is an optional OUT-parameter dict; when supplied the function
    populates _result["preset_used"] with the preset whose output we
    actually shipped — "passthrough" if the input was copied verbatim,
    "smallest" if the fallback retry succeeded, otherwise the requested
    preset.
    """
    # Resolve the final output path up front so the user's chosen name is honored.
    if output_pdf.resolve() == input_pdf.resolve() or output_pdf.exists():
        output_pdf = unique_output_path(output_pdf)

    # 1) Ghostscript writes to a private intermediate so we can linearize into the final path.
    gs_tmp = output_pdf.with_name(output_pdf.stem + "__gs_tmp" + output_pdf.suffix)
    if gs_tmp.exists():
        gs_tmp = unique_output_path(gs_tmp, suffix="__gs_tmp")
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

    if not _enforce_oversize:
        if _result is not None:
            _result["preset_used"] = preset
        return output_pdf

    # 4) Oversize-policy guard: per Design rule #1, output ≤ input. If the
    # configured policy is "fallback" and the chosen preset grew the file,
    # retry with "smallest"; if that also grows it, copy input verbatim.
    policy = get_config().settings.oversize_policy

    def _retry_smallest() -> Path:
        return compress(
            input_pdf, output_pdf, preset="smallest", _enforce_oversize=False
        )

    outcome: dict[str, str] = {}
    final_path = enforce_oversize_policy(
        input_pdf,
        output_pdf,
        policy,
        can_retry=(preset != "smallest"),
        retry_with_smallest=_retry_smallest,
        outcome=outcome,
    )

    if _result is not None:
        _result["preset_used"] = _resolve_preset_used(preset, outcome.get("status"))
    return final_path


def _resolve_preset_used(requested: str, status: str | None) -> str:
    """Map enforce_oversize_policy outcome to a preset_used label.

    - "no_violation"/"warned" -> the requested preset shipped as-is
    - "retry_succeeded"       -> the smallest fallback shipped
    - "passthrough"           -> input was copied verbatim
    """
    if status == "passthrough":
        return "passthrough"
    if status == "retry_succeeded":
        return "smallest"
    return requested
