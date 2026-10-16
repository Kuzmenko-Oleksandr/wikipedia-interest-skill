"""SKILL.md follows the Agent Skills specification and stays within the token budget."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def _fake_mac(tmp_path: Path, machine: str, wheel_arch: str) -> tuple[Path, dict[str, str]]:
    """A copy of the shim with a .venv whose numpy wheel is `wheel_arch`, on a fake macOS."""
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    shutil.copy(SKILL_DIR / "scripts" / "wikitrends", skill / "scripts" / "wikitrends")
    venv = skill / ".venv"
    dist = venv / "lib" / "python3.12" / "site-packages" / "numpy-2.5.0.dist-info"
    dist.mkdir(parents=True)
    (dist / "WHEEL").write_text(f"Tag: cp312-cp312-macosx_14_0_{wheel_arch}\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        venv / "bin" / "python": 'echo "python $*"',
        bin_dir / "uname": f'[ "$1" = -m ] && echo {machine} || echo Darwin',
        bin_dir / "arch": 'printf "arch %s " "$1"; shift; exec "$@"',
    }
    for path, body in scripts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return skill / "scripts" / "wikitrends", env


@pytest.mark.parametrize(
    ("machine", "wheel_arch", "prefix"),
    [
        ("x86_64", "arm64", "arch -arm64 "),  # shell under Rosetta, native .venv
        ("arm64", "x86_64", "arch -x86_64 "),  # native shell, .venv built under Rosetta
        ("arm64", "arm64", ""),
        ("x86_64", "x86_64", ""),  # Intel Mac
    ],
)
def test_shim_runs_python_in_the_architecture_of_the_venv(
    tmp_path: Path, machine: str, wheel_arch: str, prefix: str
) -> None:
    shim, env = _fake_mac(tmp_path, machine, wheel_arch)
    done = subprocess.run(
        ["sh", str(shim), "resolve", "--topic", "A b"],
        env=env,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == f"{prefix}python -m wikitrends resolve --topic A b\n"


def test_wrong_architecture_wheel_still_prints_one_json_line() -> None:
    code = (
        "import runpy, sys\n"
        "class Finder:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'wikitrends.cli':\n"
        "            raise ImportError('dlopen(_multiarray_umath.so): mach-o file, but is an '\n"
        "                \"incompatible architecture (have 'arm64', need 'x86_64')\")\n"
        "sys.meta_path.insert(0, Finder())\n"
        "runpy.run_module('wikitrends', run_name='__main__')\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SKILL_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1, done.stderr
    assert done.stdout.count("\n") == 1
    payload = json.loads(done.stdout)
    assert payload["ok"] is False
    assert "architecture" in payload["error"]
    assert "scripts/wikitrends" in payload["hint"] and "rm -rf" in payload["hint"]
