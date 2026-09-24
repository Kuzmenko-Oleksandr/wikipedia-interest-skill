from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from wikitrends.errors import ApiError, NoDataError, RateLimitedError
from wikitrends.transport import USER_AGENT, TokenBucket, WikimediaTransport


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_transport(
    handler: Callable[[httpx.Request], httpx.Response], clock: FakeClock | None = None
) -> WikimediaTransport:
    clock = clock or FakeClock()
    client = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT}
    )
    bucket = TokenBucket(capacity=100, clock=clock, sleep=clock.sleep)
    return WikimediaTransport(client, bucket, max_retries=2, sleep=clock.sleep)


def test_user_agent_identifies_project() -> None:
    assert USER_AGENT.startswith("wikipedia-interest-skill/")
    assert "github.com/Kuzmenko-Oleksandr/wikipedia-interest-skill" in USER_AGENT


def test_bucket_allows_burst_then_waits() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=10, per_seconds=60, clock=clock, sleep=clock.sleep)
    for _ in range(10):
        bucket.acquire()
    assert clock.slept == []
    bucket.acquire()
    assert clock.slept == [pytest.approx(6.0)]


def test_retries_429_honouring_retry_after() -> None:
    calls = iter(
        [
            httpx.Response(429, text="Too many", headers={"Retry-After": "30"}),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    clock = FakeClock()
    transport = make_transport(lambda request: next(calls), clock)
    assert transport.get_json("https://x.test") == {"ok": 1}
    assert clock.slept == [30.0]


def test_gives_up_on_persistent_429() -> None:
    transport = make_transport(lambda request: httpx.Response(429, text="Too many"))
    with pytest.raises(RateLimitedError) as exc:
        transport.get_json("https://x.test")
    assert exc.value.hint


def test_404_is_no_data() -> None:
    transport = make_transport(lambda request: httpx.Response(404, json={"title": "Not found"}))
    with pytest.raises(NoDataError):
        transport.get_json("https://x.test")


def test_html_200_is_rejected() -> None:
    response = httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
    transport = make_transport(lambda request: response)
    with pytest.raises(ApiError, match="non-JSON"):
        transport.get_json("https://x.test")
