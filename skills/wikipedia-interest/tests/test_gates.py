from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np

from wikitrends import gates
from wikitrends.gates import Finding, Gate, GateContext, Severity
from wikitrends.models import TrafficFilter
from wikitrends.series import DailySeries, FloatArray

START = date(2023, 1, 1)
N = 800


def healthy(n: int = N) -> FloatArray:
    rng = np.random.default_rng(7)
    return np.round(200 + rng.normal(0, 10, n))


def with_nan(values: FloatArray, idx: Iterable[int]) -> FloatArray:
    out = values.copy()
    out[list(idx)] = np.nan
    return out


def spread(count: int, n: int = N) -> list[int]:
    """`count` distinct indices spread evenly, never touching day 0."""
    return np.linspace(1, n - 2, count).astype(int).tolist()


def make(values: FloatArray, traffic: TrafficFilter | None = None) -> DailySeries:
    return DailySeries(START, values, traffic or TrafficFilter())


def run(gate: Gate, values: FloatArray, total: DailySeries | None = None) -> Finding | None:
    return gate(GateContext(make(values), total))


def fire(gate: Gate, values: FloatArray, total: DailySeries | None = None) -> Finding:
    finding = run(gate, values, total)
    assert finding is not None
    return finding


def test_healthy_series_passes_every_gate() -> None:
    report = gates.evaluate(GateContext(make(healthy()), make(np.full(N, 1e7))))
    assert report.findings == ()
    assert report.blocking is None


def test_g1_low_volume() -> None:
    assert fire(gates.low_volume, np.full(N, 9.0)).severity is Severity.STOP
    degraded = fire(gates.low_volume, np.full(N, 10.0))
    assert (degraded.severity, degraded.flag) == (Severity.DEGRADE, "direction_only")
    assert fire(gates.low_volume, np.full(N, 49.0)).severity is Severity.DEGRADE
    assert run(gates.low_volume, np.full(N, 50.0)) is None


def test_g1_empty_series_stops() -> None:
    finding = fire(gates.low_volume, np.full(N, np.nan))
    assert finding.severity is Severity.STOP
    assert "No pageviews" in finding.message


def test_g2_few_points() -> None:
    assert fire(gates.few_points, with_nan(healthy(), range(59, N))).gate == "G2_few_points"
    assert run(gates.few_points, with_nan(healthy(), range(60, N))) is None


def test_g3_short_window() -> None:
    assert fire(gates.short_window, healthy(179)).severity is Severity.STOP
    assert fire(gates.short_window, healthy(180)).flag == "no_annualization"
    assert fire(gates.short_window, healthy(364)).severity is Severity.DEGRADE
    assert run(gates.short_window, healthy(365)) is None


def test_g4_no_seasonal_baseline() -> None:
    assert fire(gates.no_seasonal_baseline, healthy(729)).flag == "no_annual_baseline"
    assert run(gates.no_seasonal_baseline, healthy(730)) is None


def test_g5_missing_share() -> None:
    assert run(gates.missing_share, with_nan(healthy(), spread(80))) is None
    warned = fire(gates.missing_share, with_nan(healthy(), spread(81)))
    assert (warned.severity, warned.flag) == (Severity.WARN, "gappy")
    assert fire(gates.missing_share, with_nan(healthy(), spread(200))).severity is Severity.WARN
    assert fire(gates.missing_share, with_nan(healthy(), spread(201))).severity is Severity.STOP


def test_g5_ignores_late_start() -> None:
    assert run(gates.missing_share, with_nan(healthy(), range(300))) is None


def test_g6_long_gap() -> None:
    finding = fire(gates.long_gap, with_nan(healthy(), range(400, 415)))
    assert finding.message == "No data for 15 consecutive days (2024-02-05 to 2024-02-19)."
    assert run(gates.long_gap, with_nan(healthy(), range(400, 414))) is None


def test_g6_ignores_late_start() -> None:
    assert run(gates.long_gap, with_nan(healthy(), range(40))) is None


def test_g7_end_collapse() -> None:
    values = np.full(N, 200.0)
    values[-30:] = 9
    assert fire(gates.discontinuity, values).gate == "G7_end_collapse"
    values[-30:] = 10
    assert run(gates.discontinuity, values) is None


def test_g7_dead_tail() -> None:
    assert fire(gates.discontinuity, with_nan(healthy(), range(N - 7, N))).severity is Severity.STOP
    assert run(gates.discontinuity, with_nan(healthy(), range(N - 6, N))) is None
    quiet = with_nan(np.full(N, 19.0), range(N - 7, N))
    assert run(gates.discontinuity, quiet) is None


def test_g7_start_jump() -> None:
    values = np.full(N, 200.0)
    values[:30] = 9
    assert fire(gates.discontinuity, values).gate == "G7_start_jump"
    values[:30] = 10
    assert run(gates.discontinuity, values) is None


def test_g7_leaves_late_start_to_g8() -> None:
    assert run(gates.discontinuity, with_nan(healthy(), range(60))) is None


def test_g8_late_start() -> None:
    finding = fire(gates.late_start, with_nan(healthy(), range(31)))
    assert finding.flag == "late_start"
    assert "2023-02-01" in finding.message
    assert run(gates.late_start, with_nan(healthy(), range(30))) is None


def test_g9_many_zeros() -> None:
    values = healthy()
    values[spread(161)] = 0
    assert fire(gates.many_zeros, values).flag == "many_zeros"
    values = healthy()
    values[spread(160)] = 0
    assert run(gates.many_zeros, values) is None


def test_g10_denominator_gaps() -> None:
    gappy = make(with_nan(np.full(N, 1e7), spread(41)))
    assert fire(gates.denominator_gaps, healthy(), gappy).flag == "vpm_suppressed"
    fine = make(with_nan(np.full(N, 1e7), spread(40)))
    assert run(gates.denominator_gaps, healthy(), fine) is None
    assert run(gates.denominator_gaps, healthy()) is None


def test_g11_slice_mismatch() -> None:
    bots = make(np.full(N, 1e7), TrafficFilter(agent="all-agents"))
    assert fire(gates.slice_mismatch, healthy(), bots).flag == "vpm_suppressed"
    shorter = make(np.full(N - 1, 1e7))
    assert fire(gates.slice_mismatch, healthy(), shorter).gate == "G11_slice_mismatch"
    assert run(gates.slice_mismatch, healthy(), make(np.full(N, 1e7))) is None


def test_report_blocks_on_first_stop_and_keeps_every_finding() -> None:
    report = gates.evaluate(GateContext(make(np.full(100, 5.0))))
    blocking = report.blocking
    assert blocking is not None
    assert blocking.gate == "G1_low_volume"
    assert [f.gate for f in report.findings][:3] == [
        "G1_low_volume",
        "G3_short_window",
        "G4_no_seasonal_baseline",
    ]


def test_report_flags_are_unique_and_ordered() -> None:
    total = make(with_nan(np.full(400, 1e7), range(0, 400, 10)))
    report = gates.evaluate(GateContext(make(np.full(400, 30.0)), total))
    assert report.blocking is None
    assert report.flags == ("direction_only", "no_annual_baseline", "vpm_suppressed")
