"""Offline fixtures: record real responses once, replay them without network.

Pageview series are stored whole and sliced per request, so a fixture works for any
window inside it regardless of cache state. Other lookups are stored per request.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode

from .errors import ApiError, NoDataError
from .transport import JsonTransport

BUNDLED = Path(__file__).resolve().parent / "fixtures"

_PAGEVIEWS = re.compile(
    r"/metrics/pageviews/(?P<kind>per-article|aggregate)/(?P<project>[^/]+)"
    r"/(?P<access>[^/]+)/(?P<agent>[^/]+)(?:/(?P<title>[^/]+))?"
    r"/daily/(?P<start>\d{8})/(?P<end>\d{8})$"
)


def fixture_dir(name: str) -> Path:
    """A bundled fixture by name, or any directory path."""
    bundled = BUNDLED / name
    return bundled if bundled.is_dir() else Path(name)


@dataclass(frozen=True, slots=True)
class SeriesKey:
    kind: str
    project: str
    access: str
    agent: str
    title: str

    @property
    def filename(self) -> str:
        raw = "|".join((self.kind, self.project, self.access, self.agent, self.title))
        return hashlib.sha1(raw.encode()).hexdigest()[:16] + ".json"


def _day(text: str) -> date:
    return datetime.strptime(text, "%Y%m%d").date()


class FixtureStore:
    """Directory layout: series/<hash>.json, lookups/<hash>.json, manifest.json."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        self._write(self.root / "manifest.json", manifest)

    def load_series(self, key: SeriesKey) -> dict[date, int | None]:
        path = self.root / "series" / key.filename
        if not path.exists():
            raise ApiError(
                f"offline fixture has no series for {key.project} {key.title or '(total)'}",
                "Use a topic and languages covered by the fixture, or drop --offline-fixture.",
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        start = date.fromisoformat(data["start"])
        return {start + timedelta(days=i): v for i, v in enumerate(data["views"])}

    def save_series(self, key: SeriesKey, counts: Mapping[date, int | None]) -> None:
        path = self.root / "series" / key.filename
        merged: dict[date, int | None] = {}
        if path.exists():
            merged.update(self.load_series(key))
        merged.update(counts)
        start, end = min(merged), max(merged)
        views = [merged.get(start + timedelta(days=i)) for i in range((end - start).days + 1)]
        payload = {
            "kind": key.kind,
            "project": key.project,
            "traffic": f"{key.access}/{key.agent}",
            "title": key.title,
            "start": start.isoformat(),
            "views": views,
        }
        self._write(path, payload)

    def load_lookup(self, url: str, params: Mapping[str, str] | None) -> Any:
        path = self.root / "lookups" / self._lookup_name(url, params)
        if not path.exists():
            query = urlencode(sorted((params or {}).items()))
            raise ApiError(
                f"offline fixture has no response for {url}?{query}",
                "Use a topic and languages covered by the fixture, or drop --offline-fixture.",
            )
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["status"] == 404:
            raise NoDataError(f"no data at {url}")
        return record["body"]

    def save_lookup(
        self, url: str, params: Mapping[str, str] | None, status: int, body: Any
    ) -> None:
        record = {"url": url, "params": dict(params or {}), "status": status, "body": body}
        self._write(self.root / "lookups" / self._lookup_name(url, params), record)

    @staticmethod
    def _lookup_name(url: str, params: Mapping[str, str] | None) -> str:
        raw = url + "?" + urlencode(sorted((params or {}).items()))
        return hashlib.sha1(raw.encode()).hexdigest()[:16] + ".json"

    @staticmethod
    def _write(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _series_request(url: str) -> tuple[SeriesKey, date, date] | None:
    match = _PAGEVIEWS.search(url)
    if match is None:
        return None
    key = SeriesKey(
        match["kind"],
        match["project"],
        match["access"],
        match["agent"],
        unquote(match["title"] or ""),
    )
    return key, _day(match["start"]), _day(match["end"])


class ReplayTransport:
    """Answers from a fixture directory; anything not recorded is an error."""

    def __init__(self, store: FixtureStore) -> None:
        self._store = store

    @property
    def today(self) -> date | None:
        value = self._store.manifest.get("today")
        return date.fromisoformat(value) if value else None

    @property
    def synthetic(self) -> bool:
        return bool(self._store.manifest.get("synthetic"))

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> Any:
        request = _series_request(url)
        if request is None:
            return self._store.load_lookup(url, params)
        key, start, end = request
        counts = self._store.load_series(key)
        items = [
            {"project": key.project, "timestamp": f"{day:%Y%m%d}00", "views": views}
            for day, views in sorted(counts.items())
            if start <= day <= end and views is not None
        ]
        if not items:
            raise NoDataError(f"no data at {url}")
        return {"items": items}


class RecordingTransport:
    """Passes requests through and writes every answer into a fixture directory."""

    def __init__(self, inner: JsonTransport, store: FixtureStore) -> None:
        self._inner = inner
        self._store = store

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> Any:
        request = _series_request(url)
        try:
            body = self._inner.get_json(url, params)
        except NoDataError:
            if request is None:
                self._store.save_lookup(url, params, 404, None)
            else:
                key, start, end = request
                span = range((end - start).days + 1)
                self._store.save_series(key, {start + timedelta(days=i): None for i in span})
            raise
        if request is None:
            self._store.save_lookup(url, params, 200, body)
        else:
            key, _, _ = request
            self._store.save_series(
                key, {_day(item["timestamp"][:8]): int(item["views"]) for item in body["items"]}
            )
        return body
