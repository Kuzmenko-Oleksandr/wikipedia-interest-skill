"""End-to-end run: resolve, fetch, analyze. No rendering and no printing."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from .analysis import LanguageAnalyzer, LanguageResult, Ranking, rank
from .cache import CachedPageviews
from .errors import WikitrendsError
from .models import Article, DateRange
from .resolve import Resolution, TopicResolver
from .series import DailySeries

log = logging.getLogger(__name__)

MAX_REDIRECTS = 10
NO_TITLES: frozenset[str] = frozenset()
SLUG_TITLE_CHARS = 40

_CYRILLIC = (
    "а a б b в v г h ґ g д d е e є ie ж zh з z и y і i ї i й i к k л l м m н n о o п p "  # noqa: RUF001
    "р r с s т t у u ф f х kh ц ts ч ch ш sh щ shch ь - ю iu я ia ы y э e ё e ъ -"  # noqa: RUF001
)
_TRANSLIT = str.maketrans(
    {
        **{
            src: "" if dst == "-" else dst
            for src, dst in zip(*[iter(_CYRILLIC.split())] * 2, strict=True)
        },
        "ł": "l",
        "ø": "o",
        "ß": "ss",
        "đ": "d",
        "æ": "ae",
        "œ": "oe",
    }
)


def slugify(text: str) -> str:
    """Lowercase ASCII words joined by hyphens; Cyrillic is transliterated."""
    folded = unicodedata.normalize("NFKD", text.casefold().translate(_TRANSLIT))
    ascii_text = folded.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug[:SLUG_TITLE_CHARS].rstrip("-") or "topic"


class UsageError(WikitrendsError):
    """The request itself is malformed."""


@dataclass(frozen=True, slots=True)
class CompareRequest:
    """What to analyze; the slug is derived from it, never from the clock."""

    langs: tuple[str, ...]
    span: DateRange
    topic: str | None = None
    titles: tuple[Article, ...] = field(default=())
    source_lang: str = "en"
    include_redirects: bool = False

    def __post_init__(self) -> None:
        if (self.topic is None) == (not self.titles):
            raise UsageError(
                "pass exactly one of --topic or --titles", "Example: --topic Astronomy"
            )
        if not self.langs:
            raise UsageError(
                "no languages given",
                "Pass --langs uk,pl or run `resolve --topic X` to list available editions.",
            )

    @property
    def subject(self) -> str:
        """The topic, else the source-language title, else the first title by language."""
        if self.topic:
            return self.topic
        titles = {a.lang: a.title for a in self.titles}
        return titles.get(self.source_lang) or titles[min(titles)]

    @property
    def slug(self) -> str:
        span = f"{self.span.start:%Y%m%d}-{self.span.end:%Y%m%d}"
        return f"{'-'.join(self.langs)}_{slugify(self.subject)}_{span}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "langs": list(self.langs),
            "since": self.span.start.isoformat(),
            "until": self.span.end.isoformat(),
            "topic": self.topic,
            "titles": [f"{a.lang}:{a.title}" for a in self.titles],
            "source_lang": self.source_lang,
            "include_redirects": self.include_redirects,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompareRequest:
        return cls(
            langs=tuple(data["langs"]),
            span=DateRange(date.fromisoformat(data["since"]), date.fromisoformat(data["until"])),
            topic=data.get("topic"),
            titles=tuple(parse_titles(",".join(data.get("titles", [])))),
            source_lang=data.get("source_lang", "en"),
            include_redirects=bool(data.get("include_redirects")),
        )


def parse_titles(text: str) -> list[Article]:
    """`uk:Астрономія,pl:Astronomia` to articles; titles may contain commas only if quoted out."""
    articles = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        lang, sep, title = part.partition(":")
        if not sep or not lang or not title:
            raise UsageError(f"bad title spec {part!r}", "Use lang:Title, e.g. uk:Астрономія")
        articles.append(Article(lang.strip(), title.strip()))
    return articles


@dataclass(frozen=True, slots=True, eq=False)
class RunResult:
    request: CompareRequest
    qid: str | None
    results: dict[str, LanguageResult]
    missing: tuple[str, ...]
    ranking: Ranking
    warnings: tuple[str, ...]
    cache_hits: int
    cache_fetched: int

    @property
    def ordered(self) -> list[LanguageResult]:
        return [self.results[lang] for lang in sorted(self.results)]


class PageLookup(Protocol):
    def canonical(self, lang: str, title: str) -> Article | None: ...

    def redirects_to(self, article: Article) -> list[str]: ...


class InterestService:
    """Composes resolver, cached pageviews and analysis; network access happens here."""

    def __init__(
        self,
        resolver: TopicResolver,
        pageviews: CachedPageviews,
        pages: PageLookup,
        analyzer: LanguageAnalyzer | None = None,
    ) -> None:
        self._resolver = resolver
        self._pageviews = pageviews
        self._pages = pages
        self._analyzer = analyzer or LanguageAnalyzer()

    def resolve(self, request: CompareRequest) -> Resolution:
        if request.titles:
            return self._resolver.resolve_titles(request.titles)
        assert request.topic is not None
        return self._resolver.resolve_topic(request.topic, request.source_lang, request.langs)

    def fetch(self, request: CompareRequest) -> tuple[Resolution, dict[str, DailySeries]]:
        """Warms the cache; returns the article series per language."""
        resolution = self.resolve(request)
        warnings: list[str] = []
        views = {}
        for lang, article in sorted(resolution.articles.items()):
            views[lang], _ = self._views(article, request, warnings)
            self._total(lang, request.span)
        return resolution, views

    def run(self, request: CompareRequest, notices: Sequence[str] = ()) -> RunResult:
        resolution = self.resolve(request)
        warnings = list(notices)
        results = {
            lang: self._analyze(article, request, warnings)
            for lang, article in sorted(resolution.articles.items())
        }
        for lang in resolution.missing:
            warnings.append(f"{lang}: no article on this topic in that edition.")
        return RunResult(
            request=request,
            qid=resolution.qid,
            results=results,
            missing=resolution.missing,
            ranking=rank(results),
            warnings=tuple(warnings),
            cache_hits=self._pageviews.hits,
            cache_fetched=self._pageviews.fetched,
        )

    def _analyze(
        self, article: Article, request: CompareRequest, warnings: list[str]
    ) -> LanguageResult:
        total = self._total(article.lang, request.span)
        views, summed = self._views(article, request, warnings)
        result = self._analyzer.analyze(article, views, total)
        if any(f.gate == "G7_end_collapse" for f in result.gates.findings):
            moved = self._pages.canonical(article.lang, article.title)
            if moved is not None and moved.title != article.title:
                # Old-title views before the move plus new-title views after it.
                warnings.append(
                    f"{article.lang}: {article.title!r} was renamed to {moved.title!r}; "
                    "both titles were combined."
                )
                # The old title is now a redirect of the new one; never count it twice.
                extra, _ = self._views(moved, request, warnings, exclude=summed)
                result = self._analyzer.analyze(moved, views.plus(extra), total)
        return result

    def _total(self, lang: str, span: DateRange) -> DailySeries:
        counts = self._pageviews.project_daily(lang, span)
        return DailySeries.from_counts(counts, span, self._pageviews.traffic)

    def _views(
        self,
        article: Article,
        request: CompareRequest,
        warnings: list[str],
        exclude: frozenset[str] = NO_TITLES,
    ) -> tuple[DailySeries, frozenset[str]]:
        """Views of the article, plus its redirects if asked; also the titles summed."""
        titles = [article.title]
        if request.include_redirects:
            redirects = self._pages.redirects_to(article)
            if len(redirects) > MAX_REDIRECTS:
                warnings.append(
                    f"{article.lang}: summed {MAX_REDIRECTS} of {len(redirects)} redirects "
                    "to stay within the rate limit."
                )
            titles += redirects[:MAX_REDIRECTS]
        titles = [title for title in titles if title not in exclude]
        series = DailySeries.from_counts({}, request.span, self._pageviews.traffic)
        for title in titles:
            series = series.plus(self._series(Article(article.lang, title), request.span))
        return series, frozenset(titles) | exclude

    def _series(self, article: Article, span: DateRange) -> DailySeries:
        counts = self._pageviews.article_daily(article, span)
        return DailySeries.from_counts(counts, span, self._pageviews.traffic)
