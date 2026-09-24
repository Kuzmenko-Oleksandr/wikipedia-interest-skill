"""Known-answer tests: hand-computed examples and synthetic series with a planted effect."""

from __future__ import annotations

import math

import numpy as np
import pytest

from tests import synthetic
from wikitrends import stats
from wikitrends.stats import SeriesAnalysis, TrendAnalyzer


def analyze(values: np.ndarray) -> SeriesAnalysis:
    series = synthetic.series(values)
    result = TrendAnalyzer().analyze(series, stats.detect_spikes(series.values).mask)
    assert result is not None
    return result


def test_mann_kendall_worked_example() -> None:
    # Var 8.667 means the tie correction is missing; Z -0.361 means no continuity correction.
    result = stats.mann_kendall(np.array([1.0, 3.0, 2.0, 1.0]))
    assert result.s == -1
    assert result.variance == pytest.approx(7.667, abs=1e-3)
    assert result.z == 0.0
    assert result.p == 1.0


def test_mann_kendall_without_ties() -> None:
    result = stats.mann_kendall(np.array([1.0, 2.0, 3.0, 4.0]))
    assert (result.s, result.variance) == (6, pytest.approx(8.667, abs=1e-3))
    assert result.z == pytest.approx(5 / math.sqrt(156 / 18))
    assert result.p == pytest.approx(math.erfc(result.z / math.sqrt(2)))


def test_theil_sen_recovers_exact_line_and_ignores_outlier() -> None:
    t = np.arange(20, dtype=np.float64) * 7
    y = 3.0 + 0.5 * t
    y[5] = 1000.0
    fit = stats.theil_sen(t, y)
    assert fit.slope == pytest.approx(0.5)
    assert fit.intercept == pytest.approx(3.0)
    assert fit.low <= 0.5 <= fit.high


def test_theil_sen_interval_widens_with_noise() -> None:
    rng = np.random.default_rng(3)
    t = np.arange(100, dtype=np.float64)
    tight = stats.theil_sen(t, 0.2 * t + rng.normal(0, 1, 100))
    loose = stats.theil_sen(t, 0.2 * t + rng.normal(0, 5, 100))
    assert tight.low < 0.2 < tight.high
    assert loose.high - loose.low > tight.high - tight.low


def test_pettitt_worked_example() -> None:
    result = stats.pettitt(np.array([1.0, 2.0, 3.0, 10.0, 11.0, 12.0]))
    assert (result.index, result.statistic) == (3, 9.0)
    assert result.p == pytest.approx(2 * math.exp(-6 * 81 / (216 + 36)))


def test_average_ranks_share_ties() -> None:
    assert stats.average_ranks(np.array([10.0, 20.0, 10.0, 30.0])).tolist() == [1.5, 3, 1.5, 4]


def test_median_ci_brackets_median() -> None:
    values = np.arange(1, 101, dtype=np.float64)
    median, low, high = stats.median_ci(values)
    assert median == 50.5
    assert low < median < high
    assert (low, high) == (40.0, 61.0)


def test_annualize_uses_log_slope() -> None:
    assert stats.annualize(math.log(1.3) / 365.25) == pytest.approx(30.0)


def test_planted_growth_is_recovered() -> None:
    result = analyze(synthetic.growth(30.0))
    low, high = result.trend_clean.pct_per_year_log_ci
    assert low < 30.0 < high
    assert result.trend_clean.pct_per_year_log == pytest.approx(30.0, abs=2.0)
    assert result.trend_clean.mk.p < 1e-10
    assert not result.level_shift


def test_flat_noise_gives_uniform_p_values() -> None:
    rng = np.random.default_rng(11)
    p = np.array([stats.mann_kendall(rng.normal(size=104)).p for _ in range(400)])
    assert 0.02 < np.mean(p < 0.05) < 0.08
    assert np.histogram(p, bins=4, range=(0, 1))[0].min() > 70


def test_flat_series_has_no_trend_and_small_mde() -> None:
    result = analyze(synthetic.flat())
    assert result.trend_clean.mk.p > result.alpha
    assert not result.trend_clean.log.excludes_zero
    assert 0 < result.mde_pct_per_year < 5


def test_decaying_spike_is_found_with_its_tail() -> None:
    values = synthetic.with_events(synthetic.flat(), (700,), height=40)
    scan = stats.detect_spikes(values)
    assert len(scan.events) == 1
    event = scan.events[0]
    assert event.start == 700
    assert event.end >= 710
    assert event.ratio > 20


def test_ordinary_noise_is_not_a_spike() -> None:
    assert stats.detect_spikes(synthetic.flat()).events == ()


def test_low_traffic_mad_floor_prevents_infinite_z() -> None:
    values = np.full(100, 3.0)
    values[50] = 4.0
    scan = stats.detect_spikes(values)
    assert np.isfinite(scan.z[50])
    assert not scan.spike_days.any()


def test_growth_from_events_loses_significance_when_cleaned() -> None:
    values = synthetic.with_events(synthetic.flat(), (560, 610, 660, 710, 760))
    result = analyze(values)
    assert result.trend_all.mk.p < 0.05
    assert result.trend_clean.mk.p >= 0.05


def test_step_is_a_level_shift_not_growth() -> None:
    result = analyze(synthetic.with_step(synthetic.flat(), 400, 1.6))
    assert result.level_shift
    assert result.step.ratio == pytest.approx(1.6, rel=0.05)
    assert abs(result.step.day - 400) <= 7
    assert not result.multiple_changepoints


def test_linear_growth_is_not_a_level_shift() -> None:
    assert not analyze(synthetic.growth(40.0)).level_shift


def test_small_step_is_not_a_level_shift() -> None:
    assert not analyze(synthetic.with_step(synthetic.flat(), 400, 1.08)).level_shift


def test_seasonality_is_removed_not_read_as_trend() -> None:
    result = analyze(synthetic.seasonal(0.3))
    assert result.seasonality.month_amplitude == pytest.approx(math.expm1(0.6), rel=0.25)
    assert result.trend_clean.mk.p > 0.05


def test_short_window_has_no_month_offsets() -> None:
    result = analyze(synthetic.flat(n=400))
    assert result.seasonality.month is None
    assert result.seasonality.month_amplitude == 0.0


def test_weekday_offsets_are_recovered() -> None:
    offsets = stats.estimate_seasonality(synthetic.series(synthetic.flat())).weekday
    expected = np.log(synthetic.WEEKDAY) - np.log(synthetic.WEEKDAY).mean()
    assert np.allclose(offsets, expected, atol=0.05)


def test_autocorrelated_weeks_tighten_alpha() -> None:
    rng = np.random.default_rng(5)
    walk = np.cumsum(rng.normal(0, 0.03, 800))
    result = analyze(np.round(synthetic.flat() * np.exp(walk)))
    assert result.autocorrelation > stats.AUTOCORR_LIMIT
    assert result.alpha == stats.STRICT_ALPHA


def test_mde_does_not_collapse_on_tied_low_counts() -> None:
    values = np.random.default_rng(2).poisson(12, 800).astype(np.float64)
    assert analyze(values).mde_pct_per_year > 1.0


def test_too_few_weeks_returns_none() -> None:
    series = synthetic.series(synthetic.flat(n=180))
    assert TrendAnalyzer().analyze(series, np.zeros(180, dtype=bool)) is None


def test_strong_seasonality_rarely_reads_as_trend() -> None:
    false_alarms = 0
    for seed in range(20):
        result = analyze(synthetic.seasonal(0.3, seed=seed))
        false_alarms += result.trend_clean.mk.p < result.alpha or result.level_shift
    assert false_alarms <= 3
