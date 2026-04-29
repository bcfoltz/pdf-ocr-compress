"""Utility functions for file handling and common operations."""

from .errors import (
    FileAccessError,
    InsufficientResourcesError,
    PDFFormatError,
    PDFProcessingError,
    SystemToolError,
    create_error_report,
    format_error_for_user,
)
from .file_utils import (
    human_readable_size,
    safe_file_operation,
    unique_output_path,
)
from .logging_config import (
    get_logger,
    get_performance_logger,
    log_user_action,
    setup_logging,
)

__all__ = [
    "setup_logging",
    "get_logger",
    "get_performance_logger",
    "log_user_action",
    "PDFProcessingError",
    "SystemToolError",
    "PDFFormatError",
    "InsufficientResourcesError",
    "FileAccessError",
    "format_error_for_user",
    "create_error_report",
    "unique_output_path",
    "human_readable_size",
    "safe_file_operation",
]
