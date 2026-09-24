"""SQLite cache and a caching decorator over any pageview source."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .models import Article, DailyCounts, DateRange, TrafficFilter

log = logging.getLogger(__name__)

# Days this close to the fetch date may still be revised upstream.
SETTLE_DAYS = 3
UNSETTLED_TTL = timedelta(days=1)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pageviews (
    kind TEXT NOT NULL, key TEXT NOT NULL, day TEXT NOT NULL, views INTEGER NOT NULL,
    PRIMARY KEY (kind, key, day));
CREATE TABLE IF NOT EXISTS coverage (
    kind TEXT NOT NULL, key TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT NOT NULL, fetched_at TEXT NOT NULL);
"""

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def default_cache_path() -> Path:
    root = os.environ.get("WIKITRENDS_CACHE_DIR") or Path.home() / ".cache" / "wikipedia-interest"
    return Path(root) / "cache.db"


class CacheDatabase:
    """Owns the SQLite connection and schema."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> CacheDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class PageviewStore:
    """Daily counts plus a record of which ranges were actually requested."""

    def __init__(self, db: CacheDatabase) -> None:
        self._conn = db.connection

    def load(self, kind: str, key: str, span: DateRange) -> DailyCounts:
        rows = self._conn.execute(
            "SELECT day, views FROM pageviews WHERE kind=? AND key=? AND day BETWEEN ? AND ?",
            (kind, key, span.start.isoformat(), span.end.isoformat()),
        )
        return {date.fromisoformat(day): views for day, views in rows}

    def save(
        self, kind: str, key: str, span: DateRange, counts: DailyCounts, fetched_at: datetime
    ) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO pageviews VALUES (?, ?, ?, ?)",
                [(kind, key, day.isoformat(), views) for day, views in counts.items()],
            )
            self._conn.execute(
                "INSERT INTO coverage VALUES (?, ?, ?, ?, ?)",
                (kind, key, span.start.isoformat(), span.end.isoformat(), fetched_at.isoformat()),
            )

    def missing_days(self, kind: str, key: str, span: DateRange, now: datetime) -> list[date]:
        """Days never requested, or requested while still unsettled and now stale."""
        intervals = [
            (date.fromisoformat(s), date.fromisoformat(e), datetime.fromisoformat(f))
            for s, e, f in self._conn.execute(
                "SELECT start, end, fetched_at FROM coverage WHERE kind=? AND key=?", (kind, key)
            )
        ]
        return [day for day in span.dates() if not self._is_fresh(day, intervals, now)]

    @staticmethod
    def _is_fresh(day: date, intervals: list[tuple[date, date, datetime]], now: datetime) -> bool:
        for start, end, fetched_at in intervals:
            if not start <= day <= end:
                continue
            settled = day <= fetched_at.date() - timedelta(days=SETTLE_DAYS)
            if settled or now - fetched_at < UNSETTLED_TTL:
                return True
        return False


class JsonStore:
    """Small key-value cache for resolver and site matrix lookups."""

    def __init__(self, db: CacheDatabase) -> None:
        self._conn = db.connection

    def get(self, key: str, max_age: timedelta, now: datetime) -> Any | None:
        row = self._conn.execute("SELECT value, fetched_at FROM kv WHERE key=?", (key,)).fetchone()
        if row is None or now - datetime.fromisoformat(row[1]) > max_age:
            return None
        return json.loads(row[0])

    def put(self, key: str, value: Any, now: datetime) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), now.isoformat()),
            )


class PageviewSource(Protocol):
    traffic: TrafficFilter

    def article_daily(self, article: Article, span: DateRange) -> DailyCounts: ...

    def project_daily(self, lang: str, span: DateRange) -> DailyCounts: ...


class CachedPageviews:
    """PageviewSource decorator that fetches only the missing part of a range."""

    def __init__(
        self,
        source: PageviewSource,
        store: PageviewStore,
        clock: Clock = utc_now,
        refresh: bool = False,
    ) -> None:
        self._source = source
        self._store = store
        self._clock = clock
        self._refresh = refresh
        self.traffic = source.traffic
        self.hits = 0
        self.fetched = 0

    def article_daily(self, article: Article, span: DateRange) -> DailyCounts:
        key = f"{article.project}|{article.api_title}|{self.traffic.key}"
        return self._get("article", key, span, lambda s: self._source.article_daily(article, s))

    def project_daily(self, lang: str, span: DateRange) -> DailyCounts:
        key = f"{lang}.wikipedia|{self.traffic.key}"
        return self._get("project", key, span, lambda s: self._source.project_daily(lang, s))

    def _get(
        self, kind: str, key: str, span: DateRange, fetch: Callable[[DateRange], DailyCounts]
    ) -> DailyCounts:
        now = self._clock()
        missing = span.dates() if self._refresh else self._store.missing_days(kind, key, span, now)
        if missing:
            # One request for the whole gap is cheaper than several under the rate limit.
            gap = DateRange(missing[0], missing[-1])
            log.info("fetching %s %s %s..%s", kind, key, gap.start, gap.end)
            self._store.save(kind, key, gap, fetch(gap), now)
            self.fetched += 1
        else:
            self.hits += 1
        return self._store.load(kind, key, span)
