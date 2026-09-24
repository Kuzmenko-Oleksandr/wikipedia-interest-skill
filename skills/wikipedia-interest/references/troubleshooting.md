# Troubleshooting

Every failure prints `{"ok":false,...,"hint":"..."}` on stdout and exits with 1. Follow the
hint first. Details and logs are on stderr; add `-v` for progress messages.

## Setup

| Symptom | Cause | Fix |
|---|---|---|
| `Python 3.12+ is required` | Old interpreter (numpy 2.5 needs 3.12). | Run the command in `hint`: it creates `.venv` with `python3.12`. Use `python3.13` if 3.12 is absent. |
| `missing dependency: httpx` (or numpy, matplotlib) | Requirements not installed. | Run the command in `hint`. `scripts/wikitrends` picks up the skill's `.venv` automatically. |
| `error: externally-managed-environment` from pip | System Python refuses global installs (PEP 668). | Install into the skill's `.venv` as the hint says, never with `--break-system-packages`. |
| `Glyph ... missing from font` warnings | A user `matplotlibrc` or an old matplotlib. | The code forces DejaVu Sans, shipped with matplotlib; check `pip show matplotlib` is 3.11.2. |

## Network and API

The API hosts are `wikimedia.org` (pageviews), `<lang>.wikipedia.org` (search, titles),
`www.wikidata.org` (sitelinks) and `meta.wikimedia.org` (list of editions).

| Status / error | Meaning here | What the skill does | What you do |
|---|---|---|---|
| 200 with fewer days than asked | Days without data are omitted, not zero. | Reindexes to the full calendar with NaN. | Nothing. |
| 400 | Malformed parameter. | Stops. | Check dates are `YYYY-MM-DD` and titles exist. |
| 403 | User-Agent rejected. | Stops. | Do not change the User-Agent; report it. |
| 404 | "No data in this range", not "no such article". | Treats the series as empty; gates refuse it. | If the article should exist, run `resolve`. |
| 429 | Rate limit (about 10 requests/minute per IP in practice). The body is plain text. | Retries with backoff, honouring `Retry-After`, 4 times. | If it still fails: wait a minute and rerun once; the cache keeps what was fetched. |
| 5xx | Backend overload. | Retries with backoff. | Rerun later. |
| `network error` | No route to Wikimedia (sandbox without network, proxy, DNS). | Stops. | Tell the user the skill needs network access to wikimedia.org. |
| `non-JSON response` | A redirect or an HTML page (for example `api.wikimedia.org/metrics/...` is not a mirror). | Stops. | Report it; the code only uses `wikimedia.org/api/rest_v1`. |

A typical three-language, two-year question needs 8 requests (search, sitelinks, three
articles, three edition totals). A follow-up on the same data needs none; adding one
language needs two.

## Results that look wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| Verdict about the wrong subject (a film, a person) | The search's top hit was a different article. | `resolve --topic`, then `compare --titles lang:Exact title`. |
| `G7_end_collapse` | The article was renamed or merged near the end of the window. | The skill re-checks redirects automatically; if it still fails, pass the new title with `--titles`. |
| `G1_low_volume` for a big language | Wrong or very narrow article. | Use a broader article, or `--include-redirects`. |
| `level_shift_up` right after a known event | A link from a popular page, a rename or a search-engine change. | Report it as a one-off shift; do not call it growth. |
| Much lower numbers than expected | Views of redirects are not summed by default. | Add `--include-redirects` (up to 10 redirects per language). |
| `raw_vpm_divergence` | The whole edition grew or shrank. | Read the note in `metrics.json` → `conclusions`. |

## Cache

The cache lives in `~/.cache/wikipedia-interest/cache.db` (override with `--cache-dir` or
`WIKITRENDS_CACHE_DIR`). Days older than 3 days are never refetched; the last 3 days are
refetched once they are a day old. Titles and the list of editions expire after 30 days.
`--refresh` ignores the cache for one run; `cache --clear` deletes it.

## Offline mode

`--offline-fixture demo` replays the bundled synthetic fixture (topic `Astronomy`, editions
`en uk pl cs de fr`, data up to 2026-09-22) without network access and with an in-memory
cache. Every output is marked "synthetic". Anything outside the fixture fails with a hint.

To capture real data for offline tests, run any command once with
`--record-fixture DIR` on a machine with network access, then replay with
`--offline-fixture DIR`.
