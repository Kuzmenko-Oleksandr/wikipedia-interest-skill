from __future__ import annotations

from dataclasses import replace

import numpy as np

from tests import synthetic
from wikitrends import narrative
from wikitrends.analysis import Interval, LanguageAnalyzer, LanguageResult, rank
from wikitrends.models import Article


def result(lang: str, level: float, edition: float = 5e6) -> LanguageResult:
    views = synthetic.series(synthetic.flat(seed=len(lang) + ord(lang[0])) * level / 200)
    total = synthetic.series(np.full(synthetic.DAYS, edition))
    return LanguageAnalyzer().analyze(Article(lang, "X"), views, total)


def test_rank_by_penetration_and_tier_overlaps() -> None:
    results = {"uk": result("uk", 400), "pl": result("pl", 402), "cs": result("cs", 100)}
    ranking = rank(results)
    assert ranking.tiers == (("pl", "uk"), ("cs",))
    assert ranking.unranked == ()


def test_penetration_not_reach_decides_the_order() -> None:
    results = {"en": result("en", 4000, edition=250e6), "uk": result("uk", 400)}
    assert rank(results).order == ("uk", "en")


def test_refused_language_is_listed_apart_not_last() -> None:
    results = {"uk": result("uk", 400), "cs": result("cs", 5)}
    ranking = rank(results)
    assert ranking.order == ("uk",)
    assert ranking.unranked == ("cs",)
    sentences = narrative.comparison_sentences(results, ranking)
    assert any("not the same as low interest" in s for s in sentences)


def test_ties_on_penetration_break_on_reach() -> None:
    base = result("uk", 400)
    same = Interval(10.0, 9.0, 11.0)
    small = replace(base, penetration=same, reach=Interval(100.0, 90.0, 110.0))
    big = replace(base, article=Article("pl", "X"), penetration=same, reach=Interval(900, 1, 999))
    assert rank({"uk": small, "pl": big}).order == ("pl", "uk")


def test_interval_overlap() -> None:
    assert Interval(5, 4, 6).overlaps(Interval(7, 6, 8))
    assert not Interval(5, 4, 6).overlaps(Interval(8, 7, 9))
