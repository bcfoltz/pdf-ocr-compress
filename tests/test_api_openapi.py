"""Phase 4 item 3 — /openapi.json reflects the APIError wire shape.

Locks in the responses= declarations on each route. If a future change
removes them or forgets to wire APIError onto a new error code, this
fails. Also asserts the request/response example bodies (used by /docs)
are present so the interactive docs stay informative.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pdf_ocr_compress.api.server import app


@pytest.fixture
def client(isolated_api_storage) -> TestClient:
    return TestClient(app)


@pytest.fixture
def schema(client: TestClient) -> dict:
    return client.get("/openapi.json").json()


def _ref_to_name(ref: str) -> str:
    """`#/components/schemas/APIError` -> `APIError`."""
    return ref.rsplit("/", 1)[-1]


def _response_model_name(schema: dict, path: str, method: str, status: str) -> str:
    """Resolve the response model name for a (path, method, status) triple."""
    body = schema["paths"][path][method]["responses"][status]
    content = body.get("content", {}).get("application/json", {})
    ref = content.get("schema", {}).get("$ref")
    assert ref, f"{path} {method.upper()} {status} has no JSON schema ref"
    return _ref_to_name(ref)


def test_components_include_apierror(schema: dict) -> None:
    assert "APIError" in schema["components"]["schemas"]


@pytest.mark.parametrize(
    "path, method, status",
    [
        ("/api/process", "post", "400"),
        ("/api/process", "post", "422"),
        ("/api/process", "post", "500"),
        ("/api/process", "post", "503"),
        ("/api/batch", "post", "400"),
        ("/api/batch", "post", "422"),
        ("/api/download/{file_id}", "get", "404"),
        ("/api/batch/{job_id}/status", "get", "404"),
    ],
)
def test_error_response_uses_apierror_schema(
    schema: dict, path: str, method: str, status: str
) -> None:
    assert _response_model_name(schema, path, method, status) == "APIError"


def test_batch_request_has_example(schema: dict) -> None:
    """The /docs interactive form should pre-fill with a working example."""
    body_schema = schema["components"]["schemas"]["BatchRequest"]
    example = body_schema.get("example") or body_schema.get("examples")
    assert example, "BatchRequest is missing a json_schema_extra example"


def test_process_response_has_example(schema: dict) -> None:
    body_schema = schema["components"]["schemas"]["ProcessResponse"]
    example = body_schema.get("example") or body_schema.get("examples")
    assert example, "ProcessResponse is missing a json_schema_extra example"
