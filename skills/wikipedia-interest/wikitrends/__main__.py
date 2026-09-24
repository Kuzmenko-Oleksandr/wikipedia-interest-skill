"""Entry point: `python -m wikitrends`."""

import json
import os
import sys
from pathlib import Path
from typing import NoReturn

# Must precede any import that can reach pyplot: headless, no display needed.
os.environ.setdefault("MPLBACKEND", "Agg")

SKILL_DIR = Path(__file__).resolve().parent.parent
INSTALL = (
    f"python3.12 -m venv {SKILL_DIR}/.venv && "
    f"{SKILL_DIR}/.venv/bin/pip install -r {SKILL_DIR}/requirements.txt"
)


def _fail(error: str) -> NoReturn:
    # Same one-line contract as the CLI, before the CLI can even be imported.
    print(json.dumps({"ok": False, "schema": 1, "error": error, "hint": f"Run: {INSTALL}"}))
    raise SystemExit(1)


# Runs exactly when requires-python was not honoured, e.g. a bare python3 of 3.11.
if sys.version_info < (3, 12):  # noqa: UP036
    _fail(f"Python 3.12+ is required, this is {sys.version.split()[0]}")

try:
    from wikitrends.cli import main
except ModuleNotFoundError as exc:
    _fail(f"missing dependency: {exc.name}")

raise SystemExit(main())
