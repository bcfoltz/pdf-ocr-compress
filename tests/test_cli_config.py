"""Tests for `pdf-ocr config show|set` (accepted proposal P-004).

Uses an isolated config dir so the user's real settings.json is never
touched, and resets the process-wide config singleton so earlier tests'
state can't leak in.
"""

import json
from dataclasses import fields as dc_fields

import pytest
from typer.testing import CliRunner

import pdf_ocr_compress.config.settings as cfg_settings
from pdf_ocr_compress.cli import app

runner = CliRunner()


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point ConfigManager's default dir at tmp_path; reset the singleton."""
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setattr(cfg_settings, "_default_config_dir", lambda: cfg_dir)
    monkeypatch.setattr(cfg_settings, "_config_manager", None)
    return cfg_dir


def _read_settings_file(cfg_dir):
    return json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))


def test_config_show_lists_all_fields_and_path(isolated_config):
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    for f in dc_fields(cfg_settings.AppSettings):
        assert f.name in result.output
    assert str(isolated_config / "settings.json") in result.output


def test_config_set_persists_to_disk(isolated_config):
    result = runner.invoke(app, ["config", "set", "default_preset", "archival"])
    assert result.exit_code == 0, result.output
    assert _read_settings_file(isolated_config)["default_preset"] == "archival"


def test_config_set_rejects_unknown_key(isolated_config):
    result = runner.invoke(app, ["config", "set", "no_such_key", "1"])
    assert result.exit_code != 0
    # The error lists the valid keys so the user can self-correct.
    assert "default_preset" in result.output


def test_config_set_validates_choices(isolated_config):
    bad_preset = runner.invoke(app, ["config", "set", "default_preset", "ultra"])
    assert bad_preset.exit_code != 0
    bad_policy = runner.invoke(app, ["config", "set", "oversize_policy", "explode"])
    assert bad_policy.exit_code != 0
    assert not (isolated_config / "settings.json").exists()


def test_config_set_coerces_ints(isolated_config):
    ok = runner.invoke(app, ["config", "set", "default_jobs", "8"])
    assert ok.exit_code == 0, ok.output
    assert _read_settings_file(isolated_config)["default_jobs"] == 8

    bad = runner.invoke(app, ["config", "set", "default_jobs", "lots"])
    assert bad.exit_code != 0


def test_config_set_does_not_persist_env_overrides(isolated_config, monkeypatch):
    """PDF_OCR_* env values apply per-session; `set` must never bake them
    into settings.json.
    """
    monkeypatch.setenv("PDF_OCR_DEFAULT_PRESET", "archival")
    result = runner.invoke(app, ["config", "set", "default_jobs", "2"])
    assert result.exit_code == 0, result.output
    data = _read_settings_file(isolated_config)
    assert data["default_jobs"] == 2
    # The file keeps the factory preset, not the env value.
    assert data["default_preset"] == "smallest"


def test_config_show_notes_env_overrides(isolated_config, monkeypatch):
    monkeypatch.setenv("PDF_OCR_DEFAULT_PRESET", "archival")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "PDF_OCR_DEFAULT_PRESET" in result.output
