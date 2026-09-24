from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from wikitrends.cache import CacheDatabase, CachedPageviews, PageviewStore
from wikitrends.models import Article, DailyCounts, DateRange, TrafficFilter

ARTICLE = Article("uk", "Астрономія")


class FakeSource:
    traffic = TrafficFilter()

    def __init__(self) -> None:
        self.requests: list[DateRange] = []

    def article_daily(self, article: Article, span: DateRange) -> DailyCounts:
        self.requests.append(span)
        return {day: 100 for day in span.dates()}

    def project_daily(self, lang: str, span: DateRange) -> DailyCounts:
        self.requests.append(span)
        return {day: 10**6 for day in span.dates()}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make(now: datetime) -> tuple[CachedPageviews, FakeSource, Clock]:
    source, clock = FakeSource(), Clock(now)
    return CachedPageviews(source, PageviewStore(CacheDatabase()), clock), source, clock


def test_second_call_hits_cache() -> None:
    cached, source, _ = make(datetime(2025, 6, 1, tzinfo=UTC))
    span = DateRange(date(2025, 1, 1), date(2025, 3, 31))
    first = cached.article_daily(ARTICLE, span)
    assert cached.article_daily(ARTICLE, span) == first
    assert len(source.requests) == 1
    assert (cached.fetched, cached.hits) == (1, 1)


def test_extension_fetches_only_the_gap() -> None:
    cached, source, _ = make(datetime(2025, 6, 1, tzinfo=UTC))
    cached.article_daily(ARTICLE, DateRange(date(2025, 1, 1), date(2025, 1, 31)))
    cached.article_daily(ARTICLE, DateRange(date(2025, 1, 1), date(2025, 2, 28)))
    assert source.requests[-1] == DateRange(date(2025, 2, 1), date(2025, 2, 28))


def test_unsettled_tail_is_refetched_after_a_day() -> None:
    cached, source, clock = make(datetime(2025, 3, 5, tzinfo=UTC))
    span = DateRange(date(2025, 2, 1), date(2025, 3, 4))
    cached.article_daily(ARTICLE, span)
    clock.now += timedelta(hours=2)
    cached.article_daily(ARTICLE, span)
    assert len(source.requests) == 1
    clock.now += timedelta(days=1)
    cached.article_daily(ARTICLE, span)
    assert source.requests[-1] == DateRange(date(2025, 3, 3), date(2025, 3, 4))


def test_numerator_and_denominator_do_not_collide() -> None:
    cached, _, _ = make(datetime(2025, 6, 1, tzinfo=UTC))
    span = DateRange(date(2025, 1, 1), date(2025, 1, 2))
    assert set(cached.article_daily(ARTICLE, span).values()) == {100}
    assert set(cached.project_daily("uk", span).values()) == {10**6}
