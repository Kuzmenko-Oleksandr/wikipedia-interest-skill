# pyright: reportUnusedParameter=false
# Fakes keep the protocol signatures even when they ignore an argument.
"""One test per defect found by the independent code review."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from pypdf import PdfReader

from tests import synthetic
from wikitrends import cli, narrative
from wikitrends.analysis import LanguageAnalyzer, rank
from wikitrends.api import WikidataEntity
from wikitrends.artifacts import ArtifactWriter
from wikitrends.cache import CacheDatabase, CachedPageviews, JsonStore, PageviewStore
from wikitrends.errors import WikitrendsError
from wikitrends.models import Article, DailyCounts, DateRange, Edition, TrafficFilter
from wikitrends.output import error_payload, to_line
from wikitrends.report import ReportBuilder
from wikitrends.resolve import EditionRegistry, TopicResolver
from wikitrends.service import CompareRequest, InterestService, RunResult
from wikitrends.stats import MannKendall, Slope, TrendFit
from wikitrends.verdict import Verdict

SPAN = DateRange(date(2024, 1, 1), date(2026, 3, 1))
MOVE = date(2026, 2, 10)


class RenamedSource:
    """500 views/day on "Old" until MOVE; then "New" gets 497 and the redirect keeps 3."""

    traffic = TrafficFilter()

    def article_daily(self, article: Article, span: DateRange) -> DailyCounts:
        if article.title == "Old":
            return {day: 500 if day < MOVE else 3 for day in span.dates()}
        if article.title == "New":
            return {day: 497 for day in span.dates() if day >= MOVE}
        return {}

    def project_daily(self, lang: str, span: DateRange) -> DailyCounts:
        return dict.fromkeys(span.dates(), 5_000_000)


class StalePages:
    """The first lookup still sees the old title, as a 30-day cache would."""

    def __init__(self) -> None:
        self.calls = 0

    def search(self, lang: str, query: str, limit: int = 3) -> list[str]:
        return ["Old"]

    def canonical(self, lang: str, title: str) -> Article | None:
        self.calls += 1
        return Article(lang, "Old" if self.calls == 1 else "New")

    def redirects_to(self, article: Article) -> list[str]:
        return ["Old"] if article.title == "New" else []


class Editions:
    def wikipedia_editions(self) -> list[Edition]:
        return [Edition("uk", "ukwiki")]


class NoEntity:
    def entity_for(self, dbname: str, title: str) -> WikidataEntity | None:
        return None


def test_rename_with_redirects_counts_the_old_title_once() -> None:
    db = CacheDatabase()
    store = JsonStore(db)
    pages = StalePages()
    clock = lambda: datetime(2026, 3, 10, tzinfo=UTC)  # noqa: E731
    resolver = TopicResolver(pages, NoEntity(), EditionRegistry(Editions(), store, clock), store)
    pageviews = CachedPageviews(RenamedSource(), PageviewStore(db), clock)
    service = InterestService(resolver, pageviews, pages)
    request = CompareRequest(("uk",), SPAN, titles=(Article("uk", "Old"),), include_redirects=True)
    run = service.run(request)
    result = run.results["uk"]
    assert result.article.title == "New"
    assert np.nanmedian(result.views.values) == 500
    assert not result.assessment.level_shift
    assert any("renamed" in w for w in run.warnings)


def test_step_size_is_withheld_under_low_volume() -> None:
    values = synthetic.with_step(synthetic.flat(), 400, 1.8) / 8
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    result = LanguageAnalyzer().analyze(Article("uk", "X"), synthetic.series(values), total)
    a = result.assessment
    assert a.level_shift
    assert "direction_only" in a.flags
    assert a.step_ratio is None
    sentence = narrative.language_sentence(result)
    assert "%" not in sentence
    assert "800-day window" in sentence


def test_step_sentence_names_the_window() -> None:
    values = synthetic.with_step(synthetic.flat(), 400, 1.6)
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    result = LanguageAnalyzer().analyze(Article("uk", "X"), synthetic.series(values), total)
    sentence = narrative.language_sentence(result)
    assert re.search(r"~6\d%", sentence)
    assert "800-day window" in sentence


def test_direction_falls_back_to_mann_kendall_when_the_slope_ties_at_zero() -> None:
    flat = Slope(0.0, 0.0, 0.0, 0.01)
    fit = TrendFit(53, flat, flat, MannKendall(612, 1.0, 5.0, 1e-8), 20.0)
    assert fit.direction == 1


def test_error_line_keeps_error_and_hint_and_fits() -> None:
    payload = error_payload(WikitrendsError("x" * 3000, "Ж" * 3000))
    line = to_line(payload)
    decoded = json.loads(line)
    assert len(line.encode()) <= 1024
    assert decoded["error"].startswith("xxx")
    assert decoded["hint"].startswith("ЖЖЖ")


def test_success_line_fits_even_with_absurd_paths() -> None:
    long = "/" + "p" * 700 + "/report.pdf"
    languages = [{"lang": f"l{i}", "verdict": "stable"} for i in range(8)]
    payload = {"ok": True, "schema": 1, "slug": "s", "report_pdf": long, "metrics_json": long}
    payload |= {"summary": "x" * 200, "languages": languages}
    assert len(to_line(payload).encode()) <= 1024


def test_zero_edition_totals_suppress_the_share_openly() -> None:
    total = synthetic.series(np.zeros(synthetic.DAYS))
    views = synthetic.series(synthetic.growth(30.0))
    a = LanguageAnalyzer().analyze(Article("uk", "X"), views, total).assessment
    assert "vpm_suppressed" in a.flags
    assert str(a.basis) == "raw_views"


def test_cache_path_is_absolute(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["cache", "--status", "--cache-dir", "relcache"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["path"]).is_absolute()


def test_report_with_fourteen_languages_stays_one_page(tmp_path: Path) -> None:
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    langs = [f"l{i:02d}" for i in range(13)]
    results = {
        lang: LanguageAnalyzer().analyze(
            Article(lang, "X"), synthetic.series(synthetic.flat(seed=i)), total
        )
        for i, lang in enumerate(langs)
    }
    request = CompareRequest((*langs, "zz"), total.span, topic="X")
    run = RunResult(request, None, results, ("zz",), rank(results), (), 0, 0)
    metrics = {
        "conclusions": [narrative.language_sentence(r) for r in run.ordered],
        "warnings": [],
        "limitations": list(narrative.limitations()),
    }
    built = ReportBuilder().build(run, metrics, tmp_path)
    assert len(PdfReader(built.pdf).pages) == 1


def test_small_multiples_keep_their_panel_labels(tmp_path: Path) -> None:
    from wikitrends.render import draw_timeseries, plt, style

    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    langs = [f"l{i}" for i in range(9)]
    results = {
        lang: LanguageAnalyzer().analyze(
            Article(lang, "X"), synthetic.series(synthetic.flat(seed=i)), total
        )
        for i, lang in enumerate(langs)
    }
    request = CompareRequest(tuple(langs), total.span, topic="X")
    run = RunResult(request, None, results, (), rank(results), (), 0, 0)
    with style():
        fig = plt.figure(figsize=(8, 6))
        draw_timeseries(fig, fig.add_gridspec(1, 1)[0], run)
        assert [ax.get_title(loc="left") for ax in fig.axes] == langs
        plt.close(fig)


def test_step_day_is_the_first_day_at_the_new_level() -> None:
    values = synthetic.with_step(synthetic.flat(), 400, 1.6)
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    result = LanguageAnalyzer().analyze(Article("uk", "X"), synthetic.series(values), total)
    headline = result.assessment.headline
    assert headline is not None
    step_day = result.views.day(headline.step.day)
    assert abs(step_day - (synthetic.START + timedelta(days=400))) <= timedelta(days=4)
    assert result.assessment.verdict is Verdict.LEVEL_SHIFT_UP


def test_titles_run_is_named_after_the_source_language() -> None:
    # A live run with --titles de:...,en:... was saved and titled as "englische-sprache".
    titles = (Article("de", "Englische Sprache"), Article("en", "English language"))
    request = CompareRequest(("de", "en"), SPAN, titles=titles)
    assert request.subject == "English language"
    assert "_english-language_" in request.slug
    assert "_englische-sprache_" in replace(request, source_lang="de").slug


def test_long_report_title_is_cut_to_the_page_width(tmp_path: Path) -> None:
    # Thirty languages ran the title off the right edge of the page.
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    langs = tuple(f"l{i:02d}" for i in range(30))
    request = CompareRequest(langs, total.span, topic="Astronomy")
    run = RunResult(request, None, {}, langs, rank({}), (), 0, 0)
    metrics = {"conclusions": [], "warnings": [], "limitations": []}
    built = ReportBuilder().build(run, metrics, tmp_path)
    first = PdfReader(built.pdf).pages[0].extract_text().splitlines()[0]
    assert first.startswith("Wikipedia interest: Astronomy (l00, l01")
    assert first.endswith("…")


def test_decline_is_worded_without_a_double_sign() -> None:
    # "fell ~-12%/yr" read as a rise to a live Haiku run.
    total = synthetic.series(np.full(synthetic.DAYS, 5e6))
    values = synthetic.growth(-30.0)
    result = LanguageAnalyzer().analyze(Article("uk", "X"), synthetic.series(values), total)
    assert result.assessment.verdict is Verdict.DECLINING
    assert re.search(r"fell ~\d+%/yr", narrative.language_sentence(result))


class LargeEditions:
    def wikipedia_editions(self) -> list[Edition]:
        return [Edition(lang, f"{lang}wiki") for lang in cli.LARGE_EDITIONS]


class LongTitles:
    def entity_for(self, dbname: str, title: str) -> WikidataEntity | None:
        title = "Intermittent fasting and time-restricted eating"
        return WikidataEntity("Q1", {f"{lang}wiki": title for lang in cli.LARGE_EDITIONS})


def test_resolve_keeps_the_largest_editions_when_twenty_titles_do_not_fit(tmp_path: Path) -> None:
    # A live resolve of 20 long titles printed {"ok":true,"schema":1,"languages":[]}.
    db = CacheDatabase()
    store = JsonStore(db)
    clock = lambda: datetime(2026, 3, 10, tzinfo=UTC)  # noqa: E731
    pages = StalePages()
    registry = EditionRegistry(LargeEditions(), store, clock)
    resolver = TopicResolver(pages, LongTitles(), registry, store)
    pageviews = CachedPageviews(RenamedSource(), PageviewStore(db), clock)
    service = InterestService(resolver, pageviews, pages)
    ctx = cli.Context(
        service, resolver, PageviewStore(db), ArtifactWriter(tmp_path), None, date(2026, 3, 10), ()
    )
    args = argparse.Namespace(topic="Intermittent fasting", source_lang=None, langs=None)
    line = to_line(cli.cmd_resolve(args, ctx))
    payload = json.loads(line)
    assert len(line.encode()) <= 1024
    assert payload["qid"] == "Q1"
    assert payload["available_count"] == len(cli.LARGE_EDITIONS)
    assert 1 < len(payload["titles"]) < cli.SUGGESTED_LIMIT
    assert list(payload["titles"])[:2] == ["en", "ja"]
    assert payload["titles_arg"].split(",") == [
        f"{lang}:{title}" for lang, title in payload["titles"].items()
    ]
