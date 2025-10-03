"""Utility functions for file handling and common operations."""

from .logging_config import (
    setup_logging,
    get_logger,
    get_performance_logger,
    log_user_action
)
from .errors import (
    PDFProcessingError,
    SystemToolError,
    PDFFormatError,
    InsufficientResourcesError,
    FileAccessError,
    format_error_for_user,
    create_error_report
)
from .temp_manager import (
    SecureTempManager,
    get_temp_manager,
    create_temp_file,
    create_temp_dir,
    temp_file,
    temp_dir
)
from .system_check import (
    SystemChecker,
    get_system_checker,
    check_system_ready,
    validate_processing_environment
)
from .file_utils import (
    unique_output_path,
    human_readable_size,
    safe_file_operation
)

# Import config functions for convenience
try:
    from ..config import get_config
except ImportError:
    # Fallback if config not available
    get_config = None

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
    "SecureTempManager",
    "get_temp_manager",
    "create_temp_file",
    "create_temp_dir",
    "temp_file",
    "temp_dir",
    "SystemChecker",
    "get_system_checker",
    "check_system_ready",
    "validate_processing_environment",
    "unique_output_path",
    "human_readable_size",
    "safe_file_operation",
    "get_config"
]