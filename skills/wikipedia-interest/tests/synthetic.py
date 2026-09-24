"""Synthetic daily series with a known answer."""

from __future__ import annotations

from datetime import date

import numpy as np

from wikitrends.series import DailySeries, FloatArray

START = date(2024, 1, 1)
DAYS = 800
LEVEL = 200.0
WEEKDAY = np.array([1.0, 1.1, 1.1, 1.05, 0.95, 0.8, 0.8])


def _base(n: int, rng: np.random.Generator, noise: float) -> FloatArray:
    t = np.arange(n)
    weekday = WEEKDAY[(t + START.weekday()) % 7]
    return LEVEL * weekday * np.exp(rng.normal(0, noise, n))


def growth(pct_per_year: float, n: int = DAYS, seed: int = 1, noise: float = 0.1) -> FloatArray:
    rng = np.random.default_rng(seed)
    rate = np.log1p(pct_per_year / 100) / 365.25
    return np.round(_base(n, rng, noise) * np.exp(rate * np.arange(n)))


def flat(n: int = DAYS, seed: int = 1, noise: float = 0.1) -> FloatArray:
    return growth(0.0, n, seed, noise)


def with_events(values: FloatArray, peaks: tuple[int, ...], height: float = 25.0) -> FloatArray:
    """News spikes decaying with a 3-day e-folding time."""
    out = values.astype(np.float64).copy()
    for peak in peaks:
        d = np.arange(len(out)) - peak
        out *= np.where(d >= 0, 1 + height * np.exp(-np.clip(d, 0, None) / 3.0), 1.0)
    return np.round(out)


def with_step(values: FloatArray, at: int, ratio: float) -> FloatArray:
    out = values.astype(np.float64).copy()
    out[at:] *= ratio
    return np.round(out)


def seasonal(amplitude: float, n: int = DAYS, seed: int = 1) -> FloatArray:
    rng = np.random.default_rng(seed)
    cycle = np.exp(amplitude * np.sin(2 * np.pi * np.arange(n) / 365.25))
    return np.round(_base(n, rng, 0.1) * cycle)


def series(values: FloatArray) -> DailySeries:
    return DailySeries(START, values)
