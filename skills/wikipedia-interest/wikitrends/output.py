"""JSON payloads: the full metrics file and the single stdout line."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import narrative
from .analysis import Interval, LanguageResult
from .errors import WikitrendsError
from .service import RunResult
from .stats import SeriesAnalysis, TrendFit

SCHEMA = 1
STDOUT_LIMIT = 1024

Payload = dict[str, Any]


def _num(value: float | None, digits: int = 1) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _interval(interval: Interval | None, digits: int = 1) -> dict[str, float | None] | None:
    if interval is None:
        return None
    return {
        "median": _num(interval.value, digits),
        "low": _num(interval.low, digits),
        "high": _num(interval.high, digits),
    }


def _fit(fit: TrendFit) -> Payload:
    low, high = fit.pct_per_year_log_ci
    return {
        "weeks": fit.n_weeks,
        "pct_per_year_log": _num(fit.pct_per_year_log),
        "pct_per_year_log_ci": [_num(low), _num(high)],
        "pct_per_year_linear": _num(fit.pct_per_year),
        "mann_kendall_z": _num(fit.mk.z, 3),
        "mann_kendall_p": _num(fit.mk.p, 5),
    }


def _analysis(result: LanguageResult, analysis: SeriesAnalysis | None) -> Payload | None:
    if analysis is None:
        return None
    return {
        "alpha": analysis.alpha,
        "lag1_autocorrelation": _num(analysis.autocorrelation, 3),
        "with_spikes": _fit(analysis.trend_all),
        "without_spikes": _fit(analysis.trend_clean),
        "mde_pct_per_year": _num(analysis.mde_pct_per_year),
        "changepoint_date": str(result.views.day(analysis.step.day)),
        "changepoint_p": _num(analysis.changepoint.p, 5),
        "step_ratio": _num(analysis.step.ratio, 3),
        "level_shift": analysis.level_shift,
        "multiple_changepoints": analysis.multiple_changepoints,
        "yearly_seasonal_amplitude": _num(analysis.seasonality.month_amplitude, 3),
    }


def language_metrics(result: LanguageResult) -> Payload:
    a = result.assessment
    return {
        "lang": result.lang,
        "title": result.article.title,
        "verdict": str(a.verdict),
        "confidence": str(a.confidence) if a.confidence else None,
        "basis": str(a.basis),
        "pct_per_year": _num(a.pct_per_year),
        "pct_per_year_ci": [_num(v) for v in a.pct_ci] if a.pct_ci else None,
        "mde_pct_per_year": _num(a.mde_pct_per_year),
        "step_ratio": _num(a.step_ratio, 2),
        "blocking_gate": a.blocking.gate if a.blocking else None,
        "flags": list(a.flags),
        "sentence": narrative.language_sentence(result),
        "reach": _interval(result.reach, 0),
        "penetration_vpm": _interval(result.penetration),
        "gate_findings": [
            {"gate": f.gate, "severity": str(f.severity), "message": f.message}
            for f in result.gates.findings
        ],
        "spike_events": [
            {
                "start": str(result.views.day(e.start)),
                "peak": str(result.views.day(e.peak)),
                "end": str(result.views.day(e.end)),
                "peak_ratio": _num(e.ratio),
            }
            for e in result.spikes.events
        ],
        "trend_views_per_million": _analysis(result, result.normalized),
        "trend_raw_views": _analysis(result, result.raw),
    }


def conclusions(run: RunResult) -> list[str]:
    out = []
    for result in run.ordered:
        out.append(narrative.language_sentence(result))
        out.extend(narrative.notes(result))
    out.extend(narrative.comparison_sentences(run.results, run.ranking))
    return out


def summary(run: RunResult) -> str:
    return narrative.summary(run.ordered, run.request.span.days)


def metrics_payload(run: RunResult, question: str) -> Payload:
    span = run.request.span
    missing = [
        {"lang": lang, "verdict": "insufficient_data", "blocking_gate": "no_article"}
        for lang in run.missing
    ]
    return {
        "schema": SCHEMA,
        "slug": run.request.slug,
        "question": question,
        "request": run.request.to_dict(),
        "window": {"start": str(span.start), "end": str(span.end), "days": span.days},
        "qid": run.qid,
        "summary": summary(run),
        "conclusions": conclusions(run),
        "ranking": {
            "tiers": [list(t) for t in run.ranking.tiers],
            "unranked": list(run.ranking.unranked),
        },
        "languages": [language_metrics(r) for r in run.ordered] + missing,
        "warnings": list(run.warnings),
        "limitations": list(narrative.limitations()),
        "cache": {"hits": run.cache_hits, "fetched": run.cache_fetched},
    }


def _stdout_language(result: LanguageResult) -> Payload:
    a = result.assessment
    entry: Payload = {"lang": result.lang, "title": result.article.title, "verdict": str(a.verdict)}
    if a.blocking is not None:
        entry["blocking_gate"] = a.blocking.gate
        return entry
    entry["confidence"] = str(a.confidence)
    for key, value in (
        ("pct_per_year", _num(a.pct_per_year)),
        ("mde_pct_per_year", _num(a.mde_pct_per_year)),
        ("step_ratio", _num(a.step_ratio, 2)),
        ("vpm_median", _num(result.penetration.value) if result.penetration else None),
        ("reach_median", _num(result.reach.value, 0) if result.reach else None),
    ):
        if value is not None:
            entry[key] = value
    entry["flags"] = list(a.flags)
    return entry


def stdout_payload(run: RunResult, paths: dict[str, Path | list[Path] | None]) -> Payload:
    payload: Payload = {"ok": True, "schema": SCHEMA, "slug": run.request.slug}
    for key, value in paths.items():
        if isinstance(value, list):
            payload[key] = [str(p) for p in value]
        elif value is not None:
            payload[key] = str(value)
    missing = [
        {"lang": lang, "verdict": "insufficient_data", "blocking_gate": "no_article"}
        for lang in run.missing
    ]
    payload["summary"] = summary(run)
    payload["languages"] = [_stdout_language(r) for r in run.ordered] + missing
    payload["warnings"] = list(run.warnings)
    payload["cache"] = {"hits": run.cache_hits, "fetched": run.cache_fetched}
    return payload


def error_payload(error: WikitrendsError) -> Payload:
    hint = error.hint or "Rerun with -v to see the log on stderr."
    return {"ok": False, "schema": SCHEMA, "error": str(error), "hint": hint}


def _dumps(payload: Payload) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _drop_language_key(key: str) -> Callable[[Payload], None]:
    def drop(payload: Payload) -> None:
        for entry in payload.get("languages", []):
            entry.pop(key, None)

    return drop


def _drop(key: str) -> Callable[[Payload], None]:
    return lambda payload: payload.pop(key, None)


def _trim_warnings(payload: Payload) -> None:
    warnings = payload.get("warnings", [])
    if len(warnings) > 1:
        payload["warnings"] = [warnings[0], f"{len(warnings) - 1} more in metrics.json"]


# Least useful first; the verdicts, summary and report path survive the longest.
_SHEDDING: Sequence[Callable[[Payload], None]] = (
    _drop_language_key("title"),
    _drop_language_key("flags"),
    _drop("charts"),
    _drop("report_png"),
    _drop("data_csv"),
    _trim_warnings,
    _drop_language_key("reach_median"),
    _drop_language_key("vpm_median"),
    _drop("cache"),
    _drop("warnings"),
)


def to_line(payload: Payload) -> str:
    """One JSON line of at most 1 KB; detail is shed in a fixed order to fit."""
    line = _dumps(payload)
    for shed in _SHEDDING:
        if len(line.encode()) <= STDOUT_LIMIT:
            break
        shed(payload)
        line = _dumps(payload)
    return line
