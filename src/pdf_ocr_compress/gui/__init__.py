"""Streamlit GUI for PDF OCR + Compression."""

import sys
from pathlib import Path

from .basic import main as basic_gui


def main_gui() -> None:
    """Launch the Streamlit GUI as a subprocess-equivalent of `streamlit run`."""
    from streamlit.web import cli as st_cli

    script_path = Path(__file__).parent / "basic.py"
    sys.argv = ["streamlit", "run", str(script_path)]
    sys.exit(st_cli.main())


__all__ = ["main_gui", "basic_gui"]
