"""Thin typed clients over Wikimedia endpoints; no caching, no policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from .errors import NoDataError
from .models import Article, DailyCounts, DateRange, Edition, TrafficFilter
from .transport import JsonTransport

PAGEVIEWS_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
WIKIDATA_URL = "https://www.wikidata.org/w/api.php"
SITEMATRIX_URL = "https://meta.wikimedia.org/w/api.php"


def _api_day(day: date) -> str:
    return day.strftime("%Y%m%d")


def _parse_day(timestamp: str) -> date:
    # Timestamps are YYYYMMDDHH; the hour is always a 00 placeholder.
    return datetime.strptime(timestamp[:8], "%Y%m%d").date()


class PageviewsApi:
    """Daily per-article and per-project pageviews."""

    def __init__(self, transport: JsonTransport, traffic: TrafficFilter | None = None) -> None:
        self._transport = transport
        self.traffic = traffic or TrafficFilter()

    def article_daily(self, article: Article, span: DateRange) -> DailyCounts:
        # safe="" encodes "/" as %2F, which the API requires.
        title = quote(article.api_title, safe="")
        url = (
            f"{PAGEVIEWS_URL}/per-article/{article.project}/{self.traffic.key}"
            f"/{title}/daily/{_api_day(span.start)}/{_api_day(span.end)}"
        )
        return self._fetch(url)

    def project_daily(self, lang: str, span: DateRange) -> DailyCounts:
        url = (
            f"{PAGEVIEWS_URL}/aggregate/{lang}.wikipedia/{self.traffic.key}"
            f"/daily/{_api_day(span.start)}/{_api_day(span.end)}"
        )
        return self._fetch(url)

    def _fetch(self, url: str) -> DailyCounts:
        try:
            payload = self._transport.get_json(url)
        except NoDataError:
            # 404 means "no data in range"; existence is checked by the resolver.
            return {}
        return {_parse_day(item["timestamp"]): int(item["views"]) for item in payload["items"]}


class ActionApi:
    """MediaWiki Action API of a single language edition."""

    def __init__(self, transport: JsonTransport) -> None:
        self._transport = transport

    def search(self, lang: str, query: str, limit: int = 3) -> list[str]:
        data = self._query(
            lang,
            {"list": "search", "srsearch": query, "srnamespace": "0", "srlimit": str(limit)},
        )
        return [hit["title"] for hit in data["query"]["search"]]

    def canonical(self, lang: str, title: str) -> Article | None:
        """Fix first-letter case and follow redirects; None if the page is missing."""
        data = self._query(lang, {"titles": title, "redirects": "1"})
        page = data["query"]["pages"][0]
        if page.get("missing") or page.get("invalid"):
            return None
        return Article(lang, page["title"])

    def redirects_to(self, article: Article) -> list[str]:
        data = self._query(
            article.lang,
            {"titles": article.title, "prop": "redirects", "rdnamespace": "0", "rdlimit": "500"},
        )
        page = data["query"]["pages"][0]
        return [r["title"] for r in page.get("redirects", [])]

    def _query(self, lang: str, params: dict[str, str]) -> Any:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        return self._transport.get_json(
            url, {"action": "query", "format": "json", "formatversion": "2", **params}
        )


@dataclass(frozen=True, slots=True)
class WikidataEntity:
    qid: str
    sitelinks: dict[str, str]  # dbname -> title


class WikidataApi:
    """Cross-language title mapping through Wikidata sitelinks."""

    def __init__(self, transport: JsonTransport) -> None:
        self._transport = transport

    def entity_for(self, dbname: str, title: str) -> WikidataEntity | None:
        data = self._transport.get_json(
            WIKIDATA_URL,
            {
                "action": "wbgetentities",
                "sites": dbname,
                "titles": title,
                "props": "sitelinks",
                "normalize": "1",
                "format": "json",
            },
        )
        # Keyed by an unknown Q-id, so iterate values.
        for qid, entity in data.get("entities", {}).items():
            if "missing" in entity:
                continue
            links = {site: link["title"] for site, link in entity.get("sitelinks", {}).items()}
            return WikidataEntity(qid, links)
        return None


class SiteMatrixApi:
    """List of open Wikipedia language editions."""

    def __init__(self, transport: JsonTransport) -> None:
        self._transport = transport

    def wikipedia_editions(self) -> list[Edition]:
        data = self._transport.get_json(
            SITEMATRIX_URL,
            {"action": "sitematrix", "smtype": "language", "format": "json", "formatversion": "2"},
        )
        editions = []
        for key, group in data["sitematrix"].items():
            if key in ("count", "specials"):
                continue
            for site in group.get("site", []):
                if site.get("code") != "wiki" or site.get("closed"):
                    continue
                lang = site["url"].removeprefix("https://").split(".")[0]
                editions.append(Edition(lang, site["dbname"]))
        return sorted(editions, key=lambda e: e.lang)
