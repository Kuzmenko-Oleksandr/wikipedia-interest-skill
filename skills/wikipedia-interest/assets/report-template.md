# Report text blocks

`wikitrends/narrative.py` reads the numbered list below and prints it verbatim in every
PDF report and in `metrics.json`. It is not optional. Edit the wording here, not in code.

## Limitations

1. Pageviews measure attention to an article, not demand, purchase intent or the number
   of people.
2. Each language is measured through one canonical article. Views of redirects (synonyms,
   old titles) are not counted unless `--include-redirects` is used, which typically
   undercounts popular topics by 10-30%.
3. Edition totals include the Main Page, search pages and non-article namespaces, so views
   per million are systematically a little low. The bias is the same across the window.
4. Only traffic classified as human (agent=user) is counted; automated traffic that
   Wikimedia misclassifies as human is not removed.
5. Data lag by 1-2 days and the most recent days can still be revised.
6. Days missing from the API are treated as unknown, never as zero.
7. The trend describes the observed window only. Nothing here is a forecast.
8. A language edition is not a country: readers of one edition live in many countries.
9. Short spikes are removed from the trend and listed separately. A coincidence in time
   with news does not establish what triggered them.
10. Sudden steps (renames, links from busy pages, search-engine changes) are reported as
    level shifts, not as growth.
11. Changes within ±5% per year are reported as stable even when statistically detectable,
    and statistical significance alone says nothing about business relevance.
12. Yearly seasonality is removed only when the window covers at least two years; shorter
    windows can mistake a seasonal swing for a trend.
