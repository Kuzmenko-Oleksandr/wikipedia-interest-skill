# Technical specification: the `wikipedia-interest` skill — interest analysis from Wikipedia data

Version 1.0 · 2026-09-24 · submission deadline 2026-09-27 23:59

This document is based on four parallel research tracks (Wikimedia API, statistics,
the Agent Skills spec + testing on Haiku, rendering). Every fact marked "verified"
was confirmed by real curl requests or by running code.

---

## 1. The task and the evaluation criteria

### 1.1 What is asked

A self-contained skill in the [Agent Skills](https://agentskills.io/specification) format
that lets an AI agent answer questions like:

- "Compare the growth of interest in intermittent fasting in the Polish and Czech Wikipedia over two years"
- "Is interest in astronomy growing in the Ukrainian Wikipedia, and how far can this be trusted?"
- "Compare interest in learning English across selected language editions and prepare a report"

Output: charts + a short report (a one-page PDF), data-backed recommendations with explicit
assumptions and limitations.

### 1.2 What is evaluated (reconstructed from the assignment text)

| Requirement in the text | How we meet it |
|---|---|
| `SKILL.md` + own code, not just markdown | Python package `wikitrends`, all logic in code, the agent only calls the CLI |
| No compiled files, reproducible dependencies | pip wheels, pinned `requirements.txt`, `uv.lock`, zero system dependencies |
| Everything inside the skill directory | The package lives inside `skills/wikipedia-interest/` |
| Help the agent assess results and check conclusions | 11 quality gates, flags, a verdict from a closed vocabulary, MDE, a table of forbidden claims |
| Handle repeated and related queries efficiently | SQLite cache, idempotent artifact names, incremental fetching |
| Recommendations are data-backed, assumptions are clear | A 12-item "Limitations" block in every report, not optional |
| Convenient and efficient for an agent on a cheap model | One main CLI call, ≤8 tool calls, ≤5000-token SKILL.md, all computation in scripts |
| Test the full scenario on Haiku 4.5 | `claude plugin eval` suite run on `claude-haiku-4-5` with an ablation arm |
| Explain how to develop it further | A README section with four stages |
| Explain how AI output was verified | A README section + unit tests on synthetic data with a known answer |

### 1.3 Explicit non-goals (stated in the README; this is a maturity signal too)

- Not forecasting. The skill describes the observed window and does not extrapolate.
- Not a measure of paying demand. Pageviews are a proxy for attention.
- Not real-time. Data lags by 1–2 days.
- Not mass screening of thousands of topics in v1 (see the roadmap).

---

## 2. Stack and key architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | matplotlib covers charts + PDF + Cyrillic with one dependency |
| Runtime dependencies | `matplotlib`, `numpy`, `httpx` | 24 MB of wheels, zero system packages, verified on macOS |
| Charts | matplotlib, Agg backend | The only headless, PDF-native option without system dependencies |
| PDF | `matplotlib.PdfPages` + GridSpec | Zero extra dependencies; 70% of the report is charts |
| Font | DejaVu Sans shipped with matplotlib | Verified: covers every UA/PL/CZ character; no font file in the repo |
| Cache | SQLite (stdlib) | Zero dependencies, atomicity, date-range queries |
| CLI | `argparse` (stdlib) | Click is not needed, one dependency saved |
| Statistics | numpy + `math.erfc` | scipy is not needed, every method fits in a few dozen lines |

**Rejected, with reasons** (stated in the README to show the choice was deliberate):
- `plotly + kaleido` — since 1.0 kaleido does not ship Chrome and needs a system browser
- `reportlab` — the bundled Vera font **has no Cyrillic** and silently renders `■■■■` (verified)
- `fpdf2` — raises an exception on the first Cyrillic letter (verified)
- hand-written SVG — hits the SVG→PDF wall: cairosvg/rsvg are ruled out by the assignment
- PHP — would need a hand-written chart renderer + mPDF + solving the font problem by hand

---

## 3. Repository layout

```
wikipedia-interest-skill/                 # root of the public repository
├── README.md                             # logic, methodology, AI verification, roadmap
├── LICENSE                               # MIT
├── .gitignore
├── .claude-plugin/
│   └── marketplace.json                  # one-command install
├── .github/workflows/ci.yml              # tests + eval gate
└── skills/
    └── wikipedia-interest/               # ← folder name == frontmatter name
        ├── SKILL.md                      # ≤500 lines, ≤5000 tokens
        ├── pyproject.toml
        ├── requirements.txt              # pinned versions
        ├── scripts/
        │   └── wikitrends                # executable shim: python -m wikitrends
        ├── wikitrends/                   # the package — all substantive logic
        │   ├── __init__.py
        │   ├── __main__.py               # MPLBACKEND=Agg before any import
        │   ├── cli.py                    # argparse, subcommands, stdout JSON contract
        │   ├── api.py                    # HTTP to Wikimedia: UA, retries, backoff
        │   ├── resolve.py                # topic → canonical titles per language
        │   ├── cache.py                  # SQLite
        │   ├── series.py                 # calendar reindex, NaN, weekly aggregation
        │   ├── stats.py                  # Theil–Sen, Mann–Kendall, Pettitt, MAD
        │   ├── gates.py                  # 11 quality gates + warning texts
        │   ├── verdict.py                # flags → verdict → confidence
        │   ├── render.py                 # charts
        │   ├── report.py                 # one-page PDF
        │   └── fixtures/                 # offline data for tests and --offline
        ├── references/
        │   ├── methodology.md            # formulas, thresholds, how to read the metrics
        │   ├── interpreting-output.md    # what every JSON field and flag means
        │   └── troubleshooting.md        # API error codes and what to do
        ├── assets/
        │   └── report-template.md        # text of the limitations block
        ├── evals/                        # claude plugin eval
        │   ├── growth-single-lang/
        │   ├── compare-two-langs/
        │   ├── spike-driven/
        │   ├── insufficient-data/
        │   └── negative-should-not-trigger/
        └── tests/
            ├── test_stats.py             # synthetic data with a known answer
            ├── test_series.py
            ├── test_gates.py
            ├── test_render.py            # glyphs, PDF structure, determinism
            └── test_cli_contract.py
```

**Why `skills/` rather than the root:** this is how `anthropics/skills` and both repositories
we looked at are laid out; it allows adding a second skill without restructuring.

---

## 4. External APIs — exact specification

Everything in this section was verified with real requests on 2026-09-24.

### 4.1 Host and the mandatory User-Agent

```
https://wikimedia.org/api/rest_v1/metrics/...
```

⚠️ `api.wikimedia.org/metrics/...` **is not a mirror** — it returns a 301 to a documentation
page. Follow redirects without checking the content type and you get HTML instead of data.

A User-Agent is mandatory, in the format required by the Wikimedia policy:

```
wikipedia-interest-skill/1.0 (https://github.com/Kuzmenko-Oleksandr/wikipedia-interest-skill) httpx/0.28
```

Default UAs (`python-httpx`, `curl`, `Python-urllib`) **are blocked with 403**, including
as a prefix. Sending a browser UA is forbidden by the policy.

### 4.2 Rate limits — the main architectural constraint

Documented: 200 req/min with a valid UA. **Actually measured: ~10 req/min**, i.e. the
"unidentified client" tier. The limit is **per IP**, not per UA — in CI and behind NAT the
bucket is shared.

Consequences for the implementation:
- Design for 10 req/min. Requests are sequential, not parallel.
- Retry on 429 and 503 with exponential backoff, honour `Retry-After`, and wait ≥5 s
  when it is absent.
- ⚠️ **The 429 response body is plain text, not JSON.** `json.loads` on it will fail.
- The cache is mandatory, not "nice to have": pageview history is immutable once settled.

Request budget for a typical scenario (3 languages, 2 years):
`1 (search) + 1 (sitelinks) + 3 (articles) + 3 (denominators) = 8 requests`. Fits
in a minute. A follow-up question on the same data costs **0 requests**.

### 4.3 Per-article pageviews

```
GET /metrics/pageviews/per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}
```

| Parameter | Value in our skill | Why |
|---|---|---|
| `project` | `uk.wikipedia` (no protocol) | |
| `access` | **`all-access`** | the mobile/desktop split reflects the requested URL, not the device, and has changed for infrastructure reasons; unusable for trends |
| `agent` | **`user`** | excludes bots and automated traffic |
| `granularity` | **`daily`** only | monthly silently truncates the edge buckets |
| `start`/`end` | `YYYYMMDD`, inclusive | |

Response:
```json
{"items":[{"project":"en.wikipedia","article":"Intermittent_fasting","granularity":"daily",
           "timestamp":"2025090100","access":"all-access","agent":"all-agents","views":628}]}
```

⚠️ `timestamp` is always `YYYYMMDDHH`; the trailing `00` is a placeholder, not an hour.

### 4.4 Aggregate pageviews — the normalization denominator

```
GET /metrics/pageviews/aggregate/{project}/{access}/{agent}/daily/{start}/{end}
```

The response schema differs: **no `article` field**, different key order. Separate parser.

**Rule:** the denominator slice must match the numerator slice — `all-access` + `user`
on both. Mixing them gives a metric that drifts with changes in bot filtering.

⚠️ The aggregate includes `Main_Page` (~1.4% of en.wikipedia traffic), `Special:Search` (~0.23%)
and every non-article namespace. There is no namespace filter. We accept a systematic
understatement of the share and say so in the limitations.

### 4.5 Data bounds

| Fact | Value | Verified |
|---|---|---|
| Earliest day (per-article) | **2015-07-01** | yes, 20150625 silently returns data from 07-01 |
| Earliest day (aggregate) | **2015-07-01** | yes, 2015-05-01 returns 404 |
| Lag behind real time | 1 day as of 2026-09-24; we allow 24–48 h | yes |

Implementation: clamp `start` to 2015-07-01 with a warning; `end` defaults to
`today - 2 days`.

Legacy pagecounts (2007-12 → 2016-08) **are not used**: a different methodology, a `count`
field instead of `views`, aggregate only, no per-article data. Splicing the two series is a
methodological break, not a trend.

### 4.6 Response codes

| Code | Meaning here | Action |
|---|---|---|
| 200 | Data for at least one day (may be fewer days than requested) | |
| 400 | Malformed parameter or date format | Do not retry, fix the request |
| 403 | Bad User-Agent | Do not retry |
| **404** | **"no data"**, NOT "the article does not exist" | Check existence via the Action API |
| 429 | Rate limit. The body is plain text | Backoff |
| 503 | Backend overload | Retry |

⚠️ **404 merges three different cases**: a typo in the title / the article exists but had no
traffic in the period / the project is not loaded. It must not be shown to the user as
"article not found".

### 4.7 Title encoding — silent error source #1

1. The canonical form uses underscores: `Intermittent_fasting`
2. Spaces work as `%20`, but **`+` is not decoded** in a path segment. Never use `+`.
3. A slash must be `%2F`: `AC%2FDC` → works, `AC/DC` → 400/404. **The response returns the
   decoded `AC/DC`** — re-encode it before reuse.
4. Unicode: UTF-8 percent-encoding. `M%C3%BCnchen` → `München` in the response.
5. ⚠️ **The first letter is case-sensitive; the API does NOT capitalize it.**

   ```
   .../Astronomy/...  → ~1500 views/day
   .../astronomy/...  → 1 view, HTTP 200
   ```

   That is a silent thousandfold undercount without a single error. **Titles must be
   normalized through the Action API or Wikidata sitelinks. Building the URL from user
   input is forbidden.**

Implementation: `urllib.parse.quote(title.replace(' ', '_'), safe='')`.

### 4.8 Gaps in the data

⚠️ **Days without data are OMITTED, not returned as 0.** If there is no data for the whole
range, the whole request is a 404, not an empty `items[]`.

The response cannot distinguish "zero views", "a data collection outage" and "the article did
not exist yet". A reindex onto the full calendar with NaN is mandatory (section 7.1). Indirect
check: if the gap is also present in the project aggregate, it is a collection incident, not a
property of the article.

### 4.9 Resolving a topic into per-language titles

**Main path — 2 requests.**

Step 1: a search on the target wiki gives the canonical title and guards against typos.
```
GET https://uk.wikipedia.org/w/api.php
    ?action=query&list=search&srsearch=астрономія&srnamespace=0&srlimit=3
    &format=json&formatversion=2
```
⚠️ `snippet` contains HTML (`<span class="searchmatch">`) — strip it before display.

Step 2: title → sitelinks in every language, one request.
```
GET https://www.wikidata.org/w/api.php
    ?action=wbgetentities&sites=ukwiki&titles=Астрономія
    &props=sitelinks&normalize=1&format=json
```
```json
{"entities":{"Q333":{"sitelinks":{
  "enwiki":{"site":"enwiki","title":"Astronomy"},
  "dewiki":{"site":"dewiki","title":"Astronomie"},
  "plwiki":{"site":"plwiki","title":"Astronomia"}}}}}
```

Q333 has 318 sitelinks, 254 of them Wikipedias.

⚠️ The response is **keyed by a Q-id that is not known in advance** — iterate over the values,
do not index by key.

⚠️ A "dbname ends with `wiki`" filter catches extras: `commonswiki`, `metawiki`,
`wikidatawiki`, `specieswiki`. Intersect with the sitematrix.

`&sitefilter=plwiki|cswiki` shrinks the response when the languages are given explicitly.

**List of valid projects** — a cacheable one-off request:
```
GET https://meta.wikimedia.org/w/api.php?action=sitematrix&smtype=language&format=json
```
⚠️ The top level is an object with numeric string keys plus `count` and `specials`.
⚠️ `"closed":""` marks a closed wiki — check for the **presence of the key**; `""` is falsy.

**Checking existence and redirects:**
```
GET https://uk.wikipedia.org/w/api.php?action=query&titles=...&redirects=1
    &format=json&formatversion=2
```
- `query.redirects[]` appears only if a redirect was followed
- `query.normalized[]` is exactly the case fix that pageviews does not do
- Missing pages: `"missing":true` with `formatversion=2`

### 4.10 Redirects do not add up views — the v1 decision

⚠️ Verified: `Obama` gets 124–206 views/day **independently** of `Barack_Obama`.
A view belongs to the title in the URL the reader requested. A metric on one canonical
title systematically undercounts — by 10–30% for topics with common synonyms.

**v1 decision:** count the canonical title. State the limitation explicitly in the report.
Add an optional `--include-redirects` flag that collects redirects via
`prop=redirects&rdlimit=500` and sums the series.

**Rationale:** at 10 req/min, listing redirects for 3 languages costs 3 more requests
for the lists plus up to N requests for the series. As a default this breaks the budget.
As an option it is correct and honest.

---

## 5. CLI contracts

Single entry point: `python -m wikitrends <command>`. The `scripts/wikitrends` shim is for convenience.

### 5.1 The main command — `compare`

Covers 90% of scenarios **in one call**. This is the key decision for a cheap model:
resolve + fetch + analysis + charts + PDF in one tool call.

```bash
python -m wikitrends compare \
  --topic "інтервальне голодування" \
  --langs uk,pl,cs \
  --since 2024-01-01 \
  [--until 2026-09-22] \
  [--source-lang uk] \
  [--out-dir ./out] \
  [--no-report] \
  [--include-redirects] \
  [--refresh]
```

Alternative when the titles are already known (skips resolution, saves 2 requests):
```bash
python -m wikitrends compare --titles uk:Астрономія,pl:Astronomia --since 2024-01-01
```

### 5.2 Auxiliary commands

| Command | Purpose | When the agent calls it |
|---|---|---|
| `resolve --topic X [--langs ...]` | topic → canonical titles + Q-id + list of available languages | The user did not name languages; options need to be offered |
| `fetch --titles ... --since ...` | fetch into the cache only | Rarely; cache warm-up |
| `analyze --titles ... --since ...` | statistics only, no images | A follow-up question on already fetched data |
| `report --from-run <slug>` | rebuild the PDF from a finished analysis | The user asked for a report after `analyze` |
| `cache --status` / `--clear` | cache state | Diagnostics |

### 5.3 The stdout contract — strict

**Exactly one line of JSON on stdout. Everything else goes to stderr.**

```json
{"ok":true,"schema":1,
 "slug":"cs-pl-uk_intermittent-fasting_20240101-20260922",
 "report_pdf":"/abs/out/<slug>/report.pdf",
 "report_png":"/abs/out/<slug>/report.png",
 "charts":["/abs/.../chart-timeseries.png","/abs/.../chart-normalized.png"],
 "metrics_json":"/abs/.../metrics.json",
 "data_csv":"/abs/.../data.csv",
 "summary":"uk: growing ~+31%/yr (medium confidence); pl: no trend; cs: insufficient data",
 "languages":[
   {"lang":"uk","title":"Інтервальне голодування","verdict":"growing","confidence":"medium",
    "pct_per_year":31.2,"vpm_median":31.7,"reach_median":412,"flags":["no_annual_baseline"]},
   {"lang":"cs","verdict":"insufficient_data","blocking_gate":"G1_low_volume"}],
 "warnings":["730-day window: each calendar month observed only twice"],
 "cache":{"hits":6,"fetched":2}}
```

Rules:
- Paths are **absolute**. The agent's working directory is not ours.
- `summary` ≤200 characters: a cheap model must be able to answer the user **without opening
  a single file**.
- The whole line ≤1 KB. Daily data never goes to stdout — it lives in `data.csv`.
- Error: `{"ok":false,"schema":1,"error":"...","hint":"..."}`, exit code 1, also one line.
- `hint` is mandatory and names a concrete action: `"Run resolve --topic X to get the canonical title"`.

### 5.4 Artifact names

`<slug>` is derived **from the request, not from the time**:
```
"-".join(sorted(langs)) + "_" + article_slug + "_" + start + "-" + end
```
Same question → same folder → a rerun is idempotent, no timestamped clutter.
File names inside are fixed and boring: `report.pdf`, `chart-timeseries.png`.
The model must not have to parse a name to find the report.

---

## 6. Processing pipeline

The stage order is strict; each stage consumes the output of the previous one.

```
0. resolve          topic → canonical titles (Action API + Wikidata)
1. fetch            HTTP + cache → raw items[]
2. reindex          full calendar, NaN for gaps
3. gates            11 quality checks → a hard stop is possible
4. normalize        denominator smoothed with a 7-day median → views per million
5. spikes           rolling median + MAD → spike mask, list of events
6. seasonality      weekday and month indices → deseasonalized series
7. weekly           weekly medians over ≥5 observed days
8. trend            Theil–Sen + Mann–Kendall, TWICE: with and without spikes
9. changepoint      Pettitt + step-size scan
10. verdict         flags → verdict → confidence level
11. render          charts
12. report          one-page PDF
```

The gates (3) run **before** estimation. A series that fails a gate gets a refusal, not a
low-confidence number.

---

## 7. Series processing and statistics

Full formulas, numpy implementations and numeric examples for self-checking are in
`references/methodology.md`. This section holds the contract and the decisions.

### 7.1 Reindex onto the calendar

1. `dates = np.arange(start, end+1d, dtype='datetime64[D]')` — the full calendar
2. `y = np.full(n, np.nan)`, values from the API are placed at their date positions
3. `t = (dates - dates[0]).astype(float)` — the **true day index**
4. ⚠️ Never renumber `t` to `0..k` after dropping days — the slope will silently
   change scale
5. A `0` from the API is a real zero and stays `0.0`; it is not the same as NaN

### 7.2 Trend

**Computed on weekly medians of the deseasonalized, spike-cleaned series.**

Rationale: Mann–Kendall requires independent observations. Daily pageviews have an
autocorrelation of 0.5–0.9. On daily data the p-value is understated by orders of magnitude,
and a flat series becomes "significantly growing". The weekly median removes the weekly cycle
mechanically and cuts n from ~1095 to ~156, close to the effective sample size.

Requirements: a week is valid with ≥5 observed days; the test runs with ≥26 valid weeks.

- **Theil–Sen**: `β = median{(y_j - y_i)/(t_j - t_i)}` over all pairs `i<j`
- **Mann–Kendall**: `S = Σ sgn(y_j - y_i)`, variance **with the tie correction**
  (low-traffic articles have dozens of days with the same value — without the correction the
  test misbehaves), normal approximation **with the continuity correction** (`S∓1`)
- **p-value without scipy**: `p = math.erfc(|Z| / sqrt(2))` — stdlib, full double precision
- **Slope CI** — from order statistics of the pairwise slopes, no distribution needed
- **Diagnostics**: lag-1 autocorrelation of the residuals; at `ρ > 0.3` the significance
  threshold tightens from 0.05 to 0.01

**Two growth percentages, both in the output:**
- linear: `100 × β × 365.25 / level_at_midpoint` (the denominator is the fitted value
  at the middle of the window, not the first day and not the mean)
- **logarithmic (headline)**: Theil–Sen on `log1p(y)`, then `100(e^(365.25b) − 1)`.
  Scale-free → **the only correct one for comparing languages**

**Hard wording rules:**
- Window <365 days — do not annualize at all
- CI covers zero — the percentage does not go into the headline
- The window length is named in the same sentence as the percentage
- Extrapolation is forbidden

### 7.3 Normalization

`vpm = 1e6 × y / D_smoothed`, where `D` is the edition aggregate smoothed with a **centred
7-day median** (the edition has its own weekly cycle and its own outage days; an unsmoothed
denominator injects the edition's noise into every article).

The denominator slice must match the numerator slice. With more than 5% of days missing
from the denominator, normalized conclusions are suppressed.

**A divergence between the raw and the normalized trend is a finding, not a nuisance:**

| raw | vpm | Conclusion |
|---|---|---|
| ↑ | ↑ | Genuine growth of interest |
| ↑ | flat | The whole edition grew and the topic merely kept up. **Growth of interest must not be claimed** |
| ↑ | ↓ | The edition grew faster than the topic; relative interest is falling |
| flat | ↑ | The edition is shrinking; the topic holds its level and gains share |

### 7.4 Spikes

Centred rolling median over 15 days (two full weekends) + MAD with the constant 1.4826.
Threshold `z > 5.0` — spike, `3.5 < z ≤ 5.0` — elevated, `z < −5.0` — dip.

⚠️ A floor `σ_min = max(1.0, 0.05 × median(y))` is mandatory: low-traffic series often have
a MAD of exactly 0, and without the floor any wobble gives `z = ∞`.

Spikes are clustered into events (gaps of ≤3 days are merged, the decay tail is followed
until `z<2` for two days in a row, at most +14 days after the peak).

**The trend is recomputed on the cleaned series and compared with the original:**

| Condition | Verdict |
|---|---|
| same sign, `p_clean < 0.05`, `|β_clean| ≥ 0.5|β_all|` | sustained level change |
| `p_all < 0.05`, but `p_clean ≥ 0.05` | **event-driven growth** |
| both significant, but `|β_clean| < 0.5|β_all|` | real but inflated by events; the headline uses `β_clean` |
| sign flipped | spurious, no trend is claimed |

### 7.5 Level shift

The Pettitt test (non-parametric, rank-based, ~15 lines) + a step-size scan for the effect
size. Models are compared by median absolute residual with a 10% margin in favour of the
simpler one (the step model has one more parameter).

Why: a traffic jump from a redirect change, a link from the main page or a change in Google
results is not growth of interest. With a "level shift" verdict the annual growth percentage
**is suppressed**, because it describes a smooth growth that did not happen.

### 7.6 Quality gates

| # | Gate | Threshold | Severity |
|---|---|---|---|
| G1 | Minimum volume | median <10/day → stop; 10–49 → direction only | stop / degrade |
| G2 | Minimum points | <60 observed days | stop |
| G3 | Window | <180 days → stop; <365 → no annualization | stop / degrade |
| G4 | Window for seasonality | <730 days → yearly seasonality unavailable | degrade |
| G5 | Missing share | >10% warning, >25% stop | warn / stop |
| G6 | Gap length | >14 consecutive days | stop |
| G7 | **End collapse** | see below | stop |
| G8 | Late start | first day >30 days after the window start | degrade |
| G9 | Zeros | >20% of observed days are zero | degrade |
| G10 | Denominator quality | >5% missing | degrade (vpm only) |
| G11 | Slice consistency | any agent/access mismatch | stop (vpm only) |

**G7 is the most important.** The article was renamed, the traffic moved to the new title, and
the old series fades. Read naively, this looks like "interest fell by 95%".

Rule: `prior = median(days −120..−30)`, `recent = median(last 30 days)`.
Fires when `prior ≥ 50 and recent < 0.05 × prior`, or when the last ≥7 days are zero
or NaN with `prior ≥ 20`. A mirror check for a "jump at the start" — the article may have been
the target of a rename, and the "growth" is inherited.

When it fires, the skill **re-checks the title** via `action=query&redirects=1`:
if `redirects[]` appears, the page was moved — follow it to the new title
and fetch again.

Every gate carries a ready-made English warning text — it goes verbatim into both the JSON
and the PDF. The texts are in `references/methodology.md`.

### 7.7 Verdict

**Not a numeric score.** A single 0–100 number hides which assumption was violated and
invites comparing series that failed in different ways.

Instead: a set of boolean flags + a verdict from a closed vocabulary + three confidence levels.

Verdict vocabulary (first match wins):
`insufficient_data` → `series_discontinuity` → `level_shift_up/down` →
`growing_event_driven/declining_event_driven` → `growing/declining` → `stable` →
`no_detectable_trend`

Confidence: starts at `high`; each of these conditions (short window, low volume, gaps,
no annual baseline, autocorrelation, zeros, suspected seasonality, raw vs vpm divergence,
several changepoints, event inflation) lowers it by one step.

**MDE on a null result.** Instead of "there is no trend" the output says:
"no trend detected; with this much data we would only have noticed a change
larger than ±9.4%/yr". This turns an empty answer into a meaningful one and is probably
the most valuable line of the report.

### 7.8 Table of forbidden claims

Implemented as a check in `verdict.py` and as text in the report template.

| Forbidden | Allowed replacement |
|---|---|
| "X people are interested in Y" | "the article received N views/day" |
| "Demand for Y is growing" | "views of articles about Y grew by ~X%/yr over this window" |
| "Y will reach N by <date>" | Nothing. **No forecasts.** |
| "There is no trend" (from p ≥ 0.05) | "no trend detected; we would not have seen less than ±MDE%/yr" |
| "Z caused the growth" | "the growth coincides with <event> on <date>; causation is not established" |
| "Language A is more interested than B" (from raw views) | "A has N times more views; per million edition views A/B = r" |
| Any percentage under `low_volume` or a window <365 days | Direction only |

### 7.9 Comparing languages

Three numbers per language, each answering its own question:
- **Reach** — median raw views: audience scale
- **Penetration** — median vpm: share of the edition's attention, comparable across languages
- **Momentum** — `pct_per_year_log` on the vpm series: direction, comparable across sizes

**Rank by penetration, break ties by reach, momentum as an annotation.
There is no single blended score** — the trade-off between reach and density of interest
is a business decision, not a statistical one.

**Tiers instead of positions.** Each median gets a CI from order statistics
(on weekly values, otherwise the interval is optimistically narrow because of autocorrelation).
Languages with overlapping CIs land in the same tier: "Tier 1: uk, pl, cs — statistically
indistinguishable" instead of a false 1/2/3.

⚠️ A language that failed a gate is marked `insufficient_data` and **is not placed last
in the ranking**. Silently ranking such a series at the bottom is the most likely way
to produce a wrong business decision: it looks like "no interest" when it means "no data".

⚠️ The windows of the compared languages must match. Intersect them and recompute on the common window.

---

## 8. Cache

SQLite, file `~/.cache/wikipedia-interest/cache.db` (overridden by `--cache-dir`).

```sql
CREATE TABLE pageviews (
  project TEXT, article TEXT, access TEXT, agent TEXT, day TEXT, views INTEGER,
  PRIMARY KEY (project, article, access, agent, day));

CREATE TABLE aggregate (
  project TEXT, access TEXT, agent TEXT, day TEXT, views INTEGER,
  PRIMARY KEY (project, access, agent, day));

CREATE TABLE coverage (             -- which ranges were actually requested
  kind TEXT, key TEXT, start TEXT, end TEXT, fetched_at TEXT,
  PRIMARY KEY (kind, key, start, end));

CREATE TABLE resolve (              -- topic → sitelinks
  source_lang TEXT, query TEXT, qid TEXT, sitelinks_json TEXT, fetched_at TEXT,
  PRIMARY KEY (source_lang, query));

CREATE TABLE sitematrix (json TEXT, fetched_at TEXT);
```

**The `coverage` table is mandatory**, because a missing `pageviews` row for a day is
indistinguishable from "this day was never requested". Without it the cache would keep
re-requesting days with a real zero forever.

Policy:
- Data older than 3 days is considered settled and is never re-requested
- The last 3 days are re-requested if the record is older than a day
- `resolve` and `sitematrix` — 30-day TTL
- `--refresh` bypasses the cache for the current request
- Writes are batched in one transaction

**This is the answer to the requirement to "handle repeated and related queries efficiently":**
the question "now the same, but in Czech" fetches only the Czech series and the Czech
denominator over the network — 2 requests instead of 8.

---

## 9. Charts and the report

### 9.1 Mandatory boilerplate

```python
# __main__.py — before any import that may reach pyplot
import os
os.environ.setdefault("MPLBACKEND", "Agg")
```
```python
# render.py
import matplotlib
matplotlib.use("Agg")          # must precede import pyplot
import matplotlib.pyplot as plt
```
Never `plt.show()`. Always `plt.close(fig)` after saving.

### 9.2 Palette and style

Okabe–Ito, 8 colours, distinguishable under all three types of colour blindness:
`#0072B2 #D55E00 #009E73 #CC79A7 #E69F00 #56B4E9 #F0E442 #000000`

More than 8 series — do not add a ninth colour; switch to small multiples.

```python
"font.family": "DejaVu Sans",     # explicit, so a user matplotlibrc cannot override it
"pdf.fonttype": 42,               # TrueType subset, text stays extractable
"axes.prop_cycle": cycler(color=OKABE_ITO),
"legend.frameon": False,
"axes.spines.top": False, "axes.spines.right": False,
```

### 9.3 Charts

**C1 — daily dynamics (full width, the tallest panel).** One line per language.
Raw values thin and translucent (`lw=0.6, alpha=0.35`), with a 7-day smoothing on top
(`lw=1.6`, same colour). The thin/thick pair conveys the noise-to-trend ratio without a
second panel. Spikes are hollow circles; the largest gets a callout with its date and
multiple.

**C2 — vpm comparison (half width).** The normalized series itself, not an index to a
base period. ⚠️ The rendering agent proposed normalizing to the mean of the first 14 days —
that is a different quantity answering a different question. There is one canonical
normalization here: per million edition views.

**C3 — ranking (half width).** `barh`, not `bar`: language labels are long, and horizontal
bars give them room without rotation.

Date axis: `MonthLocator` + `DateFormatter("%b %Y")`, minor ticks on Mondays.
⚠️ Pass `datetime.date` directly, not preformatted strings — otherwise the locator
does not work. Do not touch the locale: a locale-dependent axis breaks reproducibility.

⚠️ The charts **do not detect spikes** — they receive a ready mask from `stats.py`.
Two independent detectors with different thresholds would produce a chart that contradicts the text.

### 9.4 One-page PDF

`matplotlib.PdfPages` + `GridSpec`, A4 portrait `(8.27, 11.69)`.

Top to bottom: title + the user's question → C1 → C2 and C3 side by side → metrics table
(`ax.table`) → "Findings" → "Assumptions and limitations".

```python
with PdfPages(path, metadata={
    "Title": title, "Author": "wikitrends", "Subject": question,
    "Creator": "wikitrends", "Producer": "matplotlib",
    "CreationDate": None,        # ← the one line that makes the PDF reproducible
}) as pp:
    pp.savefig(fig)
```

⚠️ Do not use `bbox_inches="tight"` for the report page — the page size would become a
function of the text length, and A4 would stop being A4.

⚠️ Wrap text with `textwrap.fill` in advance: `fig.text` cannot wrap.
If the findings block does not fit in its space, truncate it with an ellipsis and record
that in the JSON. **A two-page report is a spec violation, not graceful degradation.**

### 9.5 Cyrillic

The risk was confirmed experimentally: reportlab with Helvetica silently draws `■■■■`, the Vera
font bundled with reportlab has no Cyrillic at all; fpdf2 raises an exception.

matplotlib ships DejaVu Sans — coverage of all 65 characters of the test string
`Вікіпедія Київ Ґ Ї Є Łódź Gdańsk źćęąśżń Řehoř Plzeň ůěščřž № — ""` was verified, and the text
extracts back from the PDF via pypdf (so these are real glyphs + a working ToUnicode CMap).

**No font file goes into the repository.** Never fall back to a system font
(`Arial`, `sans-serif`) — Linux containers often have no Cyrillic face at all.

### 9.6 Reproducibility

1. `figsize` and `dpi` are fixed in code
2. `CreationDate: None` in the PDF, `metadata={"Software": None}` in the PNG (otherwise the
   matplotlib version is embedded)
3. Deterministic iteration order everywhere: `sorted(langs)`, no sets
4. No locale, no `datetime.now()` in labels. If a date is needed, take it
   from the data window, not from the clock
5. Pin versions: output is byte-stable within a matplotlib version, **but not across versions**
   (verified on 3.9.4 vs 3.11.2)

---

## 10. SKILL.md

### 10.1 Frontmatter

```yaml
---
name: wikipedia-interest
description: >-
  Analyzes Wikipedia pageview data to compare interest in a topic across language
  editions and detect whether that interest is genuinely growing. Produces charts and
  a one-page PDF report with explicit confidence levels and stated limitations. Use when
  deciding which topic to build content for, which language to localize into, or when
  asked whether interest in a subject is rising in a given country or language. Not for
  real-time traffic, not a measure of purchase intent, and not a forecasting tool.
license: MIT
compatibility: >-
  Requires Python 3.12+ and network access to wikimedia.org. Dependencies installed via
  pip from requirements.txt. Does not work in sandboxes without network access or
  package installation.
---
```

Spec constraints we follow: `name` ≤64 characters, only `a-z0-9-`,
**matches the directory name**, no double hyphens, no "claude" or "anthropic".
`description` ≤1024 characters. Only the six fields the spec allows; Claude Code-specific
fields (`when_to_use`, `model`, `effort`) are not used, for portability.

⚠️ The `compatibility` note about no network is not a formality: the Claude API sandbox has no
network and cannot install packages, so the skill will not work there. Knowing this is a maturity signal.

### 10.2 Body — budget and structure

**≤500 lines and ≤5000 tokens** (a direct spec requirement; the body is loaded in full
on activation). Haiku 4.5 has a 200K window versus 1M for the larger models — what is fine
on Opus crowds out the task itself on Haiku.

| Section | Content | Lines |
|---|---|---|
| Overview | What it does, in three sentences | 5 |
| Setup | `pip install -r requirements.txt`, a one-command check | 10 |
| Quick start | **The main scenario as a single `compare` call** | 20 |
| Commands | Table of subcommands with examples | 60 |
| Reading the output | JSON fields, verdicts, flags — as a compact table | 80 |
| Choosing languages | When to call `resolve`, how to suggest languages to the user | 30 |
| Failure modes | Errors and what to do about each | 50 |
| What not to claim | A condensed version of table 7.8 | 30 |
| References | Links to the three files in `references/` | 10 |

Everything else goes to `references/` and is loaded on demand.

### 10.3 Writing rules (for a cheap model)

- Imperative, not discussion. "Run this" / "If X, do Y", not "you may consider"
- One decision per section, with an explicit default
- The file starts with a numbered procedure. Rationale goes to `references/`
- Maximum determinism in scripts: **the script source does not enter the context,
  only stdout does**. Every branch moved from "the model decides" to "the script decides"
  removes one turn and one way to go wrong
- Haiku 4.5 **does not support the effort parameter** — you cannot pay for extra thinking
  to resolve ambiguity, so the text must be unambiguous

---

## 11. Testing

### 11.1 Unit tests

**`test_stats.py` — synthetic data with a known answer.** This is the answer to the requirement
to "explain how you verified the output of AI tools":
- a series with an exactly specified linear trend → check that Theil–Sen recovers it
- a flat series + noise → `no_detectable_trend`, and the p-value is uniform on [0,1]
- a series with one inserted spike → `growing_event_driven`, `p_clean` loses significance
- a series with a step → `level_shift`, not "growth of X%/yr"
- hand-worked numeric examples from `methodology.md` (S = −1, Var(S) = 7.667, Z = 0, etc.) —
  if the code gives `Z = −0.361`, the continuity correction was forgotten; if `Var = 8.667`,
  the tie correction was forgotten

**`test_series.py`** — reindex: missing days become NaN, real zeros stay
zeros, `t` is not renumbered.

**`test_gates.py`** — each of the 11 gates fires on its own fixture and does not fire
on the neighbouring one.

**`test_render.py`** — five layers without visual comparison:
1. **The main test:** turn matplotlib's "glyph missing from font" warning into an error and
   build a report on a string with UA/PL/CZ characters. Verified that the test actually
   fires — Japanese text breaks it
2. PDF structure via pypdf: exactly one page, MediaBox = A4 (595×842),
   no `/CreationDate`, the words `Вікіпедія`, `Łódź`, `Řehoř`, `Limitations` extract as
   text. One check catches tofu boxes, a missing ToUnicode and accidental rasterization
   at once
3. Byte-level determinism: two runs → `a.read_bytes() == b.read_bytes()`
4. The PNG is not blank: `std > 10`, ink share within 2–60%
5. CLI contract: exactly one newline on stdout, every path absolute and existing,
   `summary` ≤200 characters

**CI:** `ubuntu-latest` **with no fonts installed and `DISPLAY` disabled**,
`MPLBACKEND=Agg`, `MPLCONFIGDIR=$RUNNER_TEMP/mpl`. If the tests pass there, the bundled-font
story is proven rather than assumed. Plus a matrix row on `macos-latest`.

**Offline fixtures.** Tests do not touch the network: `--offline-fixture` replaces the HTTP layer
with recorded responses. Otherwise CI would hit the 10 req/min limit.

### 11.2 Eval on Haiku — meets the assignment requirement

We use **`claude plugin eval`** (Claude Code v2.1.269+) — the stock harness built exactly
for this. Why it and not a custom script: every case runs **in two arms — with the skill and
without it** — and reports the Δ. If Δ≈0, the skill is decorative, and the reviewer
sees that measured rather than asserted.

Five cases:

| Case | Checks |
|---|---|
| `growth-single-lang` | "Is interest in astronomy growing in the Ukrainian Wikipedia?" — the basic path |
| `compare-two-langs` | pl/cs comparison over two years + PDF |
| `spike-driven` | A topic with one large news spike → the agent must say "event-driven growth" |
| `insufficient-data` | A low-traffic article → the agent must refuse rather than give a number |
| `negative-should-not-trigger` | A question not about Wikipedia → the skill **must not** trigger |

```bash
# quick iteration during development
claude plugin eval . --case growth-single-lang --runs 1 --ablation none \
  --model claude-haiku-4-5

# the full run that goes into the README
claude plugin eval . --model claude-haiku-4-5 --judge-model claude-sonnet-5 --runs 5

# gate in CI
claude plugin eval . --trust-plugin --json results.json --threshold 0.8 \
  --model claude-haiku-4-5 --judge-model claude-sonnet-5 --no-publish --max-cost-usd 20
```

The judge must be stronger than the model under test: a small judge marks correct but
differently formatted answers as wrong and produces a false-negative Δ.

### 11.3 Acceptance criteria

**Hard (fail the build):**

| Metric | Threshold |
|---|---|
| Triggers on natural phrasing | ≥90% of runs |
| False trigger on an unrelated question | 0% |
| Case score with the skill | ≥0.8 |
| Ablation Δ | ≥ +0.3 |
| SKILL.md body | ≤5000 tokens and ≤500 lines |
| `description` | ≤1024 characters |
| Run does not hit `max_turns` | 100% |
| Input tokens per scenario | ≤60K (30% of Haiku's window) |

**Budget (warning / regression against the previous run):**

| Metric | Target |
|---|---|
| Tool calls per scenario | ≤8, median ≤5 |
| Repeated reads of the same file | 0 |
| Reference files per run | ≤2 |
| Largest tool output | ≤5K tokens |
| Cost per scenario on Haiku | ≤$0.02 |
| Run time | ≤60 s |

⚠️ The JSON from `claude plugin eval` does not report token usage — only `costUsd`.
To measure tokens we additionally run the scenario through
`claude -p --output-format stream-json` and count from the transcript.

### 11.4 OpenRouter — a smoke test, not the main harness

The assignment allows free OpenRouter models, but:
- the `:free` limit is **50 requests a day** until credits are bought; a suite of 6 agentic
  runs uses it up at once
- `supported_parameters: ["tools"]` only means the endpoint **accepts** tool schemas,
  not that the model can run a multi-turn agentic loop
- Anthropic states plainly that it does not support routing Claude Code to non-Claude models

The real Haiku 4.5 costs $1/$5 per million tokens — the whole suite costs less than a dollar.
The README describes the OpenRouter configuration as a portability check:

```bash
export ANTHROPIC_BASE_URL="https://openrouter.ai/api"     # no /v1
export ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY"
export ANTHROPIC_API_KEY=""                                # otherwise it takes precedence
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
```

---

## 12. Installation and reproducibility

```bash
# as a Claude Code plugin — one command
claude plugin marketplace add Kuzmenko-Oleksandr/wikipedia-interest-skill
claude plugin install wikipedia-interest@wikipedia-interest-skill

# or by hand
cp -r skills/wikipedia-interest ~/.claude/skills/

# dependencies
pip install -r skills/wikipedia-interest/requirements.txt
```

`.claude-plugin/marketplace.json`:
```json
{
  "name": "wikipedia-interest-skill",
  "owner": {"name": "Kuzmenko-Oleksandr"},
  "metadata": {"description": "Wikipedia pageview interest analysis", "version": "1.0.0"},
  "plugins": [{
    "name": "wikipedia-interest",
    "description": "Analyze and compare topic interest across Wikipedia language editions",
    "source": "./", "strict": false,
    "skills": ["./skills/wikipedia-interest"]
  }]
}
```

`requirements.txt` with pins (output is byte-stable only within a version):
```
matplotlib==3.11.2
numpy==2.5.3
httpx==0.28.1
```

No `.so` files, no system packages, no compiled files in the repository.

---

## 13. Iterative development plan (README section)

**Stage 1 — from an article to a topic.** Today a topic = one article per language. In reality
interest is spread across many articles, plus redirects. Next step: a set of articles per topic
(via Wikidata categories and `prop=redirects`), summed series, and an explicitly recorded,
versioned set composition.

**Stage 2 — scale.** SQLite → Parquet/DuckDB, batch mode for hundreds of topics, backfill
from the [dumps](https://dumps.wikimedia.org/other/pageviews/) instead of the API
(the API is not meant for bulk history at 10 req/min), parallelism
that respects the limit.

**Stage 3 — more signals.** Unique devices as a second opinion on pageviews
(the `/metrics/unique-devices/` endpoint, project level only). Pageviews by country —
to separate "interest in a country" from "interest in a language", which is not the same thing
for a localization decision. Cross-checking against external sources (Google Trends, App Store)
as validation, not a replacement.

**Stage 4 — validating conclusions.** Backtest: take the decisions the skill would have
recommended two years ago and compare them with what happened. This is the only way to learn
whether pageview growth predicts real demand — today that is an assumption, not knowledge.

---

## 14. Work plan

| Stage | Content | Estimate |
|---|---|---|
| 1 | Repository skeleton, `api.py`, `cache.py`, `resolve.py` | 3 h |
| 2 | `series.py`, `gates.py` + tests on synthetic data | 3 h |
| 3 | `stats.py`: Theil–Sen, Mann–Kendall, MAD, Pettitt + numeric tests | 4 h |
| 4 | `verdict.py`, `cli.py`, JSON contract | 2 h |
| 5 | `render.py`, `report.py` + rendering tests | 3 h |
| 6 | `SKILL.md` + the three `references/` files | 2 h |
| 7 | Eval suite, run on Haiku, metric measurement | 2 h |
| 8 | README: methodology, AI verification, roadmap, limitations | 2 h |
| 9 | CI, marketplace.json, final proofreading | 1 h |

Total ~22 h. **Full scope, nothing is cut** (decision of 2026-09-24).

---

## 15. Resolved contradictions between the research tracks

Recorded so they do not resurface during implementation.

1. **Spike detection.** The rendering agent proposed its own (`0.6745·(y−med)/MAD`,
   threshold 3.0, global window); the statistics agent proposed a 15-day rolling window,
   threshold 5.0, a `σ_min` floor. **The statistics version is adopted.** The chart detects
   nothing; it draws the mask produced by `stats.py`.

2. **Normalization on chart C2.** The renderer proposed an index to the mean of the first
   14 days, the statistician — vpm per million edition views. These are **different quantities**.
   **vpm is canonical**: on the chart, in the table and in the verdict. An index to a base
   may be added as a separate panel, but not instead.

3. **Earliest data bound.** The Wikimedia documentation says "since May 2015",
   the AQS reference says "since 1 July 2015". Checked with requests: **2015-07-01 for both series**;
   May–June returns 404. The code clamps to 2015-07-01.

4. **Rate limit.** Documented 200/min, measured ~10/min.
   **We design for 10/min.**

5. **Eval format.** There is also `evals/evals.json` from the `skill-creator` plugin —
   a different, dialogue-driven format. For CI we use `claude plugin eval`.

---

## 16. Decisions made (2026-09-24)

| Question | Decision |
|---|---|
| Language | **Everything in English**: `SKILL.md`, `references/`, README, CLI output, warnings, the PDF report. Cyrillic appears in the report only in article titles (uk, bg, sr, etc.), so the DejaVu Sans font requirement and the glyph test stay |
| Repository | `github.com/Kuzmenko-Oleksandr/wikipedia-interest-skill`, public, MIT |
| Folder | `~/PhpstormProjects/wikipedia-interest-skill`, its own `git init` |
| Stack | Python 3.12+ (numpy 2.5.3 does not install on 3.11) |
| Scope | Everything in this spec |
| Contact in the User-Agent | Only the repository URL; no email is published (the Wikimedia policy allows a URL) |

## 17. Code conventions

- **OOP + SOLID + clean code** — mandatory:
  - SRP: one class, one responsibility (`PageviewsApi` talks to the network, `PageviewCache` stores, `CachedPageviews` decides what to take from the cache)
  - OCP/DIP: dependencies are passed to the constructor and typed with `typing.Protocol`; the cache wraps the API as a decorator without knowing its implementation
  - LSP/ISP: protocols are narrow (`PageviewSource` has two methods), test fakes drop in without mocks
  - Value objects — `@dataclass(frozen=True, slots=True)`
  - Pure maths (Theil–Sen, Mann–Kendall) — module functions behind a `TrendAnalyzer` facade class: wrapping a formula in a class for the sake of a class is not clean code
  - No speculative abstractions: an interface appears only if it has a second implementation or a test fake
- **PEP 8** — style; formatting and linting via `ruff` (`ruff format` + `ruff check`),
  config in `pyproject.toml`, line length 100
- **PEP 257** — docstrings: one line for simple functions; for public functions
  with a non-obvious contract, a short description + `Args`/`Returns` (Google style)
- **PEP 484** — type hints on every public function; `from __future__ import annotations`
- Comments — **English only, short, one line**, and only where the code
  cannot say it itself (why, not what). An appropriate example:
  `# API omits empty days instead of returning 0`
- No commented-out code blocks, no `TODO` without a reason
- Names: `snake_case` functions and modules, `PascalCase` classes, `UPPER_CASE` constants
- Thresholds and magic numbers — named constants at the top of the module
- Errors: own exceptions (`WikitrendsError` and subclasses) with a `hint` field;
  the CLI catches them and prints a JSON error; bare `except:` is forbidden
- Logs and progress — `logging` to stderr; `print` only for the final JSON line
