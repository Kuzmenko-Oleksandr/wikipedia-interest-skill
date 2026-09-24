"""Data quality gates that run before any estimate is made.

A series that fails a stop gate gets a refusal, never a low-confidence number.
Messages are English and go verbatim into the JSON output and the PDF.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from .series import DailySeries, FloatArray

STOP_MEDIAN = 10
DIRECTION_ONLY_MEDIAN = 50
MIN_OBSERVED_DAYS = 60
STOP_WINDOW_DAYS = 180
ANNUAL_WINDOW_DAYS = 365
SEASONAL_WINDOW_DAYS = 730
WARN_MISSING_SHARE = 0.10
STOP_MISSING_SHARE = 0.25
MAX_GAP_DAYS = 14
RECENT_DAYS = 30
PRIOR_DAYS = 120
COLLAPSE_MIN_PRIOR = 50
COLLAPSE_RATIO = 0.05
DEAD_TAIL_DAYS = 7
DEAD_TAIL_MIN_PRIOR = 20
LATE_START_DAYS = 30
MAX_ZERO_SHARE = 0.20
MAX_DENOMINATOR_MISSING = 0.05


class Severity(StrEnum):
    STOP = "stop"
    DEGRADE = "degrade"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class Finding:
    """One triggered gate.

    `flag` names what a non-stop finding switches off or weakens downstream.
    """

    gate: str
    severity: Severity
    message: str
    flag: str = ""


@dataclass(frozen=True, slots=True)
class GateContext:
    """Inputs of one language: the article series and, if fetched, the edition total."""

    article: DailySeries
    total: DailySeries | None = None


Gate = Callable[[GateContext], Finding | None]


@dataclass(frozen=True, slots=True)
class GateReport:
    findings: tuple[Finding, ...]

    @property
    def blocking(self) -> Finding | None:
        return next((f for f in self.findings if f.severity is Severity.STOP), None)

    @property
    def flags(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.flag for f in self.findings if f.flag))

    @property
    def messages(self) -> tuple[str, ...]:
        return tuple(f.message for f in self.findings)


def _median(values: FloatArray) -> float:
    """NaN-skipping median; NaN when nothing was observed."""
    observed = values[~np.isnan(values)]
    return float(np.median(observed)) if observed.size else float("nan")


def _runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """(start, length) of each run of True."""
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [(int(s), int(e - s)) for s, e in zip(starts, ends, strict=True)]


def _trailing_run(mask: NDArray[np.bool_]) -> int:
    runs = _runs(mask)
    if runs and sum(runs[-1]) == len(mask):
        return runs[-1][1]
    return 0


def _life(series: DailySeries) -> FloatArray:
    """Values from the first observed day; a late start is G8's concern, not a gap."""
    first = series.first_observed()
    return series.values[first:] if first is not None else series.values


def low_volume(ctx: GateContext) -> Finding | None:
    series = ctx.article
    if series.n_observed == 0:
        return Finding(
            "G1_low_volume",
            Severity.STOP,
            "No pageviews were recorded in this window.",
        )
    median = _median(series.values)
    if median < STOP_MEDIAN:
        return Finding(
            "G1_low_volume",
            Severity.STOP,
            f"Median {median:.0f} views/day is below {STOP_MEDIAN}: too little traffic on "
            "this article to measure a trend. It says nothing about interest in the topic, "
            "which may sit under other articles.",
        )
    if median < DIRECTION_ONLY_MEDIAN:
        return Finding(
            "G1_low_volume",
            Severity.DEGRADE,
            f"Median {median:.0f} views/day is below {DIRECTION_ONLY_MEDIAN}: "
            "only the direction of change is reported, not its size.",
            "direction_only",
        )
    return None


def few_points(ctx: GateContext) -> Finding | None:
    n = ctx.article.n_observed
    if n < MIN_OBSERVED_DAYS:
        return Finding(
            "G2_few_points",
            Severity.STOP,
            f"Only {n} days have data (minimum {MIN_OBSERVED_DAYS}).",
        )
    return None


def short_window(ctx: GateContext) -> Finding | None:
    days = len(ctx.article)
    if days < STOP_WINDOW_DAYS:
        return Finding(
            "G3_short_window",
            Severity.STOP,
            f"The {days}-day window is shorter than {STOP_WINDOW_DAYS} days: "
            "too short to tell a trend from noise.",
        )
    if days < ANNUAL_WINDOW_DAYS:
        return Finding(
            "G3_short_window",
            Severity.DEGRADE,
            f"The {days}-day window is shorter than a year: change is not annualized.",
            "no_annualization",
        )
    return None


def no_seasonal_baseline(ctx: GateContext) -> Finding | None:
    days = len(ctx.article)
    if days < SEASONAL_WINDOW_DAYS:
        return Finding(
            "G4_no_seasonal_baseline",
            Severity.DEGRADE,
            f"The {days}-day window covers less than two years: "
            "yearly seasonality cannot be separated from the trend.",
            "no_annual_baseline",
        )
    return None


def missing_share(ctx: GateContext) -> Finding | None:
    life = _life(ctx.article)
    share = float(np.count_nonzero(np.isnan(life))) / len(life)
    if share > STOP_MISSING_SHARE:
        return Finding(
            "G5_missing_days",
            Severity.STOP,
            f"{share:.0%} of days have no data (limit {STOP_MISSING_SHARE:.0%}).",
        )
    if share > WARN_MISSING_SHARE:
        return Finding(
            "G5_missing_days",
            Severity.WARN,
            f"{share:.0%} of days have no data.",
            "gappy",
        )
    return None


def long_gap(ctx: GateContext) -> Finding | None:
    series = ctx.article
    first = series.first_observed() or 0
    runs = _runs(np.isnan(series.values[first:]))
    if not runs:
        return None
    start, length = max(runs, key=lambda run: run[1])
    if length > MAX_GAP_DAYS:
        begin = series.day(first + start)
        end = series.day(first + start + length - 1)
        return Finding(
            "G6_long_gap",
            Severity.STOP,
            f"No data for {length} consecutive days ({begin} to {end}).",
        )
    return None


def discontinuity(ctx: GateContext) -> Finding | None:
    """Traffic that vanishes at the end or appears at the start usually means a rename."""
    values = ctx.article.values
    prior = _median(values[-PRIOR_DAYS:-RECENT_DAYS])
    recent = _median(values[-RECENT_DAYS:])
    if prior >= COLLAPSE_MIN_PRIOR and recent < COLLAPSE_RATIO * prior:
        return Finding(
            "G7_end_collapse",
            Severity.STOP,
            f"Views fell from a median of {prior:.0f}/day to {recent:.0f}/day "
            f"in the last {RECENT_DAYS} days; the article was probably renamed.",
        )
    tail = _trailing_run((values == 0) | np.isnan(values))
    if tail >= DEAD_TAIL_DAYS and prior >= DEAD_TAIL_MIN_PRIOR:
        return Finding(
            "G7_end_collapse",
            Severity.STOP,
            f"The last {tail} days have no views; the article was probably renamed or removed.",
        )
    early = _median(values[:RECENT_DAYS])
    later = _median(values[RECENT_DAYS:PRIOR_DAYS])
    if later >= COLLAPSE_MIN_PRIOR and early < COLLAPSE_RATIO * later:
        return Finding(
            "G7_start_jump",
            Severity.STOP,
            f"Views jumped from a median of {early:.0f}/day to {later:.0f}/day "
            "after the first days; the title may have inherited traffic from a rename.",
        )
    return None


def late_start(ctx: GateContext) -> Finding | None:
    series = ctx.article
    first = series.first_observed()
    if first is not None and first > LATE_START_DAYS:
        return Finding(
            "G8_late_start",
            Severity.DEGRADE,
            f"Data starts on {series.day(first)}, {first} days into the window; "
            "the article may be new.",
            "late_start",
        )
    return None


def many_zeros(ctx: GateContext) -> Finding | None:
    series = ctx.article
    if series.n_observed == 0:
        return None
    share = float(np.count_nonzero(series.values == 0)) / series.n_observed
    if share > MAX_ZERO_SHARE:
        return Finding(
            "G9_many_zeros",
            Severity.DEGRADE,
            f"{share:.0%} of days with data have zero views.",
            "many_zeros",
        )
    return None


def denominator_gaps(ctx: GateContext) -> Finding | None:
    if ctx.total is None:
        return None
    # A zero edition total is an outage, not a real day: it would divide by zero.
    usable = np.nan_to_num(ctx.total.values, nan=0.0) > 0
    share = float(np.count_nonzero(~usable)) / len(ctx.total)
    if share > MAX_DENOMINATOR_MISSING:
        return Finding(
            "G10_denominator_gaps",
            Severity.DEGRADE,
            f"{share:.0%} of days are missing from the edition total; "
            "views-per-million figures are suppressed.",
            "vpm_suppressed",
        )
    return None


def slice_mismatch(ctx: GateContext) -> Finding | None:
    total, article = ctx.total, ctx.article
    if total is None:
        return None
    if total.traffic != article.traffic or total.span != article.span:
        return Finding(
            "G11_slice_mismatch",
            Severity.DEGRADE,
            f"Article ({article.traffic.key}, {article.span.start}..{article.span.end}) and "
            f"edition total ({total.traffic.key}, {total.span.start}..{total.span.end}) differ; "
            "views-per-million figures are suppressed.",
            "vpm_suppressed",
        )
    return None


ALL_GATES: tuple[Gate, ...] = (
    low_volume,
    few_points,
    short_window,
    no_seasonal_baseline,
    missing_share,
    long_gap,
    discontinuity,
    late_start,
    many_zeros,
    denominator_gaps,
    slice_mismatch,
)


def evaluate(ctx: GateContext, gates: Sequence[Gate] = ALL_GATES) -> GateReport:
    """Runs every gate so the report lists all problems, not just the first."""
    return GateReport(tuple(f for gate in gates if (f := gate(ctx)) is not None))
