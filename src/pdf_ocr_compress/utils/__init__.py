"""Utility functions for file handling and common operations."""

from .logging_config import (
    setup_logging,
    get_logger,
    get_performance_logger,
    log_user_action,
)
from .errors import (
    PDFProcessingError,
    SystemToolError,
    PDFFormatError,
    InsufficientResourcesError,
    FileAccessError,
    format_error_for_user,
    create_error_report,
)
from .file_utils import (
    unique_output_path,
    human_readable_size,
    safe_file_operation,
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
