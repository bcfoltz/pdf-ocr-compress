"""Streamlit GUI for PDF OCR + Compression."""

import sys
from pathlib import Path

from .basic import main as basic_gui


def main_gui() -> None:
    """Launch the Streamlit GUI as a subprocess-equivalent of `streamlit run`."""
    from streamlit.web import cli as st_cli

    script_path = Path(__file__).parent / "basic.py"
    # Upload limits must be passed at launch: server.* options are fixed
    # at startup (st.set_option can't change them), and the repo's
    # .streamlit/config.toml is only found when the cwd is the repo root.
    # Without these flags, `pdf-ocr-gui` run from any other directory
    # silently reverts to Streamlit's 200 MB default upload cap.
    sys.argv = [
        "streamlit",
        "run",
        str(script_path),
        "--server.maxUploadSize=8192",
        "--server.maxMessageSize=8192",
    ]
    sys.exit(st_cli.main())


__all__ = ["main_gui", "basic_gui"]
