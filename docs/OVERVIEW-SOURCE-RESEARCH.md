# Movie overview source research and decision

> Research date: 2026-11-24  
> Scope: the 250-item Douban Top 250 first-launch snapshot and the 38 annual-chart items.  
> Current measured baseline: overview is 0/250 for Top 250. Missing plot descriptions must remain NULL; reviews, taglines, marketing copy and generated summaries are not substitutes.

## Executive decision

**TMDB API is the leading candidate for a first controlled pilot, not yet an approved bulk-import source.** It exposes localized movie/TV metadata including `overview`, supports localized requests such as `zh-CN`, and documents external-ID lookup using IMDb IDs. The developer API is free only for non-commercial use, requires prominent attribution and approved TMDB logo placement, and has no SLA. A commercial project requires a separate license from TMDB.

This fits a private, non-revenue home-lab deployment only if the project's actual use remains non-commercial and the applicable current terms permit the intended persistence/display. The API's no-SLA status means it cannot be the only operational dependency: imported descriptions must be optional, source-attributed cached metadata, and the application must continue working when TMDB is unavailable. Before enabling ingestion, confirm the then-current terms cover the planned caching/persistence and public/private display. Do not treat the API's existence or the FAQ alone as a blanket content copyright grant.

## Candidate assessment

| Candidate | Synopsis availability | License / usage | Stability | Decision |
|---|---|---|---|---|
| TMDB API | Structured `overview`; localized metadata; `zh-CN` request supported where translations exist | Free developer API is non-commercial only; attribution notice and approved logo required; commercial licensing via sales | Official API and docs; no SLA; API changes and rate limits are documented | **Pilot first**, subject to non-commercial and caching/display terms check |
| Chinese/English Wikipedia via Wikimedia API | Genuine plot sections may exist in some film articles; not a consistent structured synopsis field and coverage is unknown | Most article text CC BY-SA 4.0; attribution, link to source/license, indication of changes, and ShareAlike obligations apply; verify each page and any imported-source notices | Public API and reuse policy; API rate limits and User-Agent requirements; article coverage varies | **Compliant fallback for individually verified articles**, not a bulk-coverage promise |
| OMDb API | Exposes short/full plot | Terms limit user Contributions to personal, non-commercial use; prohibit unauthorized copying/archive/distribution and creating an index of Contributions | API exists but terms are incompatible with MovieHub's persistent catalog use | **Reject** |
| Douban detail-page synopsis / blocked endpoints | Potential Chinese synopsis coverage | Current project policy intentionally avoids robots-disallowed endpoints; no independent redistribution permission established | Access restrictions and scraping risk | **Do not use** |
| Douban Scout `detail.summary` | Existing importer can read summary text from Scout raw data | Source provenance and reuse rights are not established merely because Scout contains the field | Depends on external Scout database and upstream acquisition | **Do not bulk-import as approved synopsis source until rights and origin are documented** |

## Official documentation reviewed

- TMDB FAQ: https://developer.themoviedb.org/docs/faq
  - States there is no SLA.
  - Free API use is for non-commercial purposes with attribution.
  - Commercial use requires contacting TMDB.
  - Requires the notice: "This product uses the TMDB API but is not endorsed or certified by TMDB." and an approved logo.
- TMDB languages: https://developer.themoviedb.org/docs/languages
  - Metadata endpoints support localized data in many cases; translation coverage is not universal.
  - Language parameter uses ISO 639-1 plus region, e.g. `zh-CN`.
- TMDB finding data: https://developer.themoviedb.org/docs/finding-data
  - Supports external-ID lookup (for example IMDb IDs), plus text search.
- TMDB search/detail workflow: https://developer.themoviedb.org/docs/search-and-query-for-details
  - Search results include an `overview`; the returned TMDB ID can then be used for detail lookup.
- Wikimedia content reuse: https://www.mediawiki.org/wiki/Wikimedia_APIs/Content_reuse
  - Most Wikipedia editions use CC BY-SA 4.0; attribution and ShareAlike obligations must be met, and changes must be indicated.
- Wikimedia API usage policy: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines/en
  - Requires an identifiable User-Agent, compliance with rate-limit instructions, license compliance for cached/republished data, and no abusive/concurrent traffic.
- OMDb terms: https://www.omdbapi.com/legal.htm
  - Restricts Contributions to personal, non-commercial use and disallows unauthorized copying, archiving, distribution and indexing.

## Matching and ingestion design

The current Top 250 adapter extracts Douban ID, title, original title, year, rating and other page-visible fields, but it does **not** currently populate IMDb IDs. The normalized chart schema already has optional `imdb_id` and `tmdb_id` fields, and the Movie model has both identifiers.

A safe enrichment job should use this resolution order:

1. Existing `tmdb_id`: request the TMDB detail endpoint directly.
2. Existing `imdb_id`: use TMDB `/find/{external_id}?external_source=imdb_id`; require the expected media type.
3. Otherwise search by title and year, then accept only a single high-confidence candidate whose release year and normalized original/alternate title are consistent. Ambiguous or conflicting candidates go to a review report; never pick the first search result blindly.
4. Fetch localized details with `language=zh-CN`. If no Chinese overview exists, leave the field empty. A Traditional Chinese fallback may be measured separately, but must be explicitly labeled with its actual language.
5. Accept only non-empty, plot-like `overview` text from the provider's overview field. Reject tagline, review, user comment, keywords, promotional copy, and generated text.
6. Never overwrite a non-empty `movies.overview`. A later source may be recorded as an observation but must not silently replace the chosen value.

The current Top 250 adapter's lack of IMDb IDs means the pilot must first report how many of the 250 can be matched by title/year with strict confidence. Do not assume TMDB coverage or claim a projected percentage before measuring it. The 38 annual-chart rows should be measured separately.

## Provenance and compliance changes required before accepted import

Schema v3 currently records field name, source, source URL, observed time and SHA-256 of the value. That is a useful audit base, but it does not yet explicitly store license/terms label, language, attribution, or whether text was modified.

Before a production-quality synopsis import, add an additive schema migration (proposed schema v4) for at least:
- `license_name` or `terms_basis` (e.g. TMDB non-commercial developer API terms; CC BY-SA 4.0);
- `language` (e.g. zh-CN, zh-TW, en);
- `attribution_text` or a stable attribution key;
- `is_modified` (default false);
- `source_record_id` / provider ID and exact source page URL where available.

The UI must display source attribution with the synopsis. For TMDB, add the required notice and approved logo to About/Credits. For Wikipedia-derived text, show article/source link and CC BY-SA license, indicate edits, and preserve ShareAlike obligations for the adapted text. Do not mix provider text and treat the combined result as one unlicensed synopsis.

## Pilot acceptance gate

Run a dry-run against the 250 Top 250 rows plus the 38 annual rows, with no database writes, and emit:
- exact-ID matches, title/year matches, ambiguous matches, no matches;
- localized `zh-CN` overview present/empty counts;
- optional `zh-TW` counts reported separately;
- rejected records and reasons;
- per-record provider ID, source URL, language, license/terms basis and content SHA-256;
- duplicate and wrong-media-type checks.

Only after the report is reviewed should the importer write to an isolated disposable SQLite database. The write must fill only NULL/empty overviews, write field-level provenance in the same transaction, and pass integrity/foreign-key checks. Production/NAS deployment remains out of scope.

## Implemented dry-run tooling

- `backend/app/adapters/tmdb_overview.py`: read-only TMDB client. Resolution order is existing TMDB ID, IMDb external ID, then exact title+year. Every route cross-checks title/year; ambiguous or mismatched candidates are rejected. Requested locale is used for both search and detail requests. Requests are sequential and throttled, with a bounded 429 retry.
- `backend/scripts/audit_tmdb_overview.py`: reads normalized JSON snapshots recursively (including the nested artifact layout), deduplicates by Douban ID, and emits status, match method, TMDB ID, locale, overview length/hash and source URL. It does not output synopsis text and never opens MovieHub SQLite.
- `backend/tests/test_tmdb_overview.py` and `backend/tests/test_audit_tmdb_overview.py`: mocked API tests cover exact title/year, ambiguity, year mismatch, IMDb cross-check, known TMDB ID, locale, empty overview, nested artifact loading, report deduplication and no synopsis text in reports.
- Manual workflow: [tmdb-overview-audit.yml](../.github/workflows/tmdb-overview-audit.yml). It downloads the retained first-launch artifact from run `45329522019`, runs zh-CN and zh-TW dry-runs, and uploads a report that contains no synopsis text. It requires the repository Actions secret `TMDB_API_READ_TOKEN`.

## Next work order

1. Confirm the non-commercial and intended caching/display terms gate. Add `TMDB_API_READ_TOKEN` as a repository Actions secret (never commit it or paste it into chat).
2. Run the manual workflow [TMDB overview coverage audit](../.github/workflows/tmdb-overview-audit.yml) using source run `45329522019` (artifact retained until 2026-12-08). Review exact matches, ambiguous/no-match counts, and zh-CN/zh-TW overview coverage.
3. If the measured coverage and terms are acceptable, add the additive provenance migration for license/terms basis, language, attribution and modification marker, then implement the separate NULL-only importer and attribution UI.
4. If TMDB cannot meet terms or measured coverage, use individually verified Wikimedia film articles as a fallback with CC BY-SA compliance; keep unknown synopsis fields empty.
5. Then resume real-data pagination, multi-date snapshot selection/comparison, filters and edge-state E2E.
