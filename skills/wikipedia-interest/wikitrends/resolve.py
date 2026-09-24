"""Map a topic or user-typed titles to canonical articles per language."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from .api import WikidataEntity
from .cache import Clock, JsonStore, utc_now
from .errors import ResolveError
from .models import Article, Edition

LOOKUP_TTL = timedelta(days=30)


class TitleLookup(Protocol):
    def search(self, lang: str, query: str, limit: int = 3) -> list[str]: ...

    def canonical(self, lang: str, title: str) -> Article | None: ...


class EntityLookup(Protocol):
    def entity_for(self, dbname: str, title: str) -> WikidataEntity | None: ...


class EditionSource(Protocol):
    def wikipedia_editions(self) -> list[Edition]: ...


@dataclass(frozen=True, slots=True)
class Resolution:
    """Articles found per language; `missing` lists requested languages without one."""

    qid: str | None
    articles: dict[str, Article]
    missing: tuple[str, ...] = field(default=())


class EditionRegistry:
    """Open Wikipedia editions, used to validate languages and map them to dbnames."""

    def __init__(self, source: EditionSource, store: JsonStore, clock: Clock = utc_now) -> None:
        self._source = source
        self._store = store
        self._clock = clock
        self._by_lang: dict[str, str] | None = None

    def dbname(self, lang: str) -> str:
        editions = self._editions()
        if lang not in editions:
            raise ResolveError(
                f"unknown or closed Wikipedia edition: {lang!r}",
                "Use a language code as in <code>.wikipedia.org, e.g. uk, pl, cs.",
            )
        return editions[lang]

    def lang_for(self, dbname: str) -> str | None:
        return {db: lang for lang, db in self._editions().items()}.get(dbname)

    def _editions(self) -> dict[str, str]:
        editions = self._by_lang
        if editions is None:
            editions = self._store.get("sitematrix", LOOKUP_TTL, self._clock())
            if editions is None:
                editions = {e.lang: e.dbname for e in self._source.wikipedia_editions()}
                self._store.put("sitematrix", editions, self._clock())
            self._by_lang = editions
        return editions


class TopicResolver:
    """Resolves titles through search and Wikidata, never by trusting user casing."""

    def __init__(
        self,
        titles: TitleLookup,
        entities: EntityLookup,
        editions: EditionRegistry,
        store: JsonStore,
        clock: Clock = utc_now,
    ) -> None:
        self._titles = titles
        self._entities = entities
        self._editions = editions
        self._store = store
        self._clock = clock

    def resolve_topic(self, topic: str, source_lang: str, langs: Sequence[str] = ()) -> Resolution:
        """Search `topic` in `source_lang`, then follow Wikidata sitelinks to `langs`.

        With no `langs`, every edition that has the article is returned.
        """
        for lang in (source_lang, *langs):
            self._editions.dbname(lang)
        qid, sitelinks = self._lookup(topic, source_lang)
        available = {
            lang: Article(lang, title)
            for db, title in sitelinks.items()
            if (lang := self._editions.lang_for(db)) is not None
        }
        wanted = sorted(set(langs)) if langs else sorted(available)
        return Resolution(
            qid=qid,
            articles={lang: available[lang] for lang in wanted if lang in available},
            missing=tuple(lang for lang in wanted if lang not in available),
        )

    def resolve_titles(self, articles: Iterable[Article]) -> Resolution:
        """Canonicalize explicit titles: fix first-letter case and follow redirects."""
        found: dict[str, Article] = {}
        missing: list[str] = []
        for article in sorted(articles, key=lambda a: a.lang):
            self._editions.dbname(article.lang)
            canonical = self._titles.canonical(article.lang, article.title)
            if canonical is None:
                missing.append(article.lang)
            else:
                found[article.lang] = canonical
        return Resolution(qid=None, articles=found, missing=tuple(missing))

    def _lookup(self, topic: str, source_lang: str) -> tuple[str | None, dict[str, str]]:
        key = f"topic|{source_lang}|{topic.casefold().strip()}"
        cached = self._store.get(key, LOOKUP_TTL, self._clock())
        if cached is not None:
            return cached["qid"], cached["sitelinks"]
        hits = self._titles.search(source_lang, topic)
        if not hits:
            raise ResolveError(
                f"no {source_lang}.wikipedia article found for {topic!r}",
                "Rephrase the topic in the source language or pass explicit titles.",
            )
        source_db = self._editions.dbname(source_lang)
        entity = self._entities.entity_for(source_db, hits[0])
        if entity is None:
            qid, sitelinks = None, {source_db: hits[0]}
        else:
            qid, sitelinks = entity.qid, entity.sitelinks
        self._store.put(key, {"qid": qid, "sitelinks": sitelinks}, self._clock())
        return qid, sitelinks
