"""Verdicts, confidence and wording on series with a planted answer."""

from __future__ import annotations

import numpy as np
import pytest

from tests import synthetic
from wikitrends import narrative
from wikitrends.analysis import LanguageAnalyzer, LanguageResult
from wikitrends.models import Article
from wikitrends.series import DailySeries, FloatArray
from wikitrends.verdict import Basis, Confidence, Verdict

EDITION = 5e6


def edition(n: int = synthetic.DAYS, pct: float = 0.0) -> DailySeries:
    rate = np.log1p(pct / 100) / 365.25
    return synthetic.series(EDITION * np.exp(rate * np.arange(n)))


def assess(values: FloatArray, total: DailySeries | None = None) -> LanguageResult:
    views = synthetic.series(values)
    if total is None:
        total = edition(len(values))
    return LanguageAnalyzer().analyze(Article("uk", "Астрономія"), views, total)


def test_growth_is_reported_with_its_window() -> None:
    result = assess(synthetic.growth(30.0))
    a = result.assessment
    assert a.verdict is Verdict.GROWING
    assert a.basis is Basis.VPM
    assert a.pct_per_year == pytest.approx(30, abs=3)
    sentence = narrative.language_sentence(result)
    assert "800-day window" in sentence
    assert "%/yr" in sentence


def test_low_volume_reports_direction_only() -> None:
    result = assess(synthetic.growth(40.0) / 8)
    a = result.assessment
    assert "direction_only" in a.flags
    assert a.verdict is Verdict.GROWING
    assert a.pct_per_year is None
    assert "%" not in narrative.language_sentence(result)


def test_short_window_is_not_annualized() -> None:
    result = assess(synthetic.growth(40.0, n=300))
    a = result.assessment
    assert "no_annualization" in a.flags
    assert a.pct_per_year is None
    assert a.mde_pct_per_year is None
    assert "%" not in narrative.language_sentence(result)


def test_events_give_event_driven_verdict() -> None:
    values = synthetic.with_events(synthetic.flat(), (560, 610, 660, 710, 760))
    result = assess(values)
    assert result.assessment.verdict is Verdict.GROWING_EVENT_DRIVEN
    assert result.assessment.pct_per_year is None
    assert "5 short spikes" in narrative.language_sentence(result)


def test_step_is_a_level_shift_without_growth_rate() -> None:
    result = assess(synthetic.with_step(synthetic.flat(), 400, 1.6))
    a = result.assessment
    assert a.verdict is Verdict.LEVEL_SHIFT_UP
    assert a.pct_per_year is None
    assert a.step_ratio == pytest.approx(1.6, rel=0.05)
    assert "not steady growth" in narrative.language_sentence(result)


def test_flat_series_is_stable() -> None:
    a = assess(synthetic.flat()).assessment
    assert a.verdict is Verdict.STABLE
    assert a.confidence is Confidence.HIGH


def test_noisy_flat_series_has_no_detectable_trend_with_mde() -> None:
    result = assess(synthetic.flat(noise=0.6))
    a = result.assessment
    assert a.verdict is Verdict.NO_DETECTABLE_TREND
    assert a.mde_pct_per_year is not None
    assert "would have been visible" in narrative.language_sentence(result)


def test_edition_decline_turns_flat_views_into_growing_share() -> None:
    result = assess(synthetic.flat(), edition(pct=-10.0))
    a = result.assessment
    assert a.verdict is Verdict.GROWING
    assert "raw_vpm_divergence" in a.flags
    assert a.confidence is Confidence.MEDIUM
    assert any("edition shrank" in note for note in narrative.notes(result))


def test_edition_growth_blocks_a_raw_rise_claim() -> None:
    result = assess(synthetic.growth(12.0), edition(pct=12.0))
    assert result.assessment.verdict is Verdict.STABLE
    assert any("only kept pace" in note for note in narrative.notes(result))


def test_missing_edition_total_falls_back_to_raw() -> None:
    views = synthetic.series(synthetic.growth(30.0))
    result = LanguageAnalyzer().analyze(Article("uk", "X"), views, None)
    assert result.assessment.basis is Basis.RAW
    assert result.penetration is None


def test_stop_gate_refuses_instead_of_estimating() -> None:
    result = assess(np.full(synthetic.DAYS, 5.0))
    a = result.assessment
    assert a.verdict is Verdict.INSUFFICIENT_DATA
    assert a.confidence is None
    assert result.raw is None
    assert a.blocking is not None
    assert a.blocking.gate == "G1_low_volume"


def test_collapse_at_the_end_is_a_discontinuity() -> None:
    values = synthetic.flat()
    values[-30:] = 2
    a = assess(values).assessment
    assert a.verdict is Verdict.SERIES_DISCONTINUITY
    assert a.blocking is not None
    assert "renamed" in a.blocking.message


def test_confidence_drops_one_step_per_flag() -> None:
    assert Confidence.HIGH.lowered(1) is Confidence.MEDIUM
    assert Confidence.HIGH.lowered(5) is Confidence.LOW


@pytest.mark.parametrize(
    "claim",
    [
        "5000 people are interested in astronomy",
        "Demand for astronomy is growing",
        "Views will reach 900 per day by 2027",
        "There is no trend in pl",
        "The launch caused the rise",
        "uk is more interesting than pl",
    ],
)
def test_forbidden_claims_are_caught(claim: str) -> None:
    assert narrative.check_claims(claim)


def test_allowed_wording_passes() -> None:
    assert not narrative.check_claims(
        "no trend detected over the 730-day window; the rise coincides with the launch"
    )


@pytest.mark.parametrize(
    "values",
    [
        synthetic.growth(30.0),
        synthetic.growth(-30.0),
        synthetic.growth(40.0) / 8,
        synthetic.with_events(synthetic.flat(), (560, 610, 660, 710, 760)),
        synthetic.with_step(synthetic.flat(), 400, 0.5),
        synthetic.flat(noise=0.6),
        np.full(synthetic.DAYS, 5.0),
    ],
)
def test_generated_text_never_makes_forbidden_claims(values: FloatArray) -> None:
    result = assess(values)
    for text in [narrative.language_sentence(result), *narrative.notes(result)]:
        assert narrative.check_claims(text) == []


def test_limitations_block_has_twelve_items() -> None:
    items = narrative.limitations()
    assert len(items) == 12
    assert items[0].startswith("Pageviews measure attention")
