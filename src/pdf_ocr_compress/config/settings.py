"""Persisted user settings for pdf-ocr-compress.

Single flat dataclass — defaults flow through the pipeline when CLI/GUI/API
callers leave a parameter as None. Settings live at a platform-appropriate
location (Windows: %LOCALAPPDATA%\\PDFOCRCompress\\settings.json; Unix:
~/.config/pdf-ocr-compress/settings.json).
"""

import json
import os
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

OversizePolicy = Literal["fallback", "warn", "fail"]


@dataclass
class AppSettings:
    default_preset: str = "smallest"
    default_language: str = "eng"
    default_jobs: int = 4
    default_output_dir: Path | None = None
    batch_concurrency: int = 1
    oversize_policy: OversizePolicy = "fallback"
    tesseract_timeout: int = 0
    # API upload cap in bytes; 0 = unlimited. Nonzero makes /api/process
    # reject bigger uploads with the FILE_TOO_LARGE error code.
    max_upload_bytes: int = 0


def _default_config_dir() -> Path:
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "PDFOCRCompress"
    return Path.home() / ".config" / "pdf-ocr-compress"


class ConfigManager:
    """Loads, persists, and exposes AppSettings."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = Path(config_dir) if config_dir else _default_config_dir()
        self.config_file = self.config_dir / "settings.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._settings: AppSettings | None = None

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            self._settings = self.load_settings()
        return self._settings

    def load_settings(self) -> AppSettings:
        if not self.config_file.exists():
            return AppSettings()
        try:
            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            self._backup_corrupted_config()
            return AppSettings()
        return self._dict_to_settings(data)

    def save_settings(self, settings: AppSettings | None = None) -> None:
        if settings is None:
            settings = self.settings
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self._settings_to_dict(settings), f, indent=2, ensure_ascii=False)
        self._settings = settings

    def apply_env_overrides(self) -> None:
        s = self.settings
        if v := os.getenv("PDF_OCR_DEFAULT_PRESET"):
            s.default_preset = v
        if v := os.getenv("PDF_OCR_DEFAULT_LANGUAGE"):
            s.default_language = v
        if v := os.getenv("PDF_OCR_DEFAULT_JOBS"):
            s.default_jobs = int(v)
        if v := os.getenv("PDF_OCR_DEFAULT_OUTPUT_DIR"):
            s.default_output_dir = Path(v)
        if v := os.getenv("PDF_OCR_BATCH_CONCURRENCY"):
            s.batch_concurrency = int(v)
        if v := os.getenv("PDF_OCR_OVERSIZE_POLICY"):
            s.oversize_policy = v  # type: ignore[assignment]
        if v := os.getenv("PDF_OCR_TESSERACT_TIMEOUT"):
            s.tesseract_timeout = int(v)
        if v := os.getenv("PDF_OCR_MAX_UPLOAD_BYTES"):
            s.max_upload_bytes = int(v)

    @staticmethod
    def _settings_to_dict(s: AppSettings) -> dict[str, Any]:
        d = asdict(s)
        if d["default_output_dir"] is not None:
            d["default_output_dir"] = str(d["default_output_dir"])
        return d

    @staticmethod
    def _dict_to_settings(data: dict[str, Any]) -> AppSettings:
        kwargs: dict[str, Any] = {}
        valid = {f.name for f in fields(AppSettings)}
        for k, v in data.items():
            if k not in valid:
                continue
            if k == "default_output_dir" and v is not None:
                v = Path(v)
            kwargs[k] = v
        return AppSettings(**kwargs)

    def _backup_corrupted_config(self) -> None:
        if self.config_file.exists():
            self.config_file.rename(
                self.config_file.with_suffix(f".backup.{int(time.time())}")
            )


_config_manager: ConfigManager | None = None


def get_config() -> ConfigManager:
    """Return the process-wide ConfigManager (lazy, env-overrides applied once)."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
        _config_manager.apply_env_overrides()
    return _config_manager


def save_config(config: ConfigManager | None = None) -> None:
    (config or get_config()).save_settings()
