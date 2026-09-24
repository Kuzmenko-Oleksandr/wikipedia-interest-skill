from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from wikitrends.api import ActionApi, PageviewsApi
from wikitrends.errors import ApiError, NoDataError
from wikitrends.models import Article, DateRange
from wikitrends.replay import FixtureStore, RecordingTransport, ReplayTransport, fixture_dir

JAN = DateRange(date(2025, 1, 1), date(2025, 1, 10))


class FakeWikimedia:
    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> Any:
        if "per-article" in url:
            if "Missing" in url:
                raise NoDataError("404")
            return {"items": [{"timestamp": f"202501{d:02d}00", "views": d} for d in (1, 2, 5)]}
        return {"query": {"pages": [{"title": "Astronomia"}]}}


def test_record_then_replay_any_subrange(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    recorder = PageviewsApi(RecordingTransport(FakeWikimedia(), store))
    recorded = recorder.article_daily(Article("pl", "Astronomia"), JAN)
    ActionApi(RecordingTransport(FakeWikimedia(), store)).canonical("pl", "astronomia")

    replay = ReplayTransport(store)
    assert PageviewsApi(replay).article_daily(Article("pl", "Astronomia"), JAN) == recorded
    sub = DateRange(date(2025, 1, 2), date(2025, 1, 4))
    assert PageviewsApi(replay).article_daily(Article("pl", "Astronomia"), sub) == {
        date(2025, 1, 2): 2
    }
    assert ActionApi(replay).canonical("pl", "astronomia") == Article("pl", "Astronomia")


def test_recorded_404_replays_as_no_data(tmp_path: Path) -> None:
    store = FixtureStore(tmp_path)
    with pytest.raises(NoDataError):
        RecordingTransport(FakeWikimedia(), store).get_json(
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/pl.wikipedia"
            "/all-access/user/Missing/daily/20250101/20250110"
        )
    assert PageviewsApi(ReplayTransport(store)).article_daily(Article("pl", "Missing"), JAN) == {}


def test_unknown_request_is_an_error_with_hint(tmp_path: Path) -> None:
    replay = ReplayTransport(FixtureStore(tmp_path))
    with pytest.raises(ApiError) as exc:
        ActionApi(replay).search("pl", "anything")
    assert "offline-fixture" in exc.value.hint


def test_bundled_demo_is_synthetic_and_dated() -> None:
    replay = ReplayTransport(FixtureStore(fixture_dir("demo")))
    assert replay.synthetic
    assert replay.today == date(2026, 9, 24)
