"""Structured logging configuration for PDF OCR + Compression Tool."""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class PerformanceLogger:
    """Performance logging utilities."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def log_processing_start(self, file_path: Path, operation: str, **kwargs):
        """Log start of processing operation."""
        self.logger.info(
            f"Starting {operation}",
            extra={
                "extra_data": {
                    "event_type": "processing_start",
                    "operation": operation,
                    "file_path": str(file_path),
                    "file_size": (
                        file_path.stat().st_size if file_path.exists() else None
                    ),
                    **kwargs,
                }
            },
        )

    def log_processing_complete(
        self,
        file_path: Path,
        operation: str,
        duration: float,
        output_path: Path = None,
        **kwargs,
    ):
        """Log completion of processing operation."""
        extra_data = {
            "event_type": "processing_complete",
            "operation": operation,
            "file_path": str(file_path),
            "duration_seconds": duration,
            **kwargs,
        }

        if output_path and output_path.exists():
            extra_data.update(
                {
                    "output_path": str(output_path),
                    "output_size": output_path.stat().st_size,
                    "compression_ratio": (
                        file_path.stat().st_size / output_path.stat().st_size
                        if file_path.exists()
                        else None
                    ),
                }
            )

        self.logger.info(
            f"Completed {operation} in {duration:.1f}s",
            extra={"extra_data": extra_data},
        )

    def log_processing_error(
        self, file_path: Path, operation: str, error: str, **kwargs
    ):
        """Log processing error."""
        self.logger.error(
            f"Failed {operation}: {error}",
            extra={
                "extra_data": {
                    "event_type": "processing_error",
                    "operation": operation,
                    "file_path": str(file_path),
                    "error": error,
                    **kwargs,
                }
            },
        )


def setup_logging(
    log_level: str = "INFO", log_file: Path = None, structured_logging: bool = True
) -> logging.Logger:
    """
    Set up structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARN, ERROR)
        log_file: Optional file path for logging
        structured_logging: Whether to use JSON formatting

    Returns:
        Configured logger instance
    """
    # Configure root logger
    root_logger = logging.getLogger("pdf_ocr_compress")
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)

    if structured_logging:
        console_handler.setFormatter(JSONFormatter())
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            JSONFormatter()
            if structured_logging
            else logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module."""
    return logging.getLogger(f"pdf_ocr_compress.{name}")


def get_performance_logger(name: str = "performance") -> PerformanceLogger:
    """Get a performance logger instance."""
    logger = get_logger(name)
    return PerformanceLogger(logger)


# Convenience function for user action logging
def log_user_action(action: str, **kwargs):
    """Log user actions for audit trail."""
    logger = get_logger("user_actions")
    logger.info(
        f"User action: {action}",
        extra={"extra_data": {"event_type": "user_action", "action": action, **kwargs}},
    )
