# Chart data sources and acquisition policy

Last reviewed: 2026-11-27

## Current production state

The production database contains:

| Chart | Snapshots | Items |
|---|---:|---:|
| Douban Top 250 | 1 | 250 |
| 2025 Chinese films | 1 | 8 |
| 2025 international films | 1 | 10 |
| 2025 hidden gems | 1 | 10 |
| 2025 Chinese TV | 1 | 10 |
| **2025 annual total** | **4** | **38** |

The four annual charts are separate lists under period `2025`. The Chinese-film source explicitly leaves ranks 9 and 10 empty; MovieHub does not synthesize entries or renumber the remaining ranks.

**Douban real-time popular and Douban high-rated are retired and are not current product charts.** Their former `/j/search_subjects` collection path was disallowed by Douban's `robots.txt`. Collection was stopped and the UI entries were removed. Empty legacy chart-definition rows in an existing database are historical leftovers, not supported charts or evidence of collected data.

## Supported chart sources

### Douban Top 250

- The one-shot collector reads public `/top250` HTML pages.
- It checks `robots.txt` before requesting chart pages.
- It uses sequential requests with conservative pacing and respects a longer published crawl-delay.
- It does not use cookies, login sessions, proxy rotation, retries, or challenge bypass.
- It stops on access denial, rate limiting, unexpected redirects, oversized responses, missing ranks, or changed markup.
- It writes a normalized JSON snapshot; importing remains a separate explicit operation.

### Official 2025 annual lists

Douban's official 2025 annual roundup lists four film/television categories:

1. 2025 评分最高华语电影
2. 2025 评分最高外语电影
3. 2025 年度冷门佳片
4. 2025 评分最高华语剧集

Sources: [Douban official annual roundup](https://blog.douban.com/douban/2026/01/15/4382/) and [2025 annual movie page](https://movie.douban.com/annual/2025/).

The collector is a manual, one-shot adapter for the official roundup page. It checks the source's robots.txt, fails closed when access is disallowed, and emits four normalized JSON files without opening or modifying a MovieHub database. The production database has since received the four validated lists (38 entries total). See [ANNUAL-CHART-COLLECTOR.md](ANNUAL-CHART-COLLECTOR.md) for the reproducible collection and import procedure, and [ANNUAL-2025-ARTIFACT-REVIEW.md](ANNUAL-2025-ARTIFACT-REVIEW.md) for the original artifact review and later import note.

A 2026 annual taxonomy and published ranking data must be verified against an official source before adding definitions or importing snapshots. Do not infer that a new annual list exists from the calendar year alone.

## Retired sources: real-time popular and high-rated

The former popular and high-rated collectors targeted Douban's undocumented `/j/search_subjects` endpoint for the `热门` and `豆瓣高分` tags. That endpoint is disallowed by the applicable robots.txt policy. The project stopped collection and removed both chart entries from the user-facing product.

- Do not run `deploy/refresh_douban_popular.sh` or `deploy/refresh_douban_high_rated.sh`.
- Do not list those scripts as operator workflows or restore the corresponding UI entries.
- Do not bypass robots.txt, access controls, rate limits, or use alternate identities/proxies to reach the retired endpoint.
- Reconsider only after a separately documented, authorized source and policy review.

The legacy scripts may remain in the repository for historical traceability; their presence does not make the source supported.

## Other source boundaries

### Douban Scout

Scout is an optional, external detailed-metadata source. MovieHub opens a staged Scout SQLite database read-only and imports selected records into its own database. Scout is not MovieHub's database and is not a chart-acquisition source. Never modify the Scout source.

### Reference projects

- [dataxiv/movies](https://github.com/dataxiv/movies) is a reference for chart taxonomy and adapter concepts only. Do not copy code or redistribute datasets without checking the exact source and data licenses.
- [kfstorm/douban-idatabase](https://github.com/kfstorm/douban-idatabase) is a reference for multi-provider identity mapping only. Do not reuse source code unless a clear license is confirmed.

## Acquisition constraints

- Do not depend on historical embedded Douban API keys or assume legacy `api.douban.com/v2` endpoints are anonymously usable.
- Do not add a paid API provider or third-party hosted proxy as a mandatory dependency.
- Do not scrape at high frequency, bypass login/challenges, rotate identities, or evade rate limits.
- Do not commit scraped chart dumps, production databases, or copyrighted poster/data archives to Git.
- New chart sources require a separate source/permission review, conservative pacing, clear attribution, validation, and a kill switch.
- Chart collection is not scheduled by MovieHub. Collection, validation, and database import are separate deliberate operations.

## Import workflow

For an authorized, manually prepared UTF-8 JSON snapshot, validate it with the dry-run option and import it using [CHART-IMPORT.md](CHART-IMPORT.md). Re-importing the same chart/date replaces only that snapshot; other dates remain intact.

The retired popular/high-rated scripts are explicitly excluded from this workflow.

## Decision

Keep the current source set limited to the imported Top 250 and official 2025 annual lists. Do not resume the retired Douban endpoints. New sources and 2026 annual charts require evidence of publication and a separate policy review.
