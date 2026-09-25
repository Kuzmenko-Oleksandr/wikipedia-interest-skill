---
name: wikipedia-interest
description: >-
  Analyzes Wikipedia pageview data to compare interest in a topic across language
  editions and detect whether that interest is genuinely growing. Produces charts and
  a one-page PDF report with explicit confidence levels and stated limitations. Use when
  deciding which topic to build content for, which language to localize into, or when
  asked whether interest in a subject is rising in a given country or language. Also use
  it whenever a request pairs Wikipedia with interest, popularity, attention or pageviews
  of a topic. If no languages are named, use it anyway: it lists the editions that have
  the article so languages can be proposed. Not for real-time traffic, not a measure of
  purchase intent, and not a forecasting tool.
license: MIT
compatibility: >-
  Requires Python 3.12+ and network access to wikimedia.org. Dependencies installed via
  pip from requirements.txt. Does not work in sandboxes without network access or
  package installation.
---

# Wikipedia interest

## Procedure

Follow these steps in order. All numbers come from the script; never compute them yourself.

1. Pick the languages. Map names to edition codes: English `en`, Ukrainian `uk`,
   Polish `pl`, Czech `cs`, German `de`, French `fr`, Spanish `es`, Italian `it`,
   Portuguese `pt`, Japanese `ja`. If the user named no languages, run
   `resolve` first (see "Choosing languages").
2. Write the topic as the English Wikipedia article name, for example
   `Intermittent fasting`. If the topic only exists in one local edition, write it in
   that language and add `--source-lang <code>`.
3. Pick the window. Default is the last two years; omit `--since`. For "since <date>"
   or "over the last N years" pass `--since YYYY-MM-DD`.
4. Run one `compare` call (see "Quick start"). It resolves titles, downloads, analyzes,
   draws charts and writes the PDF. Do not run any setup check first.
5. Answer from the printed JSON line only: `summary`, then per language `verdict`,
   `confidence`, `pct_per_year` or `mde_pct_per_year`, `blocking_gate`. Do not open the
   PDF, PNG, CSV or metrics file unless the user asks for details they contain. If a
   field is missing from the line, leave it out; never open `metrics.json` to fill it in.
6. Answer in the user's language with exactly these parts, in this order:
   - one sentence per language: its verdict, the window, its `confidence`;
   - if `tiers` holds two or more languages, one sentence on their order: the first
     inner list gets the largest share of attention; languages in one list tie;
   - the `report_pdf` path;
   - a line starting "Limitations:" with the `caveat` text, always, even when
     `warnings` add other notes.
7. Base every recommendation on a verdict and its confidence. Say which language or
   topic the data favours and why, in one or two sentences. A level shift or a rise
   from spikes is not momentum: never call it growth or rising demand, here either.
   Choose only among the languages in the JSON line. Do not suggest other languages,
   topics, markets or product ideas: the data says nothing about them.

## Running the script

Call it with `sh` and its full path, from the current working directory:
`sh <skill-dir>/scripts/wikitrends ...`, where `<skill-dir>` is this skill's base
directory. Never `cd` into the skill directory: reports go to `./out` of the current
directory. If the JSON line says `"ok":false` with an install command in `hint`, run that
command once and repeat the call. The script uses the skill's `.venv` automatically.

## Quick start

```bash
sh <skill-dir>/scripts/wikitrends compare --topic "Intermittent fasting" --langs pl,cs \
  --since 2024-09-01 --question "Compare growth of interest in intermittent fasting in pl and cs"
```

Prints exactly one JSON line, for example:

```json
{"ok":true,"slug":"cs-pl_intermittent-fasting_20240901-20260922",
 "report_pdf":"/abs/out/.../report.pdf","metrics_json":"/abs/out/.../metrics.json",
 "summary":"Over 752 days: cs insufficient data; pl growing +18%/yr (medium)",
 "languages":[{"lang":"cs","verdict":"insufficient_data","blocking_gate":"G1_low_volume"},
  {"lang":"pl","verdict":"growing","confidence":"medium","pct_per_year":18.2,
   "vpm_median":4.1,"reach_median":310,"flags":["autocorrelated"]}],
 "tiers":[["pl"]],"caveat":"Pageviews show attention to one article per language, ...",
 "warnings":[],"cache":{"hits":0,"fetched":4}}
```

A follow-up question on the same topic and window costs no network requests: rerun the
same command and the cache answers.

## Commands

| Command | Use it when |
|---|---|
| `compare --topic T --langs a,b [--since D] [--until D] [--question Q]` | Default. One call does everything. |
| `compare --titles uk:Астрономія,pl:Astronomia ...` | You already have exact titles (skips the search). |
| `resolve --topic T [--langs a,b]` | The user named no languages; lists editions that have the article. |
| `analyze ...` (same options as compare) | Numbers only, no charts or PDF. |
| `report --from-run SLUG` | The user wants the PDF after an `analyze` run. |
| `fetch ...` | Only download into the cache. Rarely needed. |
| `cache --status` / `cache --clear` | Diagnose setup or the cache. |

Options for every data command: `--out-dir DIR` (default `./out`), `--refresh` (ignore
the cache), `--include-redirects` (also count views of redirects; costs extra requests),
`--source-lang CODE` (edition used to search the topic, default `en`).

## Reading the output

Verdicts, in the order the script tests them:

| verdict | Say |
|---|---|
| `insufficient_data` | "Not enough data to measure a trend", then the `reason` as given. Never call the topic unpopular or say readers prefer something else; never rank it last. |
| `series_discontinuity` | "The article was probably renamed; the series breaks." No trend claim. |
| `level_shift_up` / `level_shift_down` | "Views jumped (or dropped) by ~(step_ratio−1)×100% around `step_date` (the month is also in `summary`) and stayed there: a one-off shift, not growth." Never say "grew". |
| `growing_event_driven` / `declining_event_driven` | "No lasting change: the rise (or drop) came from short spikes; without them no trend is detected." Answer "is it growing?" with no. |
| `growing` / `declining` | "Grew/fell ~pct_per_year %/yr over the N-day window." Without `pct_per_year`, give the direction only. |
| `stable` | "Stable: the yearly change is within ±5%." |
| `no_detectable_trend` | "No trend detected; changes smaller than ±mde_pct_per_year %/yr would not have been visible." |

`confidence` is `high`, `medium` or `low`; each flag below lowers it one step. State it
next to the verdict as given; explain it only with the flags listed, never with reasons
of your own.

| flag | Meaning |
|---|---|
| `direction_only` | Under 50 views/day: direction only, no percentage. |
| `no_annualization` | Window under a year: no percentage per year. |
| `no_annual_baseline` | Window under two years: seasonality not removed. |
| `seasonality_suspected` | Strong yearly cycle; the trend depends on how it was removed. |
| `autocorrelated` | Weeks depend on each other; the test used a stricter threshold. |
| `raw_vpm_divergence` | Raw views and share of the edition moved differently; see `metrics.json` notes. |
| `gappy`, `late_start`, `many_zeros` | Missing days, a new article, or many zero days. |
| `vpm_suppressed` | Edition totals unusable; the verdict uses raw views. |
| `multiple_changepoints`, `event_inflated`, `sign_flip` | The series has several breaks, or spikes inflate or flip the trend. |
| `spike_events` | Spikes were found and left out of the trend (dates in `metrics.json`). |

Other fields: `pct_per_year` is the change of views per million edition views (or raw
views if `vpm_suppressed`); `vpm_median` is the share of attention and the only number
comparable across languages; `reach_median` is typical daily views; `summary` is at most
200 characters and safe to quote.

## Choosing languages

1. Run `sh <skill-dir>/scripts/wikitrends resolve --topic "T"`.
2. Read `titles` (up to 20 large editions that have the article) and `available_count`.
3. Suggest 3 to 5 editions that fit the user's goal, or ask the user to choose.
4. Then run `compare --titles <titles_arg from resolve, trimmed to the chosen languages>`.

For "which language should we localize into": rank by `vpm_median` (share of attention),
break ties by `reach_median` (audience size). Only `growing` or `declining` is momentum; a
level shift is a one-off change that says nothing about where views are heading. Treat
languages in the same inner list of `tiers` as statistically indistinguishable.

## Failure modes

| You see | Do |
|---|---|
| `"ok":false` | Run or follow the `hint` exactly, then retry once. |
| `blocking_gate: "no_article"` | That edition has no article on the topic. Say so; do not rank it. |
| `blocking_gate: "G1_low_volume"` | Too little traffic. Offer a broader topic or a larger edition. |
| `blocking_gate: "G3_short_window"` | Window under 180 days. Rerun with an earlier `--since`. |
| `blocking_gate: "G7_end_collapse"` | Article renamed or removed. Run `resolve` and retry with the new title. |
| Rate limit in `error` | Wait 60 seconds, rerun the same command once; cached data is kept. |
| Network or DNS error | Tell the user the skill needs network access to wikimedia.org. |
| A wrong article (e.g. a film instead of the subject) | Rerun with `--titles lang:Exact title`. |

Do not retry more than once. Do not edit files in this skill.

## What not to claim

| Never say | Say instead |
|---|---|
| "N people are interested in Y" | "The article got N views per day." |
| "Demand for Y is growing" | "Views of the Y article grew ~X%/yr over this window." |
| "Y will reach N by <date>" | Nothing. No forecasts. |
| "There is no trend" | "No trend detected; changes under ±MDE %/yr would not have been visible." |
| "Event Z caused the rise" | "The rise coincides with Z on <date>; causality is not established." |
| "Language A is more interested than B" (raw views) | "A gets N× the views of B; per million edition views the ratio is r." |
| `vpm_median` as absolute views or audience size | "N views per million edition views (share of attention)"; audience size is `reach_median`. |
| Any percentage when `pct_per_year` is absent | The direction only. |
| Any number the JSON line does not contain (a trust percentage, a probability) | The `confidence` word and its flags. |

Always mention: pageviews measure attention, not demand; one article per language;
the result covers the stated window only.

## References

Load only when needed:

- `references/interpreting-output.md` — every field of the JSON line and `metrics.json`.
- `references/methodology.md` — formulas, thresholds, gates and their messages.
- `references/troubleshooting.md` — API errors, setup problems, offline mode.
