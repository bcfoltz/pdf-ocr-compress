"""Enhanced error handling and user-friendly error messages."""

import sys
from pathlib import Path


class PDFProcessingError(Exception):
    """Base exception for PDF processing errors."""

    def __init__(
        self,
        message: str,
        user_message: str = None,
        suggestions: list = None,
        error_code: str = None,
    ):
        super().__init__(message)
        self.user_message = user_message or message
        self.suggestions = suggestions or []
        self.error_code = error_code


class SystemToolError(PDFProcessingError):
    """Error when system tools (Tesseract, Ghostscript) are unavailable or fail."""

    def __init__(self, tool_name: str, message: str, suggestions: list = None):
        user_message = f"{tool_name} is not available or failed to run"
        super().__init__(
            message=message,
            user_message=user_message,
            suggestions=suggestions or self._get_tool_suggestions(tool_name),
            error_code=f"TOOL_{tool_name.upper()}_ERROR",
        )

    def _get_tool_suggestions(self, tool_name: str) -> list:
        """Get installation suggestions for specific tools."""
        suggestions = {
            "tesseract": [
                "Install Tesseract OCR and ensure it's on your PATH:",
                "  Windows: winget install UB-Mannheim.TesseractOCR",
                "  macOS: brew install tesseract tesseract-lang",
                "  Linux (Debian/Ubuntu): sudo apt install tesseract-ocr",
                "  Linux (Fedora/RHEL): sudo dnf install tesseract",
                "  Linux (Arch): sudo pacman -S tesseract tesseract-data-eng",
                "Verify with: tesseract --version",
            ],
            "ghostscript": [
                "Install Ghostscript and ensure it's on your PATH:",
                "  Windows: winget install AGPL.Ghostscript",
                "  macOS: brew install ghostscript",
                "  Linux (Debian/Ubuntu): sudo apt install ghostscript",
                "  Linux (Fedora/RHEL): sudo dnf install ghostscript",
                "  Linux (Arch): sudo pacman -S ghostscript",
                "Verify with: gswin64c --version (Windows) or gs --version (other)",
            ],
        }
        return suggestions.get(
            tool_name.lower(), [f"Install {tool_name} and ensure it's in your PATH"]
        )


class PDFFormatError(PDFProcessingError):
    """Error when PDF format is unsupported or corrupted."""

    def __init__(self, file_path: Path, message: str):
        user_message = f"PDF file '{file_path.name}' cannot be processed"
        suggestions = [
            "Ensure the file is a valid PDF document",
            "Check if the PDF is password-protected or encrypted",
            "Try opening the PDF in a viewer to verify it's not corrupted",
            "If it's a very old PDF, try converting it to a newer format first",
        ]
        super().__init__(
            message=message,
            user_message=user_message,
            suggestions=suggestions,
            error_code="PDF_FORMAT_ERROR",
        )


class InsufficientResourcesError(PDFProcessingError):
    """Error when system resources are insufficient."""

    def __init__(self, resource_type: str, required: str, available: str = None):
        message = f"Insufficient {resource_type}: requires {required}"
        if available:
            message += f", available: {available}"

        suggestions = [
            f"Close other applications to free up {resource_type}",
            "Try processing a smaller file first",
            "Consider using a machine with more resources",
        ]

        if resource_type == "memory":
            suggestions.extend(
                [
                    "Reduce the number of parallel jobs (--jobs parameter)",
                    "Process the PDF in smaller chunks if possible",
                ]
            )
        elif resource_type == "disk space":
            suggestions.extend(
                [
                    "Free up disk space on your system",
                    "Clean temporary files",
                    "Specify a different temporary directory with more space",
                ]
            )

        super().__init__(
            message=message,
            user_message=f"Not enough {resource_type} available to process this file",
            suggestions=suggestions,
            error_code=f"INSUFFICIENT_{resource_type.upper()}",
        )


class FileAccessError(PDFProcessingError):
    """Error when files cannot be accessed."""

    def __init__(
        self, file_path: Path, operation: str, original_error: Exception = None
    ):
        message = f"Cannot {operation} file: {file_path}"
        if original_error:
            message += f" ({original_error})"

        suggestions = [
            "Check that the file exists and you have permission to access it",
            "Ensure the file is not open in another application",
            "Verify the file path is correct",
        ]

        if operation == "write":
            suggestions.extend(
                [
                    "Check that you have write permissions to the output directory",
                    "Ensure there is enough free disk space",
                    "Try using a different output location",
                ]
            )

        super().__init__(
            message=message,
            user_message=f"Cannot {operation} '{file_path.name}'",
            suggestions=suggestions,
            error_code=f"FILE_{operation.upper()}_ERROR",
        )


def format_error_for_user(error: Exception) -> tuple[str, list, str | None]:
    """
    Format any exception for user-friendly display.

    Returns:
        (user_message, suggestions, error_code)
    """
    if isinstance(error, PDFProcessingError):
        return error.user_message, error.suggestions, error.error_code

    # Handle common Python exceptions with user-friendly messages
    error_type = type(error).__name__
    message = str(error)

    if isinstance(error, FileNotFoundError):
        return (
            f"File not found: {message}",
            [
                "Check that the file path is correct",
                "Ensure the file exists",
                "Try browsing for the file instead of typing the path",
            ],
            "FILE_NOT_FOUND",
        )

    elif isinstance(error, PermissionError):
        return (
            f"Permission denied: {message}",
            [
                "Check that you have permission to access the file",
                "Try running as administrator (Windows) or with sudo (Linux/macOS)",
                "Ensure the file is not open in another application",
            ],
            "PERMISSION_DENIED",
        )

    elif isinstance(error, MemoryError):
        return (
            "Not enough memory to process this file",
            [
                "Close other applications to free up memory",
                "Try processing a smaller file",
                "Reduce the number of parallel jobs",
                "Consider using a machine with more RAM",
            ],
            "INSUFFICIENT_MEMORY",
        )

    elif "disk" in message.lower() or "space" in message.lower():
        return (
            "Not enough disk space available",
            [
                "Free up disk space on your system",
                "Clean temporary files",
                "Use a different output location with more space",
            ],
            "INSUFFICIENT_DISK_SPACE",
        )

    # Generic error handling
    return (
        f"An unexpected error occurred: {message}",
        [
            "Please try again",
            "If the problem persists, check the log files for more details",
            "Consider reporting this issue on GitHub",
        ],
        f"GENERIC_{error_type.upper()}",
    )


def create_error_report(error: Exception, context: dict = None) -> dict:
    """Create a detailed error report for debugging."""
    user_msg, suggestions, error_code = format_error_for_user(error)

    report = {
        "error_code": error_code,
        "user_message": user_msg,
        "suggestions": suggestions,
        "technical_details": {
            "exception_type": type(error).__name__,
            "exception_message": str(error),
            "python_version": sys.version,
            "platform": sys.platform,
        },
    }

    if context:
        report["context"] = context

    if hasattr(error, "__traceback__") and error.__traceback__:
        import traceback

        report["technical_details"]["traceback"] = traceback.format_tb(
            error.__traceback__
        )

    return report
