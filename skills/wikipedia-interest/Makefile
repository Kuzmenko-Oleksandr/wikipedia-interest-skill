.PHONY: install lint format typecheck test check

# Copies instead of hard links: claude plugin eval refuses hard-linked files in a plugin.
install:
	UV_LINK_MODE=copy uv sync --locked
	uv run pre-commit install

# Read-only, mirrors CI; fixes belong in `format`.
lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run basedpyright

test:
	uv run pytest

check: lint typecheck test
