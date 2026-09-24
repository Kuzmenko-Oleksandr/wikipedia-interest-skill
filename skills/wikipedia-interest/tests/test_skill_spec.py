"""SKILL.md follows the Agent Skills specification and stays within the token budget."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL = SKILL_DIR / "SKILL.md"
ALLOWED_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Conservative for English prose with code: about 3.5 characters per token.
CHARS_PER_TOKEN = 3.5


def frontmatter() -> tuple[dict[str, str], str]:
    _, head, body = SKILL.read_text(encoding="utf-8").split("---", 2)
    fields: dict[str, str] = {}
    key = ""
    for line in head.strip().splitlines():
        match = re.match(r"^([a-z-]+):\s*(.*)$", line)
        if match:
            key = match[1]
            fields[key] = "" if match[2] == ">-" else match[2]
        else:
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields, body


def test_name_matches_directory_and_rules() -> None:
    fields, _ = frontmatter()
    name = fields["name"]
    assert name == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
    assert len(name) <= 64
    assert "claude" not in name and "anthropic" not in name


def test_only_specified_fields() -> None:
    fields, _ = frontmatter()
    assert set(fields) <= ALLOWED_FIELDS
    assert {"name", "description", "license", "compatibility"} <= set(fields)


def test_description_length() -> None:
    fields, _ = frontmatter()
    assert 0 < len(fields["description"]) <= 1024
    assert len(fields["compatibility"]) <= 500


def test_body_budget() -> None:
    _, body = frontmatter()
    assert len(body.splitlines()) <= 500
    assert len(body) / CHARS_PER_TOKEN <= 5000


def test_referenced_files_exist() -> None:
    _, body = frontmatter()
    for path in re.findall(r"`((?:references|scripts|assets)/[^`\s]+)`", body):
        assert (SKILL_DIR / path).exists(), path


def test_shim_runs_through_sh_without_the_executable_bit(tmp_path: Path) -> None:
    shim = SKILL_DIR / "scripts" / "wikitrends"
    assert shim.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    done = subprocess.run(
        ["sh", str(shim), "resolve", "--offline-fixture", "demo", "--topic", "Astronomy"],
        cwd=tmp_path,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert '"ok":true' in done.stdout
