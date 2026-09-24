"""One-page A4 PDF report: header, charts, metrics table, findings and limitations.

The page never grows: text that does not fit is cut with an ellipsis and the cut is
reported in metrics.json. A second page would break the contract.
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from matplotlib.axes import Axes
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.transforms import Bbox

from . import __version__, narrative
from .analysis import LanguageResult
from .render import (
    MAX_COLOURS,
    draw_normalized,
    draw_ranking,
    draw_timeseries,
    plt,
    save_charts,
    style,
)
from .service import RunResult

A4_INCHES = (8.27, 11.69)
PAGE_PNG_DPI = 110
MARGIN_X = 0.55
MARGIN_TOP = 0.35
MARGIN_BOTTOM = 0.3
HEADER_INCHES = 0.62
C1_INCHES = 2.1
C2_INCHES = 1.6
ROW_INCHES = 0.18
LIMITS_INCHES = 1.45
FINDINGS_FONT = 6.6
LIMITS_FONT = 5.7
LINE_SPACING = 1.25
# Baseline-to-baseline distance at linespacing 1.0, in font sizes (measured on the PNG).
LINE_HEIGHT_EM = 1.02
# Share of the measured line width to use; long words must not spill into the next column.
WRAP_SLACK = 0.9
TITLE_CHARS = 28
MAX_TABLE_ROWS = 10
MIN_FINDINGS_INCHES = 0.4
COLUMNS = ("Lang", "Article", "Verdict", "Conf.", "Change per year", "Views/day", "Per million")
COLUMN_WIDTHS = (0.06, 0.24, 0.2, 0.08, 0.18, 0.12, 0.12)
CUT_NOTE = "… (cut to fit one page; the full text is in metrics.json)"


@dataclass(frozen=True, slots=True)
class BuiltReport:
    pdf: Path
    png: Path
    charts: list[Path]
    truncated: bool


def _signed(value: float) -> str:
    rounded = round(value)
    return "0" if rounded == 0 else f"{rounded:+d}"


def _change(result: LanguageResult) -> str:
    a = result.assessment
    if a.pct_per_year is not None and a.pct_ci is not None:
        low, high = a.pct_ci
        return f"{_signed(a.pct_per_year)}% ({_signed(low)} to {_signed(high)})"
    if a.step_ratio is not None:
        return f"step x{a.step_ratio:.2f}"
    if a.level_shift:
        return "step (size withheld)"
    if a.mde_pct_per_year is not None:
        return f"MDE ±{a.mde_pct_per_year:.0f}%"
    return "-"


def table_rows(run: RunResult) -> list[list[str]]:
    rows = []
    for result in run.ordered:
        a = result.assessment
        title = textwrap.shorten(result.article.title, TITLE_CHARS, placeholder="…")
        verdict = narrative.label(a.verdict)
        if a.blocking is not None:
            verdict = f"{verdict} ({a.blocking.gate.split('_')[0]})"
        rows.append(
            [
                result.lang,
                title,
                verdict,
                str(a.confidence) if a.confidence else "-",
                _change(result),
                f"{result.reach.value:,.0f}" if result.reach else "-",
                f"{result.penetration.value:.1f}" if result.penetration else "-",
            ]
        )
    rows += [[lang, "-", "no article", "-", "-", "-", "-"] for lang in run.missing]
    if len(rows) > MAX_TABLE_ROWS:
        hidden = len(rows) - MAX_TABLE_ROWS + 1
        rows = [*rows[: MAX_TABLE_ROWS - 1], ["…", f"+{hidden} more in metrics.json", *"-----"]]
    return rows


class PageLayout:
    """Hands out horizontal bands from the top of the page, in inches."""

    def __init__(self, fig: Figure) -> None:
        self._fig = fig
        self._width, self._height = fig.get_figwidth(), fig.get_figheight()
        self._cursor = self._height - MARGIN_TOP

    @property
    def remaining(self) -> float:
        return self._cursor - MARGIN_BOTTOM

    def band(self, height: float, gap_after: float = 0.0) -> tuple[float, float, float, float]:
        """Figure-fraction rectangle (left, bottom, width, height) of the next band."""
        bottom = self._cursor - height
        self._cursor = bottom - gap_after
        return (
            MARGIN_X / self._width,
            bottom / self._height,
            1 - 2 * MARGIN_X / self._width,
            height / self._height,
        )


class TextBox:
    """Wraps text by measured glyph widths and cuts it to the lines that fit."""

    def __init__(self, ax: Axes, fontsize: float) -> None:
        self._ax = ax
        self._fontsize = fontsize
        fig = ax.get_figure()
        assert isinstance(fig, Figure)
        box = ax.get_position()
        self._width_pt = box.width * fig.get_figwidth() * 72
        self._height_pt = box.height * fig.get_figheight() * 72
        self._renderer = fig.canvas.get_renderer()  # pyright: ignore[reportAttributeAccessIssue]

    def _chars_per_line(self, sample: str) -> int:
        prop = FontProperties(family="DejaVu Sans", size=self._fontsize)
        width, _, _ = self._renderer.get_text_width_height_descent(sample, prop, ismath=False)
        per_char = width * 72 / self._renderer.dpi / max(len(sample), 1)
        return max(20, int(self._width_pt / per_char * WRAP_SLACK))

    def write(self, heading: str, items: list[str]) -> bool:
        """Returns True when lines had to be cut."""
        ax = self._ax
        ax.set_axis_off()
        heading_pt = (self._fontsize + 1.5) * 1.8 if heading else 0.0
        pitch = self._fontsize * LINE_SPACING * LINE_HEIGHT_EM
        capacity = max(1, math.floor((self._height_pt - heading_pt) / pitch))
        chars = self._chars_per_line(" ".join(items) or "x")
        lines: list[str] = []
        for item in items:
            lines += textwrap.wrap(item, chars, subsequent_indent="   ") or [""]
        cut = len(lines) > capacity
        if cut:
            lines = [*lines[: capacity - 1], CUT_NOTE]
        if heading:
            ax.text(0, 1, heading, fontsize=self._fontsize + 1.5, weight="bold", va="top")
        ax.text(
            0,
            1 - heading_pt / self._height_pt,
            "\n".join(lines),
            fontsize=self._fontsize,
            va="top",
            linespacing=LINE_SPACING,
        )
        return cut


def _title(run: RunResult) -> str:
    request = run.request
    subject = request.topic or ", ".join(f"{a.lang}:{a.title}" for a in request.titles)
    return f"Wikipedia interest: {subject} ({', '.join(request.langs)})"


class ReportBuilder:
    """Lays the page out band by band; the page size never depends on the text."""

    def build(self, run: RunResult, metrics: dict[str, Any], directory: Path) -> BuiltReport:
        charts = save_charts(run, directory)
        with style():
            fig = plt.figure(figsize=A4_INCHES)
            truncated = self._page(fig, run, metrics)
            pdf = directory / "report.pdf"
            info = {
                "Title": _title(run),
                "Author": "wikitrends",
                "Subject": metrics.get("question") or _title(run),
                "Creator": f"wikitrends {__version__}",
                "Producer": "matplotlib",
                # The one line that makes the PDF byte-for-byte reproducible.
                "CreationDate": None,
            }
            with PdfPages(pdf, metadata=info) as pages:
                pages.savefig(fig)
            png = directory / "report.png"
            fig.savefig(png, dpi=PAGE_PNG_DPI, metadata={"Software": None})
            plt.close(fig)
        return BuiltReport(pdf, png, charts, truncated)

    def _page(self, fig: Figure, run: RunResult, metrics: dict[str, Any]) -> bool:
        layout = PageLayout(fig)
        self._header(fig.add_axes(layout.band(HEADER_INCHES, 0.1)), run, metrics)
        layout.band(self._legend_inches(run, 4))
        c1 = fig.add_gridspec(1, 1, **self._edges(layout.band(C1_INCHES, 0.62)))
        draw_timeseries(fig, c1[0], run)
        layout.band(self._legend_inches(run, 6))
        c23 = fig.add_gridspec(1, 2, **self._edges(layout.band(C2_INCHES, 0.5)), wspace=0.45)
        draw_normalized(fig, c23[0], run)
        draw_ranking(fig, c23[1], run)
        rows = table_rows(run)
        self._table(fig.add_axes(layout.band(ROW_INCHES * (len(rows) + 1), 0.16)), rows)
        findings_inches = layout.remaining - LIMITS_INCHES - 0.1
        findings = [f"• {line}" for line in metrics["conclusions"]]
        findings += [f"• Note: {warning}" for warning in metrics["warnings"]]
        if findings_inches < MIN_FINDINGS_INCHES:
            # No room left: the findings stay in metrics.json and the answer.
            cut = True
        else:
            box = fig.add_axes(layout.band(findings_inches, 0.1))
            cut = TextBox(box, FINDINGS_FONT).write("Findings", findings)
        return cut | self._limitations(fig, layout, metrics["limitations"])

    @staticmethod
    def _legend_inches(run: RunResult, columns: int) -> float:
        """Room for a legend above a shared chart; small multiples label their panels."""
        count = len(run.results)
        if count > MAX_COLOURS:
            return 0.12
        return 0.12 + 0.14 * math.ceil(count / columns)

    @staticmethod
    def _edges(rect: tuple[float, float, float, float]) -> dict[str, float]:
        """GridSpec edges of a band, leaving room for the y-axis labels."""
        left, bottom, width, height = rect
        return {
            "left": left + 0.04,
            "bottom": bottom,
            "right": left + width,
            "top": bottom + height,
        }

    @staticmethod
    def _limitations(fig: Figure, layout: PageLayout, items: list[str]) -> bool:
        numbered = [f"{i}. {text}" for i, text in enumerate(items, 1)]
        left, bottom, width, height = layout.band(LIMITS_INCHES)
        heading = fig.add_axes((left, bottom, width, height))
        heading.set_axis_off()
        heading.text(
            0, 1, "Assumptions and limitations", fontsize=LIMITS_FONT + 1.5, weight="bold", va="top"
        )
        top_gap = (LIMITS_FONT + 1.5) * 1.8 / 72 / fig.get_figheight()
        half = math.ceil(len(numbered) / 2)
        cut = False
        for column, chunk in enumerate((numbered[:half], numbered[half:])):
            rect = (left + column * width / 2, bottom, width / 2 - 0.01, height - top_gap)
            cut |= TextBox(fig.add_axes(rect), LIMITS_FONT).write("", chunk)
        return cut

    @staticmethod
    def _header(ax: Axes, run: RunResult, metrics: dict[str, Any]) -> None:
        ax.set_axis_off()
        span = run.request.span
        ax.text(0, 1, _title(run), fontsize=12, weight="bold", va="top")
        lines = []
        question = metrics.get("question")
        if question:
            lines.append(textwrap.shorten(f"Question: {question}", 150, placeholder="…"))
        lines.append(
            f"{span.start} to {span.end} ({span.days} days) · human pageviews "
            "(agent=user, all-access) from the Wikimedia REST API · "
            f"wikitrends {__version__}"
        )
        ax.text(0, 0.55, "\n".join(lines), fontsize=7, color="#333333", va="top")
        if any("synthetic" in w for w in metrics["warnings"]):
            ax.text(
                1,
                1,
                "SYNTHETIC DATA",
                fontsize=9,
                weight="bold",
                color="#D55E00",
                ha="right",
                va="top",
            )

    @staticmethod
    def _table(ax: Axes, rows: list[list[str]]) -> None:
        ax.set_axis_off()
        table = ax.table(
            cellText=rows,
            colLabels=COLUMNS,
            colWidths=COLUMN_WIDTHS,
            cellLoc="left",
            bbox=Bbox.from_bounds(0, 0, 1, 1),
        )
        table.auto_set_font_size(False)
        table.set_fontsize(6.8)
        for (row, _), cell in table.get_celld().items():
            cell.set_edgecolor("#DDDDDD")
            cell.set_linewidth(0.5)
            if row == 0:
                cell.set_text_props(weight="bold", color="#333333")
                cell.set_facecolor("#F2F2F2")
