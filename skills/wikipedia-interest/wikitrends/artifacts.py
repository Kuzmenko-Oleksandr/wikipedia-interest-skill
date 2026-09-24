"""Files of one run under out/<slug>/ with fixed, boring names."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .errors import WikitrendsError
from .output import metrics_payload
from .service import RunResult

METRICS = "metrics.json"
DATA = "data.csv"


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    directory: Path
    metrics_json: Path
    data_csv: Path
    report_pdf: Path | None = None
    report_png: Path | None = None
    charts: list[Path] = field(default_factory=list)

    def for_stdout(self) -> dict[str, Path | list[Path] | None]:
        return {
            "report_pdf": self.report_pdf,
            "report_png": self.report_png,
            "charts": self.charts or None,
            "metrics_json": self.metrics_json,
            "data_csv": self.data_csv,
        }


class ArtifactWriter:
    """Same request, same folder: reruns overwrite instead of piling up."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def directory(self, slug: str) -> Path:
        return self._root / slug

    def write(self, run: RunResult, question: str, with_report: bool) -> ArtifactPaths:
        directory = self.directory(run.request.slug)
        directory.mkdir(parents=True, exist_ok=True)
        metrics = metrics_payload(run, question)
        data_csv = directory / DATA
        _write_csv(run, data_csv)
        charts: list[Path] = []
        pdf = png = None
        if with_report:
            # Imported late: matplotlib is slow to load and only needed here.
            from .report import ReportBuilder

            built = ReportBuilder().build(run, metrics, directory)
            charts, pdf, png = built.charts, built.pdf, built.png
            metrics["report_truncated"] = built.truncated
        metrics_json = directory / METRICS
        metrics_json.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        return ArtifactPaths(directory, metrics_json, data_csv, pdf, png, charts)

    def read_metrics(self, slug: str) -> dict[str, Any]:
        path = self.directory(slug) / METRICS
        if not path.exists():
            raise WikitrendsError(
                f"no run {slug!r} under {self._root}",
                "Pass the slug printed by compare or analyze, with the same --out-dir.",
            )
        return json.loads(path.read_text(encoding="utf-8"))


def _cell(value: float) -> str:
    return "" if np.isnan(value) else f"{value:.6g}"


def _write_csv(run: RunResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["date", "lang", "views", "edition_total", "views_per_million", "spike", "excluded"]
        )
        for result in run.ordered:
            spikes, excluded = result.spikes.spike_days, result.spikes.mask
            total = result.total.values if result.total is not None else None
            vpm = result.vpm.values if result.vpm is not None else None
            for i, day in enumerate(result.views.span.dates()):
                writer.writerow(
                    [
                        day.isoformat(),
                        result.lang,
                        _cell(result.views.values[i]),
                        _cell(total[i]) if total is not None else "",
                        _cell(vpm[i]) if vpm is not None else "",
                        int(spikes[i]),
                        int(excluded[i]),
                    ]
                )
