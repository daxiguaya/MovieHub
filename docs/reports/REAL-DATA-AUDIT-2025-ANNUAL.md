# Real-data audit: Douban 2025 annual charts

Date: 2026-11-24  
Branch: `phase4/database-foundation`  
Source workflow: [GitHub Actions #45213246118](https://github.com/daxiguaya/MovieHub/actions/runs/45213246118)  
Artifact: [moviehub-douban-annual-2025](https://github.com/daxiguaya/MovieHub/actions/runs/45213246118/artifacts/14835864058)  
Artifact SHA-256: `d7d050a5816dcf645d367de4dc3182f5e629060ef70f95e498a75ac60b8de689`  
Source page declared by the collector: https://blog.douban.com/douban/2026/01/15/4382/

## Scope

This audit inspects the four normalized JSON files actually produced by the opt-in collector. It is real collected source data, not synthetic fixtures. It is **not** the Scout SQLite catalogue. The collector workflow completed its four-file dry-run; this audit independently inspected the downloaded artifact contents and metadata coverage. A subsequent disposable-CI rehearsal imported this exact artifact into a newly initialized temporary MovieHub database; details are recorded below.

## File-level results

| Chart | Entries | Rank sequence | Rating range | Unique Douban IDs |
|---|---:|---|---:|---|
| 2025 评分最高华语电影 | 8 | 1–8 | 7.5–8.8 | 8/8 |
| 2025 评分最高外语电影 | 10 | 1–10 | 7.6–8.7 | 10/10 |
| 2025 年度冷门佳片 | 10 | 1–10 | 7.8–8.6 | 10/10 |
| 2025 评分最高华语剧集 | 10 | 1–10 | 7.8–8.5 | 10/10 |
| **Total** | **38** | | | **38/38** |

Cross-chart duplicate Douban IDs: **0**. All 38 records have a non-empty title and numeric Douban ID. All rank sequences are continuous within the collected entries. The Chinese-movie list contains 8 entries rather than 10; this matches the actual artifact and must not be padded with invented ranks.

## Metadata coverage

| Field | Populated | Coverage |
|---|---:|---:|
| directors | 38/38 | 100% |
| year | 0/38 | 0% |
| rating_count | 0/38 | 0% |
| imdb_id | 0/38 | 0% |
| tmdb_id | 0/38 | 0% |
| actors | 0/38 | 0% |
| genres | 0/38 | 0% |
| regions | 0/38 | 0% |
| posters | 0/38 | 0% |
| overview | 0/38 | 0% |

## Assessment

- **Suitable for an isolated chart-snapshot import rehearsal:** yes, subject to the existing schema/preflight checks. The records contain chart identity, rank, title, Douban ID, type, rating and director.
- **Suitable as a complete movie/TV catalogue or as a substitute for Scout:** no. The absence of year, rating count, actors, genres, regions, posters and overview is substantial. The current annual collector parses ranking membership and limited fields from the official roundup; it does not enrich subject detail pages.
- **Do not infer release year from the annual chart period.** `period=2025` identifies the chart period, not each title's release year.
- **Do not fill missing ranks or metadata with guesses.** Any enrichment should be a separate, source-attributed, rate-limited stage with its own validation and provenance.
- The 8-entry Chinese-movie chart is a real observed result, not an automatic failure. Before treating it as the intended full chart, compare it with the official page and collector parsing behavior.

## Follow-up data work

The 38-record annual artifact has been imported and verified in an isolated MovieHub database, but it is not a complete searchable catalogue and its metadata is sparse. The next product-facing data work is to select the intended first-release chart set and enrich records from verified, permitted sources, retaining provenance and allowing unknown fields to remain empty. A Scout SQLite snapshot and its read-only coverage audit are **optional** and should only be pursued if Scout is deliberately selected as an external metadata source. MovieHub does not have a production source database because it has not been deployed; no Scout source or NAS production environment is required to continue development.

No Scout source file, MovieHub production database, NAS service, NPM configuration or production deployment was accessed or changed.

## Isolated real-data import rehearsal

**Workflow:** [GitHub Actions #45312215353](https://github.com/daxiguaya/MovieHub/actions/runs/45312215353)  
**Job:** `real-annual-data-import-rehearsal` — completed successfully.

The workflow downloaded the same retained artifact (ID `14835864058`), initialized a new database under the GitHub runner's temporary `/tmp/moviehub-real-annual-data/db/movies.db`, and invoked the production `scripts.import_annual_charts --apply` path. It then independently queried the persisted SQLite database.

| Assertion | Result |
|---|---:|
| Annual chart snapshots | 4 |
| Movie records | 38 |
| Chart-item records | 38 |
| Cross-chart duplicate IDs | 0 |
| Rank sequences | Continuous in all 4 charts |
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` violations | 0 |

The import service reported all four snapshots committed in one batch transaction. The database was a disposable GitHub-hosted runner file and was not uploaded to NAS or retained as a production database. This proves the real annual artifact can pass the current import path and persist consistently in an isolated database; it does not prove Scout catalogue compatibility, NAS performance or production deployment readiness.
