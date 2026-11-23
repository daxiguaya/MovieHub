# Chart data sources and acquisition policy

Last reviewed: 2026-11-23

## Current state

MovieHub has a normalized chart snapshot model, date-scoped replacement semantics, local/Cinephile-format adapters, a dry-run import CLI, and a one-shot Top 250 public-page collector.

**It does not yet run scheduled chart collection.** Top 250 can be collected manually when robots.txt permits; popular, high-rated and annual chart collectors are not yet implemented. Built-in chart definitions are display metadata only; they are not evidence that Top 250, popular, high-rated, or annual chart data has been fetched.

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
- Makes ten sequential page requests, with at least two seconds between requests.
- Does not use cookies, login sessions, proxy rotation, redirects, retries or challenge bypass.
- Stops on 401/403, 429, unexpected redirects, oversized responses, missing ranks or changed markup.
- Writes a normalized JSON file only; it does not write directly to the database or run on a schedule.

## Acquisition constraints

- Do not depend on historical embedded Douban API keys or assume legacy `api.douban.com/v2` endpoints are anonymously usable.
- Do not add an external paid API provider or third-party hosted proxy as a mandatory dependency.
- Do not scrape at high frequency, bypass login/challenges, rotate identities, or evade rate limits.
- Do not commit scraped chart dumps or copyrighted poster/data archives to Git.
- If an authorized provider or user-controlled export becomes available, implement it as a separate `ChartSourceAdapter` that emits the existing `ChartSnapshotImport` schema.
- If a future web collector is explicitly approved, it must have conservative request pacing, bounded retries, conditional caching, clear source attribution and a kill switch. It must not run as an unbounded background loop.

## Current operator workflow

Prepare a UTF-8 JSON snapshot in the documented normalized format, validate it with `--dry-run`, then import it using [CHART-IMPORT.md](CHART-IMPORT.md). Re-importing the same chart/date replaces only that snapshot; other dates remain intact.

## Decision

Keep automatic chart acquisition as an explicit pending milestone until the data source, authorization, reliability and request policy are settled. This is preferable to building a brittle collector around a deprecated API or an undocumented third-party proxy.
