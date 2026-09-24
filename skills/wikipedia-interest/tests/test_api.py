from __future__ import annotations

from datetime import date
from typing import Any

from wikitrends.api import PageviewsApi, SiteMatrixApi, WikidataApi
from wikitrends.errors import NoDataError
from wikitrends.models import Article, DateRange

SPAN = DateRange(date(2025, 1, 1), date(2025, 1, 3))


class RecordingTransport:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.urls: list[str] = []
        self.params: list[Any] = []

    def get_json(self, url: str, params: Any = None) -> Any:
        self.urls.append(url)
        self.params.append(params)
        if self.error:
            raise self.error
        return self.payload


def test_article_url_encodes_slash_and_unicode() -> None:
    transport = RecordingTransport({"items": []})
    PageviewsApi(transport).article_daily(Article("uk", "AC/DC Київ"), SPAN)
    assert transport.urls[0].endswith(
        "/per-article/uk.wikipedia/all-access/user/AC%2FDC_%D0%9A%D0%B8%D1%97%D0%B2"
        "/daily/20250101/20250103"
    )


def test_parses_timestamps_and_keeps_gaps() -> None:
    items = [{"timestamp": "2025010100", "views": 5}, {"timestamp": "2025010300", "views": 0}]
    counts = PageviewsApi(RecordingTransport({"items": items})).project_daily("pl", SPAN)
    assert counts == {date(2025, 1, 1): 5, date(2025, 1, 3): 0}


def test_404_means_empty_series() -> None:
    api = PageviewsApi(RecordingTransport(error=NoDataError("x")))
    assert api.article_daily(Article("cs", "X"), SPAN) == {}


def test_wikidata_entity_iterates_unknown_qid() -> None:
    payload = {"entities": {"Q333": {"sitelinks": {"ukwiki": {"title": "Астрономія"}}}}}
    entity = WikidataApi(RecordingTransport(payload)).entity_for("ukwiki", "Астрономія")
    assert entity is not None
    assert (entity.qid, entity.sitelinks) == ("Q333", {"ukwiki": "Астрономія"})


def test_wikidata_missing_entity() -> None:
    payload = {"entities": {"-1": {"missing": ""}}}
    assert WikidataApi(RecordingTransport(payload)).entity_for("ukwiki", "Nope") is None


def test_sitematrix_skips_closed_and_non_wikipedia() -> None:
    payload = {
        "sitematrix": {
            "count": 3,
            "0": {
                "code": "aa",
                "site": [
                    {
                        "url": "https://aa.wikipedia.org",
                        "dbname": "aawiki",
                        "code": "wiki",
                        "closed": True,
                    }
                ],
            },
            "1": {
                "code": "be-tarask",
                "site": [
                    {
                        "url": "https://be-tarask.wikipedia.org",
                        "dbname": "be_x_oldwiki",
                        "code": "wiki",
                    },
                    {
                        "url": "https://be-tarask.wiktionary.org",
                        "dbname": "x",
                        "code": "wiktionary",
                    },
                ],
            },
            "specials": [],
        }
    }
    editions = SiteMatrixApi(RecordingTransport(payload)).wikipedia_editions()
    assert [(e.lang, e.dbname) for e in editions] == [("be-tarask", "be_x_oldwiki")]
