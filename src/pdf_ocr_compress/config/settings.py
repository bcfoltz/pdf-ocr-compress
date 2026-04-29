"""Configuration management for PDF OCR + Compression Tool."""

import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class OCRSettings:
    """OCR-specific settings."""

    default_language: str = "eng"
    default_jobs: int = 4
    tesseract_timeout: int = 0  # 0 = no timeout
    rotate_pages: bool = True
    force_ocr: bool = False


@dataclass
class CompressionSettings:
    """Compression-specific settings."""

    default_preset: str = "balanced"
    archival_quality: int = 0
    balanced_quality: int = 2
    smallest_quality: int = 3
    enable_jbig2: bool = True


@dataclass
class UISettings:
    """User interface settings."""

    theme: str = "light"  # light, dark, auto
    default_source_mode: str = "Upload in browser"
    remember_settings: bool = True
    show_advanced_options: bool = False
    enable_drag_drop: bool = True
    max_upload_size_mb: int = 4096


@dataclass
class SystemSettings:
    """System and performance settings."""

    temp_dir: Optional[str] = None
    max_memory_mb: int = 2048
    cleanup_temp_files: bool = True
    enable_caching: bool = True
    cache_size_mb: int = 1024
    log_level: str = "INFO"


@dataclass
class AppSettings:
    """Main application settings."""

    ocr: OCRSettings = None
    compression: CompressionSettings = None
    ui: UISettings = None
    system: SystemSettings = None

    def __post_init__(self):
        """Initialize nested settings if not provided."""
        if self.ocr is None:
            self.ocr = OCRSettings()
        if self.compression is None:
            self.compression = CompressionSettings()
        if self.ui is None:
            self.ui = UISettings()
        if self.system is None:
            self.system = SystemSettings()


class ConfigManager:
    """Centralized configuration management."""

    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize configuration manager."""
        if config_dir is None:
            # Use platform-appropriate config directory
            if os.name == "nt":  # Windows
                config_dir = Path.home() / "AppData" / "Local" / "PDFOCRCompress"
            else:  # Unix-like
                config_dir = Path.home() / ".config" / "pdf-ocr-compress"

        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "settings.json"

        # Ensure directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._settings = None

    @property
    def settings(self) -> AppSettings:
        """Get current settings (lazy loaded)."""
        if self._settings is None:
            self._settings = self.load_settings()
        return self._settings

    def load_settings(self) -> AppSettings:
        """Load settings from file or create defaults."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._dict_to_settings(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # If config is corrupted, fall back to defaults
                self._backup_corrupted_config()

        return AppSettings()

    def save_settings(self, settings: AppSettings = None):
        """Save settings to file."""
        if settings is None:
            settings = self.settings

        data = self._settings_to_dict(settings)

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self._settings = settings

    # Environment variable overrides
    def apply_env_overrides(self):
        """Apply environment variable overrides to settings."""
        settings = self.settings

        # OCR settings
        if env_lang := os.getenv("PDF_OCR_DEFAULT_LANGUAGE"):
            settings.ocr.default_language = env_lang
        if env_jobs := os.getenv("PDF_OCR_DEFAULT_JOBS"):
            settings.ocr.default_jobs = int(env_jobs)

        # System settings
        if env_temp := os.getenv("PDF_OCR_TEMP_DIR"):
            settings.system.temp_dir = env_temp
        if env_log := os.getenv("PDF_OCR_LOG_LEVEL"):
            settings.system.log_level = env_log.upper()

        # UI settings
        if env_theme := os.getenv("PDF_OCR_THEME"):
            settings.ui.theme = env_theme

        self.save_settings(settings)

    # Utility methods
    def _settings_to_dict(self, settings: AppSettings) -> Dict[str, Any]:
        """Convert settings object to dictionary."""
        return {
            "ocr": asdict(settings.ocr),
            "compression": asdict(settings.compression),
            "ui": asdict(settings.ui),
            "system": asdict(settings.system),
        }

    def _dict_to_settings(self, data: Dict[str, Any]) -> AppSettings:
        """Convert dictionary to settings object."""
        return AppSettings(
            ocr=OCRSettings(**data.get("ocr", {})),
            compression=CompressionSettings(**data.get("compression", {})),
            ui=UISettings(**data.get("ui", {})),
            system=SystemSettings(**data.get("system", {})),
        )

    def _backup_corrupted_config(self):
        """Backup corrupted configuration file."""
        if self.config_file.exists():
            backup_file = self.config_file.with_suffix(f".backup.{int(time.time())}")
            self.config_file.rename(backup_file)


# Global configuration instance
_config_manager: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """Get global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
        _config_manager.apply_env_overrides()
    return _config_manager


def save_config(config: Optional[ConfigManager] = None) -> None:
    """Save configuration to disk."""
    if config is None:
        config = get_config()
    config.save_settings()


@contextmanager
def temp_settings(**overrides):
    """Temporarily override settings for a context."""
    config = get_config()
    original_settings = config._settings_to_dict(config.settings)

    try:
        # Apply overrides
        temp_settings_obj = config.settings
        for key, value in overrides.items():
            if hasattr(temp_settings_obj, key):
                setattr(temp_settings_obj, key, value)

        yield config.settings
    finally:
        # Restore original settings
        config._settings = config._dict_to_settings(original_settings)
