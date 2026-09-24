# wikipedia-interest

An [Agent Skill](https://agentskills.io/specification) that answers questions like

- "Compare the growth of interest in intermittent fasting on Polish and Czech Wikipedia over two years."
- "Is interest in astronomy growing on Ukrainian Wikipedia, and how far can we trust that?"
- "Which language editions pay most attention to learning English? Prepare a report."

from Wikimedia pageview data. One CLI call resolves the article in every language,
downloads daily views, runs quality gates and robust trend statistics, and writes charts
plus a one-page PDF. The agent gets back one JSON line with a verdict from a closed
vocabulary, a confidence level and the numbers it may quote, so even a small model can
answer without opening a file.

The skill lives in [`skills/wikipedia-interest/`](skills/wikipedia-interest/):
[`SKILL.md`](skills/wikipedia-interest/SKILL.md) for the agent, the `wikitrends` Python
package for all logic, `references/` for details loaded on demand.

## Install

As a Claude Code plugin:

```bash
claude plugin marketplace add Kuzmenko-Oleksandr/wikipedia-interest-skill
claude plugin install wikipedia-interest@wikipedia-interest-skill
```

Or copy the folder: `cp -r skills/wikipedia-interest ~/.claude/skills/`.

Dependencies (pure wheels, no system packages, Python 3.12+):

```bash
cd skills/wikipedia-interest
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

`scripts/wikitrends` uses that `.venv` automatically. If dependencies are missing, the CLI
itself prints the exact command to run. With uv: `UV_LINK_MODE=copy uv sync --locked`.

## Use

```bash
sh skills/wikipedia-interest/scripts/wikitrends compare --topic "Intermittent fasting" \
  --langs pl,cs --since 2024-09-01 --question "Compare growth of interest in pl and cs"
```

Try it without network on the bundled synthetic fixture:

```bash
sh skills/wikipedia-interest/scripts/wikitrends compare --offline-fixture demo \
  --topic Astronomy --langs uk,pl,cs
```

```json
{"ok":true,"schema":1,"slug":"cs-pl-uk_astronomy_20240923-20260922",
 "report_pdf":"/abs/out/cs-pl-uk_astronomy_20240923-20260922/report.pdf",
 "metrics_json":"/abs/out/cs-pl-uk_astronomy_20240923-20260922/metrics.json",
 "summary":"Over 730 days: cs insufficient data; pl stable (MDE ±2%/yr) (medium); uk growing +23%/yr (high)",
 "languages":[{"lang":"cs","verdict":"insufficient_data","blocking_gate":"G1_low_volume"},
  {"lang":"pl","verdict":"stable","confidence":"medium","pct_per_year":0.1,"mde_pct_per_year":1.6},
  {"lang":"uk","verdict":"growing","confidence":"high","pct_per_year":22.5}],
 "tiers":[["uk"],["pl"]],
 "caveat":"Pageviews show attention to one article per language, not demand; this window only, no forecast.",
 "warnings":["Offline fixture: synthetic data, not real Wikipedia traffic."]}
```

Other commands: `resolve` (which editions have the article), `analyze` (numbers only),
`report --from-run SLUG`, `fetch`, `cache --status|--clear`. See
[`SKILL.md`](skills/wikipedia-interest/SKILL.md).

## How it works

```
topic ─► resolve ─► fetch ─► reindex ─► gates ─► normalize ─► spikes ─► seasonality
          (search +   (SQLite   (NaN for   (11 checks,  (per million  (15-day robust z,
          Wikidata)   cache)    gaps)      refuse early) edition views) events + tails)
      ─► weekly medians ─► trend ×2 (with / without spikes) ─► change point ─► verdict
                          Theil-Sen + Mann-Kendall            Pettitt + step model
      ─► charts + one-page PDF + one JSON line
```

Decisions that matter most:

- **Titles are never built from user input.** The pageviews API does not capitalize the
  first letter: `astronomy` returns about 1/1000 of the views of `Astronomy` with HTTP 200.
  Titles come from search plus Wikidata sitelinks.
- **Share, not raw views.** Each article is divided by its edition's total (smoothed by a
  7-day median). If raw views rise only because the whole edition grew, no rise in
  interest is claimed; if raw views are flat while the edition shrinks, the topic gained
  share. Only the share is comparable across languages.
- **Weekly medians.** Daily views are autocorrelated (0.5-0.9); on daily points a flat
  series reads as "significantly growing". Weekly medians remove the weekday cycle and
  bring the sample close to its effective size.
- **The trend is fitted twice**, with and without spike days. Growth that disappears
  without the spikes is reported as event-driven, not as growth.
- **Steps are not growth.** A jump after a rename, a Main Page link or a search-engine
  change is reported as a level shift, and no yearly rate is given.
- **Gates run before any estimate.** A series with too little traffic, a short window,
  long gaps or a collapse that signals a rename gets a refusal, never a low-confidence
  number. A refused language is listed apart, never ranked last.
- **No score.** A closed vocabulary of verdicts plus high/medium/low confidence, lowered
  one step per weakness (short window, autocorrelation, seasonality, ...). A null result
  comes with its minimum detectable effect: "no trend detected; changes above ±9%/yr
  would have been visible".
- **Languages are ranked in tiers**, by share of attention, with confidence intervals;
  overlapping languages share a tier instead of getting a false 1/2/3.

Formulas, thresholds, worked examples and every departure from the original design:
[`references/methodology.md`](skills/wikipedia-interest/references/methodology.md).

### Stack

Python 3.12, `numpy`, `matplotlib` (Agg backend, PDF through `PdfPages`, DejaVu Sans
shipped with matplotlib), `httpx`; `sqlite3`, `argparse`, `math.erfc` from the stdlib.
Rejected: plotly+kaleido (needs a system Chrome), reportlab (its built-in font has no
Cyrillic and silently draws boxes), fpdf2 (raises on the first Cyrillic letter),
hand-written SVG (no SVG-to-PDF path without cairo), scipy (every test fits in a few
lines of numpy).

### Efficiency for repeated questions

The Wikimedia API allows about 10 requests per minute per IP in practice. A typical
question costs 8 requests (search, sitelinks, three articles, three edition totals). The
SQLite cache records which ranges were requested, never refetches settled days, and
refreshes the last three days once a day. The same question again costs 0 requests;
"now the same in Czech" costs 2. Output folders are named after the request, not the
clock, so a rerun overwrites instead of piling up.

## How the AI's work was verified

The code was written with AI assistance. Nothing below takes the model's word for it.

**Known-answer tests (162, `make test`).** Hand-computed examples that pin each formula:
Mann-Kendall on `[1, 3, 2, 1]` must give `S = −1`, `Var(S) = 7.667`, `Z = 0` (8.667 means
the tie correction is missing, −0.361 means the continuity correction is missing); Pettitt
on `[1, 2, 3, 10, 11, 12]` must split at index 3 with `p = 0.291`. Synthetic series with a
planted answer: +30%/yr is recovered within ±2 points, a flat series gives uniformly
distributed p-values (2-8% below 0.05 over 400 runs), a series with news spikes is
event-driven, a step is a level shift, a ±35% seasonal cycle raises at most 3 false alarms
in 20 seeds. Every gate fires on its fixture and not on the neighbouring one. Every
sentence the tool writes passes a forbidden-claims checker.

**The tests found real design flaws.** Four parts of the original design failed their
synthetic tests and were changed (details in methodology.md): a centred 15-day spike
window missed a 41× news spike whose decay filled half the window; +30% days on busy
articles passed as spikes; a straight-line detrend leaked level steps into the month
offsets (false seasonal trends fell from 27% to 7.5% after the fix); and the MDE
collapsed to 0 on low counts. Separately, the contract test caught stdout lines over
1 KB with six languages and long paths.

**Rendering without looking.** A missing-glyph warning is an error (verified to fire on
Japanese text); the PDF has exactly one A4 page, no creation date, and `Вікіпедія`,
`Łódź`, `Řehoř` extract back as text; two builds are byte-identical; PNGs are not blank.
CI also runs the tests in `python:3.12-slim`, which has no fonts at all.

**The full scenario on Claude Haiku 4.5.** `evals/` holds five cases for
`claude plugin eval` on the synthetic fixture (planted answers: uk growing ~23%/yr; pl
stable and fr a one-off step; de a rise made of six spikes; cs too little data; a
Google Analytics question that must not trigger the skill) and one live case. The
harness itself needs a shell sandbox that this build container lacks, so each case was
run on `claude-haiku-4-5` through `claude -p --plugin-dir` (the same agent loop without
the harness), three times after the last change to the skill, and the answers were
graded against the case rubrics by a separate Sonnet judge:

| Metric (SPEC §11.3) | Target | Measured on Haiku 4.5 |
|---|---|---|
| Skill fires on natural phrasing (6 queries ×3) | ≥ 90% | 17/18 (94%) |
| False triggers on near-miss questions (4 queries ×3) | 0% | 0/12 |
| Tool calls per scenario | ≤ 8, median ≤ 5 | 2 in every run (Skill + one `compare`) |
| Repeated file reads | 0 | 0 |
| PDF written to the user's folder | every scenario | 12/12 |
| Peak context | ≤ 60K tokens | 33.3-33.8K |
| Wall time | ≤ 60 s | 15-26 s |
| Cost per scenario | ≤ $0.02 | $0.029-0.036 (missed: the question that does not use the skill already costs $0.013, which is Claude Code's own prompt) |
| Answers passing the case rubric (Sonnet judge) | score ≥ 0.8 | 15/15 |

Getting there took several rounds, and the misses are the useful part:

1. First runs: the agent `cd`-ed into the skill folder and wrote reports there, named
   no limitation, answered "Yes, but…" to a rise made of spikes, and read "not enough
   data" as "low priority". Fixed with a full-path rule, a quotable `caveat` field in the
   JSON and exact wording per verdict in `SKILL.md`. Next round: 15/15.
2. After the review fixes a rerun scored 12/15: twice the refusal for Czech became "the
   topic is not popular", once the only limitation named was "synthetic data". Text in
   `SKILL.md` was not enough, so the data now carry the framing: a refusal comes with a
   `reason` that says low traffic on one article says nothing about interest in the
   topic, and the answer template has a fixed "Limitations:" line.
3. A request that names no languages ("in the selected editions") triggered the skill
   0 times out of 3: Haiku asked which languages first. The description now says to use
   the skill anyway, since it can list the editions itself. Final round: 17/18 triggers
   and 15/15 rubric passes.
4. Two prompts the skill was never tuned on (which language to localize a course into; a
   question naming no languages) exposed a defect in the tool, not the model: near the
   1 KB limit the line dropped a refusal's `reason` and the audience size before the chart
   paths the agent never opens. Haiku filled the gap by calling the share of attention
   "absolute" views and a one-off step "growing demand"; `SKILL.md` also told it to read
   every verdict as momentum. Paths are now shed first and only a trend counts as
   momentum. Afterwards every Czech refusal said that low traffic says nothing about
   interest, and none of 5 localization answers called the step growth or demand.

**Independent code review.** A separate agent reviewed the package for correctness bugs
and had to reproduce every finding with a probe script before reporting it. It found 11;
ten are fixed, each with a regression test in `tests/test_regressions.py`. The most
serious: `log1p` on views per million, which are often below 1, flattened growth rates
(+30%/yr read as +9%, a 60% step as 17%); the log offset is now relative to the series.
The others: a report crash with 14 or more languages, error lines that could lose their
hint, a step size shown where only the direction may be, double counting when a renamed
article is combined with its redirects, a step date a few days late, silent fallbacks
to raw views, relative cache paths and an overwritten panel label. The eleventh,
`--help` printing to stderr instead of JSON, is by design. A look at a generated report
separately caught a step dated eight weeks late: Pettitt's split drifts when the level
after a step keeps rising, so the location now comes from a median scan.

**What was not verified.** This work was done in a container without access to
wikimedia.org, so the pipeline has not been run on live data here. The API behaviour it
relies on (404 means "no data", omitted days, first-letter case, the rate limit) comes
from probes recorded in the design document. Run the `live-compare-real` eval case, or
`--record-fixture DIR` once, on a machine with network access.

### Run the evals

```bash
cd skills/wikipedia-interest
UV_LINK_MODE=copy uv sync --locked          # the harness rejects hard-linked files
claude plugin eval . --tag fixture --allow-tools Bash --trust-plugin \
  --model claude-haiku-4-5 --judge-model claude-sonnet-5 --runs 3
claude plugin eval . --tag live --allow-tools Bash --trust-plugin --model claude-haiku-4-5
```

The harness needs its shell sandbox (bubblewrap and socat on Linux). The fixture cases set
`EVAL_WIKITRENDS_FIXTURE=demo`, so the agent runs the real CLI on synthetic data with a
known answer. `evals/trigger-*.md` hold the trigger queries.

## Not goals

- Not forecasting: the skill describes the observed window and never extrapolates.
- Not a measure of demand or purchase intent: pageviews are a proxy for attention.
- Not real time: data lag by one to two days.
- Not mass screening of thousands of topics in v1 (see the roadmap).

The twelve limitations printed in every report are in
[`assets/report-template.md`](skills/wikipedia-interest/assets/report-template.md).

## Roadmap

1. **From an article to a topic.** Interest is spread over many articles and redirects.
   Build a topic as a versioned set of articles (Wikidata categories, `prop=redirects`) and
   sum their series. `--include-redirects` is the first step.
2. **Scale.** SQLite to Parquet/DuckDB, batch mode for hundreds of topics, backfill from
   the [pageview dumps](https://dumps.wikimedia.org/other/pageviews/) instead of the API,
   parallel requests within the rate limit.
3. **More signals.** Unique devices as a second opinion; pageviews by country to separate
   "interest in a country" from "interest in a language", which differ for localization;
   external sources (Google Trends, app stores) as a cross-check, not a replacement.
4. **Validate the conclusions.** Backtest: take what the skill would have recommended two
   years ago and compare with what happened. It is the only way to learn whether rising
   pageviews predict real demand; today that is an assumption.

## Repository layout

```
.claude-plugin/marketplace.json   install as a plugin
.github/workflows/ci.yml          lint, types, tests (Ubuntu, macOS, fontless container), eval
skills/wikipedia-interest/
  SKILL.md                        instructions for the agent (10 KB, under 3K tokens)
  scripts/wikitrends              CLI entry point, uses the skill's .venv
  wikitrends/                     all logic: api, cache, resolve, series, gates, stats,
                                  verdict, analysis, narrative, render, report, cli
  wikitrends/fixtures/demo/       synthetic offline fixture
  references/                     methodology, interpreting-output, troubleshooting
  assets/report-template.md       the limitations block
  evals/                          claude plugin eval cases and trigger queries
  tests/                          unit, rendering and contract tests
```

Development: `cd skills/wikipedia-interest && make check` (ruff, basedpyright, pytest).

## License

MIT
