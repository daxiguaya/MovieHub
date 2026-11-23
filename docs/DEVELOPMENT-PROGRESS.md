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

## Overall first-release progress (estimate)

| Workstream | Status |
|---|---:|
| Database foundation and Scout-safe import boundary | 100% |
| Backend API baseline (charts, movie search/filter, details, posters, import, favorites) | 80% |
| Scout import hardening | Implementation and merge/partial-retry tests complete; 1,000-row fixture passed; 10k/100k and NAS benchmark pending |
| Manual normalized chart snapshot import | Complete |
| One-shot Douban Top 250 collection | Implemented; robots-aware and low-rate |
| One-shot popular/high-rated collection | Implemented; bounded, robots-aware and low-rate |
| Annual chart collection and scheduled updates | 0% |
| Favorites API and frontend UI | Implemented; Chromium E2E passed |
| Xiaoya handoff | Configured new-tab handoff and URL encoding passed Chromium E2E; real NPM verification pending |
| React frontend and user workflows | Baseline implemented; 4 Chromium E2E tests passed, including real FastAPI + temporary SQLite integration; visual QA pending |
| Container packaging and backup/restore preparation | 100% |
| Actual NAS deployment and end-to-end production verification | 0% |

**Estimated first-release implementation progress: about 62%.** This is a planning estimate, not a test metric. The independent database, core backend APIs, import hardening, poster security, frontend baseline and dual-container packaging are substantially in place; annual/scheduled chart collection, browser E2E validation and production rollout remain unfinished.

## Phase B — Scout import hardening (in progress)

- [x] Make `force_full` functional: incremental imports skip records whose Scout `update_time` is not newer than the last imported timestamp; forced full imports reprocess all valid records.
- [x] Replace the catalogue-wide write transaction with bounded batches (500 records per transaction) to reduce SQLite writer-lock duration.
- [x] Keep per-record SAVEPOINT isolation and make interrupted/partially committed imports safe to retry.
- [x] Invalidate MovieHub caches only after committed changes; report when earlier batches were committed before a later failure.
- [x] Add regression coverage proving incremental skip, newer-timestamp updates and forced full reprocessing behavior.
- [x] Exercise a 1,000-record synthetic Scout catalogue across six bounded batches.
- [x] Add opt-in 10k/100k synthetic throughput benchmarks using temporary source and target SQLite databases; normal CI skips these hardware-sensitive runs.

**Import hardening milestone: implemented and tested, including a 1,000-row synthetic catalogue processed across multiple batches.** A larger 10k/100k and NAS-hardware benchmark remains. Source deletions remain non-destructive: absent Scout rows do not delete MovieHub movies.

## Scout import operator workflow

- [x] Document read-only source mount requirements and WAL-consistent staging guidance.
- [x] Document protected incremental and forced-full API requests plus status polling.
- [x] Document timestamp-based skip behavior, non-destructive empty-field merge policy, no source-delete propagation, batch commits and retry semantics.
- [x] Explicitly separate Scout metadata import from chart snapshot acquisition.

**Scout import runbook: complete. Large-fixture performance validation remains.**

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
- [x] Support a generic local adapter that preserves the declared chart provider and a Cinephile adapter that labels its normalized export.
- [x] Fix the latent adapter package import path discovered by exercising the CLI.
- [x] Document snapshot format, date-scoped replacement, metadata precedence and explicit non-automation boundary.

**Snapshot import workflow: implemented and tested. This is a manual normalized-data import path, not an automated Douban collector.**

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
- [ ] Add annual chart collection after confirming a stable, permitted source.
- [ ] Decide whether scheduled refresh is appropriate; no collector currently runs in the background.

**Top 250, popular and high-rated one-shot collection: implemented. Annual charts and scheduling remain pending.**

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

**Source review: complete. Top 250, popular and high-rated one-shot collection is implemented. Annual charts and scheduled refresh remain pending an authorized, reliable source path.**

## Next work

- [ ] Implement an annual chart collector if a stable public source can be validated; Top 250, popular and high-rated collectors are one-shot/manual only.
- [ ] Decide whether scheduled refresh is appropriate after verifying source authorization, robots rules and stability.
- [ ] Benchmark title/original-title LIKE search against realistic catalogue sizes; keep FTS5 optional rather than a hard runtime dependency, and add it only if measurements justify it.
- [x] Add browser end-to-end tests for chart navigation, search, detail, favorites and Xiaoya handoff using Playwright Chromium and isolated API fixtures.
- [x] Add a live browser integration test against a running FastAPI backend and a temporary initialized/seeded SQLite database.
- [ ] Verify the complete deployment path through the user's NPM reverse proxy after deployment is separately authorized.
- [x] Add reproducible opt-in 10k/100k synthetic import throughput benchmarks against temporary SQLite databases.
- [ ] Execute 10k/100k throughput and memory measurements in a controlled environment; repeat on the target NAS only during an authorized pre-deployment test.
- [ ] Before any NAS rollout, verify the actual NPM Docker network, Scout export path/read permissions, and host data/backup directory ownership.
- [ ] Prefer a separate physical volume or off-site destination for backups; same-volume backups do not protect against disk failure.
- [ ] Keep production database initialization, Scout import, deployment and NPM changes as separately reviewed operator actions.

## Latest code validation

- Latest full validation: [#286](https://github.com/daxiguaya/MovieHub/actions/runs/45141717599) — **success**.
- Backend: **99 passed, 2 skipped** (the opt-in 10k/100k performance cases); frontend: **5 Vitest tests passed**; browser: **4 Playwright Chromium E2E tests passed**.
- Compose validation, backend/frontend production builds and both container image builds passed.
- The browser job starts a real FastAPI process against a fresh temporary SQLite database, seeds a test chart/movie and runs one unmocked chart → detail → search workflow. Three additional browser tests use isolated API fixtures for favorite and Xiaoya handoff interactions.
- All browser tests run on Ubuntu 24.04; no NAS services, live Scout database or production data are used.
- Benchmark harness commit: [\`ecd9f9f\`](https://github.com/daxiguaya/MovieHub/commit/ecd9f9fe2ad662472a9dc7357f98e86bc80d1ad0); CI [#269](https://github.com/daxiguaya/MovieHub/actions/runs/45139124417) — **success**. The two performance cases remain opt-in and require a controlled execution to produce throughput measurements.

## Scope and safety boundaries

- MovieHub owns a new, independent SQLite database.
- Douban Scout is an external, read-only source. Do not migrate, write to, or otherwise modify Scout's database.
- No production database creation/migration, deployment, import, NPM proxy change, or service restart is part of this work.
- Keep validation on temporary fixtures. Do not touch the user's live Scout database.
- Do not commit credentials, tokens, private environment files, database files, or local repair backups.
