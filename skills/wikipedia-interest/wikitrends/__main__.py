"""Entry point: `python -m wikitrends`."""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import NoReturn

# Must precede any import that can reach pyplot: headless, no display needed.
os.environ.setdefault("MPLBACKEND", "Agg")

SKILL_DIR = Path(__file__).resolve().parent.parent


def _install() -> str:
    found = (f"python3.{minor}" for minor in range(12, 16) if shutil.which(f"python3.{minor}"))
    return (
        f"{next(found, 'python3.12')} -m venv {SKILL_DIR}/.venv && "
        f"{SKILL_DIR}/.venv/bin/pip install -r {SKILL_DIR}/requirements.txt"
    )


def _fail(error: str, hint: str | None = None) -> NoReturn:
    # Same one-line contract as the CLI, before the CLI can even be imported.
    hint = hint or f"Run: {_install()}"
    print(json.dumps({"ok": False, "schema": 1, "error": error, "hint": hint}))
    raise SystemExit(1)


# Runs exactly when requires-python was not honoured, e.g. a bare python3 of 3.11.
if sys.version_info < (3, 12):  # noqa: UP036
    _fail(f"Python 3.12+ is required, this is {sys.version.split()[0]}")  # pyright: ignore[reportUnreachable]

try:
    from wikitrends.cli import main
except ModuleNotFoundError as exc:
    _fail(f"missing dependency: {exc.name}")
except ImportError as exc:
    # A compiled wheel that does not load, most often arm64 vs x86_64 under Rosetta on a Mac.
    reinstall = f"rm -rf {SKILL_DIR}/.venv && {_install()}"
    if "incompatible architecture" in str(exc):
        _fail(
            "dependencies were built for another CPU architecture (Rosetta?)",
            f"Call sh {SKILL_DIR}/scripts/wikitrends, which runs Python in the matching "
            f"architecture; if that still fails, run: {reinstall}",
        )
    first_line = next(iter(str(exc).strip().splitlines()), type(exc).__name__)
    _fail(f"broken dependency: {first_line[:200]}", f"Run: {reinstall}")

raise SystemExit(main())
