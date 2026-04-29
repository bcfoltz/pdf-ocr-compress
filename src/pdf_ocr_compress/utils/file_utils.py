"""Utility functions for file handling and operations."""

import time
from pathlib import Path
from typing import Union


def unique_output_path(base_path: Union[str, Path], suffix: str = "_processed") -> Path:
    """
    Generate a unique output path to prevent overwrites.

    Args:
        base_path: Base file path
        suffix: Suffix to add before timestamp

    Returns:
        Unique path that doesn't exist
    """
    base_path = Path(base_path)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
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
    """
    Convert bytes to human readable format.

    Args:
        nbytes: Number of bytes

    Returns:
        Human readable size string
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def safe_file_operation(func):
    """
    Decorator to safely handle file operations with proper error handling.

    Args:
        func: Function to wrap

    Returns:
        Wrapped function with error handling
    """

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            raise RuntimeError(f"File not found: {e}")
        except PermissionError as e:
            raise RuntimeError(f"Permission denied: {e}")
        except OSError as e:
            raise RuntimeError(f"File operation failed: {e}")

    return wrapper
