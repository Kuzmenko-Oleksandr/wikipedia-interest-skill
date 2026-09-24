"""Charts. They draw the masks computed in stats.py and never detect anything themselves."""

from __future__ import annotations

import math
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Must precede the pyplot import.

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from cycler import cycler
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.gridspec import SubplotSpec
from matplotlib.typing import RcKeyType
from numpy.typing import NDArray

from . import narrative
from .analysis import LanguageResult
from .series import rolling_median
from .service import RunResult
from .verdict import Verdict

__all__ = [
    "CHART_FILES",
    "MAX_COLOURS",
    "draw_normalized",
    "draw_ranking",
    "draw_timeseries",
    "palette",
    "plt",
    "save_charts",
    "style",
]

# Okabe-Ito: distinguishable under all three common colour-vision deficiencies.
OKABE_ITO = (
    "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442", "#000000",
)  # fmt: skip
MAX_COLOURS = len(OKABE_ITO)
GREY = "#8C8C8C"
SMOOTH_DAYS = 7
LOG_SCALE_RATIO = 20.0
PNG_DPI = 150
MULTIPLE_COLUMNS = 4

STYLE: dict[RcKeyType, Any] = {
    "font.family": "DejaVu Sans",
    "font.size": 8,
    "pdf.fonttype": 42,
    "axes.prop_cycle": cycler(color=OKABE_ITO),
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titlesize": 9,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "legend.frameon": False,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "svg.hashsalt": "wikitrends",
}

CHART_FILES = ("chart-timeseries.png", "chart-normalized.png", "chart-ranking.png")


@contextmanager
def style() -> Generator[None]:
    """Explicit style so a user matplotlibrc cannot swap in a font without Cyrillic."""
    with plt.rc_context(STYLE):
        yield


def palette(langs: Sequence[str]) -> dict[str, str]:
    """Stable colour per language; beyond eight series the charts switch to small multiples."""
    ordered = sorted(langs)
    if len(ordered) > MAX_COLOURS:
        return dict.fromkeys(ordered, OKABE_ITO[0])
    return {lang: OKABE_ITO[i] for i, lang in enumerate(ordered)}


def _dates(result: LanguageResult) -> NDArray[np.datetime64]:
    """Real dates, never preformatted strings, so the date locators work."""
    return result.views.dates


def _date_axis(ax: Axes, days: int, max_ticks: int = 8) -> None:
    months = max(1, math.ceil(days / 30.4 / max_ticks))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=months))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))  # Mondays


def _legend_above(ax: Axes, entries: int, columns: int) -> float:
    """Legend between title and plot, so it never hides data; returns the title pad."""
    columns = max(1, min(columns, entries))
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0, 1.0),
        ncols=columns,
        borderaxespad=0.3,
        handlelength=1.4,
        columnspacing=1.0,
    )
    return 6 + 10 * math.ceil(entries / columns)


def _needs_log(levels: Sequence[float]) -> bool:
    positive = [v for v in levels if v > 0]
    return len(positive) > 1 and max(positive) / min(positive) > LOG_SCALE_RATIO


def _panels(fig: Figure, spec: SubplotSpec, count: int) -> list[Axes]:
    """One shared axes for up to eight series, otherwise a grid of small multiples."""
    if count <= MAX_COLOURS:
        return [fig.add_subplot(spec)] * max(count, 1)
    rows = math.ceil(count / MULTIPLE_COLUMNS)
    grid = spec.subgridspec(rows, MULTIPLE_COLUMNS, hspace=0.6, wspace=0.3)
    return [
        fig.add_subplot(grid[i // MULTIPLE_COLUMNS, i % MULTIPLE_COLUMNS]) for i in range(count)
    ]


def _chart_title(fig: Figure, spec: SubplotSpec, axes: list[Axes], title: str, pad: float) -> None:
    """On a shared axes the axes title; over small multiples a label above the grid."""
    if len(set(map(id, axes))) == 1:
        axes[0].set_title(title, loc="left", pad=pad)
        return
    box = spec.get_position(fig)
    fig.text(box.x0, box.y1 + 0.012, title, fontsize=9, weight="bold", va="bottom")


def draw_timeseries(fig: Figure, spec: SubplotSpec, run: RunResult) -> None:
    """C1: raw daily views thin, a 7-day median bold, spikes as hollow circles."""
    results = run.ordered
    colours = palette([r.lang for r in results])
    axes = _panels(fig, spec, len(results))
    shared = len(set(map(id, axes))) == 1
    levels = [r.reach.value for r in results if r.reach]
    pad = 6.0
    largest: tuple[float, date, float, Axes] | None = None
    for ax, result in zip(axes, results, strict=False):
        colour = colours[result.lang]
        days = _dates(result)
        values = result.views.values
        ax.plot(days, values, lw=0.6, alpha=0.35, color=colour)
        smooth = rolling_median(values, SMOOTH_DAYS, min_periods=4)
        ax.plot(days, smooth, lw=1.6, color=colour, label=f"{result.lang}: {result.article.title}")
        spikes = np.flatnonzero(result.spikes.spike_days)
        if spikes.size:
            ax.scatter(
                days[spikes],
                values[spikes],
                s=14,
                facecolors="none",
                edgecolors=colour,
                linewidths=0.8,
                zorder=3,
            )
        for event in result.spikes.events:
            if largest is None or event.ratio > largest[0]:
                largest = (event.ratio, result.views.day(event.peak), float(values[event.peak]), ax)
        if not shared:
            ax.set_title(result.lang, fontsize=7)
            _date_axis(ax, len(days))
    if shared and results:
        ax = axes[0]
        if _needs_log(levels):
            ax.set_yscale("log")
            ax.set_ylabel("views/day (log scale)")
        else:
            ax.set_ylabel("views/day")
            ax.set_ylim(bottom=0)
        _date_axis(ax, run.request.span.days)
        pad = _legend_above(ax, len(results), 4)
    if largest is not None:
        ratio, day, value, ax = largest
        ax.annotate(
            f"{day.isoformat()}, {ratio:.0f}x",
            xy=(np.datetime64(day, "D"), value),
            xytext=(-70, -6),
            textcoords="offset points",
            fontsize=7,
            arrowprops={"arrowstyle": "-", "lw": 0.6, "color": GREY},
        )
    title = "Daily views (thin) and 7-day median (bold); circles mark spikes"
    _chart_title(fig, spec, axes, title, pad)


def draw_normalized(fig: Figure, spec: SubplotSpec, run: RunResult) -> None:
    """C2: views per million views of the whole edition, the only cross-language scale."""
    results = [r for r in run.ordered if r.vpm is not None]
    colours = palette([r.lang for r in run.ordered])
    axes = _panels(fig, spec, len(results))
    shared = len(set(map(id, axes))) == 1
    pad = 6.0
    for ax, result in zip(axes, results, strict=False):
        assert result.vpm is not None
        smooth = rolling_median(result.vpm.values, SMOOTH_DAYS, min_periods=4)
        ax.plot(_dates(result), smooth, lw=1.2, color=colours[result.lang], label=result.lang)
        if not shared:
            ax.set_title(result.lang, fontsize=7)
            _date_axis(ax, len(result.views))
    ax = axes[0]
    if not results:
        ax.text(0.5, 0.5, "No edition totals available", ha="center", transform=ax.transAxes)
        ax.set_axis_off()
    elif shared:
        levels = [r.penetration.value for r in results if r.penetration]
        if _needs_log(levels):
            ax.set_yscale("log")
        else:
            ax.set_ylim(bottom=0)
        ax.set_ylabel("per million edition views")
        _date_axis(ax, run.request.span.days, max_ticks=4)
        pad = _legend_above(ax, len(results), 6)
    _chart_title(fig, spec, axes, "Views per million edition views (7-day median)", pad)


def _momentum(result: LanguageResult) -> str:
    a = result.assessment
    if a.pct_per_year is not None and a.verdict in (Verdict.GROWING, Verdict.DECLINING):
        return f"{a.pct_per_year:+.0f}%/yr"
    return narrative.label(a.verdict)


def draw_ranking(fig: Figure, spec: SubplotSpec, run: RunResult) -> None:
    """C3: horizontal bars of penetration with intervals; tiers named, refusals listed apart."""
    ax = fig.add_subplot(spec)
    colours = palette([r.lang for r in run.ordered])
    rows: list[tuple[str, LanguageResult | None]] = []
    for tier_no, tier in enumerate(run.ranking.tiers, 1):
        rows += [(f"{lang}  T{tier_no}", run.results[lang]) for lang in tier]
    rows += [(lang, None) for lang in (*run.ranking.unranked, *run.missing)]
    y = np.arange(len(rows))[::-1]
    peak = max((r.penetration.high for _, r in rows if r and r.penetration), default=1.0)
    for pos, (_, result) in zip(y, rows, strict=True):
        if result is None or result.penetration is None:
            ax.text(0, pos, " not ranked: no usable data", va="center", fontsize=7, color=GREY)
            continue
        p = result.penetration
        ax.barh(pos, p.value, color=colours[result.lang], height=0.6)
        ax.errorbar(
            p.value,
            pos,
            xerr=[[p.value - p.low], [p.high - p.value]],
            fmt="none",
            ecolor="#333333",
            elinewidth=0.8,
            capsize=2,
        )
        ax.text(p.high + 0.02 * peak, pos, _momentum(result), va="center", fontsize=7)
    ax.set_yticks(y, [name for name, _ in rows])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.set_xlim(0, peak * 1.45)
    ax.set_xlabel("per million edition views (median, 95% CI)")
    ax.set_title("Share of attention (T = tier)", loc="left")


def save_charts(run: RunResult, directory: Path) -> list[Path]:
    """Standalone PNGs with fixed size and resolution; no software stamp in the metadata."""
    paths = []
    drawers = (draw_timeseries, draw_normalized, draw_ranking)
    sizes = ((8.0, 3.4), (5.0, 3.2), (5.0, 3.2))
    with style():
        for name, draw, size in zip(CHART_FILES, drawers, sizes, strict=True):
            fig = plt.figure(figsize=size, dpi=PNG_DPI, layout="constrained")
            draw(fig, fig.add_gridspec(1, 1)[0], run)
            path = directory / name
            fig.savefig(path, dpi=PNG_DPI, metadata={"Software": None})
            plt.close(fig)
            paths.append(path)
    return paths
