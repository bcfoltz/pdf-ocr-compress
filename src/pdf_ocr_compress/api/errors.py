"""API-level error model and exception handlers.

This module owns the *wire shape* every 4xx/5xx response uses. Internal
domain exceptions live in `utils.errors`; this layer maps them to a
small, stable set of `error_code` strings consumers can branch on
without parsing English. Adding a new code is non-breaking; changing an
existing code's meaning is breaking.

Routes raise `APIException(status, code, message)` instead of
`HTTPException`, and any uncaught `PDFProcessingError` is translated by
`install_exception_handlers`.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..utils.errors import (
    PDFFormatError,
    PDFProcessingError,
    SystemToolError,
)

# --- Stable wire-level error codes ------------------------------------------
# ROADMAP Phase 4 item 2 lists a canonical subset; the rest cover existing
# 4xx paths. Codes are ALL_CAPS_SNAKE for grep-ability across consumer code.

INPUT_NOT_PDF: Final[str] = "INPUT_NOT_PDF"
INVALID_MODE: Final[str] = "INVALID_MODE"
INVALID_PRESET: Final[str] = "INVALID_PRESET"
INVALID_FOLDER: Final[str] = "INVALID_FOLDER"
INVALID_OUTPUT_DIR: Final[str] = "INVALID_OUTPUT_DIR"
FILE_NOT_FOUND: Final[str] = "FILE_NOT_FOUND"
BATCH_JOB_NOT_FOUND: Final[str] = "BATCH_JOB_NOT_FOUND"
OCR_TOOL_MISSING: Final[str] = "OCR_TOOL_MISSING"
GHOSTSCRIPT_TOOL_MISSING: Final[str] = "GHOSTSCRIPT_TOOL_MISSING"
PROCESSING_FAILED: Final[str] = "PROCESSING_FAILED"
OUTPUT_GREW_NO_FALLBACK: Final[str] = "OUTPUT_GREW_NO_FALLBACK"
VALIDATION_ERROR: Final[str] = "VALIDATION_ERROR"
# Raised (413) by /api/process when a nonzero max_upload_bytes setting is
# exceeded during the chunked upload copy. Factory default is 0 (unlimited).
FILE_TOO_LARGE: Final[str] = "FILE_TOO_LARGE"


class APIError(BaseModel):
    """Stable JSON shape for every 4xx/5xx response.

    `error_code` is the machine-readable identifier consumers branch on.
    `message` is human-readable English. `suggestions` mirrors the
    optional remediation hints from `PDFProcessingError`.
    """

    error_code: str
    message: str
    suggestions: list[str] = []


class APIException(Exception):
    """Server-side carrier for an APIError + HTTP status code.

    Routes raise this; the handler installed by
    `install_exception_handlers` converts it to a JSON response with the
    canonical `APIError` body.
    """

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        suggestions: list[str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.suggestions = suggestions or []

    def to_response(self) -> JSONResponse:
        body = APIError(
            error_code=self.error_code,
            message=self.message,
            suggestions=self.suggestions,
        ).model_dump()
        return JSONResponse(status_code=self.status_code, content=body)


def _domain_to_api(error: PDFProcessingError) -> APIException:
    """Map an internal domain exception to a wire-shape APIException."""
    if isinstance(error, SystemToolError):
        code_in = (error.error_code or "").upper()
        if code_in == "TOOL_TESSERACT_ERROR":
            wire_code = OCR_TOOL_MISSING
        elif code_in == "TOOL_GHOSTSCRIPT_ERROR":
            wire_code = GHOSTSCRIPT_TOOL_MISSING
        else:
            wire_code = PROCESSING_FAILED
        # 503 = the server's environment is missing a required binary.
        return APIException(503, wire_code, str(error), error.suggestions)
    if isinstance(error, PDFFormatError):
        return APIException(400, INPUT_NOT_PDF, str(error), error.suggestions)
    return APIException(500, PROCESSING_FAILED, str(error), error.suggestions)


def install_exception_handlers(app: FastAPI) -> None:
    """Wire APIException + PDFProcessingError + 422 handlers into `app`.

    Call once during app construction. After this, every 4xx/5xx path
    returns the `APIError` JSON shape (including FastAPI's automatic
    request-validation errors, which are normally a different schema).
    """

    @app.exception_handler(APIException)
    async def _api_exc(_request: Request, exc: APIException) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(PDFProcessingError)
    async def _domain_exc(_request: Request, exc: PDFProcessingError) -> JSONResponse:
        return _domain_to_api(exc).to_response()

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default 422 body is `{detail: [{...}, ...]}` — useful
        # but a different shape than APIError. Wrap it so consumers only
        # need to handle one schema; preserve the per-field details as
        # suggestion strings so debug info isn't lost.
        details = [
            f"{'.'.join(str(p) for p in err.get('loc', []))}: "
            f"{err.get('msg', 'invalid')}"
            for err in exc.errors()
        ]
        return APIException(
            422, VALIDATION_ERROR, "Request validation failed", details
        ).to_response()
