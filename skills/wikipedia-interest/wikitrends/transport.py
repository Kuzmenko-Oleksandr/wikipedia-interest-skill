"""HTTP access to Wikimedia with throttling, retries and status mapping."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import httpx

from . import __version__
from .errors import ApiError, NoDataError, RateLimitedError

log = logging.getLogger(__name__)

REPO_URL = "https://github.com/Kuzmenko-Oleksandr/wikipedia-interest-skill"
USER_AGENT = f"wikipedia-interest-skill/{__version__} ({REPO_URL}) httpx/{httpx.__version__}"

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class JsonTransport(Protocol):
    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> Any: ...


class TokenBucket:
    """Client-side limiter; the observed per-IP limit is ~10 requests/minute."""

    def __init__(
        self,
        capacity: int = 10,
        per_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._capacity = capacity
        self._rate = capacity / per_seconds
        self._tokens = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()

    def acquire(self) -> None:
        self._refill()
        if self._tokens < 1:
            wait = (1 - self._tokens) / self._rate
            log.info("throttling for %.1fs", wait)
            self._sleep(wait)
            self._refill()
        self._tokens -= 1

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._rate)
        self._last = now


class WikimediaTransport:
    """GET JSON with the mandatory User-Agent, throttling and backoff."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        bucket: TokenBucket | None = None,
        max_retries: int = 4,
        base_backoff: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=False
        )
        self._bucket = bucket or TokenBucket(sleep=sleep)
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._sleep = sleep

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> Any:
        for attempt in range(self._max_retries + 1):
            self._bucket.acquire()
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise ApiError(f"network error: {exc}", "Check connectivity.") from exc
                self._backoff(attempt, None)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self._max_retries:
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            return self._parse(response)
        raise AssertionError("unreachable")

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = self._base_backoff * 2**attempt
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        log.warning("retrying in %.0fs (attempt %d)", delay, attempt + 1)
        self._sleep(delay)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        status = response.status_code
        if status == 200:
            if "json" not in response.headers.get("content-type", ""):
                raise ApiError(f"non-JSON response from {response.url}")
            return response.json()
        if status == 404:
            raise NoDataError(f"no data at {response.url}")
        if status == 429:
            raise RateLimitedError(
                "Wikimedia rate limit persisted after retries",
                "Wait a minute and rerun; cached data is kept.",
            )
        if status == 403:
            raise ApiError("request forbidden (403)", "User-Agent was rejected.")
        # 429/5xx bodies are plain text, never parse them as JSON.
        raise ApiError(f"HTTP {status} from {response.url}: {response.text[:200]}")
