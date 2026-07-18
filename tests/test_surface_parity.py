"""Guardrail: surface parity — defaults flow from settings, not hardcodes.

fable_review Mode 5 guardrail for the "surface parity drift" theme
(F-003 class) and the blocking-async regression class (F-001). These
tests inspect Typer/FastAPI parameter metadata, so they fail the moment
someone reintroduces a hardcoded default or turns the processing route
back into a coroutine — no pipeline run needed.

Convention being enforced (CLAUDE.md "Defaults flow from config"): the
single-file CLI commands and the /api/process form defer preset /
language / jobs to `config.get_config().settings` by defaulting the
parameter to None. A literal default re-hardcoded on any surface
silently diverges from design rule #4 the moment the setting changes.
"""

import inspect

import pytest
from fastapi import params as fastapi_params
from typer.models import OptionInfo

from pdf_ocr_compress import cli
from pdf_ocr_compress.api import server

# Command -> parameters that must default to None (settings-driven).
SETTINGS_DRIVEN_CLI_PARAMS = [
    ("ocr", "lang"),
    ("ocr", "preset"),
    ("ocr", "jobs"),
    ("compress", "preset"),
    ("process", "lang"),
    ("process", "preset"),
    ("process", "jobs"),
    ("batch", "preset"),
    ("batch", "lang"),
    ("batch", "jobs"),
]


def _command_callback(name: str):
    for cmd in cli.app.registered_commands:
        cb = cmd.callback
        if (cmd.name or cb.__name__) == name:
            return cb
    raise AssertionError(f"CLI command {name!r} not found on cli.app")


@pytest.mark.parametrize(("cmd_name", "param"), SETTINGS_DRIVEN_CLI_PARAMS)
def test_cli_defaults_defer_to_settings(cmd_name, param):
    sig = inspect.signature(_command_callback(cmd_name))
    default = sig.parameters[param].default
    if isinstance(default, OptionInfo):
        default = default.default
    assert default is None, (
        f"pdf-ocr {cmd_name}: parameter {param!r} hardcodes {default!r} — "
        "it must default to None so config.get_config().settings decides "
        "(CLAUDE.md 'Defaults flow from config'; fable_review F-003)."
    )


@pytest.mark.parametrize("param", ["preset", "language", "jobs"])
def test_api_process_form_defaults_defer_to_settings(param):
    sig = inspect.signature(server.process_pdf)
    default = sig.parameters[param].default
    assert isinstance(default, fastapi_params.Form), (
        f"/api/process parameter {param!r} is no longer a Form field — "
        "update this guardrail if that change was intentional."
    )
    assert default.default is None, (
        f"/api/process: form field {param!r} hardcodes {default.default!r} — "
        "it must default to None and resolve from settings in the handler "
        "(fable_review F-003)."
    )


def test_api_process_route_is_sync():
    """process_pdf must stay a plain def (threadpool), never async.

    As `async def` it ran the fully blocking pipeline on the event loop,
    freezing /health and batch polling for the entire run — minutes to
    hours on real scans (fable_review F-001).
    """
    assert not inspect.iscoroutinefunction(server.process_pdf), (
        "api.server.process_pdf is a coroutine again — it calls the "
        "blocking run_pipeline() and would freeze the event loop. Keep it "
        "a plain def so FastAPI runs it in the threadpool."
    )
