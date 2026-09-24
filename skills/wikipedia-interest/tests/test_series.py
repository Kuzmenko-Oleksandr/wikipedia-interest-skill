from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from wikitrends.models import DateRange
from wikitrends.series import DailySeries, rolling_median

SPAN = DateRange(date(2025, 1, 1), date(2025, 1, 10))


def test_missing_days_become_nan_and_zeros_stay_zero() -> None:
    counts = {date(2025, 1, 1): 5, date(2025, 1, 3): 0, date(2024, 12, 31): 99}
    series = DailySeries.from_counts(counts, SPAN)
    assert len(series) == 10
    assert series.values[0] == 5
    assert np.isnan(series.values[1])
    assert series.values[2] == 0.0
    assert series.n_observed == 2


def test_day_index_is_not_renumbered() -> None:
    series = DailySeries.from_counts({date(2025, 1, 1): 1, date(2025, 1, 10): 2}, SPAN)
    assert series.t[series.observed].tolist() == [0.0, 9.0]


def test_values_are_read_only() -> None:
    series = DailySeries.from_counts({}, SPAN)
    with pytest.raises(ValueError):
        series.values[0] = 1


def test_calendar_properties() -> None:
    series = DailySeries.from_counts({date(2025, 1, 4): 1}, SPAN)
    assert series.span == SPAN
    assert series.dates[0] == np.datetime64("2025-01-01")
    assert series.dates[-1] == np.datetime64("2025-01-10")
    assert series.first_observed() == 3


def test_rolling_median_skips_nan_and_uses_partial_edges() -> None:
    values = np.array([1, 2, np.nan, 100, 5], dtype=np.float64)
    assert rolling_median(values, 3).tolist() == [1.5, 1.5, 51.0, 52.5, 52.5]


def test_rolling_median_min_periods() -> None:
    values = np.array([np.nan, np.nan, 3.0])
    assert np.isnan(rolling_median(values, 3, min_periods=2)).all()


def test_rolling_median_rejects_even_window() -> None:
    with pytest.raises(ValueError):
        rolling_median(np.ones(5), 4)


def test_per_million_smooths_denominator_outage() -> None:
    span = DateRange(date(2025, 1, 1), date(2025, 1, 14))
    article = DailySeries.from_counts(dict.fromkeys(span.dates(), 10), span)
    totals = dict.fromkeys(span.dates(), 1_000_000)
    totals[date(2025, 1, 7)] = 500_000
    vpm = article.per_million(DailySeries.from_counts(totals, span))
    assert np.allclose(vpm.values, 10.0)


def test_per_million_rejects_other_calendar() -> None:
    article = DailySeries.from_counts({}, SPAN)
    other = DailySeries.from_counts({}, DateRange(date(2025, 1, 2), date(2025, 1, 11)))
    with pytest.raises(ValueError):
        article.per_million(other)


def test_weekly_aligns_to_end_and_needs_five_days() -> None:
    span = DateRange(date(2025, 1, 1), date(2025, 1, 16))
    counts = {day: i for i, day in enumerate(span.dates()) if i not in (2, 3, 4)}
    weekly = DailySeries.from_counts(counts, span).weekly()
    assert weekly.t.tolist() == [5.0, 12.0]
    assert np.isnan(weekly.values[0])
    t, values = weekly.points()
    assert t.tolist() == [12.0]
    assert values.tolist() == [12.0]


def test_weekly_median_removes_weekday_cycle() -> None:
    span = DateRange(date(2025, 1, 1), date(2025, 3, 31))
    pattern = [100, 120, 130, 125, 110, 60, 50]
    counts = {day: pattern[day.weekday()] for day in span.dates()}
    weekly = DailySeries.from_counts(counts, span).weekly()
    assert weekly.n_valid == len(span.dates()) // 7
    assert np.all(weekly.values == 110.0)
