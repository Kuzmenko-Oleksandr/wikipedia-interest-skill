"""English wording of results and a guard against claims the data cannot support.

Rules: the window length sits in the same sentence as any percentage; no percentage
under low volume or a sub-year window; no forecasts; timing is never called a cause.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path

from .analysis import LanguageResult, Ranking
from .verdict import STABLE_BAND_PCT, Assessment, Basis, Verdict

SUMMARY_LIMIT = 200
TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "report-template.md"

FORBIDDEN: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bpeople\b.*\binterested\b|\binterested in\b", re.IGNORECASE),
        "Views are not people: say 'the article got N views/day'.",
    ),
    (
        re.compile(r"\bdemand\b", re.IGNORECASE),
        "Views measure attention, not demand: say 'views of articles about Y grew ~X%/yr'.",
    ),
    (
        re.compile(r"\bwill\s+(reach|grow|rise|fall|drop|decline|continue)\b|\bforecast|\bpredict"),
        "No forecasts: describe the observed window only.",
    ),
    (
        re.compile(r"\bno trend\b(?!\s+((is|was)\s+)?detected)", re.IGNORECASE),
        "Say 'no trend detected; changes under ±MDE %/yr would not be visible'.",
    ),
    (
        re.compile(r"\b(caused|causes|because of|due to|driven by|led to)\b", re.IGNORECASE),
        "Say the change coincides with an event; causality is not established.",
    ),
    (
        re.compile(r"\bmore (interesting|popular|interested)\b", re.IGNORECASE),
        "Compare views and share of edition views, not interest.",
    ),
)

_LABELS = {
    Verdict.INSUFFICIENT_DATA: "insufficient data",
    Verdict.SERIES_DISCONTINUITY: "series discontinuity",
    Verdict.LEVEL_SHIFT_UP: "step up",
    Verdict.LEVEL_SHIFT_DOWN: "step down",
    Verdict.GROWING_EVENT_DRIVEN: "rise from spikes",
    Verdict.DECLINING_EVENT_DRIVEN: "drop from spikes",
    Verdict.GROWING: "growing",
    Verdict.DECLINING: "declining",
    Verdict.STABLE: "stable",
    Verdict.NO_DETECTABLE_TREND: "no trend detected",
}

_DIVERGENCE = {
    (1, 0): "Raw views rose, but the whole edition grew as well: the topic only kept pace, "
    "so no rise in interest is claimed.",
    (1, -1): "Raw views rose, but the edition grew faster: the topic's share of attention fell.",
    (0, 1): "Raw views were flat while the edition shrank: the topic gained share.",
    (0, -1): "Raw views were flat while the edition grew: the topic's share fell.",
    (-1, 0): "Raw views fell, but so did the whole edition: the topic kept its share.",
    (-1, 1): "Raw views fell, but less than the edition: the topic's share grew.",
}


def check_claims(text: str) -> list[str]:
    """Advice for every forbidden claim found in `text`; empty when clean."""
    return [advice for pattern, advice in FORBIDDEN if pattern.search(text)]


@cache
def limitations() -> tuple[str, ...]:
    """The numbered limitations block, read from assets/report-template.md."""
    text = TEMPLATE.read_text(encoding="utf-8")
    block = text.split("## Limitations", 1)[1].split("\n## ", 1)[0]
    items = re.findall(r"^\d+\.\s+(.+?)(?=^\d+\.\s|\Z)", block, re.MULTILINE | re.DOTALL)
    return tuple(" ".join(item.replace("`", "").split()) for item in items)


def label(verdict: Verdict) -> str:
    return _LABELS[verdict]


def _measure(assessment: Assessment) -> str:
    return "views per million edition views" if assessment.basis is Basis.VPM else "raw views"


def _confidence(assessment: Assessment) -> str:
    return f" ({assessment.confidence} confidence)" if assessment.confidence else ""


def _ci_label(assessment: Assessment) -> str:
    alpha = assessment.headline.alpha if assessment.headline else 0.05
    return f"{100 * (1 - alpha):.0f}% CI"


def language_sentence(result: LanguageResult) -> str:
    """One sentence per language, naming the window next to any number."""
    a = result.assessment
    lang = result.lang
    if a.blocking is not None:
        return f"{lang}: {label(a.verdict)}. {a.blocking.message}"
    window = f"over the {len(result.views)}-day window"
    measure = _measure(a)
    confidence = _confidence(a)
    verdict = a.verdict
    if verdict in (Verdict.GROWING, Verdict.DECLINING):
        word = "grew" if verdict is Verdict.GROWING else "fell"
        if a.pct_per_year is not None and a.pct_ci is not None:
            low, high = a.pct_ci
            return (
                f"{lang}: {measure} {word} ~{a.pct_per_year:+.0f}%/yr {window} "
                f"({_ci_label(a)} {low:+.0f}% to {high:+.0f}%/yr){confidence}."
            )
        return f"{lang}: {measure} {word} {window}; the size is not reported{confidence}."
    if verdict is Verdict.STABLE:
        if a.pct_per_year is None:
            return f"{lang}: {measure} were stable {window}{confidence}."
        return (
            f"{lang}: {measure} were stable {window}: the yearly change is within "
            f"±{STABLE_BAND_PCT:.0f}% (estimate {a.pct_per_year:+.1f}%/yr){confidence}."
        )
    if verdict is Verdict.NO_DETECTABLE_TREND:
        if a.mde_pct_per_year is None:
            return f"{lang}: no trend detected {window}{confidence}."
        return (
            f"{lang}: no trend detected {window}; with this data only changes larger than "
            f"±{a.mde_pct_per_year:.0f}%/yr would have been visible{confidence}."
        )
    if verdict in (Verdict.GROWING_EVENT_DRIVEN, Verdict.DECLINING_EVENT_DRIVEN):
        return _event_sentence(result, window, confidence)
    return _step_sentence(result, window, confidence)


def _event_sentence(result: LanguageResult, window: str, confidence: str) -> str:
    a = result.assessment
    events = result.spikes.events
    largest = max(events, key=lambda e: e.ratio)
    change = "rise" if a.verdict is Verdict.GROWING_EVENT_DRIVEN else "drop"
    plural = "s" if len(events) > 1 else ""
    mde = ""
    if a.mde_pct_per_year is not None:
        mde = f" (changes over ±{a.mde_pct_per_year:.0f}%/yr would have been visible)"
    return (
        f"{result.lang}: the {change} {window} comes from {len(events)} short spike{plural} "
        f"(largest {result.views.day(largest.peak)}, {largest.ratio:.0f}x the usual level); "
        f"without them no trend is detected{mde}{confidence}."
    )


def _step_sentence(result: LanguageResult, window: str, confidence: str) -> str:
    a = result.assessment
    direction = "up" if a.verdict is Verdict.LEVEL_SHIFT_UP else "down"
    day = result.views.day(a.headline.step.day) if a.headline else result.views.start
    size = "" if a.step_ratio is None else f" ~{abs(a.step_ratio - 1) * 100:.0f}%"
    return (
        f"{result.lang}: {_measure(a)} stepped {direction}{size} around {day} {window} and "
        "stayed there; this is a one-off level shift, not steady growth. Shifts like this "
        f"often coincide with a rename, a link from a busy page or a search-engine change"
        f"{confidence}."
    )


def notes(result: LanguageResult) -> list[str]:
    """Secondary findings: raw vs normalized divergence and excluded spikes."""
    a = result.assessment
    out: list[str] = []
    if a.blocking is not None:
        return out
    if "raw_vpm_divergence" in a.flags:
        text = _DIVERGENCE.get((a.raw_movement, a.basis_movement))
        if text:
            out.append(f"{result.lang}: {text}")
    if result.spikes.events and a.verdict not in (
        Verdict.GROWING_EVENT_DRIVEN,
        Verdict.DECLINING_EVENT_DRIVEN,
    ):
        days = ", ".join(str(result.views.day(e.peak)) for e in result.spikes.events[:3])
        more = "" if len(result.spikes.events) <= 3 else " and more"
        out.append(
            f"{result.lang}: spikes on {days}{more} were left out of the trend; "
            "a coincidence in time with news does not establish a cause."
        )
    return out


def comparison_sentences(results: Mapping[str, LanguageResult], ranking: Ranking) -> list[str]:
    out = []
    if len(ranking.order) > 1:
        tiers = "; ".join(
            f"tier {i}: {', '.join(tier)}"
            + (" (statistically indistinguishable)" if len(tier) > 1 else "")
            for i, tier in enumerate(ranking.tiers, 1)
        )
        out.append(f"Share of edition attention (views per million), {tiers}.")
        first, second = results[ranking.order[0]], results[ranking.order[1]]
        if first.reach and second.reach and first.penetration and second.penetration:
            raw = first.reach.value / max(second.reach.value, 1e-9)
            share = first.penetration.value / max(second.penetration.value, 1e-9)
            out.append(
                f"{first.lang} gets {raw:.1f}x the daily views of {second.lang}; per million "
                f"edition views the ratio {first.lang}/{second.lang} is {share:.1f}."
            )
    if ranking.unranked:
        out.append(
            f"Not ranked for lack of usable data: {', '.join(ranking.unranked)} "
            "(this is not the same as low interest)."
        )
    return out


def _short(result: LanguageResult, detail: int) -> str:
    a = result.assessment
    text = f"{result.lang} {label(a.verdict)}"
    if detail >= 1 and a.level_shift and a.headline is not None:
        text += f" {result.views.day(a.headline.step.day):%Y-%m}"
    if detail >= 1 and a.pct_per_year is not None and a.verdict is not Verdict.STABLE:
        text += f" {a.pct_per_year:+.0f}%/yr"
    if detail >= 2 and a.mde_pct_per_year is not None:
        text += f" (MDE ±{a.mde_pct_per_year:.0f}%/yr)"
    if detail >= 2 and a.confidence is not None:
        text += f" ({a.confidence})"
    return text


def summary(results: Sequence[LanguageResult], days: int, missing: Sequence[str] = ()) -> str:
    """At most 200 characters, so the agent can answer without opening a file."""
    absent = [f"{lang} no article" for lang in missing]
    for detail in (2, 1, 0):
        parts = [_short(r, detail) for r in results] + absent
        text = f"Over {days} days: " + "; ".join(parts)
        if len(text) <= SUMMARY_LIMIT:
            return text
    return text[: SUMMARY_LIMIT - 1] + "…"
