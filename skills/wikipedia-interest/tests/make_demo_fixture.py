"""Builds the bundled synthetic `demo` fixture.

Run from the skill directory: `python -m tests.make_demo_fixture`. The series are
synthetic, each language planted with one scenario, so offline runs and tests have a
known answer. Record real data instead with `--record-fixture DIR`.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

import numpy as np

from wikitrends.api import ActionApi, SiteMatrixApi, WikidataApi
from wikitrends.replay import BUNDLED, FixtureStore, RecordingTransport, SeriesKey

TODAY = date(2026, 9, 24)
START = date(2022, 1, 1)
END = TODAY - timedelta(days=2)
DAYS = (END - START).days + 1
WEEKDAY = np.array([1.06, 1.08, 1.07, 1.03, 0.97, 0.88, 0.91])

# lang: (title, views/day, % per year, scenario)
ARTICLES = {
    "en": ("Astronomy", 4000, 0.0, "edition shrinks"),
    "uk": ("Астрономія", 450, 25.0, "growth"),
    "pl": ("Astronomia", 600, 0.0, "school-year seasonality"),
    "cs": ("Astronomie", 7, 0.0, "low volume"),
    "de": ("Astronomie", 900, 0.0, "news spikes"),
    "fr": ("Astronomie", 700, 0.0, "step"),
}
# lang: (views/day of the whole edition, % per year)
EDITIONS = {
    "en": (250e6, -8.0),
    "uk": (2.5e6, 0.0),
    "pl": (6e6, -1.0),
    "cs": (2.5e6, 0.0),
    "de": (25e6, 0.0),
    "fr": (20e6, -1.0),
}
QID = "Q333"
EXTRA_SITES = {"commonswiki": "Category:Astronomy"}
CLOSED = ("aa",)


def _curve(level: float, pct: float, seed: int, noise: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(DAYS)
    weekday = WEEKDAY[(t + START.weekday()) % 7]
    growth = np.exp(np.log1p(pct / 100) / 365.25 * t)
    return level * weekday * growth * np.exp(rng.normal(0, noise, DAYS))


def _article(lang: str) -> np.ndarray:
    _, level, pct, scenario = ARTICLES[lang]
    seed = sorted(ARTICLES).index(lang) + 1
    if scenario == "low volume":
        return np.random.default_rng(seed).poisson(level, DAYS).astype(np.float64)
    values = _curve(level, pct, seed, 0.08)
    t = np.arange(DAYS)
    if scenario == "school-year seasonality":
        dates = np.datetime64(START) + t.astype("timedelta64[D]")
        month = dates.astype("datetime64[M]").astype(int) % 12
        values *= np.where(np.isin(month, (6, 7)), 0.7, 1.0)
    if scenario == "news spikes":
        for peak in (1450, 1500, 1545, 1590, 1640, 1690):
            d = t - peak
            values *= np.where(d >= 0, 1 + 20 * np.exp(-np.clip(d, 0, None) / 3.0), 1.0)
    if scenario == "step":
        values[(date(2025, 3, 10) - START).days :] *= 1.5
    return np.round(values)


def _edition(lang: str) -> np.ndarray:
    level, pct = EDITIONS[lang]
    return np.round(_curve(level, pct, 100 + sorted(EDITIONS).index(lang), 0.02))


class ScriptedTransport:
    """Canned Action API, Wikidata and site matrix answers for the demo topic."""

    def get_json(self, url: str, params: Mapping[str, str] | None = None) -> Any:
        p = dict(params or {})
        if p.get("action") == "sitematrix":
            return self._sitematrix()
        if p.get("action") == "wbgetentities":
            links = {f"{lang}wiki": {"title": a[0]} for lang, a in ARTICLES.items()}
            links.update({site: {"title": title} for site, title in EXTRA_SITES.items()})
            return {"entities": {QID: {"sitelinks": links}}}
        lang = url.removeprefix("https://").split(".")[0]
        if p.get("list") == "search":
            return {"query": {"search": [{"title": "Astronomy"}, {"title": "Astronomer"}]}}
        title = p["titles"]
        canonical = title[:1].upper() + title[1:]
        known = ARTICLES.get(lang, ("",))[0]
        page: dict[str, Any] = {"title": canonical}
        if canonical != known:
            page["missing"] = True
        return {"query": {"pages": [page]}}

    @staticmethod
    def _sitematrix() -> dict[str, Any]:
        groups: dict[str, Any] = {"count": len(EDITIONS) + len(CLOSED)}
        for i, lang in enumerate(sorted(EDITIONS) + list(CLOSED)):
            site: dict[str, Any] = {
                "url": f"https://{lang}.wikipedia.org",
                "dbname": f"{lang}wiki",
                "code": "wiki",
            }
            if lang in CLOSED:
                site["closed"] = True
            groups[str(i)] = {"code": lang, "site": [site]}
        groups["specials"] = []
        return {"sitematrix": groups}


def main() -> None:
    root = BUNDLED / "demo"
    shutil.rmtree(root, ignore_errors=True)
    store = FixtureStore(root)
    store.write_manifest(
        {
            "today": TODAY.isoformat(),
            "synthetic": True,
            "note": "Synthetic series built by tests/make_demo_fixture.py; not real traffic.",
            "scenarios": {lang: a[3] for lang, a in ARTICLES.items()},
        },
    )
    days = [START + timedelta(days=i) for i in range(DAYS)]
    for lang, (title, *_) in ARTICLES.items():
        views = _article(lang)
        article = SeriesKey("per-article", f"{lang}.wikipedia", "all-access", "user", title)
        store.save_series(article, {d: int(v) for d, v in zip(days, views, strict=True)})
        total = SeriesKey("aggregate", f"{lang}.wikipedia", "all-access", "user", "")
        store.save_series(total, {d: int(v) for d, v in zip(days, _edition(lang), strict=True)})
    transport = RecordingTransport(ScriptedTransport(), store)
    SiteMatrixApi(transport).wikipedia_editions()
    ActionApi(transport).search("en", "Astronomy")
    WikidataApi(transport).entity_for("enwiki", "Astronomy")
    pages = ActionApi(transport)
    for lang, (title, *_) in ARTICLES.items():
        pages.canonical(lang, title)
        pages.canonical(lang, title[:1].lower() + title[1:])
    print(f"wrote {root}")


if __name__ == "__main__":
    main()
