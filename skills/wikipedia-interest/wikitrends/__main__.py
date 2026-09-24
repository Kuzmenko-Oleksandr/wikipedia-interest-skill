"""Entry point: `python -m wikitrends`."""

import os

# Must precede any import that can reach pyplot: headless, no display needed.
os.environ.setdefault("MPLBACKEND", "Agg")

from wikitrends.cli import main

raise SystemExit(main())
