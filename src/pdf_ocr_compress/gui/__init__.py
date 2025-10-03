"""GUI interfaces for PDF OCR + Compression."""

from .simple_first import main as main_gui
from .basic import main as basic_gui

__all__ = ["main_gui", "basic_gui"]