"""Unit tests for pure helpers in pdf_ocr_compress.gui.basic.

The Streamlit GUI is not unit-tested as a whole (UI code, no TDD
requirement). These tests cover the pure path/file helpers that the
GUI uses to decide where output goes and to render folder-mode pre-
flight summaries.
"""

from pathlib import Path

from pdf_ocr_compress.config.settings import ConfigManager
from pdf_ocr_compress.gui.basic import _collect_local_folder_inputs, _resolve_output_dir


def _cfg_with(tmp_path, **overrides) -> ConfigManager:
    """Return a ConfigManager whose settings reflect the given overrides.

    `tmp_path` is used as the config_dir so we never touch the user's
    real settings.json.
    """
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    for k, v in overrides.items():
        setattr(cfg.settings, k, v)
    return cfg


def test_resolve_output_dir_override_wins(tmp_path):
    cfg = _cfg_with(tmp_path, default_output_dir=tmp_path / "should_be_ignored")
    override = tmp_path / "user_typed"
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        return tmp_path / "fallback"

    path, source, detail = _resolve_output_dir(
        cfg, override=override, fallback_factory=fallback
    )

    assert path == override
    assert source == "override"
    assert detail is None
    assert override.is_dir()
    assert fallback_calls["n"] == 0


def test_resolve_output_dir_setting_used_when_writable(tmp_path):
    setting_dir = tmp_path / "setting"
    cfg = _cfg_with(tmp_path, default_output_dir=setting_dir)
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        return tmp_path / "fallback"

    path, source, detail = _resolve_output_dir(
        cfg, override=None, fallback_factory=fallback
    )

    assert path == setting_dir
    assert source == "setting"
    assert detail is None
    assert setting_dir.is_dir()
    assert fallback_calls["n"] == 0


def test_resolve_output_dir_fallback_when_setting_unset(tmp_path):
    cfg = _cfg_with(tmp_path, default_output_dir=None)
    fallback_dir = tmp_path / "fallback"
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        fallback_dir.mkdir()
        return fallback_dir

    path, source, detail = _resolve_output_dir(
        cfg, override=None, fallback_factory=fallback
    )

    assert path == fallback_dir
    assert source == "fallback"
    assert detail is None
    assert fallback_calls["n"] == 1


def test_resolve_output_dir_fallback_after_unwritable(tmp_path, monkeypatch):
    """If default_output_dir is set but mkdir raises, fall back and report it."""
    setting_dir = tmp_path / "unwritable"
    cfg = _cfg_with(tmp_path, default_output_dir=setting_dir)
    fallback_dir = tmp_path / "fallback"

    real_mkdir = Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if self == setting_dir:
            raise OSError("simulated read-only filesystem")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    def fallback():
        fallback_dir.mkdir()
        return fallback_dir

    path, source, detail = _resolve_output_dir(
        cfg, override=None, fallback_factory=fallback
    )

    assert path == fallback_dir
    assert source == "fallback_after_unwritable"
    assert isinstance(detail, OSError)
    assert "simulated read-only filesystem" in str(detail)


def test_resolve_output_dir_factory_invoked_at_most_once(tmp_path):
    """Factory must be called only on the actual fallback paths."""
    cfg = _cfg_with(tmp_path, default_output_dir=tmp_path / "setting")
    calls = {"n": 0}

    def fallback():
        calls["n"] += 1
        return tmp_path / "never"

    _resolve_output_dir(cfg, override=None, fallback_factory=fallback)
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Task 2: _collect_local_folder_inputs
# ---------------------------------------------------------------------------


def test_collect_inputs_empty_string():
    info = _collect_local_folder_inputs("")
    assert info == {"valid": False, "msg": "", "pdf_count": 0, "total_bytes": 0}


def test_collect_inputs_path_does_not_exist(tmp_path):
    info = _collect_local_folder_inputs(str(tmp_path / "does_not_exist"))
    assert info["valid"] is False
    assert "not found" in info["msg"].lower() or "does not exist" in info["msg"].lower()
    assert info["pdf_count"] == 0


def test_collect_inputs_path_is_a_file_not_a_folder(tmp_path):
    file_path = tmp_path / "actually_a_file.pdf"
    file_path.write_bytes(b"%PDF-1.4\n%EOF\n")
    info = _collect_local_folder_inputs(str(file_path))
    assert info["valid"] is False
    assert "folder" in info["msg"].lower() or "directory" in info["msg"].lower()


def test_collect_inputs_folder_with_zero_pdfs(tmp_path):
    (tmp_path / "readme.txt").write_text("not a pdf")
    info = _collect_local_folder_inputs(str(tmp_path))
    assert info["valid"] is False
    assert "no" in info["msg"].lower() and "pdf" in info["msg"].lower()
    assert info["pdf_count"] == 0


def test_collect_inputs_folder_with_pdfs_reports_count_and_bytes(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 1000)
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4\n" + b"y" * 2000)
    (tmp_path / "ignored.txt").write_text("ignore me")
    info = _collect_local_folder_inputs(str(tmp_path))
    assert info["valid"] is True
    assert info["pdf_count"] == 2
    expected_bytes = (tmp_path / "a.pdf").stat().st_size + (
        tmp_path / "b.pdf"
    ).stat().st_size
    assert info["total_bytes"] == expected_bytes
    assert "2 PDFs" in info["msg"]


def test_collect_inputs_expanduser(tmp_path, monkeypatch):
    """Ensure ~ in the typed path is expanded."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / "doc.pdf").write_bytes(b"%PDF-1.4\n%EOF\n")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows
    info = _collect_local_folder_inputs("~")
    assert info["valid"] is True
    assert info["pdf_count"] == 1
