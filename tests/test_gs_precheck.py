"""Tests for the Ghostscript binary precheck added in Phase 1."""

import shutil

import pytest

from pdf_ocr_compress.core.compress import _gs_exe
from pdf_ocr_compress.utils.errors import SystemToolError


def test_missing_ghostscript_raises_systemtool_error(monkeypatch):
    """When no GS binary is on PATH, _gs_exe must raise — not return a
    bogus default and let subprocess fail with a cryptic [WinError 2].
    """
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(SystemToolError) as excinfo:
        _gs_exe()

    assert excinfo.value.error_code == "TOOL_GHOSTSCRIPT_ERROR"
    assert any("install" in s.lower() for s in excinfo.value.suggestions)


def test_gs_exe_returns_first_match(monkeypatch):
    """Lookup order: gswin64c → gswin32c → gs."""
    found = {"gswin64c": "/fake/gswin64c"}
    monkeypatch.setattr(shutil, "which", lambda name: found.get(name))
    assert _gs_exe() == "/fake/gswin64c"


def test_gs_exe_falls_through_to_unix_name(monkeypatch):
    found = {"gs": "/usr/bin/gs"}
    monkeypatch.setattr(shutil, "which", lambda name: found.get(name))
    assert _gs_exe() == "/usr/bin/gs"
