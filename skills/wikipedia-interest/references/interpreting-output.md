# Interpreting the output

## The stdout line

Every command prints exactly one JSON line (at most 1 KB) and nothing else on stdout.
Logs go to stderr. When the line would exceed 1 KB, fields are dropped in this order:
per-language `title`, `flags`, `reason`, `charts`, `report_png`, `data_csv`, all but one warning,
`reach_median`, `vpm_median`, `cache`, `metrics_json` (only when `report_pdf` is present:
it sits in the same folder), `warnings`, `tiers`, then per-language `mde_pct_per_year`,
`step_ratio`, `step_date`, `pct_per_year` and `confidence` (the `summary` still carries
the verdicts), and finally `caveat`. Everything dropped is still in `metrics.json`.

### compare / analyze / report

| Field | Meaning |
|---|---|
| `ok` | `true` on success. On failure see "Errors" below. |
| `schema` | Output schema version, currently 1. |
| `slug` | Run name derived from languages, topic and window. The same request always gives the same slug and folder. |
| `report_pdf`, `report_png` | One-page report (compare and report only). Absolute paths. |
| `charts` | `chart-timeseries.png`, `chart-normalized.png`, `chart-ranking.png`. |
| `metrics_json` | Full detail, see below. |
| `data_csv` | Daily data: `date, lang, views, edition_total, views_per_million, spike, excluded`. |
| `summary` | At most 200 characters; quotable as is. |
| `languages[]` | One entry per requested language, sorted by code. |
| `tiers` | Languages ranked by share of attention; each inner list is statistically indistinguishable. |
| `caveat` | One sentence of limitations to quote in the answer. |
| `warnings` | Clamped dates, renames followed, missing articles, synthetic fixture data. |
| `cache` | Pageview series served from the cache (`hits`) and downloaded (`fetched`). |

### languages[] entry

| Field | Meaning |
|---|---|
| `lang`, `title` | Edition code and the canonical article title that was measured. |
| `verdict` | See the verdict table in SKILL.md. |
| `confidence` | `high`, `medium`, `low`; absent when the verdict is a refusal. |
| `pct_per_year` | Headline change per year (log-scale Theil-Sen of views per million, or raw views under `vpm_suppressed`). Absent when it must not be quoted. |
| `mde_pct_per_year` | For stable, no-trend and event-driven verdicts: the smallest yearly change this data could have detected. |
| `step_ratio` | For level shifts: level after / level before (1.5 = +50%). |
| `step_date` | For level shifts: the week the new level starts. |
| `vpm_median` | Median views per million edition views: share of attention, comparable across languages. |
| `reach_median` | Median daily views: audience size, not comparable as interest. |
| `blocking_gate` | Why a refusal happened: a gate code or `no_article`. |
| `reason` | The gate's message for a refusal, to repeat as is. |
| `flags` | Every condition that weakened the result; see SKILL.md. |

### resolve

| Field | Meaning |
|---|---|
| `qid` | Wikidata item of the topic, e.g. `Q333`. |
| `titles` | Edition → article title, for the requested editions or up to 20 large ones. |
| `titles_arg` | The same, ready to paste after `compare --titles`. |
| `missing` | Requested editions without an article on the topic. |
| `available_count` | How many Wikipedia editions have the article. |

### fetch, cache

`fetch` returns `languages[]` with `days` (days with data) and `missing`. `cache --status`
returns `path`, `size_bytes`, `series`, `days`; `cache --clear` returns `cleared`.

### Errors

```json
{"ok":false,"schema":1,"error":"unknown or closed Wikipedia edition: 'xx'",
 "hint":"Use a language code as in <code>.wikipedia.org, e.g. uk, pl, cs."}
```

Exit code 1. `hint` always names a concrete next action.

## metrics.json

| Key | Content |
|---|---|
| `request` | Exact parameters; `report --from-run` replays them. |
| `window` | `start`, `end`, `days`. |
| `question` | The `--question` text, printed on the report. |
| `summary` | Same as stdout. |
| `conclusions` | One sentence per language, secondary notes (raw vs share, excluded spikes), comparison sentences. They obey the rules in "What not to claim". |
| `ranking` | `tiers` and `unranked` languages. |
| `languages[]` | Everything from stdout plus the fields below. |
| `warnings` | All warnings. |
| `limitations` | The 12 standard limitations, verbatim from `assets/report-template.md`. |
| `report_truncated` | `true` if text had to be cut to keep the report on one page. |
| `cache` | As in stdout. |

Extra per-language fields:

| Key | Content |
|---|---|
| `basis` | `views_per_million` or `raw_views`: which series the verdict used. |
| `pct_per_year_ci` | Interval of `pct_per_year` at the level actually used (95%, or 99% when autocorrelated). |
| `sentence` | The conclusion sentence for this language. |
| `reach`, `penetration_vpm` | `median`, `low`, `high` from weekly values. |
| `gate_findings[]` | Every triggered gate: `gate`, `severity` (`stop`, `degrade`, `warn`), `message`. |
| `spike_events[]` | `start`, `peak`, `end` dates and `peak_ratio` (peak over the pre-event level). |
| `trend_views_per_million`, `trend_raw_views` | Diagnostics of each series: `alpha`, `lag1_autocorrelation`, `with_spikes` and `without_spikes` fits (weeks, log rate and interval, linear rate, Mann-Kendall z and p), `mde_pct_per_year`, `changepoint_date`, `changepoint_p`, `step_ratio`, `level_shift`, `multiple_changepoints`, `yearly_seasonal_amplitude`. |

The diagnostics exist so a result can be checked. Quote only `verdict`, `confidence`,
`pct_per_year`, `mde_pct_per_year`, `step_ratio`, the medians and `sentence`: the
diagnostic rates are not claims, for example a rate whose interval covers zero.

## How to phrase a recommendation

1. Start from the verdicts and confidence of the languages that passed the gates.
2. For "which language": the highest tier by share of attention, then audience size,
   then momentum. Say when the top languages are in the same tier.
3. For "is it growing": the verdict, the rate with its window, and the confidence.
4. Add one limitation that matters for the decision (usually: pageviews are attention,
   not demand; or one article per language).
5. Never place a refused language last. Say it had too little data.

Example: "In the 996-day window Ukrainian Wikipedia shows the largest share of attention
for the topic (tier 1) and it grew about 24% per year (high confidence). Polish and
Czech are in tier 2 and show no trend. Pageviews measure attention, not demand."
