"""Utility functions for file handling and operations."""

from datetime import datetime
from pathlib import Path


def unique_output_path(base_path: str | Path, suffix: str = "_processed") -> Path:
    """Return a non-existing sibling of base_path stamped with the current time.

    Microsecond-resolution timestamp (`%Y%m%d-%H%M%S-%f`) keeps rapid back-to-back
    calls collision-free; an integer counter handles the impossible-but-cheap
    same-microsecond case. Preserves the original file extension.
    """
    base_path = Path(base_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = base_path.with_name(
        f"{base_path.stem}{suffix}_{timestamp}{base_path.suffix}"
    )

    counter = 0
    while candidate.exists():
        counter += 1
        candidate = base_path.with_name(
            f"{base_path.stem}{suffix}_{timestamp}_{counter}{base_path.suffix}"
        )

    return candidate


def human_readable_size(nbytes: int) -> str:
    """Convert a byte count to a human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"
