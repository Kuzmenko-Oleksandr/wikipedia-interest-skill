# wikipedia-interest

**English** | [Українська](README.uk.md)

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

## Quick start: ask in plain words

No coding. You type a question, Claude downloads the data, runs the analysis and answers,
with a PDF report.

### What you need (once)

1. **Claude Code**, the desktop app or the `claude` command in a terminal, signed in:
   <https://claude.com/claude-code>. Codex and other agents work too, see
   [Other agents](#other-agents).
2. **Python 3.12 or newer.** In a terminal type `python3.12 --version`, then
   `python3.13 --version`. If one of them prints a version, you are ready. If both say
   "command not found", install Python from <https://www.python.org/downloads/>. On a Mac
   the built-in `python3` is 3.9: that is fine, it is simply not used.
3. **Internet access.** The data come from wikimedia.org.

### Steps

1. **Get the project.** In a terminal:

   ```bash
   git clone https://github.com/Kuzmenko-Oleksandr/wikipedia-interest-skill.git
   ```

   Or, without git: on the GitHub page press **Code → Download ZIP** and unpack it; the
   folder is then called `wikipedia-interest-skill-main`.
2. **Open the folder in Claude Code.** In a terminal: `cd wikipedia-interest-skill`, then
   `claude`. In the desktop app: the Code tab, then choose the `wikipedia-interest-skill`
   folder. Nothing has to be installed as a plugin: Claude Code finds the skill in the
   folder by itself.
3. **Type your question** in plain words, in any language, for example:

   > Pull Wikipedia pageviews for astronomy in the Ukrainian and Polish editions for the
   > last two years and tell me whether interest is growing.

4. **Allow the commands.** Claude asks before it runs anything: answer **Yes** or
   **Allow**. The first time only, it reports that dependencies are missing and asks to
   run a command that creates `.venv` and installs them. Allow it. After that every
   question starts right away.
5. **Read the answer.** It comes in the language you wrote in and always has:
   - one sentence per language: what happened, over which dates, and how sure it is
     (high, medium or low);
   - which language gets the most attention, when there are two or more;
   - where the PDF report is;
   - a line "Limitations:" with what the data cannot tell.
6. **Open the report.** It is in the `out/` folder of the project:
   `out/<languages>_<topic>_<dates>/report.pdf`, next to the charts (PNG) and the daily
   numbers (CSV).

A question takes 15 to 45 seconds; the first one, with the install, under a minute. It was
tested on the smallest model, Claude Haiku 4.5; larger models work too.

### Questions you can ask

- "Compare the growth of interest in intermittent fasting on Polish and Czech Wikipedia
  over two years."
- "Is interest in astronomy growing on Ukrainian Wikipedia, and how far can we trust that?"
- "Which language editions pay most attention to learning English? Prepare a report."
- "We are localizing a course on climate change. Which language first: German, French or
  Polish?"

You do not have to name languages: Claude then lists the editions that have the article
and suggests a few. The default window is the last two years; say "since 2024-01-01" or
"over the last year" to change it.

### What the answer means

| In the answer | Meaning |
|---|---|
| growing, declining | A steady trend over the whole window, with a rate per year. The only verdict that means momentum. |
| stable | The yearly change is within ±5%. |
| no detectable trend | Nothing measurable; the answer says how large a change would have been visible. |
| jumped, dropped (a level shift) | A one-off step, for example after a rename or a link from the main page. Not growth. |
| came from spikes | The rise or drop was a few short news spikes; without them there is no trend. |
| not enough data, renamed | Too little traffic or a broken series. The tool refuses instead of guessing; it does not mean the topic is unpopular. |
| high, medium, low | How far to trust the verdict. Each weakness (short window, strong seasonality, ...) lowers it one step. |

"Attention" is an article's share of all views of its edition (views per million), so a
large and a small language can be compared fairly.

### If something goes wrong

| You see | Do |
|---|---|
| Claude searches the web or writes its own script | Check that Claude Code was started inside the project folder. Start the message with `/wikipedia-interest`, or add "use the wikipedia-interest skill". |
| "Python 3.12+ is required" and the install fails | Install Python 3.12 or newer from python.org, restart Claude Code, ask again. |
| `claude: command not found` | Install Claude Code, see "What you need". |
| A network error or a timeout | Check the connection to wikimedia.org. The API allows about 10 requests a minute: wait a minute and ask again; data already downloaded are kept. |
| Windows: the skill is not found | Git on Windows may not create the link `.claude/skills/wikipedia-interest`. Install the skill as a plugin instead, see "Install in every project". |

## Install in every project

The quick start uses the skill inside this folder only. To have it in any project, add
it as a Claude Code plugin:

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

## Other agents

The skill is in the open Agent Skills format and has nothing specific to Claude:
`SKILL.md` names no Claude tool, and all the work happens in `scripts/wikitrends`, which
any agent that can run a shell command can call. Codex and Gemini CLI read project skills
from `.agents/skills/`, and this repository has a link there, so opening the clone is
enough; `AGENTS.md` carries the same instruction as `CLAUDE.md`. To have the skill in any
project, copy the folder to your user skills:

```bash
mkdir -p ~/.agents/skills && cp -r skills/wikipedia-interest ~/.agents/skills/
```

Dependencies are the same as above. An agent without skill support can be told to follow
`skills/wikipedia-interest/SKILL.md`, or you can [run the CLI directly](#run-the-cli-directly).
Only Claude Code on Haiku 4.5 was measured; other agents were not tested.

## Run the CLI directly

Without Claude, from the repository folder:

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
shipped with matplotlib plus fallback fonts in `assets/fonts` for CJK, Indic, Thai and
other scripts, so article titles render the same on any machine), `httpx`; `sqlite3`,
`argparse`, `math.erfc` from the stdlib.
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

**Known-answer tests (169, `make test`).** Hand-computed examples that pin each formula:
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
Tibetan, the one script tested that no bundled font has); the PDF has exactly one A4 page,
no creation date, and `Вікіпедія`, `Łódź`, `Řehoř`, `天文学`, `천문학`, `ดาราศาสตร์`
extract back as text; two builds are byte-identical; PNGs are not blank. CI also runs the
tests in `python:3.12-slim`, which has no fonts at all.

**The full scenario on Claude Haiku 4.5.** `evals/` holds five cases for
`claude plugin eval` on the synthetic fixture (planted answers: uk growing ~23%/yr; pl
stable and fr a one-off step; de a rise made of six spikes; cs too little data; a
Google Analytics question that must not trigger the skill) and one live case. The
harness itself needs a shell sandbox that this build container lacks, so each case was
run on `claude-haiku-4-5` through `claude -p --plugin-dir` (the same agent loop without
the harness), three times after the last change to the skill, with no user settings,
skills or MCP servers loaded and an empty cache per run, and the answers were graded
against the case rubrics by a separate Sonnet judge:

| Metric (SPEC §11.3) | Target | Measured on Haiku 4.5 |
|---|---|---|
| Skill fires on natural phrasing (6 queries ×3, uk/en) | ≥ 90% | 18/18 (100%) |
| False triggers on near-miss questions (5 queries ×3) | 0% | 0/15 |
| Tool calls per scenario | ≤ 8, median ≤ 5 | 2 in every run (Skill + one `compare`) |
| Repeated file reads | 0 | 0 |
| PDF written to the user's folder | every scenario | 12/12 |
| Peak context | ≤ 60K tokens | 33.6-34.4K |
| Wall time | ≤ 60 s | 15-28 s |
| Cost per scenario | ≤ $0.02 | $0.036-0.043 (missed: the question that does not use the skill already costs $0.020, which is Claude Code's own prompt) |
| Answers passing the case rubric (Sonnet judge) | score ≥ 0.8 | 14/15 |

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
   the skill anyway, since it can list the editions itself. In the final rerun it fired
   on this request 3 times out of 3.
4. Two prompts the skill was never tuned on (which language to localize a course into; a
   question naming no languages) exposed a defect in the tool, not the model: near the
   1 KB limit the line dropped a refusal's `reason` and the audience size before the chart
   paths the agent never opens. Haiku filled the gap by calling the share of attention
   "absolute" views and a one-off step "growing demand"; `SKILL.md` also told it to read
   every verdict as momentum. Paths are now shed first and only a trend counts as
   momentum. Afterwards every Czech refusal said that low traffic says nothing about
   interest, and none of 5 localization answers called the step growth or demand.
5. The final rerun, with every query in Ukrainian or English, passed 14 of 15 rubrics.
   The miss: an answer in Ukrainian opened the French one-off step with "views grew",
   and only then called it a one-off change, not steady growth; the judge failed it for
   the growth wording.

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

**Live data on Claude Haiku 4.5.** On a machine with network access the pipeline ran
against the live Wikimedia API; a six-language `compare` took 84 s uncached. Six prompts
(the three from the assignment, a localization question, and two near misses about Google
Analytics and Google Trends) went to Haiku 4.5 agents that, as in Claude Code, saw only
the skill's name and description. `claude plugin eval` refused to run on the Mac used:
Docker Desktop keeps symbolic links in `~/.docker`, and the harness will not start a
Bash sandbox it cannot keep out of that credential store. So there is no Sonnet judge:
each answer was checked by hand against the JSON line the tool printed. The first round
fired the skill on 4/4 prompts and 0/2 near misses, two of four answers passed, and the
live reports exposed defects the synthetic fixture could not:

1. Japanese, Chinese, Korean, Thai and Indic titles came out as empty boxes: only
   DejaVu Sans was used. Fallback fonts (Noto, Droid Sans Fallback, Nanum Gothic; 7.6 MB,
   OFL and Apache-2.0) now ship in `assets/fonts` with pinned sources; a title in a
   script none of them covers, such as Tibetan, is replaced by "(see metrics.json)".
2. With six languages the PDF title listed every article and ran off the page, and a
   `--titles` run was named after whichever title sorted first. The title now names the
   topic and is cut to the page width; the run is named after the source-language title.
3. With six languages and a long output path the stdout line shed `tiers` before the
   rates, and the answer lost the ranking. The ranking is now never shed.
4. A decline read "fell ~-12%/yr".
5. The localization answer recommended "the English-speaking audience", which was never
   measured. `SKILL.md` now limits recommendations to the analysed languages.

Each code fix has a regression test. In the second round the skill again fired on 4/4
and 0/2; the localization answer stayed within German, French and Polish with every
number matching the JSON line, and the report with Japanese and Cyrillic titles
rendered. Two answers still fell short: one gave a trust figure ("no more than 20%")
the tool never produced, and a comparison of five editions listed each trend but not
which edition gets the most attention, although `tiers` was now in the line.

`SKILL.md` now forbids any number the line does not contain and asks for one sentence
on the order in `tiers`. In a third round the trust question was answered with the
confidence level and its four flags only, and two comparisons of six and seven editions
named the order correctly. Both, however, opened `metrics.json` against the instructions
to fetch numbers the line had trimmed (the agents' folder path was 250 characters long,
which leaves little room in 1 KB), and one quoted all twelve limitations instead of the
caveat. With one more rule, "if a field is missing from the line, leave it out", two
reruns of that prompt in Ukrainian from a 263-character path took three tool calls each
and never opened `metrics.json`. One compared five editions, named the order uk, pt, then
pl and ja tied, then de, exactly as in `tiers`, matched every number and gave the caveat
alone (33 s, $0.048). The other picked six editions of which only English had enough
traffic, so there was no order to name. Its numbers matched, but it shortened the report
path to `/out/…`, which does not exist, and said the thin editions "may indicate lower
popularity", which the refusal `reason` warns against (88 s uncached, $0.053).

**Claude Code itself, from a fresh clone.** The harness and `--plugin-dir` runs load
the skill directly, so the last check used the real `claude` CLI on Haiku 4.5 with only
the skill's description to go on. An earlier description, which did not yet say that the
skill downloads the data itself and replaces web search, fired on the three Ukrainian
requests from `evals/` as often as the current one, 9 of 9 each, so the rewrite shows no
measured gain there. The current one fired on 18 of 18 requests with 0 of 15 near misses;
a question took 8-20 s and $0.034-0.043. Then copies of the repository with no plugin
installed were opened as a new user would open them, and asked to pull Wikipedia
pageviews for astronomy in Ukrainian and Polish over two years. With the link in
`.claude/skills/` and `CLAUDE.md` Haiku used the skill in 4 of 4 runs. Each copy started
without dependencies: the CLI reported that Python 3.12 was missing and printed the
install command, Haiku ran it, repeated the call and answered in 40-48 s for
$0.053-0.054, every number matching the JSON line. Three questions in Ukrainian got
answers in Ukrainian and one in English got an answer in English, although the data came
from the Ukrainian and Polish editions; an earlier answer had followed the language of the
data, which is why `SKILL.md` says to answer in the language the user wrote in. Haiku's
Ukrainian is rougher than its English (for example "артикул" for an article), but the
numbers held. Without the link and `CLAUDE.md` it was 1 of 2: once Haiku found
`skills/wikipedia-interest/SKILL.md` on its own and followed it; once it fetched monthly
pageviews by hand and reported a "-81%" fall for "Ukraine" from a September peak and a
stable Poland, where the skill found both editions declining with low confidence. A
`resolve` of a topic with long titles in 20 editions printed an empty line, since the
titles did not fit 1 KB; the smallest editions are now left out instead.

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
CLAUDE.md                         tells Claude Code in this folder to use the skill
AGENTS.md                         the same for Codex and other agents
SPEC.md, SPEC.uk.md               technical specification (English, Ukrainian)
.claude/skills/wikipedia-interest link to the skill: a clone works with no install
.agents/skills/wikipedia-interest the same link for Codex, Gemini CLI and others
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
  assets/fonts/                   fallback fonts for non-Latin titles (OFL, Apache-2.0)
  evals/                          claude plugin eval cases and trigger queries
  tests/                          unit, rendering and contract tests
```

Development: `cd skills/wikipedia-interest && make check` (ruff, basedpyright, pytest).

## License

MIT
