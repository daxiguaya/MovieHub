# MovieHub Development Progress

Branch: `phase4/database-foundation`
Last updated: 2026-11-23
Current phase: Frontend validation, chart acquisition and pre-deployment hardening

## Phase 4 — independent database foundation

- [x] Define the independent MovieHub SQLite schema (11 core tables); external provider IDs remain nullable identifiers and internal relations use `movies.id`.
- [x] Add explicit database initialization from an empty database, with validation and atomic publication; application import/startup does not silently create a database.
- [x] Validate SQL schema against SQLAlchemy ORM metadata, including core constraints, indexes and foreign-key behavior.
- [x] Add migration safety: schema version checks, verified backup, integrity/foreign-key validation and rollback restoration.
- [x] Implement chart snapshot semantics: re-import replaces only the selected chart/date snapshot, preserves other dates and does not overwrite populated Scout metadata.
- [x] Cover failure rollback, WAL sidecar cleanup and idempotent built-in chart initialization without overwriting user settings.
- [x] Add direct read-only Douban Scout fixture integration coverage for source-field mapping, MovieHub internal IDs, genre/region associations, posters, movie/TV records, and source-file immutability.

**Phase 4: 7/7 complete.**

## Application integration audit

- [x] Prevent API database dependency from silently creating a missing SQLite file; missing DB now returns HTTP 503 with explicit initialization guidance.
- [x] Verify uninitialized database requests return HTTP 503 without creating the database path or parent directory.
- [x] Verify chart and movie read APIs return successfully against a temporary database created by the explicit initializer.
- [x] Verify protected import endpoints reject missing API keys and block absolute-path and symlink escapes from the configured import directory.
- [x] Verify chart snapshot import, same-date replacement, historical-date listing and latest-snapshot reads through the HTTP API.
- [x] Remove wildcard credentialed CORS; cross-origin access is disabled by default and configurable through an explicit origin allowlist.
- [x] Add a read-only /api/ready check that verifies all required tables and schema version; keep /api/health as the process liveness check.
- [x] Review console logging configuration and graceful cancellation of the poster-cache cleanup task; no service restart or deployment performed.
- [x] Remove obsolete tracked Phase 3 repair-backup copies and the one-off source-repair script; add ignore rules for local repair and migration artifacts.
- [x] Add configuration documentation, safe backend environment template and project README links.

**Application integration audit: complete.**

## Backend container packaging

- [x] Add a Python 3.11 slim backend Dockerfile; run as a non-root UID.
- [x] Add a Compose service with read-only root filesystem, dropped capabilities, no-new-privileges, resource/PID limits and dedicated writable volumes.
- [x] Keep MovieHub data, backup destination and Scout source paths separate; mount Scout import source read-only.
- [x] Connect API only to the existing NPM Docker network and Compose bridge; do not publish a NAS/LAN host port.
- [x] Add explicit one-shot database initialization instructions; container startup never initializes or migrates a database.
- [x] Add liveness/readiness health-check wiring and document proxy-header trust boundaries.
- [x] Extend CI to validate Compose configuration and build the backend image.
- [x] Document NAS preparation, directory permissions, NPM upstream and operational safety boundaries.

**Backend packaging baseline: complete. Not deployed.**

## Database backup and restore

- [x] Add SQLite online-backup utility for consistent backups while the API is running.
- [x] Verify database integrity, foreign keys, required tables and schema version before accepting a backup.
- [x] Write SHA-256 manifest and metadata; retain the newest seven backup generations by default.
- [x] Add guarded restore requiring explicit confirmation and an operator assertion that the API is stopped.
- [x] Create a pre-restore rollback copy and atomically replace/validate the restored database.
- [x] Cover backup snapshot consistency, restore/rollback behavior, tamper rejection, retention and incomplete-schema rejection with tests.
- [x] Document NAS backup-volume preparation and the backup/restore operator runbook.

**Backup/restore baseline: complete. Poster cache is intentionally excluded because it is rebuildable.**

## Poster fetch security hardening

- [x] Restrict poster source URLs to HTTPS Douban image CDN hosts and reject credentials, non-standard ports and arbitrary hosts.
- [x] Resolve every initial/redirect host and reject private, loopback, link-local, reserved or mixed DNS answers.
- [x] Validate every redirect hop independently; cap redirects at three and disable automatic redirect following.
- [x] Enforce 8 MiB response limits, image content-type allowlist and JPEG/PNG/GIF/WebP/AVIF file-signature matching.
- [x] Add `X-Content-Type-Options: nosniff` to poster responses.
- [x] Add regression tests for allowed/blocked URLs, DNS answers, image signatures and MIME mismatch.

**Poster fetch security baseline: complete.**

## Chart collector-to-database integration

- [x] Add an end-to-end fixture test that collects a tagged chart through the adapter, imports it through the production chart import service, and verifies snapshot ranks reference MovieHub internal movie IDs.
- [x] Keep this test isolated from real Douban access and production/Scout databases.

**Collector → normalized snapshot → MovieHub SQLite integration: verified in CI.**

## Product scope and architecture

- [x] Record the agreed first-release user journey: chart discovery → movie details → Xiaoya search.
- [x] Record first-release charts, search/filter, detail, poster, favorites and Xiaoya handoff requirements.
- [x] Explicitly exclude downloading, playback and media-library management; preserve Xiaoya/Jellyfin/SmartStrm responsibilities.
- [x] Confirm React + TypeScript + Vite frontend in a separate container, FastAPI backend, SQLite with optional FTS5 only if justified, local poster cache, and no Redis/MySQL/Elasticsearch.
- [x] Map current backend coverage and identify FTS5, favorites API, frontend and frontend container as remaining work.

**Product scope and architecture baseline: complete.**

## Annual chart batch-output safety (2026-11-23)

- [x] Stage all four annual chart JSON files before publishing any destination file.
- [x] Roll back newly published files if a later publish fails.
- [x] Preserve every previous output file when an overwrite batch fails partway through.
- [x] Reject incomplete four-chart payloads and check overwrite conflicts before making the Douban network request.
- [x] Add failure-injection tests for first-time publication and overwrite rollback.

## Multi-chart import transaction boundary (2026-11-23)

- [x] Add a service entry point that imports multiple chart/date snapshots inside one outer database transaction.
- [x] Keep each snapshot's existing validation and replacement behavior inside a savepoint.
- [x] Invalidate chart caches once, and only after the complete batch commits.
- [x] Roll back all earlier chart, movie, metadata and snapshot writes if any later snapshot fails.
- [x] Reject duplicate chart/date pairs before opening the write transaction.
- [x] Add regression tests for whole-batch rollback and duplicate-pair rejection.

## Annual chart batch CLI and integration verification (2026-11-23)

- [x] Validate all four expected annual chart files as one input batch before any database readiness check.
- [x] Enforce the configured chart slug and display name, Douban source, annual category, 2025 period, matching capture date and correct movie/TV type.
- [x] Enforce normalized schema, unique IDs/ranks and ascending rank order without inventing missing source ranks.
- [x] Keep dry-run database-free; require explicit `--apply` for persistence.
- [x] Exercise the apply path against an isolated in-memory SQLite database using the real chart import service.
- [x] Verify successful application creates four charts/snapshots and that a late media-type conflict rolls back the complete batch while preserving the pre-existing Scout-like movie record.
- [x] Cover command-line output, invalid dates, missing files, mixed capture dates and incorrect chart names.

**Annual batch CLI integration: verified in CI #45180603281 (147 passed, 4 skipped).** No NAS database was opened and no production import was performed.

## Scout coverage audit reporting hardening (2026-11-23)

- [x] Reject duplicate chart/date snapshots before opening the read-only Scout database.
- [x] Add aggregate field-coverage counts and percentages across all supplied charts, alongside per-chart coverage.
- [x] Keep the aggregate denominator restricted to unique Scout ID matches with matching media type.
- [x] Add regression coverage for duplicate audit inputs and aggregate coverage output.

**Scout audit reporting hardening: implementation and regression tests added.** A consistent staged Scout copy is still required for a real coverage report; no NAS/production database was accessed.

## Overall first-release progress (estimate)

| Workstream | Status |
|---|---:|
| Database foundation and Scout-safe import boundary | 100% |
| Backend API baseline (charts, movie search/filter, details, posters, import, favorites) | 80% |
| Scout import hardening | Implementation and merge/partial-retry tests complete; 1k/10k/100k synthetic fixtures passed; NAS-hardware benchmark pending |
| Manual normalized chart snapshot import | Complete |
| One-shot Douban Top 250 collection | Implemented; robots-aware and low-rate |
| One-shot popular/high-rated collection | Implemented; bounded, robots-aware and low-rate |
| 2025 annual charts | Four official lists defined; collector and recoverable four-file output implemented; guarded four-file preflight CLI and all-or-nothing multi-chart DB import path implemented; real normalized data import pending |
| Favorites API and frontend UI | Implemented; Chromium E2E passed |
| Xiaoya handoff | Configured new-tab handoff and URL encoding passed Chromium E2E; real NPM verification pending |
| React frontend and user workflows | Baseline implemented; 4 Chromium E2E tests passed, including real FastAPI + temporary SQLite integration; visual QA pending |
| Container packaging and backup/restore preparation | 100% |
| Actual NAS deployment and end-to-end production verification | 0% |

**Estimated first-release implementation progress: about 70%.** This is a planning estimate, not a test metric. The independent database, core backend APIs, import hardening, poster security, frontend baseline, dual-container packaging and official 2025 annual chart acquisition path are substantially in place; importing the collected annual snapshots, 2026 category verification, scheduled chart refresh, NAS/NPM verification and production rollout remain unfinished.

## Chart and Scout import numeric integrity (2026-11-23)

- [x] Reject boolean and fractional values where integer ranks, years, or counts are expected.
- [x] Reject non-finite and out-of-range ratings before persistence.
- [x] Enforce the 1870–2200 year range in both the Pydantic chart schema and the service layer, including raw mapping callers that bypass schema validation.
- [x] Preserve existing Scout-owned year/rating metadata when incoming source values are invalid or absent.
- [x] Cover malformed Scout numeric metadata and raw chart-import year/rating edge cases with regression tests.

## Phase B — Scout import hardening (in progress)

- [x] Make `force_full` functional: incremental imports skip records whose Scout `update_time` is not newer than the last imported timestamp; forced full imports reprocess all valid records.
- [x] Replace the catalogue-wide write transaction with bounded batches (500 records per transaction) to reduce SQLite writer-lock duration.
- [x] Keep per-record SAVEPOINT isolation and make interrupted/partially committed imports safe to retry.
- [x] Invalidate MovieHub caches only after committed changes; report when earlier batches were committed before a later failure.
- [x] Add regression coverage proving incremental skip, newer-timestamp updates and forced full reprocessing behavior.
- [x] Exercise a 1,000-record synthetic Scout catalogue across six bounded batches.
- [x] Add opt-in 10k/100k synthetic throughput benchmarks using temporary source and target SQLite databases; normal CI skips these hardware-sensitive runs.

**Import hardening milestone: implemented and tested, including 1k/10k/100k synthetic catalogues processed across bounded batches.** The 10k/100k CI measurements are recorded below; a separate NAS-hardware benchmark remains pending. Source deletions remain non-destructive: absent Scout rows do not delete MovieHub movies.

## Scout import operator workflow

- [x] Document read-only source mount requirements and WAL-consistent staging guidance.
- [x] Document protected incremental and forced-full API requests plus status polling.
- [x] Document timestamp-based skip behavior, non-destructive empty-field merge policy, no source-delete propagation, batch commits and retry semantics.
- [x] Explicitly separate Scout metadata import from chart snapshot acquisition.

**Scout import runbook: complete. Synthetic 10k/100k performance validation is complete; NAS-hardware validation remains pending.**

## Favorites API milestone

- [x] Add protected favorites list/add/update-note/remove endpoints using internal MovieHub IDs, with idempotent writes and API-key enforcement.
- [x] Add integration tests for authentication, duplicate writes, note updates, internal-ID enforcement and removal.
- [x] Document that the browser must not embed the API key; the reverse proxy must inject it server-side.

**Favorites API and frontend favorites workflow: implemented; add/remove interaction passed real Chromium E2E using an isolated API fixture.**

## Phase D — poster-fetch security hardening

- [x] Restrict poster sources to HTTPS `imgN.doubanio.com` image CDN hosts.
- [x] Reject URL credentials, non-standard ports, non-HTTPS schemes, IP literals and arbitrary hosts.
- [x] Disable automatic redirects and validate every redirect target against the same host policy.
- [x] Resolve allowed CDN hostnames and reject DNS answers containing private, loopback, link-local or reserved IP addresses.
- [x] Restrict responses to raster image MIME types and enforce an 8 MiB maximum using both Content-Length and streamed byte counting.
- [x] Add regression tests for URL allowlisting, private DNS answers and size policy.

**Poster-fetch security milestone: implemented; 70-test CI passed.** No external poster URL is fetched unless it passes the allowlist and DNS checks.

## Chart snapshot import workflow

- [x] Add a CLI to validate and import normalized local JSON chart snapshots into the independent MovieHub database.
- [x] Add a dry-run mode that validates the input without opening or modifying the database.
- [x] Validate built-in chart slug/category/period consistency and enforce movie-versus-TV type before any database readiness check; keep custom chart slugs generic.
- [x] Support a generic local adapter that preserves the declared chart provider and a Cinephile adapter that labels its normalized export.
- [x] Fix the latent adapter package import path discovered by exercising the CLI.
- [x] Document snapshot format, date-scoped replacement, metadata precedence and explicit non-automation boundary.

**Snapshot import workflow: implemented and tested. Built-in annual chart taxonomy and movie/TV mismatches are rejected during dry-run before database access. This is a manual normalized-data import path, not an automated Douban collector.**

## Phase C — historical rank comparison

- [x] Add an API to compare two existing dated snapshots of the same chart.
- [x] Match entries using MovieHub internal movie IDs, not Douban IDs.
- [x] Report before/after rank, rank delta, new entries, removed entries, moved entries and unchanged entries.
- [x] Validate same-date and missing-snapshot requests.
- [x] Add comparison controls and rank movement display to the chart detail page.

**Historical rank comparison: implemented; backend and frontend CI passed.**

## Phase C — chart acquisition (partial)

- [x] Keep chart definitions, date-scoped snapshots and normalized JSON import separate from collection.
- [x] Add a one-shot Douban Top 250 HTML collector with robots.txt checks, two-second pacing, redirect denial and no cookies/proxies/retries.
- [x] Add one-shot popular and high-rated collectors using the site's undocumented `/j/search_subjects` web endpoint, bounded to 100 items by default, with the same robots/rate-limit safeguards.
- [x] Keep collection output as normalized JSON; validate with dry-run and import through the existing snapshot service.
- [x] Verify Douban's official 2025 annual categories and model the four distinct chart definitions without combining movie and TV rankings.
- [x] Add a one-shot collector for the official 2025 Douban annual roundup; one article fetch produces four separate normalized snapshots, with robots.txt checks and fail-closed handling.
- [x] Preserve the official rank numbers and empty positions; map the Chinese TV list to `tv` and the three film lists to `movie`.
- [x] Add parser/collector regression tests for all four sections, ID/rank duplicates, untrusted subject hosts, robots denial and HTTP 429.
- [x] Run the official collector in CI with robots.txt permission; generated 8/10/10/10 entries and all four JSON files passed `import_chart --dry-run`.
- [x] Upload the four normalized snapshots as a 14-day GitHub Actions artifact; keep generated data out of Git.
- [x] Add a read-only Scout coverage audit for chart JSON: ID match rate, metadata field coverage and media-type mismatches, with synthetic SQLite regression tests.
- [x] Download and independently review the four 2025 annual snapshots: 38/38 IDs unique across lists, ranks unique and ordered, expected 8/10/10/10 counts, and media types consistent; record the review without committing scraped JSON.
- [ ] Run the audit against a separately staged Scout copy only after that source is explicitly made available; import only after the independent MovieHub database is initialized.
- [ ] Add 2026 annual chart definitions only after the official taxonomy and ranking data are published and verified.
- [ ] Decide whether scheduled refresh is appropriate; no collector currently runs in the background.

**Top 250, popular/high-rated and official 2025 annual one-shot collectors are implemented. The 2025 annual collection, four dry-runs, artifact retention and independent structural review are complete. Scout metadata coverage and deliberate snapshot imports remain pending; 2026 category verification and scheduling remain pending.**

## Phase E — React frontend baseline

- [x] Add React + TypeScript + Vite application scaffold and typed API client.
- [x] Implement discovery home and chart-group tiles.
- [x] Implement chart snapshot page with historical date selection and cursor pagination.
- [x] Implement movie search page with keyword, movie/TV type, min/max rating, rating-count floor, year range, included/excluded genres, regions, sort direction and cursor pagination.
- [x] Add internal MovieHub movie-ID detail API and detail page with metadata, poster, Douban link and Xiaoya handoff.
- [x] Implement favorites list/add/remove UI against the protected favorites API.
- [x] Make Xiaoya search URL runtime-configurable; the title is URL-encoded into the existing `box` parameter and opens in a new tab.
- [x] Keep the API key out of frontend assets; document server-side NPM header injection only for the favorites path.
- [x] Add a separate non-root Nginx frontend container, read-only root filesystem, 128 MiB limit and Compose service.
- [x] Add five frontend regression tests covering chart navigation, search filters, Xiaoya handoff, rank comparison and favorite add/remove.
- [x] Add a separate Playwright + Chromium browser test suite for discovery → chart → detail, keyword search, favorite add and Xiaoya new-tab handoff.
- [x] Keep Playwright specs isolated from Vitest discovery; run the browser suite in a dedicated Ubuntu 24.04 CI job.
- [x] Add fixture-backed browser coverage for chart navigation, search filters, favorite add and Xiaoya new-tab URL encoding.
- [x] Start a real FastAPI process backed by a freshly initialized temporary SQLite database in CI; seed one chart snapshot and movie, then verify browser chart → detail → search without API interception.
- [x] Add CI type-check, Vite production build and frontend Docker image build.

**Frontend baseline and browser workflow validation: complete.** Five Vitest UI tests and four real Chromium E2E tests pass in CI. Three E2E cases use isolated API fixtures for interactive write/handoff behavior; the fourth uses a live FastAPI process and temporary SQLite database for real chart, detail and search API integration. NPM integration against the NAS and final visual QA remain outstanding.

## Chart source review and acquisition policy

- [x] Review Cinéphile's chart taxonomy and scheduled-refresh concept without copying code or datasets.
- [x] Add a one-shot Douban Top 250 collector that checks robots.txt, waits at least two seconds between pages, disables redirects, uses no cookies/proxies/retries, and stops on 403/429.
- [x] Add one-shot popular and high-rated collectors using the site's undocumented JSON endpoint, with bounded result counts, robots checks, two-second pacing, no cookies/proxies/retries and strict URL validation.
- [x] Review Douban iDatabase's multi-source metadata and ID-translation concepts without copying unlicensed code.
- [x] Record that Scout is a read-only metadata source, not a chart collector.
- [x] Record the manual normalized snapshot workflow and explicitly distinguish it from automatic chart collection.
- [x] Document why legacy/unauthorized API keys and mandatory third-party proxy APIs are not accepted as the default acquisition path.

**Source review: complete. Top 250, popular/high-rated and official 2025 annual one-shot collection are implemented. The 2025 annual run and artifact review are complete; Scout enrichment/import, 2026 taxonomy verification and any scheduling decision remain pending.**

## Next work

- [ ] Run the read-only Scout coverage audit against a separately staged, consistent Scout copy; review ID matches, media-type mismatches and metadata coverage before deciding whether to enrich/import the four separate 2025 snapshots. The local dry-run already enforces each built-in chart's category, period and media type.
- [ ] Review 2026 annual categories after official publication; do not expose empty placeholders.
- [x] Implement a one-shot official 2025 annual article collector that emits four separate normalized JSON snapshots and refuses collection when robots.txt or access controls do not permit it.
- [ ] Decide whether scheduled refresh is appropriate after verifying source authorization, robots rules and stability.
- [x] Add opt-in 10k/100k SQLite LIKE-search benchmarks covering sparse Chinese-title matches, original-title matches, no-match scans and multi-term searches; report count/page latency and SQLite query plans without hardware-specific pass thresholds.
- [x] Add a manually triggered GitHub Actions performance job that runs both the existing 10k/100k Scout import benchmarks and the new search benchmarks on isolated temporary SQLite databases.
- [x] Execute the isolated 10k/100k search and Scout import benchmarks in GitHub Actions; record timings and query plans. Keep FTS5 optional rather than a hard runtime dependency.
- [x] Add browser end-to-end tests for chart navigation, search, detail, favorites and Xiaoya handoff using Playwright Chromium and isolated API fixtures.
- [x] Add a live browser integration test against a running FastAPI backend and a temporary initialized/seeded SQLite database.
- [ ] Verify the complete deployment path through the user's NPM reverse proxy after deployment is separately authorized.
- [x] Add reproducible opt-in 10k/100k synthetic import throughput benchmarks against temporary SQLite databases.
- [x] Execute the isolated 10k/100k search and Scout import benchmark workflow and record timings/query plans; repeat on the target NAS only during an authorized pre-deployment test.
- [ ] Before any NAS rollout, verify the actual NPM Docker network, Scout export path/read permissions, and host data/backup directory ownership.
- [ ] Prefer a separate physical volume or off-site destination for backups; same-volume backups do not protect against disk failure.
- [ ] Keep production database initialization, Scout import, deployment and NPM changes as separately reviewed operator actions.

## SQLite search and Scout import performance results

- Benchmark run: [#314](https://github.com/daxiguaya/MovieHub/actions/runs/45152308824) — **success**; all four parameterized benchmark cases passed on GitHub Actions Ubuntu 24.04 using isolated temporary SQLite databases.
- LIKE search, 10k rows (COUNT / page): Chinese title 5.3 / 2.2 ms; original title 1.1 / 1.0 ms; no match 0.9 / 0.9 ms; multi-term 3.1 / 2.4 ms.
- LIKE search, 100k rows (COUNT / page): Chinese title 14.2 / 3.8 ms; original title 9.5 / 2.4 ms; no match 9.3 / 10.2 ms; multi-term 19.1 / 5.0 ms.
- SQLite reported `SCAN movies` for every tested LIKE scenario. This confirms leading-wildcard LIKE is not using a conventional index. Observed latency at 100k rows remains in the 2.4–19.1 ms range on the CI runner; do not add FTS5 solely on the basis of the query plan. Revisit if real catalogue size, concurrent use or measured user-facing latency warrants it.
- Scout synthetic import: 10k rows in 20.85 s (479.7 rows/s); 100k rows in 178.92 s (558.9 rows/s); configured batch size 500. These timings cover the import service run, not source fixture generation.
- Resource caveat: current benchmark harness does not record process RSS/peak memory or database file size, so no memory-footprint conclusion can be drawn. CI runner results are comparative baseline only; a NAS-hardware benchmark remains a separate, explicitly authorized pre-deployment task.

## Latest code validation

- Latest annual-collection validation: [#325](https://github.com/daxiguaya/MovieHub/actions/runs/45166104334) — backend, annual collection/dry-runs, frontend build/tests and Chromium E2E jobs succeeded. The opt-in performance job was skipped in this run; the 10k/100k performance measurements remain from successful CI #314.
- The read-only Scout coverage audit and its synthetic SQLite tests were added after the #325 artifact-producing commit. They require a subsequent CI run; do not treat #325 as validation of those later additions.
- Latest full performance validation: [#314](https://github.com/daxiguaya/MovieHub/actions/runs/45152308824) — **success**, on commit `535900b5`.
- Backend: **110 passed, 4 skipped**; the four skips are the opt-in 10k/100k search and Scout-import benchmark cases. Frontend: **5 Vitest tests passed**; browser: **4 Playwright Chromium E2E tests passed**.
- Compose validation, backend/frontend production builds and both container image builds passed.
- The browser job starts a real FastAPI process against a fresh temporary SQLite database, seeds a test chart/movie and runs one unmocked chart → detail → search workflow. Three additional browser tests use isolated API fixtures for favorite and Xiaoya handoff interactions.
- The built-in chart preflight rejects category/period/media-type mismatches before database access; the popular collector supplies its required realtime period. The four 2025 annual categories remain separate, and no unverified 2026 placeholder is exposed.
- All browser tests run on Ubuntu 24.04; no NAS services, live Scout database or production data are used.
- CI #314 explicitly ran the opt-in performance job on a marked push; the measured 10k/100k search and import results are recorded above.
- Scout import benchmark harness commit: [`ecd9f9f`](https://github.com/daxiguaya/MovieHub/commit/ecd9f9fe2ad662472a9dc7357f98e86bc80d1ad0); CI #314 now supplies the first combined 10k/100k import and LIKE-search measurements. Ordinary unmarked push CI continues to skip these hardware-sensitive benchmarks.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, import, NPM proxy change, or service restart is part of this work.
- Keep validation on temporary fixtures. Do not touch the user's live Scout database.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.


## Scout chart coverage audit hardening (2026-11-23)

- The read-only Scout coverage audit now looks up all Scout media types for requested Douban IDs, so unexpected types are reported as mismatches rather than incorrectly classified as missing.
- Duplicate Scout rows for one Douban ID are reported as ambiguous and excluded from metadata field-coverage calculations; the audit never chooses an arbitrary duplicate.
- Metadata field coverage now uses only unique ID matches whose Scout media type agrees with the chart item. Wrong-type rows remain visible as ID matches and explicit mismatches, but cannot inflate the field-coverage numerator or denominator.
- Added synthetic regression assertions for wrong-type records being excluded from field coverage, in addition to the unexpected-type and duplicate-ID cases.
- Validation status: implementation and regression tests are committed; a GitHub Actions run for the latest head is still required before treating these changes as CI-verified.



## Scout import numeric-data integrity (2026-11-23)

- Full CI and benchmark workflow requested after the importer and regression-test commits.


- Audited the Scout-to-MovieHub importer after the chart import guard passed CI. Found that raw Scout ratings were converted directly to float, allowing out-of-range or infinite values to reach database writes; invalid years could also be persisted.
- Added finite 0–10 rating normalization and a conservative year acceptance range (1870–2200). Invalid source values are treated as absent, preserving an existing valid MovieHub value and leaving a new record field unset.
- Hardened the importer's integer normalizer so booleans and fractional floats are not silently coerced to integers; this also protects rating-count and source timestamp parsing.
- Added integration coverage for out-of-range/infinite ratings, implausible years, preservation of existing valid metadata, and boolean/fractional integer inputs.
- CI status: pending for the new Scout importer changes. The preceding full CI run #350 passed all executed jobs.

## Chart import raw-input integrity hardening (2026-11-23)

- The service now validates rank values and duplicate ranks before opening its write transaction, including for mapping-based internal callers that bypass the Pydantic request schema.
- Integer normalization rejects booleans and fractional numeric values instead of silently treating `True` as rank 1 or truncating 1.5 to rank 1.
- Rating normalization rejects booleans, NaN and positive/negative infinity; invalid raw values are stored as absent rather than contaminating movie or chart-item rating columns.
- Added regression coverage for duplicate ranks, boolean/fractional ranks, and non-finite movie/source ratings. These cases also exercise the service's lower-level mapping input path.
- Validation status: implementation and tests are committed; a marked CI run is requested from the current branch head.
- Commits: service preflight `431b6fb`, integer normalization `f8d7763`, non-finite rating guard `575261a`, regression tests `ddd7d32` / `4e3e95b` / `e17b980`.

## Chart import identity/type integrity hardening (2026-11-23)

- The chart importer now preflights every existing MovieHub movie referenced by an incoming snapshot and rejects a movie/TV type conflict before updating movie metadata or replacing the chart/date snapshot.
- The importer does not silently rewrite an existing Scout-owned movie's media type to satisfy a chart. The failed import rolls back the entire transaction, preserving the previous snapshot.
- Added a regression test that first imports a valid snapshot, then attempts a conflicting movie-to-TV replacement and verifies the original MovieHub type and chart snapshot remain intact.
- Validation status: code and regression test are committed; latest-head GitHub Actions validation is pending. No production database was accessed.


## Scout coverage strict quality gate (2026-11-23)

- [x] Add an opt-in `--strict` mode to the read-only Scout chart coverage audit.
- [x] Emit the complete JSON report before returning a non-zero status when missing IDs, ambiguous duplicate IDs, or media-type mismatches are present.
- [x] Keep report-only mode as the default and avoid imposing arbitrary metadata completeness thresholds.
- [x] Add CLI regression tests for strict-mode failure and clean strict-mode success.
- [x] Document the exit-code contract for pre-import and automation use.

**Strict Scout coverage gate: implemented and CI-verified in run #45183094457.** Backend: 151 passed, 4 skipped; frontend, Chromium E2E and both Docker image builds passed. The annual collector and performance benchmark jobs were skipped by their opt-in conditions in that run. This remains a read-only audit and does not access or modify the NAS Scout database.


## Opt-in annual data collection and performance validation (2026-11-23)

- [x] Execute the official 2025 four-chart collector from GitHub Actions and retain its normalized JSON artifact.
- [x] Run the opt-in 10k/100k synthetic Scout import and search benchmarks.
- [x] Inspect the generated artifact metadata and benchmark output.
- [x] Keep collection output separate from MovieHub persistence; no production database import or deployment was performed.

**Full validation run:** [#392](https://github.com/daxiguaya/MovieHub/actions/runs/45183697856) — commit `ad865ffde7f6528cf509c830ad71d58379234f57`; all five jobs succeeded.

- Backend: **151 passed, 4 skipped**; one Starlette/httpx deprecation warning. The four skips are opt-in benchmarks in the ordinary backend test invocation; the dedicated performance job ran them separately.
- Frontend: **5 Vitest tests passed**, TypeScript/Vite production build and frontend container image build succeeded.
- Browser: **4 Playwright Chromium E2E tests passed**, including a live FastAPI + temporary SQLite integration path.
- Backend Compose validation and backend container image build succeeded.
- Annual collection: four official 2025 Douban chart snapshots were collected and each passed the chart-import dry-run; 38 entries total (8/10/10/10). Artifact: [moviehub-douban-annual-2025](https://github.com/daxiguaya/MovieHub/actions/runs/45183697856/artifacts/14820729977), 4,321 bytes, SHA-256 `64fed1bef8a21fb4bd38b4c4739a782dff110caa8976694f9e3c033077c8e69e`, retained until 2026-12-07. The JSON remains an Actions artifact, not committed or imported.
- LIKE search, 10k rows (COUNT / page): Chinese title 5.8 / 2.6 ms; original title 1.3 / 1.3 ms; no match 1.2 / 1.1 ms; multi-term 3.6 / 3.0 ms.
- LIKE search, 100k rows (COUNT / page): Chinese title 17.9 / 4.2 ms; original title 10.8 / 2.5 ms; no match 9.9 / 10.2 ms; multi-term 21.8 / 5.0 ms. SQLite reported `SCAN movies` for all scenarios; this is expected for leading-wildcard LIKE and remains a measured optimization candidate, not a reason to add mandatory FTS5 now.
- Scout synthetic import: 10k rows in 10.62 s (**941.6 rows/s**); 100k rows in 109.54 s (**912.9 rows/s**), batch size 500. These are GitHub-hosted runner results, not NAS performance or memory measurements.
- The run emitted non-blocking dependency/toolchain deprecation warnings (Starlette/httpx, Node.js 20 action runtime, and Node URL/punycode warnings); no job failed.

**Result:** acquisition, validation, benchmark execution and end-to-end CI are verified on the branch. Actual Scout ID/metadata coverage and deliberate import remain blocked on a separately staged, consistent Scout database copy. No production Scout DB, NAS service, deployment or NPM configuration was accessed or changed.


## Scout import record-error observability (2026-11-23)

- [x] Expose isolated per-record processing exceptions as `ImportStatus.errors` instead of silently folding them into the skipped count.
- [x] Include the record-error count in the completion message returned by the protected import status API.
- [x] Add an integration regression test proving one failed record rolls back independently, later records still import, and the final status reports the error count.
- [x] Update the Scout import runbook to require checking both `status` and `errors` before considering an import clean.

**Validation:** [run #403](https://github.com/daxiguaya/MovieHub/actions/runs/45187036550) passed Backend, Frontend and Playwright E2E. The run used commit `fa94f193970e9ad5687c517a1f98f35e54e0dab2`, which contains the service, schema and regression-test changes. Annual collection and performance benchmarks were skipped under their opt-in conditions. The subsequent #404 change only updated documentation; its CI was still running when this note was added.

**Scope:** no live Scout database, NAS service, deployment, NPM configuration or production data was accessed or changed. Actual Scout coverage/import remains blocked on a separately staged, consistent Scout database copy. Overall project progress remains **70%** until that real-data milestone is completed.


## Whole-catalogue Scout import quality audit (2026-11-23)

- [x] Add a read-only, snapshot-consistent audit over every Scout movie/TV row, not only IDs present in chart snapshots.
- [x] Report movie/TV totals, invalid and duplicate identities, invalid ratings/years, malformed raw JSON, and field-level metadata coverage.
- [x] Add a strict pre-import gate for identity defects and duplicate Douban IDs while keeping numeric/raw-data anomalies visible as review warnings.
- [x] Reuse the importer's source schema and normalization logic; audit does not open or write the MovieHub database.
- [x] Add synthetic regression tests, including a SHA-256 before/after check proving the Scout fixture is unchanged.
- Validation: awaiting the CI run for this commit. Actual coverage figures remain unknown until a consistent staged Scout DB copy is made available; no NAS or production database was accessed.


## Combined Scout import preflight (2026-11-23)

- [x] Combine whole-catalogue Scout quality and annual-chart coverage into one JSON report and strict decision gate.
- [x] Block on invalid identities, duplicate IDs, chart IDs missing from Scout, ambiguous IDs, and media-type mismatches.
- [x] Keep invalid ratings, years, and malformed raw JSON visible as warnings rather than silently discarding them.
- [x] Pin chart schema validation and lookup queries to one read-only SQLite transaction snapshot.
- [x] Add synthetic integration tests proving pass/block decisions and unchanged Scout source bytes.
- Validation: awaiting CI. The source DB is audited twice through separate read-only transactions; use a stable staged backup unchanged during execution. Actual coverage values remain unknown until a staged Scout copy is supplied.


## Scout import preview (2026-11-23)

- [x] Add read-only service preview using the same Scout identity/duplicate preflight as the importer.
- [x] Classify new records, incremental update candidates and unchanged timestamp skips.
- [x] Support forced-full preview semantics without writing target records.
- [x] Report invalid year/rating counts as warnings.
- [x] Add CLI that refuses to run unless the independent MovieHub database is already initialized.
- [x] Add integration tests proving source and target SQLite file hashes remain unchanged and preview classifications match importer timestamp rules.
- Validation: awaiting CI. Preview remains advisory; a later import can observe target changes and runtime record errors.


## Durable Scout import batch journal (2026-11-23)

- [x] Assign each background import a stable run ID.
- [x] Persist run-start, committed-batch, completion and failure events beside the MovieHub database.
- [x] Record batch number, processed/total, last Douban ID and cumulative import/skip/error counts only after the corresponding target transaction commits.
- [x] Use append-only JSONL, owner-only file permissions and fsync per event.
- [x] Ignore a torn final journal line after abrupt process termination while preserving preceding complete events.
- [x] Add tests for multi-batch journal ordering, checkpoint values, file permissions and truncated-tail recovery.
- Limitation: this is a durable batch ledger and recovery aid, not yet automatic checkpoint resume. Retry remains safe through idempotent upserts; explicit resume validation is the next step.


## Checkpoint-validated Scout import resume (2026-11-23)

- [x] Fingerprint the exact ordered Scout row projection consumed by import using streaming SHA-256.
- [x] Persist the source fingerprint with the original run ledger entry.
- [x] Resume through the protected import API using the original run ID.
- [x] Reject missing/completed runs, changed source contents, changed source path, or changed import mode before target writes.
- [x] Restore cumulative counters and continue strictly after the last durable Douban ID checkpoint.
- [x] Safely replay a batch when its target transaction committed but its checkpoint event was not persisted.
- [x] Add integration tests for interruption after a durable checkpoint and changed-source rejection.
- Limitation: resume requires a full read-only source fingerprint pass before writing; correctness is preferred over the fastest restart.

## Durable Scout import run-history inspection (2026-11-23)

- [x] Add a read-only journal aggregation layer for listing all import runs or selecting one exact run ID.
- [x] Reconstruct cumulative counters from committed checkpoints and final completion events.
- [x] Distinguish completed, failed and resumed/running runs; label runs without a terminal event as incomplete because a journal-only reader cannot prove whether the process is still alive.
- [x] Expose source path/mode/fingerprint, last committed Douban ID, batch/resume counts and lifecycle timestamps.
- [x] Ignore torn trailing journal records and orphan events; do not open or mutate Scout or MovieHub databases.
- [x] Add regression tests for completed summaries, failed-then-resumed runs, incomplete runs, run filtering and torn-line recovery.
- [x] Document the operator CLI.

**Import history inspection: implementation and tests added.** This is a read-only operational capability; it does not imply a real Scout catalogue has been audited or imported.


## Durable record-level import failure manifest (2026-11-23)

- [x] Persist each failed Scout row to a separate owner-only JSONL manifest after its MovieHub batch commits.
- [x] Capture run ID, batch, Douban ID, bounded title, exception type/message and timestamp without copying raw Scout payloads.
- [x] De-duplicate replayed failure entries when a batch committed but its checkpoint append did not.
- [x] Add a read-only CLI for all failures or one selected run.
- [x] Test file permissions, filtering, replay de-duplication and torn trailing-line recovery.
- [x] Extend the real importer integration test to verify exact record failure details survive in the manifest.

**Record-level failure reporting implemented.** This makes import errors actionable across restarts; it does not claim that real Scout data has been validated.


## Scout preview-to-import reconciliation (2026-11-23)

- [x] Include a SHA-256 fingerprint of the exact ordered Scout row projection in every preview report.
- [x] Allow preview JSON to be saved atomically with owner-only permissions for later audit.
- [x] Add a read-only reconciliation command linking the saved preview to a specific completed import run.
- [x] Block reconciliation when run status, source path, import mode or source fingerprint differs.
- [x] Reconcile source totals, processed rows, imported rows plus per-record failures, unchanged skips and the durable error manifest.
- [x] Add regression tests for matching imports with record errors, changed sources, incomplete runs, counter drift and malformed preview reports.

**Preview → import accounting reconciliation: implemented; CI verification pending.**


## Preview/import/reconciliation end-to-end acceptance (2026-11-23)

- [x] Add an integration test using a real temporary Scout SQLite source and isolated MovieHub target.
- [x] Execute read-only preview, actual importer, durable journal, then reconciliation in one test flow.
- [x] Verify source fingerprint continuity, expected-vs-actual import counters and zero reconciliation mismatches.
- [x] Keep the test fully isolated; no production Scout or NAS database is accessed.

**The preview → import → reconciliation chain now has a single automated integration test; CI verification pending.**


## Single-command Scout readiness package (2026-11-23)

- [x] Add one command combining whole-catalogue audit, annual-chart coverage gate and target-aware preview.
- [x] Run strict source/chart blockers before opening the target database for preview.
- [x] Persist one versioned JSON report atomically with mode 0600.
- [x] Distinguish ready-for-operator-review, no-changes and blocked outcomes with stable exit codes.
- [x] Test successful readiness, early blocking without target access, read-only behavior and report permissions.

**One-command readiness preparation implemented; CI verification pending.**


## Scout import transactionally durable receipts (2026-11-23)

- [x] Add schema-v2 `import_batch_receipts`, with a unique run/batch key, source fingerprint, cumulative counters, source cursor and bounded error details.
- [x] Add migration 002 with the existing backup, integrity-check and rollback migration runner; build new databases directly at schema v2.
- [x] Write each batch receipt in the same target-database transaction as its movie and metadata changes.
- [x] Advance in-memory counters only after the batch transaction commits, preventing rolled-back work from leaking into run totals.
- [x] Recover from database receipts, validate source fingerprint/cursor/counters, reject journal-only or conflicting checkpoints, and repair missing journal/error-manifest appends.
- [x] Add regression tests for the lost-journal-checkpoint crash window, transaction rollback atomicity and duplicate receipt rejection.
- [ ] Execute the new and existing backend suites in GitHub Actions and review the migration against a real v1 fixture before any deployment.

**Atomic receipt recovery: implementation and regression tests committed; CI execution and migration acceptance remain pending. No NAS database, Scout source or production service was accessed.**
