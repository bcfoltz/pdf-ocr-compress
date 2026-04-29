"""Oversize-policy guard: enforces Design rule #1 (output ≤ input, always).

Called at the end of compress() and run_ocr() so the invariant applies to
every pipeline branch — the auto `process` flow, direct `pdf-ocr ocr` /
`pdf-ocr compress` calls, and any API/GUI invocation.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from ..utils.errors import PDFProcessingError
from ..utils.logging_config import get_logger

logger = get_logger("oversize")


def enforce_oversize_policy(
    input_path: Path,
    output_path: Path,
    policy: str,
    *,
    can_retry: bool = False,
    retry_with_smallest: Callable[[], Path] | None = None,
) -> Path:
    """Apply oversize_policy to a pipeline output. Returns the final path.

    The caller passes the input it processed, the output the pipeline
    just produced, and the configured policy. If output ≤ input the
    helper is a no-op. Otherwise:

    - "fallback": delete the oversized output and call retry_with_smallest
      (if can_retry). If the retry result is still oversize, copy the
      input verbatim to output_path and return that.
    - "warn": log a warning and keep the oversized output.
    - "fail": delete the output and raise PDFProcessingError with
      error_code OUTPUT_GREW_NO_FALLBACK.

    can_retry should be False when the original call was already
    preset="smallest" (no smaller preset to fall back to). In that case
    fallback skips the retry and goes straight to the passthrough copy.
    """
    in_size = input_path.stat().st_size
    out_size = output_path.stat().st_size

    if out_size <= in_size:
        return output_path

    pct = 100.0 * (out_size - in_size) / max(in_size, 1)
    msg = (
        f"Output {out_size} B exceeds input {in_size} B by {pct:.1f}% "
        f"({input_path.name})"
    )

    if policy == "warn":
        logger.warning(f"{msg}; keeping output (oversize_policy=warn)")
        return output_path

    if policy == "fail":
        try:
            output_path.unlink()
        except OSError:
            pass
        raise PDFProcessingError(
            f"{msg}; oversize_policy=fail",
            f"The pipeline would produce a larger file than '{input_path.name}'.",
            [
                "Try preset 'smallest'",
                "Or set PDF_OCR_OVERSIZE_POLICY=fallback to passthrough oversize results",
            ],
            "OUTPUT_GREW_NO_FALLBACK",
        )

    if policy != "fallback":
        # Unknown policy — keep output rather than lose user data.
        logger.error(f"Unknown oversize_policy={policy!r}; keeping output")
        return output_path

    logger.info(f"{msg}; retrying with smallest preset (oversize_policy=fallback)")

    if can_retry and retry_with_smallest is not None:
        try:
            output_path.unlink()
        except OSError:
            pass
        retry_path = retry_with_smallest()
        if retry_path.stat().st_size <= in_size:
            logger.info(f"smallest preset succeeded ({retry_path.stat().st_size} B)")
            return retry_path
        logger.info("smallest also exceeded input; passing through input unchanged")
        try:
            retry_path.unlink()
        except OSError:
            pass

    shutil.copy2(input_path, output_path)
    logger.info(f"Wrote passthrough copy ({in_size} B) to {output_path.name}")
    return output_path
