# Methodology

Every number in the output comes from the code in `wikitrends/`. This file states the
formulas and thresholds, gives worked examples to check an implementation against, and
lists where the implementation departs from the original design and why.

## Pipeline

Stages run in this order; each consumes the previous one.

1. **resolve**: topic to canonical titles. Search the source edition (Action API), then
   map the top hit to other editions through Wikidata sitelinks. Titles are never built
   from user input: the pageviews API does not capitalize the first letter, and
   `astronomy` instead of `Astronomy` silently returns about 1/1000 of the views.
2. **fetch**: daily per-article and per-edition pageviews, `all-access` + `user`, through
   the SQLite cache.
3. **reindex**: a full calendar; days the API omitted become NaN, a real 0 stays 0.
4. **gates** (G1-G11): a series that fails a stop gate is refused, never estimated.
5. **normalize**: views per million edition views (vpm).
6. **spikes**: robust z-scores, events with decay tails.
7. **seasonality**: weekday and month offsets, removed on the log scale.
8. **weekly**: weekly medians.
9. **trend**: Theil-Sen and Mann-Kendall, twice: with and without spike days.
10. **change point**: Pettitt test and a step-vs-linear model comparison.
11. **verdict**: flags, a verdict from a closed vocabulary, a confidence level.
12. **render** and **report**.

## Data

- Slice: `access=all-access`, `agent=user`, `granularity=daily`. The mobile/desktop split
  reflects the requested URL, not the device, and changed with infrastructure; monthly
  granularity truncates the edge buckets.
- Numerator and denominator always share the slice and the calendar (G11).
- First day with data: 2015-07-01; earlier starts are clamped with a warning.
- Default end: two days ago (the API lags 1-2 days).
- `t` is the true day index from the window start; it is never renumbered after days
  are dropped, or the slope changes scale silently.

## Normalization

`vpm_t = 1e6 × views_t / D̃_t`, where `D̃` is the edition total smoothed by a centred
7-day median. The edition has its own weekly cycle and outage days; an unsmoothed
denominator injects them into every article.

Edition totals include the Main Page (about 1.4% of en.wikipedia), search and every
non-article namespace, so vpm is biased low by a roughly constant factor.

| raw views | vpm | Reading |
|---|---|---|
| up | up | Interest grew. |
| up | flat | The whole edition grew; the topic kept pace. No rise in interest is claimed. |
| up | down | The edition grew faster; the topic's share fell. |
| flat | up | The edition shrank; the topic gained share. |

The verdict uses vpm whenever the edition total passes G10 and G11, otherwise raw views
(flag `vpm_suppressed`).

## Gates

| Gate | Condition | Severity | Flag |
|---|---|---|---|
| G1_low_volume | median < 10 views/day | stop | |
| G1_low_volume | median 10-49 | degrade | `direction_only` |
| G2_few_points | < 60 observed days, or < 26 complete weeks | stop | |
| G3_short_window | window < 180 days | stop | |
| G3_short_window | window < 365 days | degrade | `no_annualization` |
| G4_no_seasonal_baseline | window < 730 days | degrade | `no_annual_baseline` |
| G5_missing_days | > 25% of days missing (from the first observed day) | stop | |
| G5_missing_days | > 10% missing | warn | `gappy` |
| G6_long_gap | > 14 consecutive missing days | stop | |
| G7_end_collapse | prior ≥ 50 and recent < 5% of prior; or ≥ 7 trailing zero/missing days with prior ≥ 20 | stop | |
| G7_start_jump | the mirror image at the window start | stop | |
| G8_late_start | first observed day > 30 days into the window | degrade | `late_start` |
| G9_many_zeros | > 20% of observed days are 0 | degrade | `many_zeros` |
| G10_denominator_gaps | > 5% of edition-total days missing | degrade | `vpm_suppressed` |
| G11_slice_mismatch | article and edition total differ in slice or calendar | degrade | `vpm_suppressed` |

For G7, `prior` is the median of days −120..−30 and `recent` the median of the last
30 days. A G7 finding triggers a title re-check (`action=query&redirects=1`); if the
page moved, the old and the new title are summed and the analysis reruns.

Each gate carries a fixed English message that goes verbatim into the JSON and the PDF,
for example: "Median 7 views/day is below 10: too little traffic to measure a trend."

## Spikes

For each day, two robust scores against a 15-day window:

- centred: the window of days −7..+7, which includes the day;
- trailing: the 15 days before the day.

For a window `W`: `m = median(W)`, `MAD = median(|W − m|)`,
`σ = max(1.4826 × MAD, σ_min)`, `z = (y − m) / σ`, where
`σ_min = max(1.0, 0.05 × median(y))` over the whole series (on low-traffic articles MAD
is often exactly 0 and every wiggle would get z = ∞).

A day is a **spike** when it reaches at least 1.5× the centred median and scores `z > 5`
on the centred window, or when it scores `z > 5` and reaches 1.5× the median on the
trailing window and also 1.5× the centred median. A day with centred `z < −5` is a
**dip**. `3.5 < z ≤ 5` is elevated and only reported.

Spike days separated by at most 3 other days merge into one event. The event's tail continues while the
day stays at least 2 σ above the pre-event level (the trailing median at the event
start), until two calm days in a row, and at most 14 days after the peak. The event's
ratio is peak views over the pre-event level. Charts draw this mask; they never detect.

## Seasonality

Offsets are additive on `log1p(views)`.

- Weekday: for each day, `log1p(y) − log1p(centred 7-day median)`; median per weekday;
  centred to mean 0.
- Month: only when the window is at least 730 days (each month seen twice). On weekly
  medians of the weekday-adjusted log series, fit a 53-week running median, take the
  residuals, median per calendar month, centre to mean 0. Repeat three times, each time
  fitting the running median to the series with the current month offsets removed.

`yearly_seasonal_amplitude` is `exp(max − min of month offsets) − 1`; at 0.25 or more the
flag `seasonality_suspected` is set.

## Weekly medians

Weeks are aligned to the window end, so each full week holds every weekday once. A week
is valid with at least 5 observed days; its `t` is the day index of its centre. The trend
needs at least 26 valid weeks. Daily data are autocorrelated at 0.5-0.9; on daily points
the Mann-Kendall p-value is too small by orders of magnitude and a flat series reads as
significantly growing.

## Trend

On the valid weekly medians `(t_i, y_i)`:

- **Theil-Sen**: `β = median{(y_j − y_i) / (t_j − t_i) : i < j}`,
  intercept `median(y − β t)`.
- **Slope interval** (Sen 1968): sort the `N` pairwise slopes,
  `C = z_{1−α/2} × sqrt(Var(S))`; lower = slope number `round((N − C)/2)`,
  upper = slope number `round((N + C)/2) + 1` (1-based).
- **Mann-Kendall**: `S = Σ_{i<j} sgn(y_j − y_i)`,
  `Var(S) = [n(n−1)(2n+5) − Σ_k t_k(t_k−1)(2t_k+5)] / 18` over tie groups of size `t_k`,
  `Z = (S − 1)/sqrt(Var)` if `S > 0`, `(S + 1)/sqrt(Var)` if `S < 0`, else 0,
  `p = erfc(|Z| / √2)`.
- **Autocorrelation**: lag-1 autocorrelation of the residuals of the log fit. Above 0.3
  the significance level tightens from α = 0.05 to 0.01 (flag `autocorrelated`), and
  every interval uses the same α.
- **Two rates**, both in `metrics.json`:
  - linear: `100 × β × 365.25 / level_mid`, with `level_mid` the fitted value at the
    window midpoint;
  - log (the headline): Theil-Sen on `log1p(y)` gives `b`; `100 × (e^{365.25 b} − 1)`.
    It does not depend on the article's size, so it is the only rate comparable across
    languages.

The trend runs twice: on all days, and with spike events and dips removed ("clean").

## Minimum detectable effect

With the slope interval `[b_lo, b_hi]` at level α:
`SE_rank = (b_hi − b_lo) / (2 z_{1−α/2})`, `SE_res = sd(residuals) / sqrt(Σ(t − t̄)²)`,
`MDE = 100 × (exp(365.25 × (z_{1−α/2} + z_{0.8}) × max(SE_rank, SE_res)) − 1)`.
It is the yearly change the test would detect with 80% power. The residual term keeps
the MDE from collapsing to 0 when most weekly medians tie.

## Change point

- **Pettitt** on the clean weekly log values: ranks `r_i` (ties averaged),
  `U_t = 2 Σ_{i≤t} r_i − t(n + 1)`, `K = max|U_t|`,
  `p ≈ 2 exp(−6K² / (n³ + n²))`. The split is after the `t` that maximizes `|U_t|`.
- **Step model**: segment medians before and after the split, compared with the linear
  Theil-Sen fit by median absolute residual. The step model has one more parameter, so it
  must be at least 10% better; both segments need 8 weeks or more.
- **Level shift** when `p < α`, the step model wins, and the step is at least 15%.
  A percentage per year is then withheld: it would describe smooth growth that did not
  happen. A second step in the residuals of the step model (Pettitt `p < 0.01` and a
  winning step) sets `multiple_changepoints`.

## Verdict

First match wins:

1. `insufficient_data`: a stop gate other than G7, fewer than 26 weeks, or no article.
2. `series_discontinuity`: G7.
3. `level_shift_up` / `level_shift_down`.
4. `growing_event_driven` / `declining_event_driven`: significant with spikes, not
   significant without them, and at least one spike event.
5. Both significant with opposite signs: `no_detectable_trend` with flag `sign_flip`.
6. `growing` / `declining`: clean trend significant and its interval not inside ±5%/yr.
   If the clean slope is under half the all-days slope, flag `event_inflated`.
7. `stable`: the clean interval lies inside ±5%/yr.
8. `no_detectable_trend`.

Confidence starts at `high` and drops one step per flag among: `no_annualization`,
`direction_only`, `gappy`, `no_annual_baseline`, `late_start`, `many_zeros`,
`vpm_suppressed`, `autocorrelated`, `seasonality_suspected`, `raw_vpm_divergence`,
`multiple_changepoints`, `event_inflated`. It never goes below `low`.

Percentages are withheld (`pct_per_year: null`) under `direction_only` or
`no_annualization`, for level shifts and event-driven verdicts, and when the interval of
a growing or declining trend covers zero. The window length is always in the same
sentence as any percentage.

## Comparing languages

- **Reach**: median of weekly median raw views (audience size).
- **Penetration**: median of weekly median vpm (share of attention; comparable).
- **Momentum**: the headline rate per language (annotation only).

Intervals of the medians use order statistics on weekly values:
ranks `floor(n/2 − z√n/2)` and `ceil(1 + n/2 + z√n/2)` (1-based). Languages are sorted by
penetration, ties broken by reach. A language joins the current tier when its interval
overlaps the interval of the tier's first language. Languages without a usable result
are listed apart and never ranked last. There is no blended score: trading reach against
density is a business decision.

## Worked examples

The unit tests assert each of these.

| Input | Expected |
|---|---|
| Mann-Kendall on `[1, 3, 2, 1]` | `S = −1`, `Var(S) = 7.667`, `Z = 0`, `p = 1`. `Var = 8.667` means the tie correction is missing; `Z = −0.361` means the continuity correction is missing. |
| Mann-Kendall on `[1, 2, 3, 4]` | `S = 6`, `Var(S) = 8.667`, `Z = 1.698`, `p = 0.0894`. |
| Pettitt on `[1, 2, 3, 10, 11, 12]` | `U = −5, −8, −9, −8, −5`, `K = 9`, split before index 3, `p = 0.291`. |
| Median interval, `n = 100`, values 1..100 | median 50.5, interval `[40, 61]`. |
| `b = ln(1.3) / 365.25` | 30.0%/yr. |
| Synthetic 800 days, +30%/yr, weekly cycle, 10% noise | 30 ± 2 %/yr, interval covers 30. |
| Synthetic flat series, 400 runs of Mann-Kendall | 2-8% of p-values below 0.05. |
| Synthetic ±35% yearly cycle, no trend, 20 seeds | at most 3 false trends or shifts. |

## Departures from the original design

Each was found by a failing synthetic test and is covered by one now.

1. **Trailing spike window.** A centred 15-day median alone missed a 41× news spike
   whose decay filled half the window: the median rose to the spike level. Spikes are
   now also scored against the 15 days before them.
2. **Spike size floor.** On busy articles a 15-day MAD is tight enough for +30% days to
   pass `z > 5`. A spike must also reach 1.5× the local median, and trailing detections
   must also reach 1.5× the centred median, which keeps the return from a summer dip and
   the first days of a lasting step out of the spike mask.
3. **Month offsets.** Detrending with a straight line let a level step leak into the
   month offsets and produced a second, false change point. A 53-week running median
   keeps steps sharp; three passes cut false trends on a strongly seasonal series from
   27% to 7.5% and recover the amplitude (0.81 against a true 0.82).
4. **Stable band and minimum step.** A significant 2%/yr drift or an 8% step is real but
   irrelevant for a content decision. Changes inside ±5%/yr are `stable`; steps under 15%
   are not level shifts.
5. **MDE floor.** With low counts most weekly medians tie, the rank interval has zero
   width and the MDE was 0. The residual standard error now bounds it from below.
