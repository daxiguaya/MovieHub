# Chart data sources and acquisition policy

Last reviewed: 2026-11-23

## Current state

MovieHub has a normalized chart snapshot model, date-scoped replacement semantics, local/Cinephile-format adapters, a dry-run import CLI, one-shot Top 250 and popular/high-rated collectors, and a one-shot collector for the official 2025 annual roundup.

**It does not run scheduled chart collection.** Top 250, popular and high-rated charts have opt-in, one-shot manual collectors that run only when robots.txt permits. The 2025 annual taxonomy is represented as four separate built-in lists. The manual collector has successfully fetched the official roundup and produced four normalized snapshots (8/10/10/10 entries); all four passed dry-run validation in CI and were retained as a 14-day Actions artifact. No annual data is committed to Git or imported into a database. Built-in chart definitions are display metadata only; they are not evidence that chart data has been fetched.


## Annual chart taxonomy

Douban's official 2025 annual book/film/music roundup, published on 2026-01-15, explicitly lists four film/television categories:

1. 2025 评分最高华语电影
2. 2025 评分最高外语电影
3. 2025 年度冷门佳片
4. 2025 评分最高华语剧集

Source: [Douban official 2025 annual roundup](https://blog.douban.com/douban/2026/01/15/4382/) and its [2025 annual movie page](https://movie.douban.com/annual/2025/).

MovieHub models these as four independent chart slugs under the `annual` category and period `2025`. They must not be merged into a single ranking: the source categories have different scopes, and the TV list is not a movie list. The official ranking data has now been collected and dry-run validated. It remains a CI artifact rather than a committed dataset, and has not been imported into a MovieHub database.

As of the 2026-11-23 review, a 2026 annual movie/TV taxonomy and published ranking data had not been verified. MovieHub therefore does not expose a blank `annual-2026` placeholder. Add 2026 chart definitions only after the official categories are published and reviewed; import normalized data separately. The 2025 collector is manual and one-shot; no scheduled refresh is enabled.

## Reference projects

### Cinéphile / Top Movies List

The public `dataxiv/movies` project describes scheduled collection and refresh of Top 250, popular, annual and other movie lists. MovieHub uses this only as a reference for chart taxonomy, snapshot cadence and the idea of keeping chart sources behind adapters.

- Reference: https://github.com/dataxiv/movies
- Do not copy its code or redistribute its collected datasets as part of MovieHub unless the exact source repository, file-level license and data rights have been checked. The top-level aggregator's license does not automatically license every linked dataset or upstream site's content.

### Douban iDatabase

The project describes multi-source metadata aggregation and ID translation across Douban, IMDb, TMDb and TVDB. These are useful architectural concepts, but MovieHub keeps its own schema, import pipeline and provider-ID mapping.

- Reference: https://github.com/kfstorm/douban-idatabase
- The repository did not expose a recognized license in the metadata reviewed for this milestone. Treat its source code as unavailable for reuse unless a clear license is confirmed. No code is copied into MovieHub.

### Douban Scout

Scout remains MovieHub's current detailed metadata source. MovieHub opens Scout SQLite read-only and imports into its own database. It is not a chart acquisition source, and MovieHub must not modify Scout.

## One-shot Top 250 collector

- Reads only the public `/top250` HTML pages.
- Checks `robots.txt` before requesting chart pages.
- Makes ten sequential page requests, with at least two seconds between requests, or the longer crawl-delay declared in robots.txt.
- Does not use cookies, login sessions, proxy rotation, redirects, retries or challenge bypass.
- Stops on 401/403, 429, unexpected redirects, oversized responses, missing ranks or changed markup.
- Writes a normalized JSON file only; it does not write directly to the database or run on a schedule.

## Popular and high-rated collectors

- Use Douban's undocumented `/j/search_subjects` web endpoint for the `热门` and `豆瓣高分` tags.
- Bound each run to at most 100 results by default (hard maximum 500).
- Use sequential pacing of at least two seconds (or the longer robots.txt crawl-delay), robots.txt checks, no cookies, no proxy rotation, no redirects and no retries.
- The endpoint returns only list-level fields; Scout remains the metadata enrichment source.
- Treat this as a fragile web endpoint, not a supported official API. It may stop working or be disallowed at any time.

## Acquisition constraints

- Do not depend on historical embedded Douban API keys or assume legacy `api.douban.com/v2` endpoints are anonymously usable.
- Do not add an external paid API provider or third-party hosted proxy as a mandatory dependency.
- Do not scrape at high frequency, bypass login/challenges, rotate identities, or evade rate limits.
- Do not commit scraped chart dumps or copyrighted poster/data archives to Git.
- If an authorized provider or user-controlled export becomes available, implement it as a separate `ChartSourceAdapter` that emits the existing `ChartSnapshotImport` schema.
- Existing web collectors are opt-in/manual only; they check robots.txt, apply conservative pacing and stop on access denial/rate limiting. They do not use retries, login, proxy rotation or challenge bypass.
- Any expansion to new chart types or scheduled collection requires a separate source/permission review. It must have conservative request pacing, bounded retries only where permitted, conditional caching, clear source attribution and a kill switch. It must not run as an unbounded background loop.

## Current operator workflow

- Douban high-rated: `sh deploy/refresh_douban_high_rated.sh [YYYY-MM-DD]`.
- Douban real-time popular: `sh deploy/refresh_douban_popular.sh [YYYY-MM-DD]`.
- Both scripts are operator-invoked only. They stop when robots.txt disallows the endpoint or Douban returns 401/403/429; they do not bypass access controls, and they do not restart containers.
- Each script writes a temporary normalized snapshot, dry-run validates it, creates a database backup, imports the dated snapshot, and removes the temporary file only after success.

For a manually prepared UTF-8 JSON snapshot, validate it with `--dry-run`, then import it using [CHART-IMPORT.md](CHART-IMPORT.md). Re-importing the same chart/date replaces only that snapshot; other dates remain intact.

## Decision

Keep scheduled chart acquisition as an explicit pending milestone until the data source, authorization, reliability and request policy are settled. The current one-shot collectors are experimental, operator-invoked tools around public pages/endpoints, not a guarantee of stable or officially supported access.
