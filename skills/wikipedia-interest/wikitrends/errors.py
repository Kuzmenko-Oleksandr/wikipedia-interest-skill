"""Exceptions carrying an actionable hint for the calling agent."""

from __future__ import annotations


class WikitrendsError(Exception):
    """Base error; `hint` tells the agent what to do next."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class ApiError(WikitrendsError):
    """Upstream API failed or returned an unusable response."""


class RateLimitedError(ApiError):
    """Retries exhausted while the API kept throttling."""


class NoDataError(ApiError):
    """Pageviews API returned 404: no data, not necessarily a missing article."""


class ResolveError(WikitrendsError):
    """A topic or title could not be mapped to an article."""
