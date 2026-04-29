"""Configuration management module."""

from .settings import (
    AppSettings,
    CompressionSettings,
    ConfigManager,
    OCRSettings,
    SystemSettings,
    UISettings,
    get_config,
    save_config,
    temp_settings,
)

__all__ = [
    "AppSettings",
    "OCRSettings",
    "CompressionSettings",
    "UISettings",
    "SystemSettings",
    "ConfigManager",
    "get_config",
    "save_config",
    "temp_settings",
]
