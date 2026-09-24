"""The stdout contract: one JSON line, absolute existing paths, short summary, useful hints."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from wikitrends import cli
from wikitrends.output import STDOUT_LIMIT

SKILL_DIR = Path(__file__).resolve().parent.parent
DEMO = ["--offline-fixture", "demo"]
ASTRONOMY = ["--topic", "Astronomy", "--langs", "uk,pl,cs,de,en,fr", "--since", "2023-09-01"]


def invoke(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[dict[str, Any], int]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.endswith("\n")
    assert len(out.encode()) <= STDOUT_LIMIT + 1
    return json.loads(out), code


def test_analyze_prints_one_line_with_absolute_paths(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload, code = invoke(capsys, "analyze", *DEMO, *ASTRONOMY, "--out-dir", str(tmp_path))
    assert code == 0
    assert payload["ok"] is True
    assert payload["slug"] == "cs-de-en-fr-pl-uk_astronomy_20230901-20260922"
    assert len(payload["summary"]) <= 200
    for key in ("metrics_json", "data_csv"):
        if key in payload:
            assert Path(payload[key]).is_absolute()
            assert Path(payload[key]).exists()
    verdicts = {entry["lang"]: entry["verdict"] for entry in payload["languages"]}
    assert verdicts == {
        "cs": "insufficient_data",
        "de": "growing_event_driven",
        "en": "growing",
        "fr": "level_shift_up",
        "pl": "stable",
        "uk": "growing",
    }


def test_metrics_file_holds_full_detail(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    payload, _ = invoke(capsys, "analyze", *DEMO, *ASTRONOMY, "--out-dir", str(tmp_path))
    metrics = json.loads(Path(payload["metrics_json"]).read_text(encoding="utf-8"))
    assert len(metrics["limitations"]) == 12
    assert metrics["ranking"]["unranked"] == ["cs"]
    uk = next(entry for entry in metrics["languages"] if entry["lang"] == "uk")
    assert uk["title"] == "Астрономія"
    assert 20 < uk["pct_per_year"] < 30
    assert "Offline fixture: synthetic data, not real Wikipedia traffic." in metrics["warnings"]


def test_same_request_same_folder(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    first, _ = invoke(capsys, "analyze", *DEMO, *ASTRONOMY, "--out-dir", str(tmp_path))
    second, _ = invoke(capsys, "analyze", *DEMO, *ASTRONOMY, "--out-dir", str(tmp_path))
    assert first["slug"] == second["slug"]
    assert [p.name for p in tmp_path.iterdir()] == [first["slug"]]


def test_titles_are_canonicalized_before_fetching(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    payload, code = invoke(
        capsys,
        "analyze",
        *DEMO,
        "--titles",
        "uk:астрономія,pl:astronomia",
        "--since",
        "2024-09-01",
        "--out-dir",
        str(tmp_path),
    )
    assert code == 0
    metrics = json.loads(Path(payload["metrics_json"]).read_text(encoding="utf-8"))
    assert [e["title"] for e in metrics["languages"]] == ["Astronomia", "Астрономія"]


def test_resolve_lists_titles(capsys: pytest.CaptureFixture[str]) -> None:
    payload, code = invoke(capsys, "resolve", *DEMO, "--topic", "Astronomy")
    assert code == 0
    assert payload["qid"] == "Q333"
    assert payload["titles"]["uk"] == "Астрономія"
    assert payload["available_count"] == 6
    assert "uk:Астрономія" in payload["titles_arg"]


def test_unknown_language_is_a_json_error_with_hint(capsys: pytest.CaptureFixture[str]) -> None:
    payload, code = invoke(capsys, "analyze", *DEMO, "--topic", "Astronomy", "--langs", "xx")
    assert code == 1
    assert payload["ok"] is False
    assert "language code" in payload["hint"]


def test_usage_error_is_a_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    payload, code = invoke(capsys, "compare", "--langs", "uk")
    assert code == 1
    assert payload["ok"] is False
    assert payload["hint"]


def test_topic_outside_fixture_names_the_fix(capsys: pytest.CaptureFixture[str]) -> None:
    payload, code = invoke(capsys, "analyze", *DEMO, "--topic", "Chess", "--langs", "uk")
    assert code == 1
    assert "offline-fixture" in payload["hint"]


def test_cache_status_and_clear(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    invoke(capsys, "fetch", *DEMO, *ASTRONOMY, "--cache-dir", str(tmp_path))
    status, _ = invoke(capsys, "cache", *DEMO, "--cache-dir", str(tmp_path))
    assert status["series"] == 12
    cleared, _ = invoke(capsys, "cache", *DEMO, "--cache-dir", str(tmp_path), "--clear")
    assert not Path(cleared["cleared"]).exists()


def test_second_run_uses_cache(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    cache = ["--cache-dir", str(tmp_path / "cache"), "--out-dir", str(tmp_path / "out")]
    first, _ = invoke(capsys, "analyze", *DEMO, *ASTRONOMY, *cache)
    fetched = json.loads(Path(first["metrics_json"]).read_text(encoding="utf-8"))["cache"]
    second, _ = invoke(capsys, "analyze", *DEMO, *ASTRONOMY, *cache)
    reused = json.loads(Path(second["metrics_json"]).read_text(encoding="utf-8"))["cache"]
    assert fetched == {"hits": 0, "fetched": 12}
    assert reused == {"hits": 12, "fetched": 0}


def test_module_entry_point_keeps_stdout_clean(tmp_path: Path) -> None:
    env = {**os.environ, "MPLCONFIGDIR": str(tmp_path / "mpl")}
    done = subprocess.run(
        [sys.executable, "-m", "wikitrends", "resolve", *DEMO, "--topic", "Astronomy"],
        cwd=SKILL_DIR,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.count("\n") == 1
    assert json.loads(done.stdout)["ok"] is True


def test_fixture_can_be_pinned_by_environment(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.FIXTURE_ENV, "demo")
    payload, code = invoke(capsys, "resolve", "--topic", "Astronomy")
    assert code == 0
    assert payload["qid"] == "Q333"


def test_summary_names_editions_without_an_article() -> None:
    from datetime import date

    from wikitrends.analysis import rank
    from wikitrends.models import DateRange
    from wikitrends.output import summary
    from wikitrends.service import CompareRequest, RunResult

    request = CompareRequest(("it",), DateRange(date(2025, 1, 1), date(2025, 12, 31)), topic="X")
    run = RunResult(request, None, {}, ("it",), rank({}), (), 0, 0)
    assert summary(run) == "Over 365 days: it no article"


def test_line_fits_1kb_with_eight_languages_and_long_paths() -> None:
    from wikitrends.output import CAVEAT, to_line

    long = "/" + "x" * 200 + "/report.pdf"
    languages = [
        {
            "lang": f"l{i}",
            "title": "Ж" * 40,
            "verdict": "no_detectable_trend",
            "confidence": "medium",
            "mde_pct_per_year": 12.3,
            "vpm_median": 123.4,
            "reach_median": 4321,
            "flags": ["autocorrelated", "seasonality_suspected", "spike_events"],
        }
        for i in range(8)
    ]
    payload = {
        "ok": True,
        "schema": 1,
        "slug": "x" * 80,
        "report_pdf": long,
        "report_png": long,
        "charts": [long] * 3,
        "metrics_json": long,
        "data_csv": long,
        "summary": "s" * 200,
        "languages": languages,
        "tiers": [[f"l{i}"] for i in range(8)],
        "caveat": CAVEAT,
        "warnings": ["w" * 120] * 4,
        "cache": {"hits": 16, "fetched": 0},
    }
    line = to_line(payload)
    assert len(line.encode()) <= 1024
    decoded = json.loads(line)
    assert decoded["report_pdf"] == long
    assert [entry["verdict"] for entry in decoded["languages"]] == ["no_detectable_trend"] * 8
