"""Tests for the rebuilt config.settings module."""

import json
from pathlib import Path

import pytest

from pdf_ocr_compress.config.settings import AppSettings, ConfigManager


def test_defaults_match_phase_0_invariants():
    """The Phase 0 benchmark locked these in; regression-guard them."""
    s = AppSettings()
    assert s.default_preset == "smallest"  # invariant #4
    assert s.oversize_policy == "fallback"  # invariant #1
    assert s.default_language == "eng"
    assert s.default_jobs == 4
    assert s.batch_concurrency == 1
    assert s.tesseract_timeout == 0
    assert s.default_output_dir is None


def test_round_trip_through_json(tmp_path):
    cm = ConfigManager(config_dir=tmp_path)
    s = cm.settings
    s.default_preset = "archival"
    s.default_output_dir = tmp_path / "out"
    s.batch_concurrency = 4
    cm.save_settings(s)

    cm2 = ConfigManager(config_dir=tmp_path)
    loaded = cm2.settings
    assert loaded.default_preset == "archival"
    assert loaded.default_output_dir == tmp_path / "out"
    assert isinstance(loaded.default_output_dir, Path)
    assert loaded.batch_concurrency == 4


def test_corrupted_config_is_quarantined_and_defaults_returned(tmp_path):
    cm = ConfigManager(config_dir=tmp_path)
    cm.config_file.write_text("{ this is not json", encoding="utf-8")

    cm2 = ConfigManager(config_dir=tmp_path)
    s = cm2.settings
    assert s.default_preset == "smallest"  # defaults restored
    backups = list(tmp_path.glob("settings.backup.*"))
    assert backups, "corrupted config should have been backed up"


def test_unknown_keys_in_json_are_ignored(tmp_path):
    """Forward-compat: an old settings file with stale keys must not crash."""
    cm = ConfigManager(config_dir=tmp_path)
    cm.config_file.write_text(
        json.dumps(
            {
                "default_preset": "archival",
                "ui": {"theme": "dark"},  # legacy nested key from old schema
                "unrelated_field": 42,
            }
        ),
        encoding="utf-8",
    )

    cm2 = ConfigManager(config_dir=tmp_path)
    s = cm2.settings
    assert s.default_preset == "archival"
    # No AttributeError or TypeError; unknown keys silently dropped.


@pytest.mark.parametrize(
    "env_key,attr,raw,expected",
    [
        ("PDF_OCR_DEFAULT_PRESET", "default_preset", "archival", "archival"),
        ("PDF_OCR_DEFAULT_LANGUAGE", "default_language", "spa", "spa"),
        ("PDF_OCR_DEFAULT_JOBS", "default_jobs", "8", 8),
        ("PDF_OCR_BATCH_CONCURRENCY", "batch_concurrency", "3", 3),
        ("PDF_OCR_OVERSIZE_POLICY", "oversize_policy", "warn", "warn"),
        ("PDF_OCR_TESSERACT_TIMEOUT", "tesseract_timeout", "180", 180),
    ],
)
def test_env_overrides(tmp_path, monkeypatch, env_key, attr, raw, expected):
    monkeypatch.setenv(env_key, raw)
    cm = ConfigManager(config_dir=tmp_path)
    cm.apply_env_overrides()
    assert getattr(cm.settings, attr) == expected


def test_env_override_for_output_dir(tmp_path, monkeypatch):
    target = tmp_path / "scans"
    monkeypatch.setenv("PDF_OCR_DEFAULT_OUTPUT_DIR", str(target))
    cm = ConfigManager(config_dir=tmp_path)
    cm.apply_env_overrides()
    assert cm.settings.default_output_dir == target
    assert isinstance(cm.settings.default_output_dir, Path)
