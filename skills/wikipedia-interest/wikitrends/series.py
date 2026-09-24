"""Calendar-aligned daily series, smoothing and weekly aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from .models import DailyCounts, DateRange, TrafficFilter

FloatArray = NDArray[np.float64]

WEEK = 7
MIN_WEEK_DAYS = 5
DENOMINATOR_WINDOW = 7


def rolling_median(values: FloatArray, window: int, min_periods: int = 1) -> FloatArray:
    """Centred rolling median that skips NaN; edges use the partial window.

    Args:
        values: Daily values, NaN for missing days.
        window: Odd window length in days.
        min_periods: Fewer observed days than this give NaN.
    """
    if window < 1 or window % 2 == 0:
        raise ValueError(f"window must be a positive odd number, got {window}")
    half = window // 2
    padded = np.pad(values.astype(np.float64), half, constant_values=np.nan)
    windows = sliding_window_view(padded, window)
    counts = np.count_nonzero(~np.isnan(windows), axis=1)
    result = np.full(len(values), np.nan)
    enough = counts >= max(min_periods, 1)
    result[enough] = np.nanmedian(windows[enough], axis=1)
    return result


@dataclass(frozen=True, slots=True, eq=False)
class WeeklySeries:
    """Median of each full week counted back from the window end."""

    t: FloatArray
    values: FloatArray

    @property
    def valid(self) -> NDArray[np.bool_]:
        return ~np.isnan(self.values)

    @property
    def n_valid(self) -> int:
        return int(np.count_nonzero(self.valid))

    def points(self) -> tuple[FloatArray, FloatArray]:
        """Valid weeks only; `t` keeps the true day index of each week centre."""
        mask = self.valid
        return self.t[mask], self.values[mask]


@dataclass(frozen=True, slots=True, eq=False)
class DailySeries:
    """Daily values on a full calendar; NaN marks days the API did not return."""

    start: date
    values: FloatArray
    traffic: TrafficFilter = field(default_factory=TrafficFilter)

    def __post_init__(self) -> None:
        values = np.array(self.values, dtype=np.float64)
        values.flags.writeable = False
        object.__setattr__(self, "values", values)

    @classmethod
    def from_counts(
        cls, counts: DailyCounts, span: DateRange, traffic: TrafficFilter | None = None
    ) -> DailySeries:
        values = np.full(span.days, np.nan)
        for day, views in counts.items():
            if day in span:
                # A real 0 from the API stays 0.0; only absent days become NaN.
                values[(day - span.start).days] = views
        return cls(span.start, values, traffic or TrafficFilter())

    def __len__(self) -> int:
        return len(self.values)

    @property
    def span(self) -> DateRange:
        return DateRange(self.start, self.day(len(self) - 1))

    @property
    def t(self) -> FloatArray:
        """True day index; never renumber it after dropping days."""
        return np.arange(len(self), dtype=np.float64)

    @property
    def dates(self) -> NDArray[np.datetime64]:
        return np.arange(len(self), dtype="timedelta64[D]") + np.datetime64(self.start, "D")

    @property
    def observed(self) -> NDArray[np.bool_]:
        return ~np.isnan(self.values)

    @property
    def n_observed(self) -> int:
        return int(np.count_nonzero(self.observed))

    def day(self, index: int) -> date:
        return self.start + timedelta(days=index)

    def first_observed(self) -> int | None:
        hits = np.flatnonzero(self.observed)
        return int(hits[0]) if hits.size else None

    def per_million(self, total: DailySeries) -> DailySeries:
        """Views per million views of the whole edition.

        The denominator is smoothed so the edition's own weekly cycle and outages
        do not leak into every article.
        """
        if total.start != self.start or len(total) != len(self):
            raise ValueError("numerator and denominator must share one calendar")
        smoothed = rolling_median(total.values, DENOMINATOR_WINDOW)
        with np.errstate(divide="ignore", invalid="ignore"):
            vpm = np.where(smoothed > 0, 1e6 * self.values / smoothed, np.nan)
        return DailySeries(self.start, vpm, self.traffic)

    def weekly(self, min_days: int = MIN_WEEK_DAYS) -> WeeklySeries:
        """Weekly medians; a week with fewer than `min_days` observed days is NaN.

        Weeks are aligned to the window end, so the leading remainder is dropped
        and each block holds every weekday exactly once.
        """
        offset = len(self) % WEEK
        blocks = self.values[offset:].reshape(-1, WEEK)
        counts = np.count_nonzero(~np.isnan(blocks), axis=1)
        medians = np.full(len(blocks), np.nan)
        enough = counts >= min_days
        medians[enough] = np.nanmedian(blocks[enough], axis=1)
        centres = offset + WEEK * np.arange(len(blocks), dtype=np.float64) + WEEK // 2
        return WeeklySeries(centres, medians)
