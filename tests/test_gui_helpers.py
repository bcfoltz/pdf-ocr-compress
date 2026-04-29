"""Unit tests for pure helpers in pdf_ocr_compress.gui.basic.

The Streamlit GUI is not unit-tested as a whole (UI code, no TDD
requirement). These tests cover the pure path/file helpers that the
GUI uses to decide where output goes and to render folder-mode pre-
flight summaries.
"""

from pathlib import Path

from pdf_ocr_compress.config.settings import ConfigManager
from pdf_ocr_compress.gui.basic import _resolve_output_dir


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

    path, source = _resolve_output_dir(
        cfg, override=override, fallback_factory=fallback
    )

    assert path == override
    assert source == "override"
    assert override.is_dir()
    assert fallback_calls["n"] == 0


def test_resolve_output_dir_setting_used_when_writable(tmp_path):
    setting_dir = tmp_path / "setting"
    cfg = _cfg_with(tmp_path, default_output_dir=setting_dir)
    fallback_calls = {"n": 0}

    def fallback():
        fallback_calls["n"] += 1
        return tmp_path / "fallback"

    path, source = _resolve_output_dir(cfg, override=None, fallback_factory=fallback)

    assert path == setting_dir
    assert source == "setting"
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

    path, source = _resolve_output_dir(cfg, override=None, fallback_factory=fallback)

    assert path == fallback_dir
    assert source == "fallback"
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

    path, source = _resolve_output_dir(cfg, override=None, fallback_factory=fallback)

    assert path == fallback_dir
    assert source == "fallback_after_unwritable"


def test_resolve_output_dir_factory_invoked_at_most_once(tmp_path):
    """Factory must be called only on the actual fallback paths."""
    cfg = _cfg_with(tmp_path, default_output_dir=tmp_path / "setting")
    calls = {"n": 0}

    def fallback():
        calls["n"] += 1
        return tmp_path / "never"

    _resolve_output_dir(cfg, override=None, fallback_factory=fallback)
    assert calls["n"] == 0
