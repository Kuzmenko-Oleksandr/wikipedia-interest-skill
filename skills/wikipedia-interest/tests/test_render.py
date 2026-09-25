"""Rendering checks without visual diffing: glyphs, PDF structure, determinism, ink."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from matplotlib.image import imread
from pypdf import PdfReader

from tests import synthetic
from wikitrends import cli
from wikitrends.analysis import LanguageAnalyzer, rank
from wikitrends.models import Article
from wikitrends.render import MAX_COLOURS, palette, plt, save_charts, style
from wikitrends.report import ReportBuilder
from wikitrends.service import CompareRequest, RunResult

GLYPHS = "Вікіпедія Київ Ґ Ї Є Łódź Gdańsk źćęąśżń Řehoř Plzeň ůěščřž № — “”"
# One title per bundled font family, plus Arabic from DejaVu Sans.
WORLD = {
    "ar": "علم الفلك",
    "hi": "खगोल शास्त्र",
    "ja": "天文学",
    "ko": "천문학",
    "th": "ดาราศาสตร์",
    "zh": "天文學",
}
# No bundled font has Tibetan.
TIBETAN = "སྐར་རྩིས།"
A4_POINTS = (595, 842)
ARGS = [
    "compare",
    "--offline-fixture",
    "demo",
    "--topic",
    "Astronomy",
    "--langs",
    "uk,pl,cs",
    "--since",
    "2024-01-01",
]


def build(capsys: pytest.CaptureFixture[str], out: Path, question: str) -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*missing from font.*")
        code = cli.main([*ARGS, "--out-dir", str(out), "--question", question])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    return payload


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    out = tmp_path_factory.mktemp("report")
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*missing from font.*")
        payload, code = cli.run([*ARGS, "--out-dir", str(out), "--question", GLYPHS])
    assert code == 0, payload
    return payload


def test_missing_glyph_check_really_fires() -> None:
    with style(), warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*missing from font.*")
        fig = plt.figure()
        fig.text(0.5, 0.5, TIBETAN)
        with pytest.raises(UserWarning, match="missing from font"):
            fig.canvas.draw()
        plt.close(fig)


def test_titles_in_other_scripts_render_without_tofu(tmp_path: Path) -> None:
    # A live Haiku run drew Japanese and Chinese titles as empty boxes.
    titles = {**WORLD, "bo": TIBETAN}
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    results = {
        lang: LanguageAnalyzer().analyze(
            Article(lang, title), synthetic.series(synthetic.flat(seed=i)), total
        )
        for i, (lang, title) in enumerate(titles.items())
    }
    articles = tuple(Article(lang, title) for lang, title in titles.items())
    request = CompareRequest(tuple(sorted(titles)), total.span, titles=articles)
    run = RunResult(request, None, results, (), rank(results), (), 0, 0)
    metrics = {"conclusions": [], "warnings": [], "limitations": []}
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*missing from font.*")
        built = ReportBuilder().build(run, metrics, tmp_path)
    text = PdfReader(built.pdf).pages[0].extract_text()
    for title in ("天文学", "천문학", "天文學", "ดาราศาสตร์"):
        assert title in text
    assert "(see metrics.json)" in text


def test_report_is_one_a4_page_with_extractable_text(report: dict[str, Any]) -> None:
    pdf = PdfReader(report["report_pdf"])
    assert len(pdf.pages) == 1
    box = pdf.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == A4_POINTS
    assert "/CreationDate" not in (pdf.metadata or {})
    text = pdf.pages[0].extract_text()
    for word in ("Вікіпедія", "Łódź", "Řehoř", "limitations", "Астрономія"):
        assert word in text


def test_report_text_is_not_truncated_for_three_languages(report: dict[str, Any]) -> None:
    metrics_path = Path(report["report_pdf"]).parent / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["report_truncated"] is False


def test_rebuild_is_byte_identical(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    first = build(capsys, tmp_path / "a", "same question")
    second = build(capsys, tmp_path / "b", "same question")
    for key in ("report_pdf", "report_png"):
        if key in first and key in second:
            assert Path(first[key]).read_bytes() == Path(second[key]).read_bytes()
    charts_a = sorted((tmp_path / "a" / first["slug"]).glob("chart-*.png"))
    charts_b = sorted((tmp_path / "b" / second["slug"]).glob("chart-*.png"))
    assert [p.name for p in charts_a] == [
        "chart-normalized.png",
        "chart-ranking.png",
        "chart-timeseries.png",
    ]
    for a, b in zip(charts_a, charts_b, strict=True):
        assert a.read_bytes() == b.read_bytes()


def test_pngs_are_not_blank(report: dict[str, Any]) -> None:
    directory = Path(report["report_pdf"]).parent
    for path in [directory / "report.png", *directory.glob("chart-*.png")]:
        pixels = imread(path)[..., :3]
        grey = pixels.mean(axis=2)
        assert grey.std() * 255 > 10, path.name
        ink = float(np.mean(grey < 0.85))
        assert 0.02 < ink < 0.6, (path.name, ink)


def test_compare_contract_paths_exist(report: dict[str, Any]) -> None:
    assert len(report["summary"]) <= 200
    for key in ("report_pdf", "metrics_json", "report_png", "data_csv"):
        if key in report:
            path = Path(report[key])
            assert path.is_absolute()
            assert path.exists()
    assert "caveat" in report


def test_report_rebuilds_from_run(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    analyzed = cli.main(
        [
            "analyze",
            "--offline-fixture",
            "demo",
            "--topic",
            "Astronomy",
            "--langs",
            "uk,pl",
            "--out-dir",
            str(tmp_path),
        ]
    )
    slug = json.loads(capsys.readouterr().out)["slug"]
    assert analyzed == 0
    code = cli.main(
        ["report", "--offline-fixture", "demo", "--from-run", slug, "--out-dir", str(tmp_path)]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["slug"] == slug
    assert Path(payload["report_pdf"]).exists()


def test_more_than_eight_languages_use_small_multiples(tmp_path: Path) -> None:
    langs = [f"l{i}" for i in range(MAX_COLOURS + 1)]
    assert len(set(palette(langs).values())) == 1
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    results = {
        lang: LanguageAnalyzer().analyze(
            Article(lang, "X"), synthetic.series(synthetic.flat(seed=i)), total
        )
        for i, lang in enumerate(langs)
    }
    request = CompareRequest(tuple(langs), total.span, topic="X")
    run = RunResult(request, None, results, (), rank(results), (), 0, 0)
    paths = save_charts(run, tmp_path)
    assert all(path.stat().st_size > 10_000 for path in paths)
