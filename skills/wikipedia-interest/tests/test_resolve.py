# pyright: reportUnusedParameter=false
# Fakes keep the protocol signatures even when they ignore an argument.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wikitrends.api import WikidataEntity
from wikitrends.cache import CacheDatabase, JsonStore
from wikitrends.errors import ResolveError
from wikitrends.models import Article, Edition
from wikitrends.resolve import EditionRegistry, TopicResolver

NOW = datetime(2026, 9, 24, tzinfo=UTC)
EDITIONS = [
    Edition("uk", "ukwiki"),
    Edition("pl", "plwiki"),
    Edition("cs", "cswiki"),
    Edition("en", "enwiki"),
]


class FakeEditions:
    def __init__(self) -> None:
        self.calls = 0

    def wikipedia_editions(self) -> list[Edition]:
        self.calls += 1
        return EDITIONS


class FakeTitles:
    def __init__(self) -> None:
        self.searches = 0

    def search(self, lang: str, query: str, limit: int = 3) -> list[str]:
        self.searches += 1
        return ["Інтервальне голодування"] if "голод" in query else []

    def canonical(self, lang: str, title: str) -> Article | None:
        if title == "missing":
            return None
        return Article(lang, title[:1].upper() + title[1:])


class FakeEntities:
    def entity_for(self, dbname: str, title: str) -> WikidataEntity | None:
        return WikidataEntity(
            "Q1",
            {
                "ukwiki": title,
                "plwiki": "Post przerywany",
                "enwiki": "Intermittent fasting",
                "commonswiki": "Category:Fasting",
            },
        )


def make() -> tuple[TopicResolver, FakeTitles, FakeEditions]:
    store = JsonStore(CacheDatabase())
    titles, editions = FakeTitles(), FakeEditions()
    clock = lambda: NOW  # noqa: E731
    registry = EditionRegistry(editions, store, clock)
    return TopicResolver(titles, FakeEntities(), registry, store, clock), titles, editions


def test_topic_maps_to_requested_langs_and_reports_missing() -> None:
    resolver, _, _ = make()
    result = resolver.resolve_topic("інтервальне голодування", "uk", ["pl", "cs"])
    assert result.qid == "Q1"
    assert result.articles == {"pl": Article("pl", "Post przerywany")}
    assert result.missing == ("cs",)


def test_no_langs_returns_all_wikipedias_and_drops_non_wikipedia_sites() -> None:
    resolver, _, _ = make()
    result = resolver.resolve_topic("голодування", "uk")
    assert sorted(result.articles) == ["en", "pl", "uk"]


def test_repeat_lookup_is_cached() -> None:
    resolver, titles, editions = make()
    resolver.resolve_topic("голодування", "uk", ["pl"])
    resolver.resolve_topic("  Голодування ", "uk", ["en"])
    assert titles.searches == 1
    assert editions.calls == 1


def test_unknown_language_is_rejected_with_hint() -> None:
    resolver, _, _ = make()
    with pytest.raises(ResolveError) as exc:
        resolver.resolve_topic("голодування", "uk", ["xx"])
    assert "language code" in exc.value.hint


def test_no_search_hit_raises() -> None:
    resolver, _, _ = make()
    with pytest.raises(ResolveError):
        resolver.resolve_topic("zzz", "uk")


def test_explicit_titles_are_canonicalized() -> None:
    resolver, _, _ = make()
    result = resolver.resolve_titles([Article("pl", "astronomia"), Article("cs", "missing")])
    assert result.articles == {"pl": Article("pl", "Astronomia")}
    assert result.missing == ("cs",)
