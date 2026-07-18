"""One-command quality gate: ruff + black --check (+ pytest).

Runs the same checks CI runs, with honest exit codes. Motivation
(fable_review Mode 5): a fix session piped `black --check` through
`tail`, masking its exit code, and shipped an unformatted line; a later
push went red on CI for an environment gap local runs never exercised.
One local command that mirrors CI closes that gap.

Usage (from the repo root):

    uv run python tools/check.py           # full gate: lint + format + tests
    uv run python tools/check.py --fast    # lint + format only (quick / hook)
    uv run python tools/check.py --paths some/dir   # override checked paths

Optional pre-commit wiring (Git Bash / POSIX sh):

    printf '#!/bin/sh\nuv run python tools/check.py --fast\n' > .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
"""

import argparse
import subprocess
import sys

DEFAULT_PATHS = ["src/", "tests/"]


def _run(label: str, cmd: list[str]) -> bool:
    print(f"--- {label}: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    ok = result.returncode == 0
    print(f"--- {label}: {'OK' if ok else f'FAILED (exit {result.returncode})'}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fast", action="store_true", help="skip pytest (lint + format only)"
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        default=DEFAULT_PATHS,
        help="paths for ruff/black (default: src/ tests/)",
    )
    args = parser.parse_args()

    checks: list[tuple[str, list[str]]] = [
        ("ruff", ["ruff", "check", *args.paths]),
        ("black", ["black", "--check", *args.paths]),
    ]
    if not args.fast:
        checks.append(("pytest", ["pytest", "-q"]))

    failures = [label for label, cmd in checks if not _run(label, cmd)]
    if failures:
        print(f"\nGate FAILED: {', '.join(failures)}")
        return 1
    print("\nGate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
