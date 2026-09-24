"""Flags, a verdict from a closed vocabulary, and a confidence level.

No single score: a 0-100 number hides which assumption failed and invites
comparing series that failed in different ways.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .gates import Finding, GateReport, Severity
from .stats import AUTOCORR_LIMIT, SeriesAnalysis, SpikeScan, TrendFit

STABLE_BAND_PCT = 5.0
SEASONAL_AMPLITUDE = 0.25
INFLATION_RATIO = 0.5


class Verdict(StrEnum):
    """First match wins, in declaration order."""

    INSUFFICIENT_DATA = "insufficient_data"
    SERIES_DISCONTINUITY = "series_discontinuity"
    LEVEL_SHIFT_UP = "level_shift_up"
    LEVEL_SHIFT_DOWN = "level_shift_down"
    GROWING_EVENT_DRIVEN = "growing_event_driven"
    DECLINING_EVENT_DRIVEN = "declining_event_driven"
    GROWING = "growing"
    DECLINING = "declining"
    STABLE = "stable"
    NO_DETECTABLE_TREND = "no_detectable_trend"

    @property
    def refused(self) -> bool:
        return self in (Verdict.INSUFFICIENT_DATA, Verdict.SERIES_DISCONTINUITY)


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def lowered(self, steps: int) -> Confidence:
        order = list(Confidence)
        return order[min(order.index(self) + steps, len(order) - 1)]


class Basis(StrEnum):
    VPM = "views_per_million"
    RAW = "raw_views"


# Each flag present lowers confidence by one step.
CONFIDENCE_PENALTIES = (
    "no_annualization",
    "direction_only",
    "gappy",
    "no_annual_baseline",
    "late_start",
    "many_zeros",
    "vpm_suppressed",
    "autocorrelated",
    "seasonality_suspected",
    "raw_vpm_divergence",
    "multiple_changepoints",
    "event_inflated",
)

# Any percentage is withheld under these flags; only the direction is reported.
PERCENT_SUPPRESSORS = ("direction_only", "no_annualization")

RENAME_GATES = ("G7_end_collapse", "G7_start_jump")


@dataclass(frozen=True, slots=True, eq=False)
class Assessment:
    """What may be claimed about one language, and how firmly."""

    verdict: Verdict
    confidence: Confidence | None
    basis: Basis
    flags: tuple[str, ...]
    blocking: Finding | None = None
    headline: SeriesAnalysis | None = None
    raw: SeriesAnalysis | None = None
    pct_per_year: float | None = None
    pct_ci: tuple[float, float] | None = None
    mde_pct_per_year: float | None = None
    raw_movement: int = 0
    basis_movement: int = 0

    @property
    def level_shift(self) -> bool:
        return self.verdict in (Verdict.LEVEL_SHIFT_UP, Verdict.LEVEL_SHIFT_DOWN)

    @property
    def step_ratio(self) -> float | None:
        """Size of a level shift; withheld where only the direction may be reported."""
        if not self.level_shift or self.headline is None:
            return None
        if any(flag in self.flags for flag in PERCENT_SUPPRESSORS):
            return None
        return self.headline.step.ratio


def within_stable_band(fit: TrendFit) -> bool:
    low, high = fit.pct_per_year_log_ci
    return low >= -STABLE_BAND_PCT and high <= STABLE_BAND_PCT


def movement(analysis: SeriesAnalysis | None) -> int:
    """+1 / -1 for a significant, non-negligible trend of the clean series, else 0."""
    if analysis is None:
        return 0
    fit = analysis.trend_clean
    if fit.mk.p >= analysis.alpha or within_stable_band(fit):
        return 0
    return fit.direction


def refusal(finding: Finding, basis: Basis = Basis.RAW) -> Assessment:
    verdict = (
        Verdict.SERIES_DISCONTINUITY if finding.gate in RENAME_GATES else Verdict.INSUFFICIENT_DATA
    )
    return Assessment(verdict, None, basis, (), blocking=finding)


class VerdictRules:
    """Turns gate findings and trend analyses into an `Assessment`."""

    def assess(
        self,
        gates: GateReport,
        spikes: SpikeScan,
        raw: SeriesAnalysis | None,
        normalized: SeriesAnalysis | None,
        vpm_failed: bool = False,
    ) -> Assessment:
        """`vpm_failed`: an edition total existed but too little of it was usable."""
        basis = Basis.VPM if normalized is not None else Basis.RAW
        blocking = self._blocking(gates)
        if blocking is not None:
            return refusal(blocking, basis)
        headline = normalized or raw
        if headline is None or raw is None:
            return refusal(_few_weeks(), basis)
        flags = list(gates.flags)
        if vpm_failed:
            flags.append("vpm_suppressed")
        verdict = self._verdict(headline, bool(spikes.events), flags)
        flags += self._analysis_flags(headline, raw, normalized)
        if spikes.events:
            flags.append("spike_events")
        flags = list(dict.fromkeys(flags))
        penalties = sum(flag in flags for flag in CONFIDENCE_PENALTIES)
        pct, ci = self._headline_pct(verdict, flags, headline.trend_clean)
        return Assessment(
            verdict=verdict,
            confidence=Confidence.HIGH.lowered(penalties),
            basis=basis,
            flags=tuple(flags),
            headline=headline,
            raw=raw,
            pct_per_year=pct,
            pct_ci=ci,
            mde_pct_per_year=self._mde(verdict, flags, headline),
            raw_movement=movement(raw),
            basis_movement=movement(headline),
        )

    @staticmethod
    def _blocking(gates: GateReport) -> Finding | None:
        # insufficient_data outranks series_discontinuity when both apply.
        stops = [f for f in gates.findings if f.severity is Severity.STOP]
        others = [f for f in stops if f.gate not in RENAME_GATES]
        return (others or stops or [None])[0]

    @staticmethod
    def _verdict(analysis: SeriesAnalysis, has_events: bool, flags: list[str]) -> Verdict:
        alpha = analysis.alpha
        full, clean = analysis.trend_all, analysis.trend_clean
        significant_all = full.mk.p < alpha
        significant_clean = clean.mk.p < alpha
        if analysis.level_shift:
            up = analysis.step.ratio > 1
            return Verdict.LEVEL_SHIFT_UP if up else Verdict.LEVEL_SHIFT_DOWN
        if significant_all and not significant_clean and has_events:
            up = full.direction > 0
            return Verdict.GROWING_EVENT_DRIVEN if up else Verdict.DECLINING_EVENT_DRIVEN
        if significant_all and significant_clean and full.direction != clean.direction:
            flags.append("sign_flip")
            return Verdict.NO_DETECTABLE_TREND
        if significant_clean and not within_stable_band(clean):
            if significant_all and abs(clean.log.slope) < INFLATION_RATIO * abs(full.log.slope):
                flags.append("event_inflated")
            return Verdict.GROWING if clean.direction > 0 else Verdict.DECLINING
        if within_stable_band(clean):
            return Verdict.STABLE
        return Verdict.NO_DETECTABLE_TREND

    @staticmethod
    def _analysis_flags(
        headline: SeriesAnalysis, raw: SeriesAnalysis, normalized: SeriesAnalysis | None
    ) -> list[str]:
        flags = []
        if headline.autocorrelation > AUTOCORR_LIMIT:
            flags.append("autocorrelated")
        if headline.seasonality.month_amplitude >= SEASONAL_AMPLITUDE:
            flags.append("seasonality_suspected")
        if normalized is not None and movement(raw) != movement(normalized):
            flags.append("raw_vpm_divergence")
        if headline.multiple_changepoints:
            flags.append("multiple_changepoints")
        return flags

    @staticmethod
    def _headline_pct(
        verdict: Verdict, flags: list[str], fit: TrendFit
    ) -> tuple[float | None, tuple[float, float] | None]:
        if verdict not in (Verdict.GROWING, Verdict.DECLINING, Verdict.STABLE):
            return None, None
        if any(flag in flags for flag in PERCENT_SUPPRESSORS):
            return None, None
        # An interval that covers zero keeps the percentage out of the headline.
        if verdict is not Verdict.STABLE and not fit.log.excludes_zero:
            return None, None
        return fit.pct_per_year_log, fit.pct_per_year_log_ci

    @staticmethod
    def _mde(verdict: Verdict, flags: list[str], analysis: SeriesAnalysis) -> float | None:
        shown = (
            Verdict.NO_DETECTABLE_TREND,
            Verdict.STABLE,
            Verdict.GROWING_EVENT_DRIVEN,
            Verdict.DECLINING_EVENT_DRIVEN,
        )
        if verdict not in shown or any(flag in flags for flag in PERCENT_SUPPRESSORS):
            return None
        mde = analysis.mde_pct_per_year
        return mde if math.isfinite(mde) else None


def _few_weeks() -> Finding:
    return Finding(
        "G2_few_points",
        Severity.STOP,
        "Fewer than 26 complete weeks have data; a trend cannot be tested.",
    )
