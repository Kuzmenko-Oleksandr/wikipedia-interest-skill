"""Per-language analysis and the cross-language comparison."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from . import gates
from .gates import GateContext, GateReport
from .models import Article
from .series import DailySeries
from .stats import SeriesAnalysis, SpikeScan, TrendAnalyzer, detect_spikes, median_ci
from .verdict import Assessment, VerdictRules


@dataclass(frozen=True, slots=True)
class Interval:
    """A point estimate with a distribution-free interval."""

    value: float
    low: float
    high: float

    def overlaps(self, other: Interval) -> bool:
        return self.low <= other.high and other.low <= self.high

    @classmethod
    def median_of(cls, series: DailySeries) -> Interval | None:
        # Weekly values: daily ones are autocorrelated and would make the interval too narrow.
        value, low, high = median_ci(series.weekly().values)
        return None if math.isnan(value) else cls(value, low, high)


@dataclass(frozen=True, slots=True, eq=False)
class LanguageResult:
    """Everything computed for one language edition."""

    article: Article
    views: DailySeries
    total: DailySeries | None
    vpm: DailySeries | None
    gates: GateReport
    spikes: SpikeScan
    raw: SeriesAnalysis | None
    normalized: SeriesAnalysis | None
    assessment: Assessment
    reach: Interval | None
    penetration: Interval | None

    @property
    def lang(self) -> str:
        return self.article.lang


class LanguageAnalyzer:
    """Gates first; a series that fails a stop gate is never estimated."""

    def __init__(
        self, trends: TrendAnalyzer | None = None, rules: VerdictRules | None = None
    ) -> None:
        self._trends = trends or TrendAnalyzer()
        self._rules = rules or VerdictRules()

    def analyze(
        self, article: Article, views: DailySeries, total: DailySeries | None
    ) -> LanguageResult:
        report = gates.evaluate(GateContext(views, total))
        spikes = detect_spikes(views.values)
        vpm = None
        if total is not None and "vpm_suppressed" not in report.flags:
            vpm = views.per_million(total)
        raw = normalized = None
        if report.blocking is None:
            raw = self._trends.analyze(views, spikes.mask)
            normalized = self._trends.analyze(vpm, spikes.mask) if vpm is not None else None
        return LanguageResult(
            article=article,
            views=views,
            total=total,
            vpm=vpm,
            gates=report,
            spikes=spikes,
            raw=raw,
            normalized=normalized,
            assessment=self._rules.assess(
                report, spikes, raw, normalized, vpm_failed=vpm is not None and normalized is None
            ),
            reach=Interval.median_of(views),
            penetration=Interval.median_of(vpm) if vpm is not None else None,
        )


@dataclass(frozen=True, slots=True)
class Ranking:
    """Tiers of statistically indistinguishable languages, best first.

    Languages without a usable result are listed apart, never ranked last:
    ranking them at the bottom reads as "no interest" when it means "no data".
    """

    tiers: tuple[tuple[str, ...], ...]
    unranked: tuple[str, ...]

    @property
    def order(self) -> tuple[str, ...]:
        return tuple(lang for tier in self.tiers for lang in tier)


def rank(results: Mapping[str, LanguageResult]) -> Ranking:
    """Ranks by penetration, breaks ties by reach; momentum stays an annotation."""
    ranked = [r for r in results.values() if not r.assessment.verdict.refused and r.penetration]
    ranked.sort(key=lambda r: (-_value(r.penetration), -_value(r.reach), r.lang))
    tiers: list[list[LanguageResult]] = []
    for result in ranked:
        leader = tiers[-1][0].penetration if tiers else None
        if leader and result.penetration and leader.overlaps(result.penetration):
            tiers[-1].append(result)
        else:
            tiers.append([result])
    unranked = sorted(set(results) - {r.lang for r in ranked})
    return Ranking(tuple(tuple(r.lang for r in tier) for tier in tiers), tuple(unranked))


def _value(interval: Interval | None) -> float:
    return interval.value if interval else 0.0
