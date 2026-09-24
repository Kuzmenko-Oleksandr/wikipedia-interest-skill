"""Robust trend statistics.

Estimators are plain functions over numpy arrays. `TrendAnalyzer` runs them in the
order the methodology fixes: seasonality, weekly medians, trend (with and without
spikes), change point. Formulas and worked examples are in references/methodology.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from .series import WEEK, DailySeries, FloatArray, WeeklySeries, rolling_median

BoolArray = NDArray[np.bool_]

ALPHA = 0.05
STRICT_ALPHA = 0.01
AUTOCORR_LIMIT = 0.3
POWER = 0.8
MIN_WEEKS = 26
DAYS_PER_YEAR = 365.25

SPIKE_WINDOW = 15
MAD_SCALE = 1.4826
SPIKE_Z = 5.0
MIN_SPIKE_RATIO = 1.5
ELEVATED_Z = 3.5
DIP_Z = -5.0
SIGMA_FLOOR = 1.0
SIGMA_FLOOR_SHARE = 0.05
EVENT_MERGE_GAP = 3
TAIL_Z = 2.0
TAIL_CALM_DAYS = 2
MAX_TAIL_DAYS = 14

STEP_MARGIN = 0.9
MIN_STEP_CHANGE = 0.15
MIN_SEGMENT_WEEKS = 8
WEEKDAY_WINDOW = 7
YEAR_WEEKS = 53
SEASONAL_PASSES = 3
ANNUAL_BASELINE_DAYS = 730
LOG_OFFSET_SHARE = 0.01


def z_crit(alpha: float) -> float:
    """Two-sided standard normal critical value."""
    return NormalDist().inv_cdf(1 - alpha / 2)


def two_sided_p(z: float) -> float:
    """Normal p-value from the stdlib at full double precision."""
    return math.erfc(abs(z) / math.sqrt(2))


def annualize(log_slope: float) -> float:
    """Per-day slope of the log series to percent change per year."""
    return 100 * math.expm1(DAYS_PER_YEAR * log_slope)


@dataclass(frozen=True, slots=True)
class Slope:
    """Theil-Sen fit with a rank-based confidence interval for the slope."""

    slope: float
    intercept: float
    low: float
    high: float

    def at(self, t: float) -> float:
        return self.intercept + self.slope * t

    @property
    def excludes_zero(self) -> bool:
        return self.low > 0 or self.high < 0


def _pairwise_slopes(t: FloatArray, y: FloatArray) -> FloatArray:
    i, j = np.triu_indices(len(t), k=1)
    dt = t[j] - t[i]
    keep = dt != 0
    return np.sort((y[j] - y[i])[keep] / dt[keep])


def sen_line(t: FloatArray, y: FloatArray) -> tuple[float, float]:
    """Theil-Sen slope and intercept without the interval."""
    slope = float(np.median(_pairwise_slopes(t, y)))
    return slope, float(np.median(y - slope * t))


def theil_sen(t: FloatArray, y: FloatArray, alpha: float = ALPHA) -> Slope:
    """Median of pairwise slopes; the interval uses order statistics (Sen, 1968).

    Args:
        t: True day index of each point; never renumbered after dropping points.
        y: Values at `t`.
        alpha: Two-sided level of the slope interval.
    """
    slopes = _pairwise_slopes(t, y)
    if slopes.size == 0:
        raise ValueError("Theil-Sen needs at least two distinct t values")
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * t))
    spread = z_crit(alpha) * math.sqrt(mk_variance(y))
    n = slopes.size
    lower = max(round((n - spread) / 2) - 1, 0)
    upper = min(round((n + spread) / 2), n - 1)
    return Slope(slope, intercept, float(slopes[lower]), float(slopes[upper]))


@dataclass(frozen=True, slots=True)
class MannKendall:
    s: int
    variance: float
    z: float
    p: float


def mk_variance(y: FloatArray) -> float:
    """Var(S) with the tie correction; low-traffic articles repeat values a lot."""
    n = len(y)
    _, counts = np.unique(y, return_counts=True)
    ties = counts[counts > 1].astype(np.float64)
    return float(n * (n - 1) * (2 * n + 5) - np.sum(ties * (ties - 1) * (2 * ties + 5))) / 18


def mann_kendall(y: FloatArray) -> MannKendall:
    """Mann-Kendall test with tie-corrected variance and continuity correction."""
    i, j = np.triu_indices(len(y), k=1)
    s = int(np.sign(y[j] - y[i]).sum())
    variance = mk_variance(y)
    z = 0.0 if s == 0 or variance <= 0 else (s - math.copysign(1, s)) / math.sqrt(variance)
    return MannKendall(s, variance, z, two_sided_p(z))


def average_ranks(y: FloatArray) -> FloatArray:
    """1-based ranks, ties get the mean of their positions."""
    order = np.argsort(y, kind="mergesort")
    _, first, counts = np.unique(y[order], return_index=True, return_counts=True)
    ranks = np.empty(len(y))
    ranks[order] = np.repeat(first + (counts + 1) / 2, counts)
    return ranks


@dataclass(frozen=True, slots=True)
class ChangePoint:
    """Pettitt test result; `index` is the first point of the second segment."""

    index: int
    statistic: float
    p: float


def pettitt(y: FloatArray) -> ChangePoint:
    """Rank-based single change point test with the usual p-value approximation."""
    n = len(y)
    if n < 2:
        return ChangePoint(0, 0.0, 1.0)
    u = 2 * np.cumsum(average_ranks(y))[:-1] - np.arange(1, n) * (n + 1)
    split = int(np.argmax(np.abs(u)))
    k = float(abs(u[split]))
    p = min(1.0, 2 * math.exp(-6 * k**2 / (n**3 + n**2)))
    return ChangePoint(split + 1, k, p)


def median_ci(values: FloatArray, alpha: float = ALPHA) -> tuple[float, float, float]:
    """Median with a distribution-free interval from order statistics.

    Returns:
        (median, low, high); NaN triple when nothing was observed.
    """
    x = np.sort(values[~np.isnan(values)])
    n = x.size
    if n == 0:
        return math.nan, math.nan, math.nan
    half = z_crit(alpha) * math.sqrt(n) / 2
    low = max(math.floor(n / 2 - half), 1)
    high = min(math.ceil(1 + n / 2 + half), n)
    return float(np.median(x)), float(x[low - 1]), float(x[high - 1])


def lag1_autocorrelation(residuals: FloatArray) -> float:
    r = residuals - residuals.mean()
    denom = float(np.dot(r, r))
    if len(r) < 3 or denom == 0:
        return 0.0
    return float(np.dot(r[:-1], r[1:])) / denom


def _median_abs(values: FloatArray) -> float:
    return float(np.median(np.abs(values)))


@dataclass(frozen=True, slots=True)
class SpikeEvent:
    """Spike days and their decay tail, as day indices into the series."""

    start: int
    peak: int
    end: int
    ratio: float


@dataclass(frozen=True, slots=True, eq=False)
class RobustScore:
    """Robust z-scores of each day against a local median and MAD scale."""

    z: FloatArray
    baseline: FloatArray
    sigma: FloatArray


def _sigma_floor(values: FloatArray) -> float:
    observed = values[~np.isnan(values)]
    typical = float(np.median(observed)) if observed.size else 0.0
    # Low-traffic MAD is often exactly 0; without a floor any wiggle is z = inf.
    return max(SIGMA_FLOOR, SIGMA_FLOOR_SHARE * typical)


def _score(values: FloatArray, windows: NDArray[np.float64]) -> RobustScore:
    """Scores `values` against one window of neighbours per day."""
    baseline = np.full(len(values), np.nan)
    mad = np.full(len(values), np.nan)
    ok = np.count_nonzero(~np.isnan(windows), axis=1) > 0
    baseline[ok] = np.nanmedian(windows[ok], axis=1)
    mad[ok] = np.nanmedian(np.abs(windows[ok] - baseline[ok, None]), axis=1)
    sigma = np.maximum(MAD_SCALE * mad, _sigma_floor(values))
    return RobustScore((values - baseline) / sigma, baseline, sigma)


def centred_score(values: FloatArray) -> RobustScore:
    """Against the centred 15-day window, which contains the day itself."""
    half = SPIKE_WINDOW // 2
    padded = np.pad(values, half, constant_values=np.nan)
    return _score(values, sliding_window_view(padded, SPIKE_WINDOW))


def trailing_score(values: FloatArray) -> RobustScore:
    """Against the 15 days before each day.

    A decay longer than a week fills half of a centred window and lifts its median
    to the spike level; the days before the onset stay clean.
    """
    padded = np.pad(values, (SPIKE_WINDOW, 0), constant_values=np.nan)
    return _score(values, sliding_window_view(padded, SPIKE_WINDOW)[:-1])


@dataclass(frozen=True, slots=True, eq=False)
class SpikeScan:
    """Spike and dip days, and the events the spikes form."""

    z: FloatArray
    spike_days: BoolArray
    dip_days: BoolArray
    events: tuple[SpikeEvent, ...]

    @property
    def elevated_days(self) -> BoolArray:
        z = np.nan_to_num(self.z, nan=0.0)
        return (z > ELEVATED_Z) & (z <= SPIKE_Z)

    @property
    def mask(self) -> BoolArray:
        """Days dropped from the clean series: events with their tails, and dips."""
        mask = self.dip_days.copy()
        for event in self.events:
            mask[event.start : event.end + 1] = True
        return mask


def _clusters(days: NDArray[np.intp]) -> list[tuple[int, int]]:
    clusters: list[tuple[int, int]] = []
    for day in days.tolist():
        if clusters and day - clusters[-1][1] - 1 <= EVENT_MERGE_GAP:
            clusters[-1] = (clusters[-1][0], day)
        else:
            clusters.append((day, day))
    return clusters


def _tail_end(values: FloatArray, last: int, peak: int, base: float, sigma: float) -> int:
    """Last day above the pre-event level before two calm days, capped after the peak."""
    end, calm = last, 0
    for day in range(last + 1, min(peak + MAX_TAIL_DAYS, len(values) - 1) + 1):
        if np.isnan(values[day]):
            continue
        if (values[day] - base) / sigma < TAIL_Z:
            calm += 1
            if calm == TAIL_CALM_DAYS:
                break
        else:
            calm, end = 0, day
    return end


def _spikes(values: FloatArray, score: RobustScore) -> BoolArray:
    # On busy articles a 15-day MAD is tight enough for +30% days to pass z > 5.
    with np.errstate(invalid="ignore"):
        return (score.z > SPIKE_Z) & (values >= MIN_SPIKE_RATIO * score.baseline)


def _spike_days(values: FloatArray, centred: RobustScore, trailing: RobustScore) -> BoolArray:
    """A spike must stand out from the days before it and from the days around it.

    The second test keeps a lasting step, or the return from a summer dip, out:
    past the change the centred median already sits at the new level.
    """
    with np.errstate(invalid="ignore"):
        above_centred = values >= MIN_SPIKE_RATIO * centred.baseline
    return _spikes(values, centred) | (_spikes(values, trailing) & above_centred)


def detect_spikes(values: FloatArray) -> SpikeScan:
    """Finds spike events; charts draw this mask and never detect on their own."""
    centred, trailing = centred_score(values), trailing_score(values)
    spike_days = _spike_days(values, centred, trailing)
    events: list[SpikeEvent] = []
    for first, last in _clusters(np.flatnonzero(spike_days)):
        start = first
        peak = first + int(np.nanargmax(values[first : last + 1]))
        before = trailing if not np.isnan(trailing.baseline[first]) else centred
        base, sigma = float(before.baseline[first]), float(before.sigma[first])
        end = _tail_end(values, last, peak, base, sigma)
        ratio = float(values[peak] / max(base, 1.0))
        if events and start <= events[-1].end + EVENT_MERGE_GAP + 1:
            previous = events.pop()
            start = previous.start
            if values[previous.peak] >= values[peak]:
                peak, ratio = previous.peak, previous.ratio
            end = max(end, previous.end)
        events.append(SpikeEvent(start, peak, end, ratio))
    dip_days = np.nan_to_num(centred.z, nan=0.0) < DIP_Z
    return SpikeScan(np.fmax(centred.z, trailing.z), spike_days, dip_days, tuple(events))


def _weekday(dates: NDArray[np.datetime64]) -> NDArray[np.int64]:
    # 1970-01-01 was a Thursday; Monday is 0.
    return (dates.astype("datetime64[D]").astype(np.int64) + 3) % 7


def _month(dates: NDArray[np.datetime64]) -> NDArray[np.int64]:
    return dates.astype("datetime64[M]").astype(np.int64) % 12


def _group_medians(values: FloatArray, groups: NDArray[np.int64], size: int) -> FloatArray:
    """Median per group, centred on zero; empty groups get 0."""
    out = np.zeros(size)
    for g in range(size):
        member = values[(groups == g) & ~np.isnan(values)]
        if member.size:
            out[g] = np.median(member)
    return out - out.mean()


@dataclass(frozen=True, slots=True)
class LogScale:
    """log(y + c) with c one percent of the series' typical value.

    log1p adds 1 whatever the unit. Views per million are often below 1, and there it
    flattens every rate: +30%/yr read as +9% at 0.4 per million. An offset relative to the
    series keeps rates comparable between raw views and shares and still admits zeros.
    """

    offset: float

    @classmethod
    def of(cls, values: FloatArray) -> LogScale:
        positive = values[np.nan_to_num(values, nan=0.0) > 0]
        typical = float(np.median(positive)) if positive.size else 1.0
        return cls(max(LOG_OFFSET_SHARE * typical, 1e-12))

    def log(self, values: FloatArray) -> FloatArray:
        return np.log(values + self.offset)

    def exp(self, logs: FloatArray) -> FloatArray:
        return np.exp(logs) - self.offset


@dataclass(frozen=True, slots=True, eq=False)
class Seasonality:
    """Additive offsets on the log scale; `month` is None without two full years."""

    scale: LogScale
    weekday: FloatArray
    month: FloatArray | None = None

    def offsets(self, dates: NDArray[np.datetime64]) -> FloatArray:
        out = self.weekday[_weekday(dates)]
        if self.month is not None:
            out = out + self.month[_month(dates)]
        return out

    def remove(self, series: DailySeries) -> DailySeries:
        logs = self.scale.log(series.values) - self.offsets(series.dates)
        return series.replace(self.scale.exp(logs))

    @property
    def month_amplitude(self) -> float:
        """Peak-to-trough of the yearly cycle as a ratio minus one."""
        return math.expm1(float(np.ptp(self.month))) if self.month is not None else 0.0


def estimate_seasonality(series: DailySeries, scale: LogScale | None = None) -> Seasonality:
    """Weekday offsets always; month offsets only when each month is seen twice."""
    scale = scale or LogScale.of(series.values)
    logs = scale.log(series.values)
    weekday_of = _weekday(series.dates)
    local = scale.log(rolling_median(series.values, WEEKDAY_WINDOW))
    weekday = _group_medians(logs - local, weekday_of, 7)
    if len(series) < ANNUAL_BASELINE_DAYS:
        return Seasonality(scale, weekday)
    weekly = series.replace(logs - weekday[weekday_of]).weekly()
    months = _month(series.dates[weekly.t.astype(np.int64)])
    month = np.zeros(12)
    for _ in range(SEASONAL_PASSES):
        # A year-long median filter follows trends and keeps steps sharp, so neither
        # leaks into the month offsets the way a straight-line detrend would. Each pass
        # re-fits it on the adjusted series, shrinking the bias of the partial-year edges.
        level = rolling_median(weekly.values - month[months], YEAR_WEEKS)
        month = _group_medians(weekly.values - level, months, 12)
    return Seasonality(scale, weekday, month)


@dataclass(frozen=True, slots=True)
class TrendFit:
    """Trend of weekly medians; slopes are per day."""

    n_weeks: int
    linear: Slope
    log: Slope
    mk: MannKendall
    level_mid: float

    @property
    def pct_per_year(self) -> float:
        """Linear change relative to the fitted level at the window midpoint."""
        if self.level_mid <= 0:
            return math.nan
        return 100 * self.linear.slope * DAYS_PER_YEAR / self.level_mid

    @property
    def pct_per_year_log(self) -> float:
        """Scale-free change; the only rate comparable across languages."""
        return annualize(self.log.slope)

    @property
    def pct_per_year_log_ci(self) -> tuple[float, float]:
        return annualize(self.log.low), annualize(self.log.high)

    @property
    def direction(self) -> int:
        # With heavy ties the median slope can be exactly 0 while S is clearly signed.
        return int(np.sign(self.log.slope)) or int(np.sign(self.mk.s))


def fit_trend(weekly: WeeklySeries, mid: float, alpha: float, scale: LogScale) -> TrendFit:
    t, y = weekly.points()
    linear = theil_sen(t, y, alpha)
    return TrendFit(
        n_weeks=len(t),
        linear=linear,
        log=theil_sen(t, scale.log(y), alpha),
        mk=mann_kendall(y),
        level_mid=linear.at(mid),
    )


@dataclass(frozen=True, slots=True)
class StepModel:
    """Two-level model at the scanned split, compared with the linear trend.

    `day` is the first day of the first week at the new level.
    """

    day: int
    ratio: float
    residual: float
    linear_residual: float
    long_enough: bool

    @property
    def preferred(self) -> bool:
        # The step model has one more parameter, so it must win by a margin.
        return self.long_enough and self.residual < STEP_MARGIN * self.linear_residual


def step_scan(y: FloatArray, min_segment: int = MIN_SEGMENT_WEEKS) -> int | None:
    """Split that minimizes absolute deviation from the two segment medians.

    Pettitt's statistic keeps growing past a step when the later segment drifts, so it
    only supplies the significance; this scan supplies the location and the size.

    Returns:
        First index of the second segment, or None when either would be too short.
    """
    splits = range(min_segment, len(y) - min_segment + 1)
    if not splits:
        return None
    costs = [
        float(np.abs(y[:k] - np.median(y[:k])).sum() + np.abs(y[k:] - np.median(y[k:])).sum())
        for k in splits
    ]
    return splits[int(np.argmin(costs))]


def fit_step(t: FloatArray, y: FloatArray, split: int, linear: Slope) -> StepModel:
    """Compares a one-step model with the linear fit by median absolute residual."""
    before, after = y[:split], y[split:]
    level_before = float(np.median(before)) if before.size else math.nan
    level_after = float(np.median(after)) if after.size else math.nan
    fitted = np.where(np.arange(len(y)) < split, level_before, level_after)
    return StepModel(
        day=max(int(t[min(split, len(t) - 1)]) - WEEK // 2, 0),
        ratio=math.exp(level_after - level_before),
        residual=_median_abs(y - fitted),
        linear_residual=_median_abs(y - (linear.intercept + linear.slope * t)),
        long_enough=min(before.size, after.size) >= MIN_SEGMENT_WEEKS,
    )


@dataclass(frozen=True, slots=True, eq=False)
class SeriesAnalysis:
    """Everything the verdict needs about one daily series."""

    trend_all: TrendFit
    trend_clean: TrendFit
    alpha: float
    autocorrelation: float
    mde_pct_per_year: float
    seasonality: Seasonality
    changepoint: ChangePoint
    step: StepModel
    multiple_changepoints: bool
    weekly_clean: WeeklySeries

    @property
    def level_shift(self) -> bool:
        big_enough = abs(math.log(self.step.ratio)) >= math.log1p(MIN_STEP_CHANGE)
        return self.changepoint.p < self.alpha and self.step.preferred and big_enough


def _mde(fit: TrendFit, t: FloatArray, log_y: FloatArray, alpha: float) -> float:
    """Smallest yearly change the test would catch with 80% power.

    The rank interval collapses to zero width when most weekly medians tie, so the
    residual-based standard error serves as a floor.
    """
    z = z_crit(alpha)
    se_ranks = (fit.log.high - fit.log.low) / (2 * z)
    residuals = log_y - (fit.log.intercept + fit.log.slope * t)
    spread = float(np.sum((t - t.mean()) ** 2))
    se_residuals = float(np.std(residuals)) / math.sqrt(spread) if spread > 0 else 0.0
    return annualize((z + NormalDist().inv_cdf(POWER)) * max(se_ranks, se_residuals))


class TrendAnalyzer:
    """Facade over the estimators for one daily series (raw views or views per million)."""

    def __init__(self, alpha: float = ALPHA, min_weeks: int = MIN_WEEKS) -> None:
        self._alpha = alpha
        self._min_weeks = min_weeks

    def analyze(self, series: DailySeries, anomalies: BoolArray) -> SeriesAnalysis | None:
        """Runs the trend twice, with and without the anomaly days.

        Returns:
            None when fewer than `min_weeks` complete weeks remain.
        """
        clean = series.masked(anomalies)
        scale = LogScale.of(clean.values)
        seasonality = estimate_seasonality(clean, scale)
        weekly_all = seasonality.remove(series).weekly()
        weekly_clean = seasonality.remove(clean).weekly()
        if min(weekly_all.n_valid, weekly_clean.n_valid) < self._min_weeks:
            return None
        mid = (len(series) - 1) / 2
        alpha = self._alpha
        trend_clean = fit_trend(weekly_clean, mid, alpha, scale)
        t, y = weekly_clean.points()
        log_y = scale.log(y)
        rho = lag1_autocorrelation(log_y - (trend_clean.log.intercept + trend_clean.log.slope * t))
        if rho > AUTOCORR_LIMIT:
            # Autocorrelated weeks overstate significance; demand stronger evidence.
            alpha = min(alpha, STRICT_ALPHA)
            trend_clean = fit_trend(weekly_clean, mid, alpha, scale)
        changepoint = pettitt(log_y)
        split = step_scan(log_y)
        step = fit_step(t, log_y, changepoint.index if split is None else split, trend_clean.log)
        return SeriesAnalysis(
            trend_all=fit_trend(weekly_all, mid, alpha, scale),
            trend_clean=trend_clean,
            alpha=alpha,
            autocorrelation=rho,
            mde_pct_per_year=_mde(trend_clean, t, log_y, alpha),
            seasonality=seasonality,
            changepoint=changepoint,
            step=step,
            multiple_changepoints=step.preferred and _second_step(t, log_y, step),
            weekly_clean=weekly_clean,
        )


def _second_step(t: FloatArray, log_y: FloatArray, step: StepModel) -> bool:
    """Another significant step left in the residuals of the one-step model."""
    split = int(np.searchsorted(t, step.day))
    before, after = log_y[:split], log_y[split:]
    residuals = np.concatenate((before - np.median(before), after - np.median(after)))
    extra = pettitt(residuals)
    flat = Slope(0.0, 0.0, 0.0, 0.0)
    return extra.p < STRICT_ALPHA and fit_step(t, residuals, extra.index, flat).preferred
